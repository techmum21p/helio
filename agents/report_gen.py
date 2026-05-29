"""
Agent 4: Report Generation Agent
Uses Claude to write a comprehensive markdown report
from the synthesis output. Saves to /reports and /kb/reports.
"""

import json
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

    markdown = generate_report_markdown(state["location"], top_targets)
    report_path = save_report(state["location"], markdown, state["run_id"])

    province = top_targets[0].get("province", state["location"]) if top_targets else state["location"]
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
