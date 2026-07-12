"""
One-time migration: remove the pre-real-data-fix municipality docs from the
ChromaDB kb/index/ collection (see docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md).

Scope: only the per-municipality kb/intel/*.md chunks. Province-level
kb/reports docs are left alone (out of scope — see spec).

Usage:
    python scripts/purge_stale_kb_docs.py --dry-run   # default, lists what would be removed
    python scripts/purge_stale_kb_docs.py --execute    # actually deletes from ChromaDB
"""
import argparse
import sqlite3

from loguru import logger

import config


def find_stale_municipalities(conn: sqlite3.Connection) -> list[dict]:
    """Municipalities whose latest 'done' run completed before geo_scores.computed_at."""
    rows = conn.execute(
        """SELECT m.id AS municipality_id, m.name, m.province
           FROM municipalities m
           JOIN geo_scores g ON g.municipality_id = m.id
           JOIN run_results rr ON rr.municipality_id = m.id AND rr.assessment IS NOT NULL
           JOIN runs r ON r.id = rr.run_id AND r.status = 'done'
           GROUP BY m.id
           HAVING MAX(r.completed_at) < g.computed_at"""
    ).fetchall()
    return [dict(r) for r in rows]


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace(",", "").replace(".", "").replace("/", "_")


def stale_doc_ids(collection_ids: list[str], stale: list[dict]) -> list[str]:
    """Chunk ids in the Chroma collection whose muni_slug segment matches a stale municipality.

    Doc ids from agents/kb_builder.py's save_municipality_docs are always
    ``{location_slug}__{muni_slug}__{run_id}`` (chunk ids append ``_chunk_N`` to the
    run_id segment). location_slug is derived from the caller-supplied `location`
    string (e.g. "Daraga, Albay" -> "daraga_albay"), which is NOT reliably the
    municipality's province column, so we must not match on it. Instead, split on
    "__" and match the middle segment (always the muni_slug) against the stale
    municipality's name-slug.
    """
    stale_muni_slugs = {_slug(m["name"]) for m in stale}
    matched = []
    for cid in collection_ids:
        parts = cid.split("__")
        if len(parts) != 3:
            continue
        _location_slug, muni_slug, _run_chunk = parts
        if muni_slug in stale_muni_slugs:
            matched.append(cid)
    return matched


def main(dry_run: bool = True) -> None:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        stale = find_stale_municipalities(conn)
    finally:
        conn.close()
    logger.info(f"Found {len(stale)} stale-basis municipalities.")

    from agents.chatbot import _get_collection
    collection = _get_collection()
    all_ids = collection.get(include=[])["ids"]
    to_delete = stale_doc_ids(all_ids, stale)
    logger.info(f"{len(to_delete)} ChromaDB chunks match stale municipalities.")

    if dry_run:
        logger.info("Dry run — no deletions made. Re-run with --execute to purge.")
        for cid in to_delete[:20]:
            logger.info(f"  would delete: {cid}")
        return

    if to_delete:
        collection.delete(ids=to_delete)
        logger.info(f"Deleted {len(to_delete)} stale chunks from kb/index.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run).")
    args = parser.parse_args()
    main(dry_run=not args.execute)
