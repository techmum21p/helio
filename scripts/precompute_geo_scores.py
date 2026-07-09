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
import re
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
    "city of manila": (14.5995, 120.9842),
    # CAR
    "abra": (17.5951, 120.7983), "apayao": (18.0126, 121.1710),
    "benguet": (16.5500, 120.6800), "ifugao": (16.8331, 121.1710),
    "kalinga": (17.4740, 121.3542), "mountain province": (17.0700, 121.0300),
    # BARMM Special Geographic Area (barangays in the Cotabato area)
    "special geographic area": (7.0500, 124.6000),
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

# ── Highly Urbanized Cities (HUCs) ──────────────────────────────────────────────
# See agents/geo_scoring.py for the full explanation: in the `barangay` package,
# HUCs sit at the province level but hold a flat barangay list, not a dict of
# municipalities — every loader that checks `isinstance(prov_data, dict)` was
# silently skipping all 33 of them (Quezon City, Cebu City, Davao City, etc.).
HUC_NOT_A_PROVINCE_SUFFIX = " (Not a Province)"

HUC_CENTROIDS = {
    "city of baguio": (16.4023, 120.5960), "city of puerto princesa": (9.7392, 118.7353),
    "city of caloocan": (14.6499, 120.9833), "city of las piñas": (14.4499, 120.9829),
    "city of makati": (14.5547, 121.0244), "city of malabon": (14.6681, 120.9569),
    "city of mandaluyong": (14.5794, 121.0359), "city of marikina": (14.6507, 121.1029),
    "city of muntinlupa": (14.4081, 121.0415), "city of navotas": (14.6667, 120.9437),
    "city of parañaque": (14.4793, 121.0198), "city of pasig": (14.5764, 121.0851),
    "city of san juan": (14.6019, 121.0355), "city of taguig": (14.5176, 121.0509),
    "city of valenzuela": (14.7011, 120.9830), "pasay city": (14.5378, 121.0014),
    "quezon city": (14.6760, 121.0437), "pateros": (14.5441, 121.0685),
    "city of bacolod": (10.6713, 122.9511), "city of angeles": (15.1450, 120.5930),
    "city of olongapo": (14.8294, 120.2825), "city of lucena": (13.9314, 121.6165),
    "city of zamboanga": (6.9214, 122.0790), "city of iloilo": (10.7202, 122.5621),
    "city of cebu": (10.3157, 123.8854), "city of lapu-lapu": (10.3103, 123.9494),
    "city of mandaue": (10.3236, 123.9227), "city of tacloban": (11.2543, 125.0000),
    "city of cagayan de oro": (8.4822, 124.6472), "city of iligan": (8.2280, 124.2452),
    "city of davao": (7.0722, 125.6131), "city of general santos": (6.1164, 125.1716),
    "city of butuan": (8.9475, 125.5406),
}


def _huc_province(name: str) -> str:
    return f"{name}{HUC_NOT_A_PROVINCE_SUFFIX}"


for _huc_name, _coord in HUC_CENTROIDS.items():
    PROVINCE_CENTROIDS[_huc_province(_huc_name).lower()] = _coord
del _huc_name, _coord


INCOME_CLASSES = ["1st", "2nd", "3rd", "4th", "5th", "6th"]
INCOME_CLASS_MAP = {
    "1st": 6, "2nd": 5, "3rd": 4, "4th": 3, "5th": 2, "6th": 1, "special": 6,
}


# ── GEE initialization ─────────────────────────────────────────────────────────

def _init_gee():
    """Initialize Google Earth Engine. Returns ee module or None."""
    try:
        import ee
        try:
            ee.Initialize(project=config.GEE_PROJECT_ID)
        except Exception:
            ee.Authenticate()
            ee.Initialize(project=config.GEE_PROJECT_ID)
        print("GEE initialized.")
        return ee
    except ImportError:
        return None
    except Exception:
        return None


def fetch_gee_irradiance_batch(ee, units: list[dict]) -> dict:
    """
    Fetch mean annual solar irradiance for a batch of municipalities via GEE reduceRegions.

    Returns {"province:name": kwh_per_day_or_None} for all units in the batch.
    None means GEE had no data for that location (caller should fall back).

    Three passes, because ERA5-Land is masked over water and its coastal fringe
    pixels hold artificially low values (a lakeside buffer mean reads ~1.6 kWh
    where the true value is ~5.0):
      1. exact point sample (accurate; null if the point lands on a masked pixel)
      2. 11 km buffer with Reducer.max() — picks the nearest clean land pixel
      3. 25 km buffer with Reducer.max() — small offshore islands

    NOTE: reduceRegions names its output property after the *reducer* ("mean",
    "max"), not after the input band — reading the band name here silently
    returns null for every feature.
    """
    dataset = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate("2023-01-01", "2023-12-31")
        .select("surface_solar_radiation_downwards_sum")
        .mean()
    )

    result: dict = {}
    remaining = list(units)

    passes = [
        (None,   ee.Reducer.mean(), "mean"),
        (11000,  ee.Reducer.max(),  "max"),
        (25000,  ee.Reducer.max(),  "max"),
    ]

    for buffer_m, reducer, prop in passes:
        if not remaining:
            break
        by_key = {f"{u['province']}:{u['name']}": u for u in remaining}
        features = []
        for u in remaining:
            geom = ee.Geometry.Point([u["lon"], u["lat"]])
            if buffer_m:
                geom = geom.buffer(buffer_m)
            features.append(ee.Feature(geom, {"name": u["name"], "province": u["province"]}))

        result_fc = dataset.reduceRegions(
            collection=ee.FeatureCollection(features),
            reducer=reducer,
            scale=11132,
        ).getInfo()

        next_remaining = []
        for feat in result_fc.get("features", []):
            props = feat.get("properties", {})
            key   = f"{props.get('province', '')}:{props.get('name', '')}"
            if key not in by_key:
                continue
            raw = props.get(prop)
            if raw is not None and float(raw) > 0:
                result[key] = float(raw) / 3_600_000
            else:
                next_remaining.append(by_key[key])
        remaining = next_remaining

    for u in remaining:
        result[f"{u['province']}:{u['name']}"] = None

    return result


def _load_db_coords() -> dict:
    """
    Return {"province:name" -> (lat, lon)} from the municipalities table.
    DB coordinates are the best available (Nominatim-geocoded where a pipeline
    run has touched the province) — always at least as good as the hash-based
    placeholder from _municipality_coord().
    """
    if not config.HELIO_DB.exists():
        return {}
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT name, province, lat, lon FROM municipalities
               WHERE lat IS NOT NULL AND lon IS NOT NULL"""
        ).fetchall()
        return {f"{r['province']}:{r['name']}": (r["lat"], r["lon"]) for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def _load_existing_solar() -> dict:
    """
    Return {"province:name" -> solar_irradiance} for rows where
    geo_scores.solar_irradiance IS NOT NULL, enabling resume of interrupted runs.
    """
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT m.name, m.province, g.solar_irradiance
               FROM geo_scores g
               JOIN municipalities m ON m.id = g.municipality_id
               WHERE g.solar_irradiance IS NOT NULL"""
        ).fetchall()
        return {f"{r['province']}:{r['name']}": r["solar_irradiance"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def _upsert_solar_batch(conn: sqlite3.Connection, units: list[dict]) -> None:
    """Write solar_irradiance to geo_scores for a batch; commits immediately.

    Synthetic fallback values are never written — solar_irradiance in the DB
    must only ever hold real GEE data, otherwise the resume logic
    (_load_existing_solar) would treat fabricated values as already-fetched
    and skip GEE for them forever.
    """
    for u in units:
        if u.get("solar") is None or u.get("solar_synthetic"):
            continue
        row = conn.execute(
            "SELECT id FROM municipalities WHERE name=? AND province=?",
            (u["name"], u["province"]),
        ).fetchone()
        if row is None:
            continue
        muni_id = row[0]
        conn.execute(
            """INSERT INTO geo_scores (municipality_id, solar_irradiance, computed_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(municipality_id) DO UPDATE SET
                   solar_irradiance = excluded.solar_irradiance,
                   computed_at      = excluded.computed_at""",
            (muni_id, u["solar"]),
        )
    conn.commit()


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


# ── Real PSA data (income classification + 2024 census population) ─────────────

PSA_CSV_PATH = Path(__file__).parent.parent / "data" / "raw" / "psa_income_population.csv"

_PSA_INCOME_TO_CLASS = {
    "1st": "1st", "2nd": "2nd", "3rd": "3rd",
    "4th": "4th", "5th": "5th", "6th": "6th",
}


def _load_psa_lookup() -> dict:
    """
    Load real PSA income classification + 2024 census population, keyed by
    (normalized_name, normalized_province). Returns {} if the CSV hasn't been
    fetched yet (run scripts/fetch_psa_data.py first).
    """
    if not PSA_CSV_PATH.exists():
        print(f"WARNING: {PSA_CSV_PATH} not found — run scripts/fetch_psa_data.py first. "
              f"Falling back to synthetic demographics for all municipalities.")
        return {}

    import pandas as pd
    df = pd.read_csv(PSA_CSV_PATH)

    lookup = {}
    for _, row in df.iterrows():
        name = str(row["name"]).strip()
        province = str(row["province"]).strip() if pd.notna(row["province"]) else ""
        key = (name.lower(), province.lower())
        # PSA appends footnote markers to a handful of entries (e.g. "4th*" for
        # a recently-reclassified LGU) — strip any trailing non-alphanumeric
        # characters so these still match "4th" instead of silently falling
        # through to the synthetic fallback. Confirmed exactly 6 affected rows
        # in the Q1 2026 release (Tipo-Tipo, Mankayan, Alfonso Castaneda,
        # Arteche, Lugait, Sultan Sa Barongis) — all have real data, this was
        # a pure string-matching bug, not a genuine PSA gap.
        raw_classification = str(row["income_classification"]).strip()
        clean_classification = re.sub(r"[^0-9a-zA-Z]+$", "", raw_classification)
        income_class = _PSA_INCOME_TO_CLASS.get(clean_classification)
        population = int(row["population_2024"]) if pd.notna(row["population_2024"]) else None
        lookup[key] = {"income_class": income_class, "population": population}
    return lookup


def _match_psa_record(psa_lookup: dict, psa_by_province: dict, muni_name: str, prov_name: str) -> dict | None:
    """Exact match first, then fuzzy match within the same province.

    HUCs (province ends with " (Not a Province)") aren't part of any province
    in the PSA data either — it stores them with an empty/NaN province — so
    they're matched against the name-only key (name, "") instead.
    """
    if prov_name.endswith(HUC_NOT_A_PROVINCE_SUFFIX):
        return psa_lookup.get((muni_name.lower(), ""))

    key = (muni_name.lower(), prov_name.lower())
    if key in psa_lookup:
        return psa_lookup[key]

    from rapidfuzz import process as rfprocess
    candidates = psa_by_province.get(prov_name.lower())
    if not candidates:
        return None
    result = rfprocess.extractOne(muni_name.lower(), list(candidates.keys()), score_cutoff=85)
    if result:
        return candidates[result[0]]
    return None


# ── Real land area (geoBoundaries ADM3, point-in-polygon matched) ──────────────

AREA_CSV_PATH = Path(__file__).parent.parent / "data" / "raw" / "municipality_land_area.csv"


def _load_area_lookup() -> dict:
    """
    Load real land area (km²) computed by scripts/fetch_land_area.py, keyed by
    (normalized_name, normalized_province). Returns {} if the CSV hasn't been
    generated yet (run scripts/fetch_land_area.py first).

    Already matched by point-in-polygon against our own geocoded coordinates
    (not by name), so this is an exact-key lookup — no fuzzy fallback needed,
    unlike the PSA income/population match.
    """
    if not AREA_CSV_PATH.exists():
        print(f"WARNING: {AREA_CSV_PATH} not found — run scripts/fetch_land_area.py first. "
              f"Falling back to synthetic land area for all municipalities.")
        return {}

    import pandas as pd
    df = pd.read_csv(AREA_CSV_PATH)
    return {
        (str(row["name"]).strip().lower(), str(row["province"]).strip().lower()): float(row["area_km2"])
        for _, row in df.iterrows()
    }


# ── Municipality enumeration ────────────────────────────────────────────────────

def _get_all_municipalities() -> list[dict]:
    """
    Enumerate all municipalities from the barangay package and attach real PSA
    demographics (income classification + 2024 census population) where a match
    is found; falls back to hash-based synthetic estimates otherwise.

    Returns a list of dicts, each with keys:
        name, province, region, income_class, income_score,
        population, area_km2, pop_density, solar, lat, lon
    """
    import barangay as br

    data = br.BARANGAY  # Region -> Province -> Municipality -> [barangays]

    psa_lookup = _load_psa_lookup()
    psa_by_province: dict = {}
    for (name, province), rec in psa_lookup.items():
        psa_by_province.setdefault(province, {})[name] = rec

    area_lookup = _load_area_lookup()
    area_matched = [0]

    def _build_record(muni_name: str, prov_name: str, region_name: str) -> dict:
        psa_rec = _match_psa_record(psa_lookup, psa_by_province, muni_name, prov_name) if psa_lookup else None

        if psa_rec and psa_rec.get("income_class"):
            income_class = psa_rec["income_class"]
        else:
            income_class = _stable_income_class(muni_name, prov_name)

        if psa_rec and psa_rec.get("population"):
            population = psa_rec["population"]
        else:
            population = int(_stable_float(f"{prov_name}:{muni_name}:pop", 5000, 150000))

        area_rec = area_lookup.get((muni_name.lower(), prov_name.lower()))
        if area_rec:
            area_km2 = area_rec
            area_matched[0] += 1
        else:
            area_km2 = _stable_float(f"{prov_name}:{muni_name}:area", 20, 500)

        income_score = INCOME_CLASS_MAP.get(income_class, 3)
        pop_density = population / area_km2
        lat, lon = _municipality_coord(muni_name, prov_name)

        return {
            "name": muni_name,
            "province": prov_name,
            "region": region_name,
            "income_class": income_class,
            "income_score": income_score,
            "population": population,
            "area_km2": area_km2,
            "pop_density": pop_density,
            "solar": None,  # filled by GEE in precompute_geo_scores()
            "lat": lat,
            "lon": lon,
        }, psa_rec is not None

    matched_count = 0
    units = []
    for region_name, region_data in data.items():
        if not isinstance(region_data, dict):
            continue
        for prov_name, prov_data in region_data.items():
            if isinstance(prov_data, dict):
                for muni_name in prov_data.keys():
                    record, matched = _build_record(muni_name, prov_name, region_name)
                    units.append(record)
                    matched_count += matched
            else:
                # HUC: province-level entry is itself a single municipality.
                record, matched = _build_record(prov_name, _huc_province(prov_name), region_name)
                units.append(record)
                matched_count += matched

    if psa_lookup:
        print(f"PSA data matched: {matched_count} / {len(units)} municipalities "
              f"(real income_class + population; unmatched fall back to synthetic).")
    if area_lookup:
        print(f"Real land area matched: {area_matched[0]} / {len(units)} municipalities "
              f"(geoBoundaries point-in-polygon; unmatched fall back to synthetic).")

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

    pop_density is log1p-transformed before MinMax scaling. Raw density is
    heavy-tailed (a handful of dense cities vs. a long tail of rural
    municipalities) — plain MinMax on the raw values let a single outlier
    (City of Bacoor at ~28,000/km² on the old fake-area data) crush ~96% of
    municipalities into pop_density_norm < 0.05, making the 20% population
    weight contribute almost nothing. log1p compresses the tail so the
    component actually differentiates.
    """
    if not units:
        return units

    w = config.WEIGHTS  # {"solar": 0.35, "income": 0.45, "population": 0.20}

    solar_arr = np.array([[u["solar"]] for u in units], dtype=float)
    income_arr = np.array([[u["income_score"]] for u in units], dtype=float)
    pop_density_arr = np.log1p(np.array([[u["pop_density"]] for u in units], dtype=float))

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
                # Demographics only — never overwrite lat/lon here. Real coordinates
                # come from agents/geocoder.py (Nominatim) during pipeline runs;
                # this script's lat/lon is a hash-based placeholder that would
                # clobber real geocoded positions on existing rows.
                conn.execute(
                    """UPDATE municipalities
                       SET area_km2 = ?, population = ?,
                           income_class = ?, region = ?
                       WHERE id = ?""",
                    (u["area_km2"], u["population"],
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
                    # NULL for synthetic — solar_irradiance holds real GEE data only,
                    # so future resume/audit can distinguish real from fabricated
                    None if u.get("solar_synthetic") else u["solar"],
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
    Full pipeline: enumerate municipalities → fetch real GEE irradiance in batches
    → normalize → upsert to DB.

    Exits with error if GEE is not authenticated (never silently uses synthetic values
    during a deliberate precompute run).
    Resumes interrupted runs: skips municipalities that already have solar_irradiance in DB.
    """
    import time

    ee = _init_gee()
    if ee is None:
        print("ERROR: GEE initialization failed.")
        print("Run: earthengine authenticate && earthengine set_project <project-id>")
        sys.exit(1)

    units = _get_all_municipalities()  # solar=None for all

    # Use best-available coordinates from DB (Nominatim-geocoded where runs
    # have touched the province) instead of hash-based placeholders — the GEE
    # fetch samples irradiance at these points.
    db_coords = _load_db_coords()
    coords_used = 0
    for u in units:
        coord = db_coords.get(f"{u['province']}:{u['name']}")
        if coord:
            u["lat"], u["lon"] = coord
            coords_used += 1
    print(f"Using DB coordinates for {coords_used}/{len(units)} municipalities.")

    # Resume: fill in already-fetched solar values
    existing = _load_existing_solar()
    for u in units:
        key = f"{u['province']}:{u['name']}"
        if key in existing:
            u["solar"] = existing[key]

    to_fetch      = [u for u in units if u["solar"] is None]
    total_batches = (len(to_fetch) + 199) // 200

    if to_fetch:
        db_conn = sqlite3.connect(str(config.HELIO_DB))
        db_conn.row_factory = sqlite3.Row
        try:
            for batch_idx in range(0, len(to_fetch), 200):
                batch     = to_fetch[batch_idx : batch_idx + 200]
                batch_num = batch_idx // 200 + 1
                range_str = f"{batch[0]['name']} … {batch[-1]['name']}"
                t0        = time.time()
                print(f"  Batch {batch_num}/{total_batches}: {len(batch)} munis ({range_str})")

                try:
                    gee_results = fetch_gee_irradiance_batch(ee, batch)
                except Exception as exc:
                    print(f"    WARNING: batch {batch_num} GEE call failed ({exc}); using synthetic fallback")
                    gee_results = {}

                for u in batch:
                    key = f"{u['province']}:{u['name']}"
                    val = gee_results.get(key)
                    if val is not None and val > 0:
                        u["solar"] = val
                    else:
                        # leave None — filled with the province mean of real GEE
                        # values after all batches complete
                        print(f"    WARNING: GEE returned null for {key}; will use province-mean fallback")

                _upsert_solar_batch(db_conn, batch)
                elapsed = time.time() - t0
                print(f"    Done in {elapsed:.1f}s")
                time.sleep(1)
        finally:
            db_conn.close()
    else:
        print("All municipalities already have GEE solar data. Skipping fetch.")

    # Fill remaining None with the province mean of real GEE values —
    # neighbouring municipalities share climate, unlike a hash-based value
    # which can exceed the real national maximum and distort rankings.
    # These estimates are scored but persisted as NULL (solar_synthetic).
    real_by_province: dict = {}
    for u in units:
        if u["solar"] is not None and not u.get("solar_synthetic"):
            real_by_province.setdefault(u["province"], []).append(u["solar"])
    prov_mean = {p: sum(v) / len(v) for p, v in real_by_province.items()}
    all_real = [s for v in real_by_province.values() for s in v]
    national_mean = sum(all_real) / len(all_real) if all_real else 5.0

    for u in units:
        if u["solar"] is None:
            u["solar"] = prov_mean.get(u["province"], national_mean)
            u["solar_synthetic"] = True

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
