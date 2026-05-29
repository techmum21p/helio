import sqlite3
import pytest
import config

SCHEMA_SQL = """
CREATE TABLE municipalities (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, province TEXT NOT NULL,
    region TEXT NOT NULL, lat REAL, lon REAL, area_km2 REAL,
    population INTEGER, income_class TEXT
);
CREATE TABLE geo_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL UNIQUE,
    solar_irradiance REAL, solar_norm REAL, income_score REAL,
    pop_density REAL, pop_density_norm REAL, geo_score REAL,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO municipalities (id,name,province,region,lat,lon,area_km2,population,income_class) "
        "VALUES (1,'Santa Rosa','Laguna','IV-A',14.31,121.11,55.0,330000,'1st')"
    )
    conn.execute(
        "INSERT INTO geo_scores (municipality_id,solar_irradiance,solar_norm,income_score,"
        "pop_density,pop_density_norm,geo_score) VALUES (1,5.2,0.72,6,6000,0.65,0.68)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    return db_path


def test_load_scores_from_db_returns_correct_shape(populated_db):
    from agents.geo_scoring import _load_scores_from_db
    units = [{"name": "Santa Rosa", "province": "Laguna"}]
    result = _load_scores_from_db(units)
    assert "Santa Rosa" in result
    r = result["Santa Rosa"]
    assert r["geo_score"] == pytest.approx(0.68)
    assert r["province"] == "Laguna"
    assert "solar_norm" in r
    assert "income_norm" in r
    assert "pop_norm" in r
    assert "lat" in r
    assert "lon" in r


def test_load_scores_from_db_returns_empty_for_unknown(populated_db):
    from agents.geo_scoring import _load_scores_from_db
    result = _load_scores_from_db([{"name": "Nonexistent", "province": "Nowhere"}])
    assert result == {}


def test_geo_scoring_agent_uses_db_when_populated(populated_db, monkeypatch):
    import agents.geo_scoring as gs
    gee_called = []
    monkeypatch.setattr(gs, "_init_gee", lambda: gee_called.append(1) or None)

    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "Santa Rosa, Laguna",
        "run_id": "test01", "geo_scores": None, "geo_geojson": None,
        "web_intel": None, "final_scores": None, "top_targets": None,
        "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    result = gs.geo_scoring_agent(state)
    assert "Santa Rosa" in (result.get("geo_scores") or {})
    assert gee_called == []   # GEE must NOT have been called


def test_geo_scoring_agent_falls_back_when_db_empty(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)

    import agents.geo_scoring as gs
    fallback_called = []
    original = gs.compute_geo_scores

    def fake_compute(gdf, ee=None):
        fallback_called.append(1)
        return original(gdf, ee=None)

    monkeypatch.setattr(gs, "compute_geo_scores", fake_compute)

    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "Santa Rosa, Laguna",
        "run_id": "test02", "geo_scores": None, "geo_geojson": None,
        "web_intel": None, "final_scores": None, "top_targets": None,
        "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    gs.geo_scoring_agent(state)
    assert fallback_called == [1]
