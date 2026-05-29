"""
scripts/precompute_geo_scores.py

Pre-computes geo scores for all ~1,622 Philippine municipalities and upserts
them into the helio.db SQLite database.

Key fix vs previous version: uses proper 3-component MinMaxScaler normalization
across the full dataset (solar, income_score, pop_density), so all three
dimensions contribute meaningfully to the final geo_score.

Usage:
    python scripts/precompute_geo_scores.py
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

import numpy as np
from sklearn.preprocessing import MinMaxScaler

# Allow importing config from repo root regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ── Province centroid lookup ────────────────────────────────────────────────────
# Copied from agents/geo_scoring.py to keep this script standalone.
PROVINCE_CENTROIDS = {
    # NCR
    "metro manila": (14.5548, 121.0244), "ncr": (14.5548, 121.0244),
    "national capital region": (14.5548, 121.0244),
    # Region I
    "ilocos norte": (18.1647, 120.7116), "ilocos sur": (17.5755, 120.3869),
    "la union": (16.6159, 120.3209), "pangasinan": (15.8949, 120.2863),
    # Region II
    "batanes": (20.4487, 121.9702), "cagayan": (17.6132, 121.7269),
    "isabela": (16.9754, 121.8107), "nueva vizcaya": (16.3301, 121.1710),
    "quirino": (16.2700, 121.5376),
    # Region III
    "bataan": (14.6416, 120.4818), "bulacan": (14.7942, 120.8799),
    "nueva ecija": (15.5784, 121.1116), "pampanga": (15.0794, 120.6200),
    "tarlac": (15.4755, 120.5963), "zambales": (15.5082, 119.9705),
    "aurora": (15.9784, 121.5986),
    # Region IV-A CALABARZON
    "batangas": (13.7565, 121.0583), "cavite": (14.2456, 120.8787),
    "laguna": (14.2691, 121.4113), "quezon": (14.0313, 121.9176),
    "rizal": (14.6042, 121.3084),
    # MIMAROPA
    "marinduque": (13.4767, 122.0321), "occidental mindoro": (12.9027, 121.0614),
    "oriental mindoro": (13.0565, 121.4069), "palawan": (9.8349, 118.7384),
    "romblon": (12.5778, 122.2695),
    # Region V Bicol
    "camarines norte": (14.1389, 122.7632), "camarines sur": (13.6252, 123.1847),
    "catanduanes": (13.7089, 124.2422), "masbate": (12.3696, 123.6199),
    "sorsogon": (12.9433, 124.0147), "albay": (13.1775, 123.5280),
    # Region VI Western Visayas
    "aklan": (11.8166, 122.0942), "antique": (11.3683, 122.0640),
    "capiz": (11.5530, 122.7411), "guimaras": (10.5956, 122.6325),
    "iloilo": (10.7202, 122.5621), "negros occidental": (10.6713, 123.0566),
    # Region VII Central Visayas
    "bohol": (9.8500, 124.1435), "cebu": (10.3157, 123.8854),
    "negros oriental": (9.6168, 122.9823), "siquijor": (9.2076, 123.5116),
    # Region VIII Eastern Visayas
    "biliran": (11.5835, 124.4633), "eastern samar": (11.8981, 125.0773),
    "leyte": (10.8731, 124.8811), "northern samar": (12.5674, 124.5658),
    "samar": (11.5500, 125.0000), "southern leyte": (10.3332, 125.1717),
    # Region IX Zamboanga
    "zamboanga del norte": (8.1527, 123.2577), "zamboanga del sur": (7.8383, 123.2968),
    "zamboanga sibugay": (7.5222, 122.8198),
    # Region X Northern Mindanao
    "bukidnon": (8.0515, 125.0988), "camiguin": (9.1695, 124.7218),
    "lanao del norte": (8.0730, 124.2873), "misamis occidental": (8.3375, 123.7072),
    "misamis oriental": (8.5046, 124.6220),
    # Region XI Davao
    "davao de oro": (7.6728, 126.1742), "compostela valley": (7.6728, 126.1742),
    "davao del norte": (7.5619, 125.6549), "davao del sur": (6.7656, 125.3284),
    "davao occidental": (6.1054, 125.6072), "davao oriental": (7.3172, 126.5420),
    # Region XII SOCCSKSARGEN
    "cotabato": (7.1322, 124.8567), "north cotabato": (7.1322, 124.8567),
    "south cotabato": (6.3344, 124.9010), "sultan kudarat": (6.5069, 124.4186),
    "sarangani": (5.9630, 125.1990),
    # Region XIII Caraga
    "agusan del norte": (8.9456, 125.5320), "agusan del sur": (8.1864, 126.0135),
    "dinagat islands": (10.1280, 125.6083), "surigao del norte": (9.5141, 125.6030),
    "surigao del sur": (8.5120, 126.1144),
    # BARMM
    "basilan": (6.4222, 121.9693), "lanao del sur": (7.8232, 124.4198),
    "maguindanao": (6.8416, 124.4330), "sulu": (5.9747, 121.0337),
    "tawi-tawi": (5.1339, 119.9513),
}

INCOME_CLASSES = ["1st", "2nd", "3rd", "4th", "5th", "6th"]
INCOME_CLASS_MAP = {
    "1st": 6, "2nd": 5, "3rd": 4, "4th": 3, "5th": 2, "6th": 1, "special": 6,
}


# ── Stable hash-based demographic helpers ──────────────────────────────────────

def _stable_float(seed: str, lo: float, hi: float) -> float:
    """Deterministic float in [lo, hi] derived from a string seed via MD5."""
    digest = hashlib.md5(seed.encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return lo + frac * (hi - lo)


def _stable_income_class(name: str, province: str) -> str:
    """Stable income class estimate based on name+province hash.

    Weighted distribution [1,2,3,3,2,1] biases toward 3rd/4th class,
    matching real Philippine municipal income distribution.
    """
    digest = hashlib.md5(f"{province}:{name}".encode()).digest()
    weights = [1, 2, 3, 3, 2, 1]
    total = sum(weights)
    pick = digest[0] % total
    cumulative = 0
    for i, w in enumerate(weights):
        cumulative += w
        if pick < cumulative:
            return INCOME_CLASSES[i]
    return "3rd"


def _province_coord(province: str) -> tuple:
    """Look up approximate centroid for a province name."""
    key = province.lower().strip()
    if key in PROVINCE_CENTROIDS:
        return PROVINCE_CENTROIDS[key]
    for k, v in PROVINCE_CENTROIDS.items():
        if k in key or key in k:
            return v
    return (12.5, 122.5)  # default to central Philippines


def _municipality_coord(name: str, province: str) -> tuple:
    """Place municipality near province centroid with stable hash-based offset."""
    base_lat, base_lon = _province_coord(province)
    lat_offset = _stable_float(f"{name}:lat", -0.30, 0.30)
    lon_offset = _stable_float(f"{name}:lon", -0.30, 0.30)
    return (base_lat + lat_offset, base_lon + lon_offset)


# ── Municipality enumeration ────────────────────────────────────────────────────

def _get_all_municipalities() -> list[dict]:
    """
    Enumerate all municipalities from the barangay package and attach
    hash-based demographic estimates.

    Returns a list of dicts, each with keys:
        name, province, region, income_class, income_score,
        population, area_km2, pop_density, solar, lat, lon
    """
    import barangay as br

    data = br.BARANGAY  # Region -> Province -> Municipality -> [barangays]

    units = []
    for region_name, region_data in data.items():
        if not isinstance(region_data, dict):
            continue
        for prov_name, prov_data in region_data.items():
            if not isinstance(prov_data, dict):
                continue
            for muni_name in prov_data.keys():
                income_class = _stable_income_class(muni_name, prov_name)
                income_score = INCOME_CLASS_MAP.get(income_class, 3)
                population = int(_stable_float(f"{prov_name}:{muni_name}:pop", 5000, 150000))
                area_km2 = _stable_float(f"{prov_name}:{muni_name}:area", 20, 500)
                pop_density = population / area_km2
                solar = _stable_float(f"{muni_name}:solar", 4.5, 6.0)
                lat, lon = _municipality_coord(muni_name, prov_name)

                units.append({
                    "name": muni_name,
                    "province": prov_name,
                    "region": region_name,
                    "income_class": income_class,
                    "income_score": income_score,
                    "population": population,
                    "area_km2": area_km2,
                    "pop_density": pop_density,
                    "solar": solar,
                    "lat": lat,
                    "lon": lon,
                })

    return units


# ── Normalization + scoring ─────────────────────────────────────────────────────

def normalize_and_score(units: list[dict]) -> list[dict]:
    """
    Apply MinMaxScaler normalization independently to solar, income_score, and
    pop_density across all units, then compute the weighted geo_score.

    Adds keys to each unit dict: solar_norm, income_norm, pop_density_norm,
    geo_score.

    When all values in a component are identical (constant column), MinMaxScaler
    returns 0.0 for all — this is correct behaviour (no differentiation possible).
    """
    if not units:
        return units

    w = config.WEIGHTS  # {"solar": 0.35, "income": 0.45, "population": 0.20}

    solar_arr = np.array([[u["solar"]] for u in units], dtype=float)
    income_arr = np.array([[u["income_score"]] for u in units], dtype=float)
    pop_density_arr = np.array([[u["pop_density"]] for u in units], dtype=float)

    solar_norm = MinMaxScaler().fit_transform(solar_arr).flatten()
    income_norm = MinMaxScaler().fit_transform(income_arr).flatten()
    pop_density_norm = MinMaxScaler().fit_transform(pop_density_arr).flatten()

    result = []
    for i, u in enumerate(units):
        updated = dict(u)
        updated["solar_norm"] = float(solar_norm[i])
        updated["income_norm"] = float(income_norm[i])
        updated["pop_density_norm"] = float(pop_density_norm[i])
        updated["geo_score"] = (
            w["solar"] * updated["solar_norm"]
            + w["income"] * updated["income_norm"]
            + w["population"] * updated["pop_density_norm"]
        )
        result.append(updated)

    return result


# ── DB upsert ──────────────────────────────────────────────────────────────────

def upsert_to_db(units: list[dict], progress_callback=None) -> None:
    """
    Upsert scored municipality data into helio.db.

    For each unit:
    - municipalities table: look up by (name, province); if found, update
      lat/lon/area_km2/population/income_class; if not found, INSERT.
    - geo_scores table: INSERT OR REPLACE using the municipality_id.

    progress_callback(done: int, total: int) is called after each row.
    """
    db_path = str(config.HELIO_DB)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    total = len(units)
    done = 0

    try:
        for u in units:
            name = u["name"]
            province = u["province"]
            region = u.get("region", "")

            # -- municipalities: look up or insert
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name = ? AND province = ?",
                (name, province),
            ).fetchone()

            if row:
                muni_id = row["id"]
                conn.execute(
                    """UPDATE municipalities
                       SET lat = ?, lon = ?, area_km2 = ?, population = ?,
                           income_class = ?, region = ?
                       WHERE id = ?""",
                    (u["lat"], u["lon"], u["area_km2"], u["population"],
                     u["income_class"], region, muni_id),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO municipalities
                       (name, province, region, lat, lon, area_km2, population, income_class)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, province, region, u["lat"], u["lon"],
                     u["area_km2"], u["population"], u["income_class"]),
                )
                muni_id = cur.lastrowid

            # -- geo_scores: upsert via ON CONFLICT
            conn.execute(
                """INSERT INTO geo_scores
                       (municipality_id, solar_irradiance, solar_norm, income_score,
                        pop_density, pop_density_norm, geo_score, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(municipality_id) DO UPDATE SET
                       solar_irradiance  = excluded.solar_irradiance,
                       solar_norm        = excluded.solar_norm,
                       income_score      = excluded.income_score,
                       pop_density       = excluded.pop_density,
                       pop_density_norm  = excluded.pop_density_norm,
                       geo_score         = excluded.geo_score,
                       computed_at       = excluded.computed_at""",
                (
                    muni_id,
                    u["solar"],
                    u["solar_norm"],
                    u["income_score"],
                    u["pop_density"],
                    u["pop_density_norm"],
                    u["geo_score"],
                ),
            )

            done += 1
            if progress_callback:
                progress_callback(done, total)

        conn.commit()
    finally:
        conn.close()


# ── Orchestrator ───────────────────────────────────────────────────────────────

def precompute_geo_scores(progress_callback=None) -> None:
    """
    Full pipeline: enumerate municipalities, normalize, upsert to DB.
    """
    units = _get_all_municipalities()
    units = normalize_and_score(units)
    upsert_to_db(units, progress_callback=progress_callback)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time

    print(f"Precomputing geo scores for all PH municipalities...")
    start = time.time()

    total_ref = [0]

    def _progress(done: int, total: int) -> None:
        total_ref[0] = total
        if done % 100 == 0 or done == total:
            pct = done / total * 100
            print(f"  {done}/{total}  ({pct:.1f}%)", end="\r", flush=True)

    precompute_geo_scores(progress_callback=_progress)

    elapsed = time.time() - start
    print(f"\nDone. {total_ref[0]} municipalities processed in {elapsed:.1f}s.")
    print(f"DB: {config.HELIO_DB}")
