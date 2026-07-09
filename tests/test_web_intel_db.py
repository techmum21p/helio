import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
import config

SCHEMA_SQL = """
CREATE TABLE municipalities (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, province TEXT NOT NULL,
    region TEXT NOT NULL
);
CREATE TABLE web_intel_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL UNIQUE,
    business_count INTEGER, avg_price_level REAL,
    places_data TEXT, tavily_snippets TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME, web_score REAL
);
"""

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO municipalities (id, name, province, region) VALUES (1,'Biñan','Laguna','IV-A')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    return db_path


def test_compute_web_score_range():
    from agents.web_intel import _compute_web_score
    intel = {"business_count": 10, "avg_price_level": 2.0,
             "avg_rating": 4.0, "commercial_anchors": 2}
    score = _compute_web_score(intel)
    assert 0.0 <= score <= 1.0


def test_compute_web_score_zero_for_empty():
    from agents.web_intel import _compute_web_score
    assert _compute_web_score({}) == 0.0


def test_set_and_get_db_cache_round_trips(fresh_db):
    from agents.web_intel import _set_db_cache, _get_db_cache
    intel = {"business_count": 15, "avg_price_level": 2.5,
             "avg_rating": 4.2, "commercial_anchors": 3,
             "news_snippet": "Good economy", "property_snippet": "",
             "commerce_snippet": "", "solar_news_snippet": "", "total_reviews": 100}
    _set_db_cache("Biñan", "Laguna", intel, web_score=0.52)
    result = _get_db_cache("Biñan", "Laguna")
    assert result is not None
    assert result["business_count"] == 15
    assert result["web_score"] == pytest.approx(0.52)


def test_get_db_cache_returns_none_for_unknown_municipality(fresh_db):
    from agents.web_intel import _get_db_cache
    assert _get_db_cache("Nonexistent", "Nowhere") is None


def test_get_db_cache_returns_none_for_expired_entry(fresh_db):
    from agents.web_intel import _get_db_cache
    intel = {"business_count": 5, "avg_price_level": 1.0,
             "avg_rating": 3.0, "commercial_anchors": 0,
             "news_snippet": "", "property_snippet": "",
             "commerce_snippet": "", "solar_news_snippet": "", "total_reviews": 0}
    past = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        """INSERT INTO web_intel_cache
           (municipality_id, business_count, places_data, web_score, fetched_at, expires_at)
           VALUES (1, 5, ?, 0.2, datetime('now','-31 days'), ?)""",
        (json.dumps(intel), past),
    )
    conn.commit()
    conn.close()
    assert _get_db_cache("Biñan", "Laguna") is None


def test_web_intel_agent_uses_db_cache_on_hit(fresh_db, monkeypatch):
    from agents.web_intel import _set_db_cache
    intel = {"business_count": 12, "avg_price_level": 2.0,
             "avg_rating": 4.0, "commercial_anchors": 2,
             "news_snippet": "cached", "property_snippet": "",
             "commerce_snippet": "", "solar_news_snippet": "", "total_reviews": 50}
    _set_db_cache("Biñan", "Laguna", intel, web_score=0.48)

    import agents.web_intel as wi
    api_called = []
    monkeypatch.setattr(wi, "search_web", lambda q: api_called.append(q) or "")
    monkeypatch.setattr(wi, "get_places_signal", lambda *a, **kw: api_called.append("places") or {})

    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "Biñan, Laguna", "run_id": "t1",
        "geo_scores": {"Biñan": {"province": "Laguna", "lat": 14.34, "lon": 121.08}},
        "geo_geojson": None, "web_intel": None, "final_scores": None,
        "top_targets": None, "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    result = wi.web_intel_agent(state)
    assert api_called == []   # no API calls — all from cache
    assert result["web_intel"]["Biñan"]["web_score"] == pytest.approx(0.48)


def test_web_intel_agent_selects_top_n_by_geo_score(monkeypatch):
    """Regression for a live bug (2026-07-08): the TOP_N_TARGETS truncation was
    applied to the geo_scores dict in raw insertion (DB row-return) order, NOT
    sorted by geo_score — so in every province with >20 municipalities an
    arbitrary 20 got the web-intel/synthesis budget while true top scorers
    (e.g. Cavite's #2 and #3) were silently skipped. The agent must sort by
    geo_score descending BEFORE truncating."""
    import agents.web_intel as wi

    fetched = []
    monkeypatch.setattr(
        wi, "gather_intel_for_municipality",
        lambda muni, geo=None: fetched.append(muni) or {"web_score": 0.1},
    )
    monkeypatch.setattr(config, "TOP_N_TARGETS", 2)

    # Insertion order deliberately puts the highest scorers LAST
    geo_scores = {
        "LowTown":  {"geo_score": 0.20},
        "MidTown":  {"geo_score": 0.50},
        "BestTown": {"geo_score": 0.90},
        "NextTown": {"geo_score": 0.80},
    }
    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "TestProv", "run_id": "t2", "geo_scores": geo_scores,
        "geo_geojson": None, "web_intel": None, "final_scores": None,
        "top_targets": None, "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    result = wi.web_intel_agent(state)

    assert fetched == ["BestTown", "NextTown"]   # top 2 by score, not first 2 inserted
    assert set(result["web_intel"].keys()) == {"BestTown", "NextTown"}
