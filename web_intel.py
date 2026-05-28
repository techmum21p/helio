"""
Agent 2: Web Intelligence Agent
Uses Tavily search + Google Places API to gather economic signals
per municipality — business density, property prices, news activity.
Runs in parallel with Agent 1.
"""

import os
import requests
from loguru import logger
from tavily import TavilyClient

import config
from graph.state import SolarLeadState


tavily = TavilyClient(api_key=config.TAVILY_API_KEY) if config.TAVILY_API_KEY else None


def search_web(query: str) -> str:
    """Tavily web search. Returns a summarized text result."""
    if not tavily:
        logger.warning("Tavily API key not set. Skipping web search.")
        return ""
    try:
        result = tavily.search(query=query, max_results=config.MAX_WEB_RESULTS)
        snippets = [r.get("content", "") for r in result.get("results", [])]
        return " ".join(snippets)[:2000]  # cap to avoid token overflow
    except Exception as e:
        logger.warning(f"Tavily search failed for '{query}': {e}")
        return ""


def get_places_signal(municipality: str) -> dict:
    """
    Query Google Places API for business density and price level.
    Returns count of establishments and avg price level (1-4).
    """
    if not config.GOOGLE_PLACES_API_KEY:
        logger.warning("Google Places API key not set. Skipping Places lookup.")
        return {"business_count": 0, "avg_price_level": 0}

    try:
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": f"businesses in {municipality}, Philippines",
            "key": config.GOOGLE_PLACES_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        results = data.get("results", [])
        price_levels = [r["price_level"] for r in results if "price_level" in r]

        return {
            "business_count": len(results),
            "avg_price_level": round(sum(price_levels) / len(price_levels), 2) if price_levels else 0,
        }
    except Exception as e:
        logger.warning(f"Google Places failed for '{municipality}': {e}")
        return {"business_count": 0, "avg_price_level": 0}


def gather_intel_for_municipality(municipality: str) -> dict:
    """
    Gather all web signals for a single municipality.
    Queries run sequentially here; parallelize if speed becomes an issue.
    """
    logger.info(f"  [Web Intel] Gathering intel for: {municipality}")

    # Economic news
    news = search_web(f"economic development {municipality} Philippines 2024 2025")

    # Real estate proxy (property prices = wealth signal)
    property_signal = search_web(f"house prices real estate {municipality} Philippines Lamudi PropertyPro")

    # Commercial activity
    commerce = search_web(f"business establishments commercial activity {municipality} Philippines")

    # Solar adoption news (existing awareness)
    solar_news = search_web(f"solar panel installation {municipality} Philippines")

    # Google Places
    places = get_places_signal(municipality)

    return {
        "news_snippet": news[:500],
        "property_snippet": property_signal[:500],
        "commerce_snippet": commerce[:500],
        "solar_news_snippet": solar_news[:300],
        "business_count": places["business_count"],
        "avg_price_level": places["avg_price_level"],
    }


def web_intel_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 2] Web intel for: {state['location']}")

    # Get municipality list from state (set by Agent 1) or derive from location
    geo_scores = state.get("geo_scores") or {}
    municipalities = list(geo_scores.keys()) if geo_scores else [state["location"]]

    # Limit to top candidates to save API calls
    municipalities = municipalities[:config.TOP_N_TARGETS]

    web_intel = {}
    for muni in municipalities:
        web_intel[muni] = gather_intel_for_municipality(muni)

    logger.info(f"[Agent 2] Gathered intel for {len(web_intel)} municipalities.")

    return {
        **state,
        "web_intel": web_intel,
    }
