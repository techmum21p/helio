"""
Agent 2: Web Intelligence Agent
Uses Tavily search + Google Places API to gather economic signals
per municipality — business density, property prices, news activity.
Runs after Agent 1 (sequential) so it knows the exact municipality list.
"""

import json
import sqlite3 as _sqlite3
import time
from datetime import datetime, timezone, timedelta

import requests
from loguru import logger
from tavily import TavilyClient

import config
from graph.state import SolarLeadState


tavily = TavilyClient(api_key=config.TAVILY_API_KEY) if config.TAVILY_API_KEY else None

_TAVILY_DELAY = 0.4  # seconds between requests — keeps dev key under rate limit

# ── DuckDuckGo fallback ────────────────────────────────────────────────────────
_tavily_rate_limited = False  # flip to True on first rate-limit hit; stays True for session

def _search_ddg(query: str) -> str:
    """DuckDuckGo search via duckduckgo_search package. No API key required."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=config.MAX_WEB_RESULTS))
        snippets = [r.get("body", "") for r in results]
        return " ".join(snippets)[:2000]
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed for '{query}': {e}")
        return ""

# ── SQLite web intel cache ─────────────────────────────────────────────────────

def _compute_web_score(intel: dict) -> float:
    """Compute web_score from raw intel signals. Range: 0–1."""
    biz_density   = min(intel.get("business_count", 0) / 20, 1.0)
    price_signal  = min(intel.get("avg_price_level", 0) / 4, 1.0)
    rating_raw    = intel.get("avg_rating", 0)
    rating_signal = max((rating_raw - 1.0) / 4.0, 0) if rating_raw else 0
    anchor_signal = min(intel.get("commercial_anchors", 0) / 5, 1.0)
    return round(
        0.35 * biz_density
        + 0.25 * price_signal
        + 0.25 * rating_signal
        + 0.15 * anchor_signal,
        4,
    )


def _get_db_cache(municipality: str, province: str) -> dict | None:
    """Return cached intel dict if fresh, else None."""
    from agents.db_store import get_municipality_id
    muni_id = get_municipality_id(municipality, province)
    if muni_id is None:
        return None
    conn = _sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = _sqlite3.Row
    try:
        row = conn.execute(
            """SELECT places_data, web_score FROM web_intel_cache
               WHERE municipality_id=? AND expires_at > datetime('now')""",
            (muni_id,),
        ).fetchone()
        if row and row["places_data"]:
            result = json.loads(row["places_data"])
            result["web_score"] = row["web_score"]
            return result
        return None
    except Exception as e:
        logger.warning(f"web_intel._get_db_cache failed: {e}")
        return None
    finally:
        conn.close()


def _set_db_cache(municipality: str, province: str, intel: dict, web_score: float) -> None:
    """Write intel + web_score to web_intel_cache table."""
    from agents.db_store import get_municipality_id
    muni_id = get_municipality_id(municipality, province)
    if muni_id is None:
        logger.warning(f"web_intel: no municipality_id for {municipality}, {province} — skipping DB cache")
        return
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(days=config.WEB_INTEL_CACHE_TTL_DAYS)
    conn = _sqlite3.connect(str(config.HELIO_DB))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO web_intel_cache
               (municipality_id, business_count, avg_price_level, places_data,
                web_score, fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                muni_id,
                intel.get("business_count", 0),
                intel.get("avg_price_level", 0),
                json.dumps(intel),
                web_score,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"web_intel._set_db_cache failed: {e}")
    finally:
        conn.close()


def search_web(query: str) -> str:
    """Web search via Tavily (primary) with DuckDuckGo fallback on rate-limit."""
    global _tavily_rate_limited

    if not _tavily_rate_limited and tavily:
        logger.info(f"  [Tavily] {query[:80]}…")
        try:
            time.sleep(_TAVILY_DELAY)
            result = tavily.search(query=query, max_results=config.MAX_WEB_RESULTS)
            snippets = [r.get("content", "") for r in result.get("results", [])]
            text = " ".join(snippets)[:2000]
            logger.debug(f"  [Tavily] OK — {len(text)} chars")
            return text
        except Exception as e:
            err = str(e).lower()
            if "usage limit" in err or "rate limit" in err or "429" in err:
                logger.warning("  [Tavily] Rate-limit hit — falling back to DuckDuckGo for rest of session.")
                _tavily_rate_limited = True
            else:
                logger.warning(f"  [Tavily] Failed: {e}")
                return ""

    if _tavily_rate_limited or not tavily:
        logger.info(f"  [DDG] {query[:80]}…")
        text = _search_ddg(query)
        logger.debug(f"  [DDG] OK — {len(text)} chars")
        return text

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
        return {"business_count": 0, "avg_price_level": 0, "avg_rating": 0, "total_reviews": 0, "commercial_anchors": 0}

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
    Results are cached in web_intel_cache table (SQLite) for WEB_INTEL_CACHE_TTL_DAYS days.
    """
    province = (geo or {}).get("province", "")

    cached = _get_db_cache(municipality, province)
    if cached:
        logger.info(f"  [Web Intel] DB cache hit: {municipality} ({province})")
        return cached

    provider = "DDG" if (_tavily_rate_limited or not tavily) else "Tavily"
    logger.info(f"  [Web Intel] Fetching: {municipality} ({province}) via {provider}")
    lat = (geo or {}).get("lat")
    lon = (geo or {}).get("lon")
    search_name = f"{municipality}, {province}" if province else municipality

    combined = search_web(
        f"economic development businesses real estate solar energy {search_name} Philippines 2024 2025"
    )
    places = get_places_signal(municipality, province=province, lat=lat, lon=lon)

    result = {
        "news_snippet":        combined[:500],
        "property_snippet":    combined[500:1000],
        "commerce_snippet":    combined[1000:1500],
        "solar_news_snippet":  combined[1500:1800],
        "business_count":      places.get("business_count", 0),
        "avg_price_level":     places.get("avg_price_level", 0),
        "avg_rating":          places.get("avg_rating", 0),
        "total_reviews":       places.get("total_reviews", 0),
        "commercial_anchors":  places.get("commercial_anchors", 0),
    }

    web_score = _compute_web_score(result)
    _set_db_cache(municipality, province, result, web_score)
    result["web_score"] = web_score
    return result


def web_intel_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 2] Web intel for: {state['location']}")

    geo_scores = state.get("geo_scores") or {}
    # Sort by geo_score BEFORE truncating to TOP_N_TARGETS. The dict arrives in
    # DB row-return order (no ORDER BY upstream), so slicing it unsorted selects
    # an arbitrary 20 — in provinces with >20 municipalities the true top
    # scorers could be silently skipped while low scorers got the web-intel and
    # synthesis budget (confirmed live 2026-07-08: all 33 such provinces were
    # affected; e.g. Cavite's #2/#3 by geo_score never made any run).
    if geo_scores:
        municipalities = sorted(
            geo_scores, key=lambda m: geo_scores[m].get("geo_score", 0), reverse=True
        )
    else:
        municipalities = [state["location"]]
    municipalities = municipalities[:config.TOP_N_TARGETS]

    web_intel = {}
    for muni in municipalities:
        web_intel[muni] = gather_intel_for_municipality(muni, geo=geo_scores.get(muni))

    logger.info(f"[Agent 2] Gathered intel for {len(web_intel)} municipalities.")

    return {
        **state,
        "web_intel": web_intel,
    }
