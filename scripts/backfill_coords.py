"""One-time script: populate municipalities.lat/lon using the same deterministic
coord function used by the geo_scoring agent."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.geo_scoring import _municipality_coord
from api.db import get_db

def main():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, province FROM municipalities WHERE lat IS NULL"
        ).fetchall()
        if not rows:
            print("All municipalities already have coordinates.")
            return
        for r in rows:
            lat, lon = _municipality_coord(r["name"], r["province"])
            conn.execute(
                "UPDATE municipalities SET lat=?, lon=? WHERE id=?",
                (lat, lon, r["id"]),
            )
        print(f"Backfilled {len(rows)} municipalities.")

if __name__ == "__main__":
    main()
