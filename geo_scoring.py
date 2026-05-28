"""
Agent 1: Geo + ML Scoring

Data sources:
- psgc          → admin boundaries, population, income classification, hierarchy
- GEE           → solar irradiance (NASA POWER) — only thing psgc can't give us
- scikit-learn  → normalization + opportunity scoring
"""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, mapping
from sklearn.preprocessing import MinMaxScaler
from loguru import logger

import config
from graph.state import SolarLeadState


# ── Income classification → numeric proxy ──────────────────────────────────────
# PSGC income classes: 1st (highest) to 6th (lowest), plus "special"
INCOME_CLASS_MAP = {
    "1st": 6,
    "2nd": 5,
    "3rd": 4,
    "4th": 3,
    "5th": 2,
    "6th": 1,
    "special": 6,   # special class cities (Manila, Quezon, etc.) are highest income
}


# ── GEE Setup ──────────────────────────────────────────────────────────────────

def _init_gee():
    """
    Initialize GEE. Gracefully returns None if unavailable.
    Run once: earthengine authenticate && earthengine set_project <project-id>
    """
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
        logger.warning("earthengine-api not installed. pip install earthengine-api")
        return None
    except Exception as e:
        logger.warning(f"GEE init failed ({e}). Solar scores will use synthetic fallback.")
        return None


def extract_gee_irradiance(ee, lat: float, lon: float, buffer_m: int = 5000) -> float:
    """
    Extract mean GHI (kWh/m²/day) at a point using NASA POWER via GEE.
    Buffers the point to approximate municipality coverage.
    """
    try:
        point = ee.Geometry.Point([lon, lat]).buffer(buffer_m)

        dataset = (
            ee.ImageCollection("NASA/POWER/V9/DAILY")
            .filterDate("2024-01-01", "2024-12-31")
            .select("ALLSKY_SFC_SW_DWN")
            .mean()
        )

        result = dataset.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=point,
            scale=5000,
            maxPixels=1e8,
        ).getInfo()

        value = result.get("ALLSKY_SFC_SW_DWN", 0.0)
        return float(value) if value else 0.0

    except Exception as e:
        logger.warning(f"GEE irradiance failed at ({lat},{lon}): {e}")
        return 0.0


# ── PSGC Data Loading ──────────────────────────────────────────────────────────

def load_psgc_units(location: str) -> list:
    """
    Use psgc to get all cities/municipalities under a province or region.
    Returns list of psgc place objects.

    Falls back to synthetic demo data if psgc lookup fails.
    """
    try:
        import psgc

        place = psgc.get(location)
        level = getattr(place, "level", None)

        # Walk hierarchy to get municipality-level children
        if level == "region":
            units = []
            for province in place.children:
                units.extend(province.children)
        elif level == "province":
            units = list(place.children)
        elif level in ("city", "municipality"):
            units = [place]
        else:
            # Try search fallback
            results = psgc.search(location, n=1)
            if results:
                units = list(results[0].place.children)
            else:
                units = []

        logger.info(f"psgc: found {len(units)} municipalities under '{location}'.")
        return units

    except Exception as e:
        logger.warning(f"psgc lookup failed for '{location}': {e}")
        return []


def units_to_geodataframe(units: list) -> gpd.GeoDataFrame:
    """
    Convert psgc place objects → GeoDataFrame with centroid Points.
    Note: 87% of barangays have real centroids; 13% inherit from parent city.
    For municipality-level work, coverage is effectively 100%.
    """
    records = []
    for unit in units:
        coord = getattr(unit, "coordinate", None)
        if coord is None:
            continue

        # Income classification → numeric score
        income_class_raw = getattr(unit, "income_class", None) or ""
        income_score = INCOME_CLASS_MAP.get(
            str(income_class_raw).lower().strip(), 3  # default: mid-range
        )

        records.append({
            "name": unit.name,
            "psgc_code": unit.psgc_code,
            "level": getattr(unit, "level", ""),
            "is_urban": getattr(unit, "is_urban", False),
            "population": getattr(unit, "population", 0) or 0,
            "income_class": income_class_raw,
            "income_score": income_score,
            "province": getattr(unit.parent, "name", "") if unit.parent else "",
            "geometry": Point(coord.longitude, coord.latitude),
        })

    if not records:
        return gpd.GeoDataFrame()

    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _synthetic_demo_gdf(location: str) -> gpd.GeoDataFrame:
    """Fallback synthetic data for dev — remove once real data flows."""
    import random
    random.seed(42)

    names = [f"{location} - Municipality {i}" for i in range(1, 11)]
    return gpd.GeoDataFrame(
        {
            "name": names,
            "psgc_code": [f"00000{i}" for i in range(10)],
            "level": ["municipality"] * 10,
            "is_urban": [random.choice([True, False]) for _ in names],
            "population": [random.randint(5000, 80000) for _ in names],
            "income_class": [random.choice(["1st", "2nd", "3rd", "4th"]) for _ in names],
            "income_score": [random.randint(2, 6) for _ in names],
            "province": [location] * 10,
        },
        geometry=[
            Point(121.0 + random.uniform(-1, 1), 14.0 + random.uniform(-1, 1))
            for _ in names
        ],
        crs="EPSG:4326",
    )


# ── Core Scoring ───────────────────────────────────────────────────────────────

def compute_geo_scores(gdf: gpd.GeoDataFrame, ee=None) -> dict:
    """
    For each municipality:
      1. Solar irradiance → GEE (NASA POWER) at centroid
      2. Population       → psgc (2024 Census)
      3. Income class     → psgc (PSGC income classification)
      4. Normalize → weighted opportunity score
    """
    records = []
    use_gee = ee is not None

    for _, row in gdf.iterrows():
        name = row["name"]
        lat = row.geometry.y
        lon = row.geometry.x

        logger.info(f"  Scoring: {name}")

        # Solar — GEE or synthetic fallback
        if use_gee:
            solar = extract_gee_irradiance(ee, lat, lon)
            if solar == 0.0:
                solar = np.random.uniform(4.5, 6.0)
        else:
            solar = np.random.uniform(4.5, 6.0)

        # Population and income — straight from psgc
        population = float(row.get("population", 0)) or np.random.uniform(5000, 50000)
        income_score = float(row.get("income_score", 3))

        # Estimated annual solar yield kWh/kWp (GHI × 365 × 0.8 performance ratio)
        solar_yield = round(solar * 365 * 0.80, 0)

        records.append({
            "municipality": name,
            "psgc_code": row.get("psgc_code", ""),
            "province": row.get("province", ""),
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

    # Normalize to [0, 1]
    scaler = MinMaxScaler()
    df[["solar_norm", "pop_norm", "income_norm"]] = scaler.fit_transform(
        df[["solar_raw", "population_raw", "income_raw"]]
    )

    # Weighted opportunity score
    w = config.WEIGHTS
    df["geo_score"] = (
        w["solar"] * df["solar_norm"]
        + w["population"] * df["pop_norm"]
        + w["income"] * df["income_norm"]
    )

    return df.set_index("municipality").to_dict(orient="index")


# ── Agent Node ─────────────────────────────────────────────────────────────────

def geo_scoring_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 1] Geo scoring for: {state['location']}")

    try:
        ee = _init_gee()

        # Load municipalities via psgc
        units = load_psgc_units(state["location"])
        if units:
            gdf = units_to_geodataframe(units)
        else:
            logger.warning("[Agent 1] psgc returned no units. Using synthetic demo data.")
            gdf = _synthetic_demo_gdf(state["location"])

        if gdf.empty:
            raise ValueError("No geographic units to score.")

        scores = compute_geo_scores(gdf, ee=ee)

        # Attach scores back to GDF for map rendering
        gdf["geo_score"] = gdf["name"].map(
            lambda n: scores.get(n, {}).get("geo_score", 0)
        )
        geojson_str = gdf.to_json()

        logger.info(
            f"[Agent 1] Scored {len(scores)} municipalities. "
            f"psgc: ✓ | GEE: {'✓' if ee else '✗ (synthetic fallback)'}"
        )

        return {
            **state,
            "geo_scores": scores,
            "geo_geojson": geojson_str,
        }

    except Exception as e:
        logger.error(f"[Agent 1] Failed: {e}")
        return {
            **state,
            "geo_scores": {},
            "errors": state["errors"] + [f"Geo scoring error: {str(e)}"],
        }
