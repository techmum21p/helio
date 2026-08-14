"""
Agent 4: Report Generation Agent
Uses Claude to write a comprehensive markdown report
from the synthesis output. Saves to /reports and /kb/reports.
"""

import json
import uuid
from datetime import datetime
from loguru import logger
import anthropic

import config
from graph.state import SolarLeadState
from agents import db_store

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)


REPORT_PROMPT = """You are writing a solar installation market intelligence report for a small business owner in the Philippines.

Location analyzed: {location}
Date: {date}
Top {n} target municipalities identified.

Full ranked data:
{targets_json}

Write a professional but readable markdown report with these sections:

# Solar Installation Opportunity Report: {location}
## Executive Summary
(3-4 sentences. Total opportunity, top region, key recommendation.)

## Top Target Areas
(Table with columns: Rank | Municipality | Score | Tier | Key Opportunity)

## Score Breakdown
(Table with columns: Municipality | Irradiance (kWh/m²/day) | Income Class | Pop Density (ppl/km²) | Annual Yield (kWh/kWp) | Final Score)

## Detailed Profiles
(For each of the top 5 targets, one paragraph with assessment, opportunity, and risk.)

## Recommended Action Plan
(3 concrete next steps for the sales team.)

## Methodology Note
(Brief 2-3 sentence note on data sources used.)

Keep it grounded and factual. Do not invent statistics not present in the data.
"""


def generate_report_markdown(location: str, top_targets: list) -> str:
    prompt = REPORT_PROMPT.format(
        location=location,
        date=datetime.now().strftime("%B %d, %Y"),
        n=len(top_targets),
        targets_json=json.dumps(top_targets[:10], indent=2),
    )

    try:
        response = client.messages.create(
            model=config.REPORT_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(b.text for b in response.content if hasattr(b, "text"))
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return f"# Report Generation Failed\n\nError: {e}"


def save_report(location: str, markdown: str, run_id: str) -> str:
    """Save report to both /reports (for download) and /kb/reports (for RAG)."""
    slug = location.lower().replace(" ", "_").replace(",", "")
    filename = f"{slug}_{run_id}.md"

    report_path = config.REPORTS_DIR / filename
    kb_path = config.KB_REPORTS / filename

    for path in [report_path, kb_path]:
        path.write_text(markdown, encoding="utf-8")
        logger.info(f"Report saved: {path}")

    return str(report_path)


def report_gen_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 4] Generating report for: {state['location']}")

    top_targets = state.get("top_targets") or []
    if not top_targets:
        logger.warning("[Agent 4] No targets to report on.")
        return {**state, "report_markdown": "No targets found.", "report_path": None}

    province = top_targets[0].get("province", state["location"]) if top_targets else state["location"]
    named_ids = []
    for t in top_targets:
        muni_id = db_store.get_municipality_id(t.get("municipality", ""), t.get("province", province))
        if muni_id is not None:
            named_ids.append((t["municipality"], muni_id))

    markdown = generate_report_markdown(state["location"], top_targets) + _full_score_breakdown_section(named_ids)
    report_path = save_report(state["location"], markdown, state["run_id"])

    try:
        db_store.save_report(
            run_id=state["run_id"],
            province=province,
            municipality=None,
            markdown=markdown,
            file_path=report_path,
        )
    except Exception as e:
        logger.error(f"[Agent 4] DB report save failed: {e}")

    return {
        **state,
        "report_markdown": markdown,
        "report_path": report_path,
    }


def _pending_section(pending: list[dict]) -> str:
    """Deterministic (non-LLM) list of geo-only municipalities, so the report
    is honest about partial province coverage instead of omitting them or
    having the LLM invent narrative for towns with no web intel yet."""
    if not pending:
        return ""
    rows = "\n".join(
        f"| {m['name']} | {m['geo_score']:.3f} |" if m["geo_score"] is not None
        else f"| {m['name']} | — |"
        for m in pending
    )
    return (
        "\n## Not Yet Fully Assessed\n"
        "These municipalities have a geo-based score but no web intelligence/AI "
        "assessment yet, so they're excluded from ranking and profiles above.\n\n"
        "| Municipality | Geo Score |\n|---|---|\n" + rows + "\n\n"
        "🔄 *Want a full assessment for one of these? Drill into that municipality "
        "in the explorer to trigger an on-demand re-assessment.*\n"
    )


def _score_breakdown_markdown(name: str, breakdown: dict) -> str:
    """Deterministic (non-LLM) full component breakdown for one municipality —
    same components/weights shown in the app's per-municipality expander, so the
    report is a transparent, auditable record rather than an LLM paraphrase."""
    geo = breakdown["geo"]
    w = breakdown["weights"]
    lines = [f"### {name}", "", "**Geo Score components**", "",
              "| Component | Raw | Normalized (0-1) | Weight |", "|---|---|---|---|"]
    lines.append(
        f"| Solar Irradiance | {geo['solar_irradiance']:.2f} kWh/m²/day | {geo['solar_norm']:.3f} | {w['solar']:.0%} |"
        if geo["solar_irradiance"] is not None else f"| Solar Irradiance | — | — | {w['solar']:.0%} |"
    )
    lines.append(f"| Income Class | {geo['income_class'] or '—'} | {geo['income_norm']:.3f} | {w['income']:.0%} |")
    lines.append(
        f"| Population Density | {geo['pop_density']:.1f} ppl/km² | {geo['pop_density_norm']:.3f} | {w['population']:.0%} |"
        if geo["pop_density"] is not None else f"| Population Density | — | — | {w['population']:.0%} |"
    )
    lines.append("")
    lines.append(
        f"Geo Score = {w['solar']:.0%}×Solar + {w['income']:.0%}×Income + {w['population']:.0%}×Pop. Density "
        f"= **{geo['geo_score']:.3f}**" if geo["geo_score"] is not None else "Geo Score not available"
    )
    lines.append("")

    web = breakdown["web"]
    if web is not None:
        ww = web["weights"]
        lines += [
            "**Web Score components**", "",
            "| Component | Raw | Normalized (0-1) | Weight |", "|---|---|---|---|",
            f"| Business Density | {web['business_count']} businesses (capped at 20) | {web['business_density']:.3f} | {ww['business_density']:.0%} |",
            f"| Price Signal | {web['avg_price_level']}/4 avg price level | {web['price_signal']:.3f} | {ww['price_signal']:.0%} |",
            f"| Rating Signal | {web['avg_rating']}/5 avg rating | {web['rating_signal']:.3f} | {ww['rating_signal']:.0%} |",
            f"| Anchor Signal | {web['commercial_anchors']} commercial/industrial anchors (capped at 5) | {web['anchor_signal']:.3f} | {ww['anchor_signal']:.0%} |",
            "",
            f"Web Score = {ww['business_density']:.0%}×Density + {ww['price_signal']:.0%}×Price + "
            f"{ww['rating_signal']:.0%}×Rating + {ww['anchor_signal']:.0%}×Anchors = **{web['web_score']:.3f}**",
            "",
        ]
        fw = breakdown["final_weights"]
        if breakdown["final_score"] is not None:
            lines.append(
                f"Solar Opportunity Score = {fw['geo']:.0%}×Geo Score + {fw['web']:.0%}×Web Score "
                f"= **{breakdown['final_score']:.3f}**"
            )
    else:
        lines.append("_No web intelligence cached yet — Web Score and Solar Opportunity Score not available._")
    lines.append("")
    return "\n".join(lines)


def _full_score_breakdown_section(named_ids: list[tuple[str, int]]) -> str:
    parts = ["\n## Full Score Breakdown\n"]
    for name, municipality_id in named_ids:
        breakdown = db_store.get_score_breakdown(municipality_id)
        if breakdown:
            parts.append(_score_breakdown_markdown(name, breakdown))
    return "\n".join(parts)


def regenerate_province_report(province: str) -> dict | None:
    """Rebuilds the province report from current `run_results` data (used when
    a lazy per-municipality refresh has made the stored report stale). Only
    municipalities with a current final_score are ranked/profiled; the rest
    are listed as pending in a separate section. Returns the same shape as
    db_store.get_latest_report_for_province(), or None if nothing is assessed yet."""
    municipalities = [
        m for m in db_store.get_latest_scored_municipalities()
        if m["province"] == province
    ]
    assessed = sorted(
        (m for m in municipalities if m["final_score"] is not None),
        key=lambda m: m["final_score"], reverse=True,
    )
    pending = sorted(
        (m for m in municipalities if m["final_score"] is None),
        key=lambda m: m["geo_score"] or 0, reverse=True,
    )
    if not assessed:
        return None

    top_targets = [
        {
            "municipality":      m["name"],
            "province":          m["province"],
            "region":            m["region"],
            "lat":               m["lat"],
            "lon":               m["lon"],
            "population":        m["population"],
            "income_class":      m["income_class"],
            "geo_score":         m["geo_score"],
            "web_score":         m["web_score"],
            "final_score":       m["final_score"],
            "tier":              m["tier"],
            "assessment":        m["assessment"],
            "opportunity":       m["opportunities"][0] if m["opportunities"] else "",
            "risk":              m["risks"][0] if m["risks"] else "",
            "solar_irradiance":  m["solar_irradiance"],
            "solar_yield_kwh":   m["solar_yield_kwh"],
            "pop_density":       m["pop_density"],
        }
        for m in assessed
    ]

    breakdown_section = _full_score_breakdown_section(
        [(m["name"], m["municipality_id"]) for m in assessed]
    )
    markdown = generate_report_markdown(province, top_targets) + breakdown_section + _pending_section(pending)
    run_id = f"regen_{uuid.uuid4().hex[:8]}"
    report_path = save_report(province, markdown, run_id)

    try:
        db_store.create_run(run_id, province, province)
        db_store.save_report(
            run_id=run_id, province=province, municipality=None,
            markdown=markdown, file_path=report_path,
        )
    except Exception as e:
        logger.error(f"report_gen.regenerate_province_report DB save failed: {e}")

    return db_store.get_latest_report_for_province(province)
