"""
Agent 1: Geo + ML Scoring

Data sources:
- barangay       → real PH municipality/city names by province (PSGC April 2026)
- GEE            → solar irradiance (NASA POWER) — remote sensing
- scikit-learn   → normalization + opportunity scoring

Population and income use stable hash-based estimates (consistent per municipality name)
until a census data source is integrated.
"""

import hashlib
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sklearn.preprocessing import MinMaxScaler
from loguru import logger

import config
from graph.state import SolarLeadState


# ── Province centroid lookup ────────────────────────────────────────────────────
# Approximate geographic centroids (lat, lon) for all PH provinces/regions.
# Municipalities are placed near the province centroid with a hash-based offset.
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
# In the `barangay` package, HUCs sit at the *province* level of the
# Region → Province → Municipality dict, but their value is a flat list of
# barangay names (not a nested dict of municipalities) — every other loader in
# this file skips non-dict entries via `isinstance(prov_data, dict)`, so all 33
# HUCs (Quezon City, Cebu City, Davao City, Makati, Baguio, etc.) were silently
# absent from every run. Treated here as a single municipality whose "province"
# is itself, following the same "<Name> (Not a Province)" convention the
# barangay package already uses for City of Isabela.
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


INCOME_CLASS_MAP = {
    "1st": 6, "2nd": 5, "3rd": 4, "4th": 3, "5th": 2, "6th": 1, "special": 6,
}

INCOME_CLASSES = ["1st", "2nd", "3rd", "4th", "5th", "6th"]

# Fixed PH-wide ranges for single-municipality normalization
PH_SOLAR_RANGE  = (4.5, 6.0)      # kWh/m²/day
PH_POP_RANGE    = (5_000, 150_000)
PH_INCOME_RANGE = (1, 6)           # income_score scale


def _normalize_fixed(value: float, lo: float, hi: float) -> float:
    """Normalize value against a fixed range, clamped to [0, 1]."""
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# ── Stable hash-based demographic estimates ────────────────────────────────────

def _stable_float(seed: str, lo: float, hi: float) -> float:
    """Deterministic float in [lo, hi] derived from a string seed."""
    digest = hashlib.md5(seed.encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return lo + frac * (hi - lo)


def _stable_income_class(name: str, province: str) -> str:
    """Stable income class estimate based on name hash."""
    digest = hashlib.md5(f"{province}:{name}".encode()).digest()
    # Bias toward middle classes (3rd/4th most common in PH)
    weights = [1, 2, 3, 3, 2, 1]
    cumulative = 0
    total = sum(weights)
    pick = (digest[0] % total)
    for i, w in enumerate(weights):
        cumulative += w
        if pick < cumulative:
            return INCOME_CLASSES[i]
    return "3rd"


def _province_coord(province: str) -> tuple:
    """Look up approximate centroid for a province name."""
    key = province.lower().strip()
    # Try exact match first, then fuzzy
    if key in PROVINCE_CENTROIDS:
        return PROVINCE_CENTROIDS[key]
    # Partial match
    for k, v in PROVINCE_CENTROIDS.items():
        if k in key or key in k:
            return v
    # Default to central Philippines
    return (12.5, 122.5)


def _municipality_coord(name: str, province: str) -> tuple:
    """Rough hash-based placement — overridden by geocoder.py when pipeline runs."""
    base_lat, base_lon = _province_coord(province)
    lat_offset = _stable_float(f"{name}:lat", -0.30, 0.30)
    lon_offset = _stable_float(f"{name}:lon", -0.30, 0.30)
    return (base_lat + lat_offset, base_lon + lon_offset)


# ── GEE Setup ──────────────────────────────────────────────────────────────────

def _init_gee():
    try:
        import ee
        try:
            ee.Initialize(project=config.GEE_PROJECT_ID)
        except Exception:
            ee.Authenticate()
            ee.Initialize(project=config.GEE_PROJECT_ID)
        logger.info("GEE initialized.")
        return ee
    except ImportError:
        logger.warning("earthengine-api not installed.")
        return None
    except Exception as e:
        logger.warning(f"GEE init failed ({e}). Using synthetic solar fallback.")
        return None


def extract_gee_irradiance(ee, lat: float, lon: float, buffer_m: int = 11000) -> float:
    """
    Returns mean daily solar irradiance in kWh/m²/day using ERA5-Land.
    ERA5-Land ECMWF/ERA5_LAND/DAILY_AGGR band surface_solar_radiation_downwards_sum
    is in J/m² per day — divide by 3,600,000 to get kWh/m²/day.
    Philippines range: ~4.5–6.0 kWh/m²/day.
    """
    try:
        point = ee.Geometry.Point([lon, lat]).buffer(buffer_m)
        dataset = (
            ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
            .filterDate("2023-01-01", "2023-12-31")
            .select("surface_solar_radiation_downwards_sum")
            .mean()
        )
        result = dataset.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=point,
            scale=11132,  # ERA5-Land native resolution (~0.1°)
            maxPixels=1e8,
        ).getInfo()
        value = result.get("surface_solar_radiation_downwards_sum", 0.0)
        kwh_per_day = float(value) / 3_600_000 if value else 0.0
        return kwh_per_day
    except Exception as e:
        logger.warning(f"GEE irradiance failed at ({lat},{lon}): {e}")
        return 0.0


# ── Municipality Loading via barangay package ──────────────────────────────────

def load_municipalities(location: str) -> list[dict]:
    """
    Use the barangay package to get real PH municipality/city names.
    Returns list of dicts: {name, province, region, lat, lon, income_class, population}
    Falls back to synthetic data if lookup fails.
    """
    try:
        import barangay as br
        from rapidfuzz import process as rfprocess

        data = br.BARANGAY  # Region → Province → City/Municipality → [barangays]

        # Build flat index: normalized_name → (level, region_name, province_name, place_data)
        index = {}
        for region_name, region_data in data.items():
            if not isinstance(region_data, dict):
                continue
            # Add region itself
            region_key = region_name.lower()
            index[region_key] = ("region", region_name, None, region_data)
            for prov_name, prov_data in region_data.items():
                if isinstance(prov_data, dict):
                    prov_key = prov_name.lower()
                    index[prov_key] = ("province", region_name, prov_name, prov_data)
                else:
                    # HUC: province-level entry holds a flat barangay list, not a
                    # dict of municipalities — it IS a single municipality.
                    # Index under BOTH the bare name ("quezon city") and the
                    # pseudo-province form ("quezon city (not a province)",
                    # what db_store/run_all_provinces.py actually pass in) so
                    # an exact match always wins. Without the second key, a
                    # short/well-known real province name (Cebu, Iloilo,
                    # Cagayan) can outscore the correct HUC in the fuzzy
                    # fallback below — confirmed live: "City of Cebu (Not a
                    # Province)" fuzzy-matched to Cebu *province* (50 munis)
                    # instead of the HUC, and City of Cagayan De Oro matched
                    # Cagayan province in Luzon, silently burning API calls on
                    # the wrong location entirely.
                    huc_key = prov_name.lower()
                    index[huc_key] = ("huc", region_name, prov_name, None)
                    index[_huc_province(prov_name).lower()] = ("huc", region_name, prov_name, None)

        location_lower = location.lower().strip()
        # Try exact match first
        match_key = None
        if location_lower in index:
            match_key = location_lower
        else:
            result = rfprocess.extractOne(location_lower, list(index.keys()), score_cutoff=60)
            if result:
                match_key = result[0]

        if not match_key:
            logger.warning(f"barangay: no match found for '{location}'")
            return []

        level, region_name, province_name, place_data = index[match_key]

        units = []
        if level == "region":
            for prov_name, prov_data in place_data.items():
                if isinstance(prov_data, dict):
                    for muni_name in prov_data.keys():
                        units.append(_build_unit(muni_name, prov_name, region_name))
                else:
                    units.append(_build_unit(prov_name, _huc_province(prov_name), region_name))
        elif level == "huc":
            units.append(_build_unit(province_name, _huc_province(province_name), region_name))
        else:
            for muni_name in place_data.keys():
                units.append(_build_unit(muni_name, province_name, region_name))

        logger.info(f"barangay: found {len(units)} municipalities under '{location}'.")
        return units

    except Exception as e:
        logger.warning(f"barangay lookup failed for '{location}': {e}")
        return []


def load_single_municipality(town: str, province: str) -> list[dict]:
    """
    Find a single municipality by town + province name.
    Both names are fuzzy-matched. Returns a single-item list or [].
    """
    try:
        import barangay as br
        from rapidfuzz import process as rfprocess

        data = br.BARANGAY

        # Build province index: lowercase_name → (region_name, prov_name, prov_data)
        # and a HUC index: lowercase_name → (region_name, prov_name) — HUCs aren't
        # "in" any province, so a query like "Quezon City, NCR" or "Quezon City,
        # Metro Manila" must resolve by town name alone, independent of province_key.
        prov_index = {}
        huc_index = {}
        for region_name, region_data in data.items():
            if not isinstance(region_data, dict):
                continue
            for prov_name, prov_data in region_data.items():
                if isinstance(prov_data, dict):
                    prov_index[prov_name.lower()] = (region_name, prov_name, prov_data)
                else:
                    huc_index[prov_name.lower()] = (region_name, prov_name)

        # HUC short-circuit: exact match first, then a strict fuzzy fallback
        # (high cutoff — avoid hijacking a real municipality of similar name,
        # e.g. "Quezon" province vs. "Quezon City" HUC).
        town_lower = town.lower().strip()
        huc_match = None
        if town_lower in huc_index:
            huc_match = huc_index[town_lower]
        else:
            result = rfprocess.extractOne(town_lower, list(huc_index.keys()), score_cutoff=90)
            if result:
                huc_match = huc_index[result[0]]
        if huc_match:
            region_name, prov_name = huc_match
            logger.info(f"load_single_municipality: matched HUC '{prov_name}', {region_name}")
            return [_build_unit(prov_name, _huc_province(prov_name), region_name)]

        # Match province
        prov_key = province.lower().strip()
        if prov_key not in prov_index:
            result = rfprocess.extractOne(prov_key, list(prov_index.keys()), score_cutoff=60)
            if not result:
                logger.warning(f"load_single_municipality: province '{province}' not found")
                return []
            prov_key = result[0]

        region_name, prov_name, prov_data = prov_index[prov_key]
        muni_names = list(prov_data.keys())

        # Match municipality — exact first, then fuzzy
        muni_match = None
        town_lower = town.lower().strip()
        for muni_name in muni_names:
            if muni_name.lower() == town_lower:
                muni_match = muni_name
                break

        if not muni_match:
            result = rfprocess.extractOne(
                town_lower,
                [m.lower() for m in muni_names],
                score_cutoff=60,
            )
            if result:
                matched_lower = result[0]
                for muni_name in muni_names:
                    if muni_name.lower() == matched_lower:
                        muni_match = muni_name
                        break

        if not muni_match:
            logger.warning(f"load_single_municipality: '{town}' not found in '{prov_name}'")
            return []

        logger.info(f"load_single_municipality: matched '{muni_match}', {prov_name}, {region_name}")
        return [_build_unit(muni_match, prov_name, region_name)]

    except Exception as e:
        logger.warning(f"load_single_municipality failed: {e}")
        return []


def _build_unit(name: str, province: str, region: str) -> dict:
    """Build a municipality record with real name + estimated demographics."""
    lat, lon = _municipality_coord(name, province)
    income_class = _stable_income_class(name, province)
    population = int(_stable_float(f"{province}:{name}:pop", 5000, 150000))
    return {
        "name": name,
        "province": province,
        "region": region,
        "lat": lat,
        "lon": lon,
        "income_class": income_class,
        "income_score": INCOME_CLASS_MAP.get(income_class, 3),
        "population": population,
        "is_urban": population > 50000,
    }


def units_to_geodataframe(units: list[dict]) -> gpd.GeoDataFrame:
    if not units:
        return gpd.GeoDataFrame()
    records = [{**u, "geometry": Point(u["lon"], u["lat"])} for u in units]
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


# ── Core Scoring ───────────────────────────────────────────────────────────────

def compute_geo_scores(gdf: gpd.GeoDataFrame, ee=None) -> dict:
    records = []
    use_gee = ee is not None

    for _, row in gdf.iterrows():
        name = row["name"]
        lat = row.geometry.y
        lon = row.geometry.x

        logger.info(f"  Scoring: {name}")

        if use_gee:
            solar = extract_gee_irradiance(ee, lat, lon)
            if solar == 0.0:
                solar = _stable_float(f"{name}:solar", 4.5, 6.0)
        else:
            solar = _stable_float(f"{name}:solar", 4.5, 6.0)

        population = float(row.get("population", 0)) or _stable_float(f"{name}:pop2", 5000, 80000)
        income_score = float(row.get("income_score", 3))
        solar_yield = round(solar * 365 * 0.80, 0)

        records.append({
            "municipality": name,
            "province": row.get("province", ""),
            "region": row.get("region", ""),
            "is_urban": row.get("is_urban", False),
            "income_class": row.get("income_class", ""),
            "solar_raw": solar,
            "population_raw": population,
            "income_raw": income_score,
            "solar_yield_kwh": solar_yield,
            "lat": lat,
            "lon": lon,
        })

    df = pd.DataFrame(records)
    if df.empty:
        return {}

    if len(df) == 1:
        df["solar_norm"]  = df["solar_raw"].apply(lambda v: _normalize_fixed(v, *PH_SOLAR_RANGE))
        df["pop_norm"]    = df["population_raw"].apply(lambda v: _normalize_fixed(v, *PH_POP_RANGE))
        df["income_norm"] = df["income_raw"].apply(lambda v: _normalize_fixed(v, *PH_INCOME_RANGE))
    else:
        scaler = MinMaxScaler()
        df[["solar_norm", "pop_norm", "income_norm"]] = scaler.fit_transform(
            df[["solar_raw", "population_raw", "income_raw"]]
        )

    w = config.WEIGHTS
    df["geo_score"] = (
        w["solar"] * df["solar_norm"]
        + w["population"] * df["pop_norm"]
        + w["income"] * df["income_norm"]
    )

    return df.set_index("municipality").to_dict(orient="index")


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _load_scores_from_db(units: list[dict]) -> dict:
    """
    Look up pre-computed geo scores from helio.db.
    Returns the same dict shape as compute_geo_scores() so downstream agents are unaffected.
    """
    import sqlite3 as _sq
    if not config.HELIO_DB.exists() or not units:
        return {}

    conditions = " OR ".join(["(m.name=? AND m.province=?)"] * len(units))
    params = []
    for u in units:
        params.extend([u["name"], u.get("province", "")])

    conn = _sq.connect(str(config.HELIO_DB))
    conn.row_factory = _sq.Row
    try:
        rows = conn.execute(
            f"""SELECT m.name, m.province, m.region, m.lat, m.lon,
                       m.income_class, m.population, m.area_km2,
                       g.solar_irradiance, g.solar_norm, g.income_score,
                       g.pop_density, g.pop_density_norm, g.geo_score
                FROM municipalities m
                JOIN geo_scores g ON g.municipality_id = m.id
                WHERE {conditions}""",
            params,
        ).fetchall()
    finally:
        conn.close()

    result = {}
    for r in rows:
        income_norm = (r["income_score"] - 1) / 5.0 if r["income_score"] else 0
        population  = r["population"] or 0
        result[r["name"]] = {
            "province":       r["province"],
            "region":         r["region"],
            "is_urban":       population > 50000,
            "income_class":   r["income_class"] or "3rd",
            "solar_raw":      r["solar_irradiance"] or 5.0,
            "population_raw": population,
            "income_raw":     r["income_score"] or 3,
            "solar_yield_kwh": round((r["solar_irradiance"] or 5.0) * 365 * 0.80, 0),
            "lat":            r["lat"],
            "lon":            r["lon"],
            "solar_norm":     r["solar_norm"] or 0,
            "pop_norm":       r["pop_density_norm"] or 0,
            "income_norm":    income_norm,
            "geo_score":      r["geo_score"] or 0,
        }
    return result


def _db_has_scores() -> bool:
    """Return True if geo_scores table is populated."""
    import sqlite3 as _sq
    if not config.HELIO_DB.exists():
        return False
    try:
        conn = _sq.connect(str(config.HELIO_DB))
        count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


# ── Agent Node ─────────────────────────────────────────────────────────────────

def geo_scoring_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 1] Geo scoring for: {state['location']}")

    try:
        location = state["location"]

        # ── Parse location into unit list (names + provinces only) ──────────
        # Also retain original input names for DB lookup fallback
        raw_db_units: list[dict] = []
        if location.count(",") == 1:
            parts = location.rsplit(",", 1)
            town_part, province = parts[0].strip(), parts[1].strip()
            if " | " in town_part:
                towns = [t.strip() for t in town_part.split(" | ")]
                units = []
                for town in towns:
                    raw_db_units.append({"name": town, "province": province})
                    units.extend(load_single_municipality(town, province))
            else:
                raw_db_units = [{"name": town_part, "province": province}]
                units = load_single_municipality(town_part, province)
        else:
            units = load_municipalities(location)

        if not units:
            logger.warning("[Agent 1] No municipalities found. Using synthetic fallback.")
            units = _synthetic_fallback(state["location"])

        # ── Try DB lookup ────────────────────────────────────────────────────
        if _db_has_scores():
            # Try barangay-resolved names first, then original input names as fallback
            scores = _load_scores_from_db(units)
            if not scores and raw_db_units:
                scores = _load_scores_from_db(raw_db_units)
            if scores:
                logger.info(
                    f"[Agent 1] DB lookup: {len(scores)} municipalities (no GEE)."
                )
                # Geocode for accurate coordinates (file-cached; only slow on first encounter)
                from agents.geocoder import geocode_units
                units_to_geo = [
                    {"name": k, "province": v.get("province", ""),
                     "lat": v.get("lat") or 0.0, "lon": v.get("lon") or 0.0}
                    for k, v in scores.items()
                ]
                geocoded = geocode_units(units_to_geo)
                # Update scores and persist real coordinates back to DB
                import sqlite3 as _sq
                conn = _sq.connect(str(config.HELIO_DB))
                for g in geocoded:
                    scores[g["name"]]["lat"] = g["lat"]
                    scores[g["name"]]["lon"] = g["lon"]
                    conn.execute(
                        "UPDATE municipalities SET lat=?, lon=? WHERE name=? AND province=?",
                        (g["lat"], g["lon"], g["name"], g["province"]),
                    )
                conn.commit()
                conn.close()
                # Build GeoJSON from geocoded coordinates
                records = [
                    {**v, "name": k, "geometry": Point(v["lon"], v["lat"])}
                    for k, v in scores.items()
                    if v.get("lat") and v.get("lon")
                ]
                gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
                gdf["geo_score"] = gdf["name"].map(
                    lambda n: scores.get(n, {}).get("geo_score", 0)
                )
                return {**state, "geo_scores": scores, "geo_geojson": gdf.to_json()}

        # ── On-the-fly fallback (DB empty or unit not found) ─────────────────
        logger.info("[Agent 1] DB empty — computing geo scores on the fly.")
        ee = _init_gee()
        from agents.geocoder import geocode_units
        units = geocode_units(units)
        gdf = units_to_geodataframe(units)
        if gdf.empty:
            raise ValueError("No geographic units to score.")
        scores = compute_geo_scores(gdf, ee=ee)
        gdf["geo_score"] = gdf["name"].map(
            lambda n: scores.get(n, {}).get("geo_score", 0)
        )
        logger.info(f"[Agent 1] On-the-fly scored {len(scores)} municipalities.")
        return {**state, "geo_scores": scores, "geo_geojson": gdf.to_json()}

    except Exception as e:
        logger.error(f"[Agent 1] Failed: {e}")
        return {
            **state,
            "geo_scores": {},
            "errors": state["errors"] + [f"Geo scoring error: {str(e)}"],
        }


def _synthetic_fallback(location: str) -> list[dict]:
    """Last-resort fallback using province centroid if barangay lookup fails."""
    names = [f"{location} Area {i}" for i in range(1, 11)]
    return [_build_unit(n, location, "Unknown") for n in names]
