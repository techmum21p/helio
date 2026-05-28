"""
Agent 2: Web Intelligence Agent
Uses Tavily search + Google Places API to gather economic signals
per municipality — business density, property prices, news activity.
Runs after Agent 1 (sequential) so it knows the exact municipality list.
"""

import json
import time
from datetime import datetime, timezone, timedelta

import requests
from loguru import logger
from tavily import TavilyClient

import config
from graph.state import SolarLeadState


tavily = TavilyClient(api_key=config.TAVILY_API_KEY) if config.TAVILY_API_KEY else None

_TAVILY_DELAY = 0.4  # seconds between requests — keeps dev key under rate limit

# ── Persistent web intel cache ─────────────────────────────────────────────────
_CACHE_FILE = config.DATA_PROCESSED / "web_intel_cache.json"
_CACHE_TTL_DAYS = config.WEB_INTEL_CACHE_TTL_DAYS
_cache: dict | None = None  # loaded lazily on first access


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if _CACHE_FILE.exists():
        try:
            _cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            logger.debug(f"Web intel cache loaded: {len(_cache)} entries")
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save_cache() -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(_cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(municipality: str, province: str) -> str:
    return f"{province}::{municipality}"


def _is_fresh(entry: dict) -> bool:
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
        return datetime.now(timezone.utc) - cached_at < timedelta(days=_CACHE_TTL_DAYS)
    except Exception:
        return False


def get_cached_intel(municipality: str, province: str) -> dict | None:
    cache = _load_cache()
    entry = cache.get(_cache_key(municipality, province))
    if entry and _is_fresh(entry):
        return entry["data"]
    return None


def set_cached_intel(municipality: str, province: str, data: dict) -> None:
    cache = _load_cache()
    cache[_cache_key(municipality, province)] = {
        "data": data,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache()


def search_web(query: str) -> str:
    """Tavily web search. Returns a summarized text result."""
    if not tavily:
        logger.warning("Tavily API key not set. Skipping web search.")
        return ""
    try:
        time.sleep(_TAVILY_DELAY)
        result = tavily.search(query=query, max_results=config.MAX_WEB_RESULTS)
        snippets = [r.get("content", "") for r in result.get("results", [])]
        return " ".join(snippets)[:2000]
    except Exception as e:
        logger.warning(f"Tavily search failed for '{query}': {e}")
        return ""


_PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_PLACES_FIELDS = "places.displayName,places.priceLevel,places.rating,places.userRatingCount,places.types"


def _places_query(query: str, lat: float | None, lon: float | None, radius_m: int = 8000) -> list:
    """Single Places API (New) call. Returns list of place dicts."""
    headers = {
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": _PLACES_FIELDS,
    }
    body: dict = {"textQuery": query, "maxResultCount": 20}
    if lat is not None and lon is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": radius_m,
            }
        }
    resp = requests.post(_PLACES_URL, json=body, headers=headers, timeout=10)
    return resp.json().get("places", [])


def get_places_signal(municipality: str, province: str = "", lat: float | None = None, lon: float | None = None) -> dict:
    """
    Query Google Places API (New) with two targeted searches:
      1. General commercial activity — business density, price level, ratings
      2. Commercial/industrial anchors — malls, factories, warehouses (B2B solar signal)

    Uses real municipality coordinates for location bias when available.
    """
    if not config.GOOGLE_PLACES_API_KEY:
        return {"business_count": 0, "avg_price_level": 0, "avg_rating": 0, "commercial_anchors": 0}

    location_str = f"{municipality}, {province}, Philippines" if province else f"{municipality}, Philippines"

    try:
        # Query 1: general commercial activity
        places = _places_query(f"businesses establishments {location_str}", lat, lon)

        price_levels = [
            _PRICE_LEVEL_MAP[p["priceLevel"]]
            for p in places if p.get("priceLevel") in _PRICE_LEVEL_MAP
        ]
        ratings = [p["rating"] for p in places if p.get("rating")]
        total_reviews = sum(p.get("userRatingCount", 0) for p in places)

        # Query 2: commercial/industrial anchors (high-value B2B solar prospects)
        anchors = _places_query(
            f"shopping mall factory industrial warehouse commercial center {location_str}",
            lat, lon,
        )

        return {
            "business_count": len(places),
            "avg_price_level": round(sum(price_levels) / len(price_levels), 2) if price_levels else 0,
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
            "total_reviews": total_reviews,
            "commercial_anchors": len(anchors),
        }

    except Exception as e:
        logger.warning(f"Google Places failed for '{municipality}': {e}")
        return {"business_count": 0, "avg_price_level": 0, "avg_rating": 0, "total_reviews": 0, "commercial_anchors": 0}


def gather_intel_for_municipality(municipality: str, geo: dict | None = None) -> dict:
    """
    Gather all web signals for a single municipality.
    Results are cached to disk for _CACHE_TTL_DAYS days — re-runs skip all API calls.
    geo dict (from Agent 1) provides province + real coordinates for Places location bias.
    """
    province = (geo or {}).get("province", "")

    cached = get_cached_intel(municipality, province)
    if cached:
        logger.info(f"  [Web Intel] Cache hit: {municipality} ({province})")
        return cached

    logger.info(f"  [Web Intel] Fetching: {municipality} ({province})")

    lat = (geo or {}).get("lat")
    lon = (geo or {}).get("lon")
    search_name = f"{municipality}, {province}" if province else municipality

    news = search_web(f"economic development {search_name} Philippines 2024 2025")
    property_signal = search_web(f"house prices real estate {search_name} Philippines Lamudi PropertyPro")
    commerce = search_web(f"business establishments commercial activity {search_name} Philippines")
    solar_news = search_web(f"solar panel installation {search_name} Philippines")
    places = get_places_signal(municipality, province=province, lat=lat, lon=lon)

    result = {
        "news_snippet": news[:500],
        "property_snippet": property_signal[:500],
        "commerce_snippet": commerce[:500],
        "solar_news_snippet": solar_news[:300],
        "business_count": places["business_count"],
        "avg_price_level": places["avg_price_level"],
        "avg_rating": places["avg_rating"],
        "total_reviews": places["total_reviews"],
        "commercial_anchors": places["commercial_anchors"],
    }

    set_cached_intel(municipality, province, result)
    return result


def web_intel_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 2] Web intel for: {state['location']}")

    geo_scores = state.get("geo_scores") or {}
    municipalities = list(geo_scores.keys()) if geo_scores else [state["location"]]
    municipalities = municipalities[:config.TOP_N_TARGETS]

    web_intel = {}
    for muni in municipalities:
        web_intel[muni] = gather_intel_for_municipality(muni, geo=geo_scores.get(muni))

    logger.info(f"[Agent 2] Gathered intel for {len(web_intel)} municipalities.")

    return {
        **state,
        "web_intel": web_intel,
    }
