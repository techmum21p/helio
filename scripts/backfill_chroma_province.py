#!/usr/bin/env python3
"""
One-off backfill: add `province` metadata to existing kb/intel chunks in
ChromaDB so search_kb can filter by province. Idempotent — chunks that
already carry province metadata are skipped. Safe to re-run.

Run: python scripts/backfill_chroma_province.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

BATCH = 500


def province_for_source(source: str, slug_map: dict[str, str]) -> str | None:
    """Canonical province for an intel-file source path, else None."""
    if not source or "kb/intel" not in source:
        return None
    stem = Path(source).stem
    return slug_map.get(stem.split("__")[0])


def main() -> None:
    from agents.chatbot import _get_collection
    from agents.chat_tools import province_slug_map

    slug_map = province_slug_map()
    logger.info(f"Loaded {len(slug_map)} province slugs from DB")
    col = _get_collection()
    updated = skipped = unmatched = 0
    offset = 0
    while True:
        page = col.get(include=["metadatas"], limit=BATCH, offset=offset)
        ids, metas = page["ids"], page["metadatas"]
        if not ids:
            break
        upd_ids, upd_metas = [], []
        for cid, meta in zip(ids, metas):
            meta = dict(meta or {})
            if meta.get("province"):
                skipped += 1
                continue
            province = province_for_source(meta.get("source", ""), slug_map)
            if province is None:
                if "kb/intel" in meta.get("source", ""):
                    unmatched += 1
                    logger.warning(f"No province match for {meta.get('source')}")
                else:
                    skipped += 1
                continue
            meta["province"] = province
            upd_ids.append(cid)
            upd_metas.append(meta)
        if upd_ids:
            col.update(ids=upd_ids, metadatas=upd_metas)
            updated += len(upd_ids)
        offset += len(ids)
        logger.info(f"...scanned {offset} chunks (updated so far: {updated})")
    logger.info(f"Backfill complete: updated={updated} skipped={skipped} unmatched={unmatched}")


if __name__ == "__main__":
    main()
