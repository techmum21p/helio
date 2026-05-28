"""
KB document builder — generates structured per-municipality intel documents.

Produces one markdown file per municipality in kb/intel/, covering:
- Exact scores (final, geo, solar yield)
- Commercial activity signals from Google Places
- AI assessment, opportunity, risk
- Web intelligence snippets
- Full barangay list from the barangay package

These complement the high-level province report so the chatbot can answer
granular questions: "Which barangays are in Los Baños?", "What's Santa Rosa's
commercial anchor count?", "Compare Bay vs Calauan."
"""

from pathlib import Path
from loguru import logger

import config


def _get_barangays(municipality: str, province: str) -> list[str]:
    """Return barangay names for a municipality via the barangay package."""
    try:
        import barangay as br
        data = br.BARANGAY
        prov_lower = province.lower().strip()
        muni_lower = municipality.lower().strip()

        for region_data in data.values():
            if not isinstance(region_data, dict):
                continue
            for prov_name, prov_data in region_data.items():
                if prov_name.lower().strip() != prov_lower:
                    continue
                if not isinstance(prov_data, dict):
                    continue
                for muni_name, brgys in prov_data.items():
                    if muni_name.lower().strip() == muni_lower:
                        if isinstance(brgys, list):
                            return brgys
                        if isinstance(brgys, dict):
                            return list(brgys.keys())
    except Exception as e:
        logger.warning(f"Barangay lookup failed for {municipality}: {e}")
    return []


def _build_municipality_doc(municipality: str, scores: dict, intel: dict) -> str:
    province  = scores.get("province", "")
    region    = scores.get("region", "")
    barangays = _get_barangays(municipality, province)

    brgy_count   = len(barangays)
    brgy_listing = ", ".join(barangays) if barangays else "Not available"

    lines = [
        f"# {municipality}, {province} — Solar Lead Intelligence Profile",
        f"",
        f"**Province:** {province}  ",
        f"**Region:** {region}  ",
        f"**Income Class:** {scores.get('income_class', 'N/A')} (1st=highest, 6th=lowest)  ",
        f"**Estimated Population:** {scores.get('population', 0):,}  ",
        f"**Urban/Rural:** {'Urban' if scores.get('is_urban') else 'Rural'}",
        f"",
        f"## Opportunity Score",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Final Score | {scores.get('final_score', 0):.3f} |",
        f"| Tier | **{scores.get('tier', 'N/A')}** |",
        f"| Geo Score | {scores.get('geo_score', 0):.3f} |",
        f"| Est. Annual Solar Yield | {scores.get('solar_kwh_estimate', 0):,.0f} kWh/kWp |",
        f"",
        f"## Commercial Activity (Google Places)",
        f"- Businesses found nearby: **{intel.get('business_count', 0)}**",
        f"- Average business rating: **{intel.get('avg_rating', 0)}/5** ({intel.get('total_reviews', 0):,} total reviews)",
        f"- Commercial/industrial anchors (malls, factories, warehouses): **{intel.get('commercial_anchors', 0)}**",
        f"- Average price level: {intel.get('avg_price_level', 0)}/4",
        f"",
        f"## AI Assessment",
        f"{scores.get('assessment', 'Not available')}",
        f"",
        f"**Key Opportunity:** {scores.get('opportunity', 'Not available')}",
        f"",
        f"**Key Risk:** {scores.get('risk', 'Not available')}",
        f"",
        f"## Web Intelligence",
        f"**Economic Activity:**",
        f"{intel.get('news_snippet', 'No data')}",
        f"",
        f"**Property Market:**",
        f"{intel.get('property_snippet', 'No data')}",
        f"",
        f"**Commerce:**",
        f"{intel.get('commerce_snippet', 'No data')}",
        f"",
        f"**Solar Awareness:**",
        f"{intel.get('solar_news_snippet', 'No data')}",
        f"",
        f"## Barangays ({brgy_count} total)",
        f"{brgy_listing}",
    ]

    return "\n".join(lines)


def save_municipality_docs(
    location: str,
    final_scores: dict,
    web_intel: dict,
    run_id: str,
) -> list[Path]:
    """
    Generate and save one KB document per municipality to kb/intel/.
    Returns list of saved paths.
    """
    slug = location.lower().replace(" ", "_").replace(",", "")
    saved = []

    for municipality, scores in final_scores.items():
        intel = web_intel.get(municipality, {})
        doc = _build_municipality_doc(municipality, scores, intel)

        muni_slug = (
            municipality.lower()
            .replace(" ", "_")
            .replace(",", "")
            .replace(".", "")
        )
        filename = f"{slug}__{muni_slug}__{run_id}.md"
        path = config.KB_INTEL / filename
        path.write_text(doc, encoding="utf-8")
        saved.append(path)
        logger.debug(f"KB doc saved: {path.name}")

    logger.info(f"[KB Builder] Saved {len(saved)} municipality documents to kb/intel/")
    return saved
