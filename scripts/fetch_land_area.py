"""
scripts/fetch_land_area.py

Fetches real municipality/city boundary polygons for the Philippines from
geoBoundaries (NAMRIA/PSA/OCHA-sourced, CC BY 3.0 IGO) and computes true
geodesic land area for every polygon. Matches each of our municipalities to
its polygon by point-in-polygon (using the real Nominatim-geocoded lat/lon
already in helio.db) rather than by name, because 114 of the 1,647 shapes
share a name with at least one other shape (no province field in the
source data) — point-in-polygon disambiguates correctly where name matching
cannot.

Replaces the `area_km2 = _stable_float(...)` hash-based placeholder in
scripts/precompute_geo_scores.py, which fed a fabricated area into every
pop_density calculation (20% of geo_score weight).

Output: data/raw/municipality_land_area.csv (name, province, area_km2, match_method)

Usage:
    python scripts/fetch_land_area.py [--refresh]
"""

import argparse
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

BOUNDARY_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/"
    "PHL/ADM3/geoBoundaries-PHL-ADM3_simplified.geojson"
)
BOUNDARY_PATH = Path(__file__).parent.parent / "data" / "raw" / "ph_adm3_boundaries_simplified.geojson"
OUTPUT_CSV = Path(__file__).parent.parent / "data" / "raw" / "municipality_land_area.csv"


def _download_boundaries(refresh: bool = False) -> None:
    if BOUNDARY_PATH.exists() and not refresh:
        print(f"Using cached boundaries: {BOUNDARY_PATH}")
        return
    BOUNDARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {BOUNDARY_URL} ...")
    urllib.request.urlretrieve(BOUNDARY_URL, BOUNDARY_PATH)
    print(f"Saved to {BOUNDARY_PATH}")


def _load_municipalities() -> "list[dict]":
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name, province, lat, lon FROM municipalities WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_land_area(refresh: bool = False) -> None:
    import geopandas as gpd
    import pandas as pd
    from pyproj import Geod
    from shapely.geometry import Point

    _download_boundaries(refresh=refresh)

    boundaries = gpd.read_file(BOUNDARY_PATH)
    boundaries = boundaries.set_crs("EPSG:4326", allow_override=True)

    geod = Geod(ellps="WGS84")
    boundaries["area_km2"] = boundaries.geometry.apply(
        lambda geom: abs(geod.geometry_area_perimeter(geom)[0]) / 1_000_000
    )

    munis = _load_municipalities()
    points = gpd.GeoDataFrame(
        munis,
        geometry=[Point(m["lon"], m["lat"]) for m in munis],
        crs="EPSG:4326",
    )

    # Point-in-polygon join — disambiguates duplicate names correctly since it
    # uses actual location, not the (ambiguous) shapeName.
    joined = gpd.sjoin(points, boundaries[["geometry", "area_km2"]], how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]  # a point exactly on a shared border can double-match

    matched = 0
    unmatched_idx = []
    results = []
    for i, row in joined.iterrows():
        if pd.notna(row["area_km2"]):
            results.append({"name": row["name"], "province": row["province"], "area_km2": row["area_km2"], "match_method": "contains"})
            matched += 1
        else:
            unmatched_idx.append(i)

    # Fallback for points that fell just outside every polygon (simplification
    # artifacts / coastal geocoding jitter): nearest polygon centroid.
    if unmatched_idx:
        unmatched_pts = points.loc[unmatched_idx]
        nearest = gpd.sjoin_nearest(unmatched_pts, boundaries[["geometry", "area_km2"]], how="left")
        nearest = nearest[~nearest.index.duplicated(keep="first")]
        for _, row in nearest.iterrows():
            results.append({"name": row["name"], "province": row["province"], "area_km2": row["area_km2"], "match_method": "nearest"})

    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_CSV, index=False)

    n_nearest = (df["match_method"] == "nearest").sum()
    print(f"Matched {matched}/{len(munis)} by point-in-polygon, {n_nearest} by nearest-polygon fallback.")
    print(f"Wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-download boundary data")
    args = parser.parse_args()
    fetch_land_area(refresh=args.refresh)
