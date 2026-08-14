"""
Lazy staleness-aware re-synthesis for a single municipality.

A stored assessment is treated as current only if its run completed at or
after the municipality's geo_scores.computed_at (see
docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md). This
module regenerates a stale or missing assessment on demand using only the
LLM synthesis step — it never calls Google Places or Tavily. It only acts
when a web_intel_cache row already exists for the municipality (any age);
otherwise the municipality stays geo-only.
"""
import json
import uuid

from loguru import logger

import config
from agents import db_store
from agents.geo_scoring import _load_scores_from_db
from agents.synthesis import synthesize_municipality, compute_final_score
from agents.kb_builder import save_municipality_docs


def _load_cached_intel(municipality_id: int) -> dict | None:
    """Any cached web_intel_cache row for this municipality, ignoring expiry —
    reused regardless of age since no new Places/Tavily call will be made."""
    import sqlite3
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT places_data, web_score FROM web_intel_cache WHERE municipality_id=?",
            (municipality_id,),
        ).fetchone()
        if row and row["places_data"]:
            result = json.loads(row["places_data"])
            result["web_score"] = row["web_score"]
            return result
        return None
    except Exception as e:
        logger.warning(f"refresh._load_cached_intel failed: {e}")
        return None
    finally:
        conn.close()


def maybe_refresh_assessment(municipality_id: int) -> dict | None:
    """
    Ensures the municipality has a current assessment if possible without any
    new Google Places/Tavily calls. Returns the current row (same shape as
    db_store.get_latest_scored_municipalities()) or None if the municipality
    doesn't exist.
    """
    rows = db_store.get_latest_scored_municipalities()
    row = next((r for r in rows if r["municipality_id"] == municipality_id), None)
    if row is None:
        return None
    if row["assessment"] is not None:
        return row  # already current

    intel = _load_cached_intel(municipality_id)
    if intel is None:
        return row  # no cached web intel — stays geo-only, no API call

    try:
        geo_map = _load_scores_from_db([{"name": row["name"], "province": row["province"]}])
        geo = geo_map.get(row["name"])
        if geo is None:
            return row
    except Exception as e:
        logger.warning(f"refresh.maybe_refresh_assessment failed to load scores for {row['name']}: {e}")
        return row

    try:
        final_score, web_score = compute_final_score(geo, intel)
        narrative = synthesize_municipality(row["name"], geo, intel)
    except Exception as e:
        logger.warning(f"refresh.maybe_refresh_assessment synthesis failed for {row['name']}: {e}")
        return row

    run_id = f"refresh_{uuid.uuid4().hex[:8]}"
    top_target = {
        "municipality":     row["name"],
        "province":         row["province"],
        "region":           row["region"],
        "lat":              row["lat"],
        "lon":              row["lon"],
        "population":       row["population"],
        "income_class":     row["income_class"],
        "geo_score":        geo.get("geo_score", 0),
        "web_score":        web_score,
        "final_score":      final_score,
        "tier":             narrative["confidence"],
        "assessment":       narrative["assessment"],
        "opportunity":      narrative["opportunity"],
        "risk":             narrative["risk"],
        "solar_irradiance": geo.get("solar_raw"),
        "solar_yield_kwh":  geo.get("solar_yield_kwh"),
        "pop_density":      geo.get("pop_norm"),
    }
    db_store.create_run(run_id, row["name"], row["province"])
    db_store.complete_run(run_id, [top_target])

    try:
        final_scores = {row["name"]: {
            "final_score":        final_score,
            "tier":               narrative["confidence"],
            "geo_score":          geo.get("geo_score", 0),
            "solar_kwh_estimate": geo.get("solar_yield_kwh", 0),
            "assessment":         narrative["assessment"],
            "opportunity":        narrative["opportunity"],
            "risk":               narrative["risk"],
            "province":           row["province"],
            "region":             row["region"],
            "income_class":       row["income_class"],
            "population":         row["population"] or 0,
            "is_urban":           (row["population"] or 0) > 50000,
        }}
        save_municipality_docs(
            location=row["province"], final_scores=final_scores,
            web_intel={row["name"]: intel}, run_id=run_id,
        )
    except Exception as e:
        logger.warning(f"refresh.maybe_refresh_assessment KB update failed for {row['name']}: {e}")

    refreshed = db_store.get_latest_scored_municipalities()
    return next((r for r in refreshed if r["municipality_id"] == municipality_id), row)
