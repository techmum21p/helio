"""
Agent 3: Synthesis Agent
Combines geo/ML scores with web intelligence.
Uses Claude to generate a reasoned narrative per location
and produces a final ranked target list.
"""

import anthropic
from loguru import logger

import config
from graph.state import SolarLeadState

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)


SYNTHESIS_PROMPT = """You are a market intelligence analyst for a solar panel installation company in the Philippines.

Given the data below for a municipality, provide a grounded assessment using your knowledge of this specific place and the data provided.

Municipality: {municipality}
Province: {province}
Region: {region}
Urban/Rural: {urban_rural}
Income Classification: {income_class} class (1st = highest, 6th = lowest)
Estimated Population: {population:,}

Scored Data (normalized 0-1 relative to other municipalities in this run):
- Solar irradiance score: {solar_norm:.2f}  (est. {solar_kwh:.0f} kWh/kWp/year)
- Population score: {pop_norm:.2f}
- Income score: {income_norm:.2f}
- Composite geo score: {geo_score:.2f}

Web Intelligence (Google Places + Tavily):
- Businesses found nearby: {business_count} (avg rating: {avg_rating}/5, {total_reviews} reviews)
- Commercial/industrial anchors (malls, factories, warehouses): {commercial_anchors}
- Avg price level of businesses (0-4): {avg_price_level}
- Economic activity news: {news_snippet}
- Property market signals: {property_snippet}
- Commerce: {commerce_snippet}
- Solar awareness: {solar_news_snippet}

Using your knowledge of {municipality}, {province} and the data above:
1. Write a 2-3 sentence assessment grounded in what you know about this specific place.
2. Rate confidence: HIGH / MEDIUM / LOW
3. Identify one concrete opportunity and one real risk specific to this municipality.

Respond in this exact format:
ASSESSMENT: <2-3 sentence assessment referencing the specific municipality>
CONFIDENCE: <HIGH|MEDIUM|LOW>
OPPORTUNITY: <specific opportunity for {municipality}>
RISK: <specific risk for {municipality}>
"""


def synthesize_municipality(
    municipality: str,
    geo: dict,
    intel: dict,
) -> dict:
    """Claude synthesizes geo scores + web intel into a final profile."""
    prompt = SYNTHESIS_PROMPT.format(
        municipality=municipality,
        province=geo.get("province", "Philippines"),
        region=geo.get("region", "Philippines"),
        urban_rural="Urban" if geo.get("is_urban") else "Rural",
        income_class=geo.get("income_class", "3rd"),
        population=int(geo.get("population_raw", 0)),
        solar_norm=geo.get("solar_norm", 0),
        solar_kwh=geo.get("solar_yield_kwh", 0),
        pop_norm=geo.get("pop_norm", 0),
        income_norm=geo.get("income_norm", 0),
        geo_score=geo.get("geo_score", 0),
        business_count=intel.get("business_count", 0),
        avg_rating=intel.get("avg_rating", 0),
        total_reviews=intel.get("total_reviews", 0),
        commercial_anchors=intel.get("commercial_anchors", 0),
        avg_price_level=intel.get("avg_price_level", 0),
        news_snippet=intel.get("news_snippet", "No data"),
        property_snippet=intel.get("property_snippet", "No data"),
        commerce_snippet=intel.get("commerce_snippet", "No data"),
        solar_news_snippet=intel.get("solar_news_snippet", "No data"),
    )

    try:
        response = client.messages.create(
            model=config.REPORT_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next(b.text for b in response.content if hasattr(b, "text"))

        # Parse structured response
        lines = {
            line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
            for line in raw.strip().splitlines()
            if ":" in line
        }

        return {
            "assessment": lines.get("ASSESSMENT", ""),
            "confidence": lines.get("CONFIDENCE", "MEDIUM"),
            "opportunity": lines.get("OPPORTUNITY", ""),
            "risk": lines.get("RISK", ""),
        }

    except Exception as e:
        logger.warning(f"Claude synthesis failed for {municipality}: {e}")
        return {
            "assessment": "Synthesis unavailable.",
            "confidence": "LOW",
            "opportunity": "",
            "risk": "",
        }


def compute_final_score(geo: dict, intel: dict) -> float:
    """
    Final score = 0.80 × geo_score + 0.20 × web_score

    web_score combines four Places + Tavily signals (each 0-1):
      - business_density  : commercial activity (count, capped at 20)
      - price_signal      : avg price level of businesses (0-4 scale)
      - rating_signal     : avg Google rating (1-5, normalized) — economic quality proxy
      - anchor_signal     : malls/factories/industrial anchors (B2B solar opportunity)
    """
    geo_score = geo.get("geo_score", 0)

    biz_density   = min(intel.get("business_count", 0) / 20, 1.0)
    price_signal  = min(intel.get("avg_price_level", 0) / 4, 1.0)
    rating_raw    = intel.get("avg_rating", 0)
    rating_signal = max((rating_raw - 1.0) / 4.0, 0) if rating_raw else 0  # normalize 1-5 → 0-1
    anchor_signal = min(intel.get("commercial_anchors", 0) / 5, 1.0)       # cap at 5 anchors

    web_score = (
        0.35 * biz_density
        + 0.25 * price_signal
        + 0.25 * rating_signal
        + 0.15 * anchor_signal
    )

    return round(0.80 * geo_score + 0.20 * web_score, 4)


def synthesis_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 3] Synthesizing scores for: {state['location']}")

    geo_scores = state.get("geo_scores") or {}
    web_intel = state.get("web_intel") or {}

    final_scores = {}
    for municipality in geo_scores:
        geo = geo_scores[municipality]
        intel = web_intel.get(municipality, {})

        final_score = compute_final_score(geo, intel)
        narrative = synthesize_municipality(municipality, geo, intel)

        final_scores[municipality] = {
            "geo_score": geo.get("geo_score", 0),
            "final_score": final_score,
            "solar_kwh_estimate": round(geo.get("solar_raw", 5.0) * 365 * 0.8, 0),
            "tier": narrative["confidence"],
            "assessment": narrative["assessment"],
            "opportunity": narrative["opportunity"],
            "risk": narrative["risk"],
            "province": geo.get("province", ""),
            "region": geo.get("region", ""),
            "income_class": geo.get("income_class", ""),
            "population": int(geo.get("population_raw", 0)),
            "is_urban": geo.get("is_urban", False),
        }

    # Rank and return top N
    top_targets = sorted(
        [{"municipality": k, **v} for k, v in final_scores.items()],
        key=lambda x: x["final_score"],
        reverse=True,
    )[:config.TOP_N_TARGETS]

    logger.info(f"[Agent 3] Top target: {top_targets[0]['municipality'] if top_targets else 'None'}")

    return {
        **state,
        "final_scores": final_scores,
        "top_targets": top_targets,
        "status": "complete",
    }
