"""
Municipality geocoder using Nominatim (OpenStreetMap).

Results are cached to data/municipality_coords.json so each place is only
looked up once. Subsequent pipeline runs for the same province are instant.
"""

import json
import time

import requests
from loguru import logger

import config

_CACHE_FILE = config.DATA_PROCESSED / "municipality_coords.json"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "helio-solar-leads/1.0 (solar intelligence platform)"}
_DELAY = 1.1  # Nominatim requires max 1 req/sec


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _nominatim_lookup(name: str, province: str) -> tuple[float, float] | None:
    """Single Nominatim query. Returns (lat, lon) or None."""
    query = f"{name}, {province}, Philippines"
    try:
        time.sleep(_DELAY)
        r = requests.get(
            _NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "ph"},
            headers=_HEADERS,
            timeout=10,
        )
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        logger.warning(f"Nominatim lookup failed for '{query}': {e}")
    return None


def get_coords(name: str, province: str, fallback: tuple[float, float]) -> tuple[float, float]:
    """
    Return (lat, lon) for a municipality. Checks cache first, then Nominatim.
    Falls back to the provided fallback coords if geocoding fails.
    """
    cache_key = f"{province}::{name}"
    cache = _load_cache()

    if cache_key in cache:
        return tuple(cache[cache_key])

    logger.debug(f"Geocoding: {name}, {province}")
    result = _nominatim_lookup(name, province)

    if result:
        cache[cache_key] = list(result)
        _save_cache(cache)
        return result

    logger.debug(f"Geocoding failed for {name}, {province} — using fallback")
    cache[cache_key] = list(fallback)
    _save_cache(cache)
    return fallback


def geocode_units(units: list[dict]) -> list[dict]:
    """
    Geocode a list of municipality dicts in-place.
    Only queries Nominatim for entries not already in cache.
    Logs progress since this can take ~1 sec per uncached municipality.
    """
    cache = _load_cache()
    uncached = [u for u in units if f"{u['province']}::{u['name']}" not in cache]

    if uncached:
        logger.info(f"Geocoding {len(uncached)} municipalities via Nominatim (cached: {len(units)-len(uncached)})...")

    updated = []
    for u in units:
        fallback = (u["lat"], u["lon"])
        lat, lon = get_coords(u["name"], u["province"], fallback)
        updated.append({**u, "lat": lat, "lon": lon})

    return updated
