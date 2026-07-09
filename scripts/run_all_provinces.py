"""
Bulk-run the pipeline for every province that doesn't have a completed run yet,
to build a complete national geo_scores / run_results dataset.

Usage:
    python scripts/run_all_provinces.py                 # run all missing provinces
    python scripts/run_all_provinces.py --dry-run        # just list what would run
    python scripts/run_all_provinces.py --delay 10       # seconds between runs (default 5)
    python scripts/run_all_provinces.py --provinces "Cebu,Iloilo"  # run specific provinces

Resumable: re-running the script skips provinces that already have a 'done' run,
so it's safe to stop (Ctrl+C) and restart.
"""
import argparse
import sys
import time
import uuid

from loguru import logger

from agents import db_store
from graph.pipeline import run_pipeline


def get_all_provinces() -> list[str]:
    """
    Source of truth is helio.db's municipalities table, NOT agents.location_db
    (backed by the separate data/ph_locations.db, built once from the barangay
    package via build_location_db.py) — that DB predates the 2026-07-08 HUC fix
    and is missing all 33 highly urbanized cities (Quezon City, Cebu City,
    Davao City, etc.), which would make this script silently skip them forever.
    """
    conn = db_store._get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT province FROM municipalities ORDER BY province").fetchall()
        return [r["province"] for r in rows]
    finally:
        conn.close()


def get_done_provinces() -> set[str]:
    conn = db_store._get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT province FROM runs WHERE status='done'"
        ).fetchall()
        return {r["province"] for r in rows}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List missing provinces without running them")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to sleep between provinces (rate-limit friendly)")
    parser.add_argument("--provinces", type=str, default=None, help="Comma-separated province names to run instead of all missing ones")
    args = parser.parse_args()

    all_provinces = get_all_provinces()
    done = get_done_provinces()

    if args.provinces:
        targets = [p.strip() for p in args.provinces.split(",")]
    else:
        targets = [p for p in all_provinces if p not in done]

    logger.info(f"{len(targets)} province(s) to run: {targets}")

    if args.dry_run:
        for p in targets:
            print(p)
        return

    for i, province in enumerate(targets, 1):
        if province in get_done_provinces():
            logger.info(f"[{i}/{len(targets)}] {province}: already done, skipping")
            continue

        run_id = str(uuid.uuid4())[:8]
        logger.info(f"[{i}/{len(targets)}] {province}: starting run {run_id}")
        db_store.create_run(run_id, province, province)
        try:
            result = run_pipeline(province, run_id=run_id)
            db_store.complete_run(run_id, result.get("top_targets") or [])
            errors = result.get("errors") or []
            if errors:
                logger.warning(f"{province}: completed with {len(errors)} non-fatal error(s): {errors}")
            else:
                logger.info(f"{province}: done cleanly")
        except Exception as exc:
            logger.error(f"{province}: failed — {exc}")
            db_store.fail_run(run_id, str(exc))

        if i < len(targets):
            time.sleep(args.delay)


if __name__ == "__main__":
    sys.exit(main())
