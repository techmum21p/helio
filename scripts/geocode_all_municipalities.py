"""
scripts/geocode_all_municipalities.py

One-time migration: geocode every municipality in helio.db via Nominatim
(agents/geocoder.py, disk-cached) and persist real lat/lon to the
municipalities table.

Why: municipalities in provinces never touched by a pipeline run still carry
hash-based placeholder coordinates from the original precompute INSERT.
Provinces missing from PROVINCE_CENTROIDS (CAR, City of Manila, Special
Geographic Area) defaulted to (12.5, 122.5) — the Sibuyan Sea — which made
the GEE solar fetch sample open water.

Safe to re-run: already-geocoded municipalities hit the cache instantly.
Nominatim rate limit (1.1 s/lookup) means ~1,000 uncached entries take ~20 min.

Usage:
    PYTHONPATH=. python scripts/geocode_all_municipalities.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from agents.geocoder import geocode_units
from scripts.precompute_geo_scores import _municipality_coord


def geocode_all() -> None:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name, province FROM municipalities").fetchall()

    # Fallback = corrected hash placeholder (right province at least),
    # NOT the possibly-wrong coords currently in the DB.
    units = []
    for r in rows:
        lat, lon = _municipality_coord(r["name"], r["province"])
        units.append({"id": r["id"], "name": r["name"], "province": r["province"],
                      "lat": lat, "lon": lon})

    print(f"Geocoding {len(units)} municipalities (cached ones are instant)...")
    geocoded = geocode_units(units)

    for i, u in enumerate(geocoded, 1):
        conn.execute("UPDATE municipalities SET lat=?, lon=? WHERE id=?",
                     (u["lat"], u["lon"], u["id"]))
        if i % 100 == 0 or i == len(geocoded):
            conn.commit()
            print(f"  persisted {i}/{len(geocoded)}", flush=True)

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    geocode_all()
