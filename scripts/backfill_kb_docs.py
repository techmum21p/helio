"""
One-time migration: register the current kb/intel/*.md file for each
municipality into the kb_docs DB table (see agents/db_store.py::register_kb_doc),
and delete the superseded duplicate files. Replaces the old ChromaDB-index
purge script now that the KB is read straight off disk via the kb_docs table
instead of a vector index (see agents/chat_tools.py::search_kb).

Usage:
    python scripts/backfill_kb_docs.py --dry-run   # default, lists what would happen
    python scripts/backfill_kb_docs.py --execute    # actually registers + deletes
"""
import argparse
import re
from pathlib import Path

from loguru import logger

import config
from agents import db_store


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace(",", "").replace(".", "").replace("/", "_")


def _strip_city_of(slug: str) -> str:
    return slug[len("city_of_"):] if slug.startswith("city_of_") else slug


def match_municipality(doc_key: str, municipalities: list[dict]) -> int | None:
    """Match a `{location_slug}__{muni_slug}__{run_id}` kb/intel filename stem
    to a municipality_id. Requires the muni_slug segment to match a
    municipality's name-slug (ignoring a 'City of' prefix on either side —
    some docs predate a municipality being reclassified as a city in the DB)
    AND the location_slug segment to either equal that municipality's
    province-slug, or contain the muni_slug as a substring (historical
    multi-municipality location strings)."""
    parts = doc_key.split("__")
    if len(parts) != 3:
        return None
    location_slug, muni_slug, _run_id = parts
    bare_muni_slug = _strip_city_of(muni_slug)
    for m in municipalities:
        name_slug = _slug(m["name"])
        if _strip_city_of(name_slug) != bare_muni_slug:
            continue
        province_slug = _slug(m["province"])
        if location_slug == province_slug or muni_slug in location_slug:
            return m["municipality_id"]
    return None


def pick_current(paths: list[Path]) -> Path:
    """Newest file by mtime wins."""
    return max(paths, key=lambda p: p.stat().st_mtime)


def main(dry_run: bool = True) -> None:
    conn = db_store._get_conn()
    try:
        rows = conn.execute("SELECT id AS municipality_id, name, province FROM municipalities").fetchall()
        municipalities = [dict(r) for r in rows]
    finally:
        conn.close()

    by_municipality: dict[int, list[Path]] = {}
    unmatched = []
    for path in sorted(Path(config.KB_INTEL).glob("*.md")):
        municipality_id = match_municipality(path.stem, municipalities)
        if municipality_id is None:
            unmatched.append(path)
            continue
        by_municipality.setdefault(municipality_id, []).append(path)

    logger.info(f"{len(by_municipality)} municipalities have kb/intel files; {len(unmatched)} files unmatched.")

    for municipality_id, paths in by_municipality.items():
        current = pick_current(paths)
        superseded = [p for p in paths if p != current]
        province = next(m["province"] for m in municipalities if m["municipality_id"] == municipality_id)
        run_id = current.stem.split("__")[-1]

        if dry_run:
            logger.info(f"  would register: {current.name} (municipality_id={municipality_id})")
            for p in superseded:
                logger.info(f"  would delete: {p.name}")
            continue

        db_store.register_kb_doc(municipality_id, province, str(current), run_id)
        for p in superseded:
            try:
                p.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {p}: {e}")

    if dry_run:
        logger.info("Dry run — no changes made. Re-run with --execute to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually register + delete (default is dry-run).")
    args = parser.parse_args()
    main(dry_run=not args.execute)
