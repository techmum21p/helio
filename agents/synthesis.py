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

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


SYNTHESIS_PROMPT = """You are a market intelligence analyst for a solar panel installation company in the Philippines.

Given the data below for a municipality, provide:
1. A 2-3 sentence assessment of its solar installation potential
2. A confidence level: HIGH / MEDIUM / LOW
3. One key opportunity and one key risk

Municipality: {municipality}

Geo/ML Scores:
- Solar irradiance (normalized 0-1): {solar_norm:.2f}
- Population density (normalized 0-1): {pop_norm:.2f}
- Income level (normalized 0-1): {income_norm:.2f}
- Composite geo score: {geo_score:.2f}

Web Intelligence:
- Business count nearby: {business_count}
- Avg price level (1-4): {avg_price_level}
- Economic news: {news_snippet}
- Property signal: {property_snippet}
- Commerce activity: {commerce_snippet}
- Solar awareness: {solar_news_snippet}

Respond in this exact format:
ASSESSMENT: <your 2-3 sentence assessment>
CONFIDENCE: <HIGH|MEDIUM|LOW>
OPPORTUNITY: <one key opportunity>
RISK: <one key risk>
"""


def synthesize_municipality(
    municipality: str,
    geo: dict,
    intel: dict,
) -> dict:
    """Claude synthesizes geo scores + web intel into a final profile."""
    prompt = SYNTHESIS_PROMPT.format(
        municipality=municipality,
        solar_norm=geo.get("solar_norm", 0),
        pop_norm=geo.get("pop_norm", 0),
        income_norm=geo.get("income_norm", 0),
        geo_score=geo.get("geo_score", 0),
        business_count=intel.get("business_count", 0),
        avg_price_level=intel.get("avg_price_level", 0),
        news_snippet=intel.get("news_snippet", "No data"),
        property_snippet=intel.get("property_snippet", "No data"),
        commerce_snippet=intel.get("commerce_snippet", "No data"),
        solar_news_snippet=intel.get("solar_news_snippet", "No data"),
    )

    try:
        response = client.messages.create(
            model=config.REPORT_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text

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
    Final score blends geo score with web intel signals.
    Web intel adds up to 0.2 bonus on top of geo score (0.8 weight).
    """
    geo_score = geo.get("geo_score", 0)

    # Normalize business count (cap at 20 = max signal)
    biz_score = min(intel.get("business_count", 0) / 20, 1.0)
    price_score = min(intel.get("avg_price_level", 0) / 4, 1.0)
    web_score = (biz_score + price_score) / 2

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
