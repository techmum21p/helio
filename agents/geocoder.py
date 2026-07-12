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


_PSEUDO_PROVINCE_SUFFIX = " (Not a Province)"


_HONORIFIC_PREFIXES = ("pres. ", "sen. ", "gen. ", "dr. ")
# One-off: the only Roman-numeral-split barangay name in the whole dataset
# (verified 2026-07-08 — no other "X I/II" pattern exists), not worth a
# generic regex rule for n=1. "Tondo, Manila" resolves; "Tondo I/II" doesn't.
_NAME_OVERRIDES = {"tondo i/ii": "Tondo"}


def _strip_city_of(text: str) -> str:
    """'City of Candon' -> 'Candon'. Nominatim/OSM indexes most PH cities by
    their common name, not the formal PSGC 'City of X' designation — the
    formal form alone can return zero results even for well-known, easily
    mappable cities."""
    if text.lower().startswith("city of "):
        return text[len("city of "):]
    return text


def _strip_honorific(text: str) -> str:
    """'Pres. Manuel A. Roxas' -> 'Manuel A. Roxas', 'Sen. Ninoy Aquino' ->
    'Ninoy Aquino'. A handful of PH municipality names carry a formal
    honorific (Pres./Sen./Gen./Dr.) that OSM doesn't always index by —
    confirmed live for Pres. and Sen. cases; Gen./Dr. cases already resolve
    on their full name today, so this is purely a fallback candidate."""
    lower = text.lower()
    for prefix in _HONORIFIC_PREFIXES:
        if lower.startswith(prefix):
            return text[len(prefix):]
    return text


def _query_candidates(name: str, province: str) -> list[str]:
    """
    Build a list of Nominatim query strings to try in order, most-specific
    first. Confirmed live (2026-07-08) that the formal "City of X" name and/or
    "City of Manila" as a province silently return zero results for real,
    well-known, easily mappable places — e.g. "City of Candon, Ilocos Sur"
    fails but "Candon, Ilocos Sur" resolves precisely; "Binondo, City of
    Manila" fails but "Binondo, Manila" resolves precisely. Pseudo-provinces
    (HUCs) are handled first since that fix already existed.
    """
    province = province.removesuffix(_PSEUDO_PROVINCE_SUFFIX)
    if province.strip().lower() == name.strip().lower():
        province = ""

    override_name = _NAME_OVERRIDES.get(name.strip().lower())
    bare_name = _strip_city_of(name)
    bare_province = _strip_city_of(province) if province else province
    honorific_name = _strip_honorific(bare_name)

    candidates = []
    seen = set()
    name_variants = [name, bare_name, honorific_name]
    if override_name:
        name_variants.append(override_name)
    for n in name_variants:
        for p in [province, bare_province]:
            query = f"{n}, {p}, Philippines" if p else f"{n}, Philippines"
            if query not in seen:
                seen.add(query)
                candidates.append(query)
    return candidates


def _nominatim_query(query: str) -> tuple[float, float] | None:
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


def _nominatim_lookup(name: str, province: str) -> tuple[float, float] | None:
    """
    Try progressively less formal query variants until one resolves.
    Returns (lat, lon) from the first successful query, or None if all fail.
    """
    for query in _query_candidates(name, province):
        result = _nominatim_query(query)
        if result:
            return result
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
