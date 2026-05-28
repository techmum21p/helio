#!/usr/bin/env python3
"""
One-time script to populate data/ph_locations.db from the barangay package.
Run once: python scripts/build_location_db.py
Idempotent — skips if municipalities table already has rows.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS regions (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS provinces (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(id)
);
CREATE TABLE IF NOT EXISTS municipalities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    province_id INTEGER NOT NULL REFERENCES provinces(id)
);
CREATE TABLE IF NOT EXISTS barangays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id)
);
CREATE INDEX IF NOT EXISTS idx_provinces_region    ON provinces(region_id);
CREATE INDEX IF NOT EXISTS idx_municipalities_prov ON municipalities(province_id);
CREATE INDEX IF NOT EXISTS idx_barangays_muni      ON barangays(municipality_id);
"""


def build(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    count = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
    if count > 0:
        print(f"Already built ({count} municipalities). Delete {db_path} to rebuild.")
        conn.close()
        return

    import barangay as br
    data = br.BARANGAY

    region_count = prov_count = muni_count = brgy_count = 0

    with conn:
        for region_name, region_data in data.items():
            if not isinstance(region_data, dict):
                continue
            cur = conn.execute("INSERT INTO regions (name) VALUES (?)", (region_name,))
            region_id = cur.lastrowid
            region_count += 1

            for prov_name, prov_data in region_data.items():
                if not isinstance(prov_data, dict):
                    continue
                cur = conn.execute(
                    "INSERT INTO provinces (name, region_id) VALUES (?, ?)",
                    (prov_name, region_id),
                )
                prov_id = cur.lastrowid
                prov_count += 1

                for muni_name, barangays in prov_data.items():
                    cur = conn.execute(
                        "INSERT INTO municipalities (name, province_id) VALUES (?, ?)",
                        (muni_name, prov_id),
                    )
                    muni_id = cur.lastrowid
                    muni_count += 1

                    if isinstance(barangays, list):
                        conn.executemany(
                            "INSERT INTO barangays (name, municipality_id) VALUES (?, ?)",
                            [(b, muni_id) for b in barangays],
                        )
                        brgy_count += len(barangays)

    print(
        f"Built: {region_count} regions, {prov_count} provinces, "
        f"{muni_count} municipalities, {brgy_count} barangays"
    )
    conn.close()


if __name__ == "__main__":
    build(config.LOCATION_DB)
