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
from pathlib import Path

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


def _stale_index(stale: list[dict]) -> dict[str, str]:
    """Map municipality name-slug -> province-slug, for the stale municipality set."""
    return {_slug(m["name"]): _slug(m["province"]) for m in stale}


def _doc_key_matches_stale(doc_key: str, stale_index: dict[str, str]) -> bool:
    """True if a ``{location_slug}__{muni_slug}__{run_id}`` doc id or kb/intel
    filename stem (chunk ids append ``_chunk_N`` to the run_id segment; that
    trailing suffix is irrelevant here since we only look at the first two
    segments) belongs to one of the stale municipalities.

    Doc ids/filenames from agents/kb_builder.py's save_municipality_docs are
    always ``{location_slug}__{muni_slug}__{run_id}``. location_slug is derived
    from the caller-supplied `location` string, which for every doc-generation
    path still active on this branch is the bare province name (e.g.
    "Albay" -> "albay") — but historical pre-branch files may instead encode a
    multi-municipality location string (e.g. "Tanay|San Mateo, Rizal" ->
    "tanay_san-mateo_rizal").

    Matching requires BOTH:
      (a) the middle segment equals the stale municipality's name-slug, AND
      (b) the leading location_slug segment either equals that municipality's
          province-slug exactly, or contains the municipality's own name-slug
          as a substring (to still catch the historical multi-muni case).

    This prevents cross-province collisions: the Philippines has many
    duplicate municipality names across provinces (San Isidro, Santa Cruz,
    etc.), so matching on muni_slug alone would incorrectly match a stale
    "San Isidro, Nueva Ecija" against a current "San Isidro, Davao del Sur".
    """
    parts = doc_key.split("__")
    if len(parts) != 3:
        return False
    location_slug, muni_slug, _run_chunk = parts
    province_slug = stale_index.get(muni_slug)
    if province_slug is None:
        return False
    return location_slug == province_slug or muni_slug in location_slug


def stale_doc_ids(collection_ids: list[str], stale: list[dict]) -> list[str]:
    """Chunk ids in the Chroma collection that match a stale municipality (see
    ``_doc_key_matches_stale`` for the matching rule)."""
    stale_index = _stale_index(stale)
    return [cid for cid in collection_ids if _doc_key_matches_stale(cid, stale_index)]


def stale_kb_intel_files(kb_intel_dir: Path, stale: list[dict]) -> list[Path]:
    """kb/intel/*.md files whose filename stem matches a stale municipality,
    using the exact same matching rule as ``stale_doc_ids`` (see
    ``_doc_key_matches_stale``) so the file-deletion and ChromaDB-deletion
    criteria stay in lockstep by construction."""
    stale_index = _stale_index(stale)
    return [
        p for p in sorted(Path(kb_intel_dir).glob("*.md"))
        if _doc_key_matches_stale(p.stem, stale_index)
    ]


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
    stale_files = stale_kb_intel_files(config.KB_INTEL, stale)
    logger.info(f"{len(to_delete)} ChromaDB chunks match stale municipalities.")
    logger.info(f"{len(stale_files)} kb/intel/*.md files match stale municipalities.")

    if dry_run:
        logger.info("Dry run — no deletions made. Re-run with --execute to purge.")
        for cid in to_delete[:20]:
            logger.info(f"  would delete chunk: {cid}")
        for p in stale_files[:20]:
            logger.info(f"  would delete file: {p.name}")
        return

    if to_delete:
        collection.delete(ids=to_delete)
        logger.info(f"Deleted {len(to_delete)} stale chunks from kb/index.")

    deleted_files = 0
    for p in stale_files:
        try:
            p.unlink()
            deleted_files += 1
        except OSError as e:
            logger.warning(f"Failed to delete {p}: {e}")
    if deleted_files:
        logger.info(f"Deleted {deleted_files} stale kb/intel/*.md files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run).")
    args = parser.parse_args()
    main(dry_run=not args.execute)
