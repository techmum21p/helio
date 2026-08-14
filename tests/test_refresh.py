import json
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
    id INTEGER PRIMARY KEY AUTOINCREMENT, municipality_id INTEGER NOT NULL UNIQUE,
    solar_irradiance REAL, solar_norm REAL, income_score REAL,
    pop_density REAL, pop_density_norm REAL, geo_score REAL,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY, location TEXT NOT NULL, province TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME, error TEXT
);
CREATE TABLE run_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    municipality_id INTEGER, geo_score REAL, web_score REAL, final_score REAL,
    tier TEXT, assessment TEXT, opportunities TEXT, risks TEXT,
    solar_irradiance REAL, solar_yield_kwh REAL, pop_density REAL
);
CREATE TABLE web_intel_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT, municipality_id INTEGER NOT NULL UNIQUE,
    business_count INTEGER, avg_price_level REAL, places_data TEXT,
    tavily_snippets TEXT, fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME, web_score REAL
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    province TEXT, municipality TEXT, slug TEXT NOT NULL UNIQUE,
    markdown TEXT NOT NULL, file_path TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO municipalities (id, name, province, region, lat, lon, population, income_class) "
        "VALUES (1, 'Biñan', 'Laguna', 'Region IV-A', 14.33, 121.08, 407437, '1st')"
    )
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, geo_score, solar_irradiance, solar_norm, "
        "income_score, pop_density_norm, computed_at) "
        "VALUES (1, 0.72, 5.2, 0.8, 6, 0.6, '2026-07-08 11:37:53')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    import importlib
    import agents.db_store as ds
    importlib.reload(ds)
    yield db_path


def test_returns_none_for_unknown_municipality(fresh_db):
    from agents.refresh import maybe_refresh_assessment
    assert maybe_refresh_assessment(999) is None


def test_current_assessment_is_returned_without_resynthesis(fresh_db, monkeypatch):
    from agents import db_store
    db_store.create_run("r1", "Laguna", "Laguna")
    db_store.complete_run("r1", [{
        "municipality": "Biñan", "province": "Laguna", "region": "Region IV-A",
        "lat": 14.33, "lon": 121.08, "population": 407437, "income_class": "1st",
        "geo_score": 0.72, "final_score": 0.7, "tier": "HIGH", "assessment": "current",
    }])
    from agents import refresh
    monkeypatch.setattr(refresh, "synthesize_municipality", lambda *a, **k: pytest.fail("must not resynthesize"))

    result = refresh.maybe_refresh_assessment(1)
    assert result["assessment"] == "current"


def test_stale_with_cached_web_intel_resynthesizes(fresh_db, monkeypatch, tmp_path):
    from agents import db_store
    kb_intel_dir = tmp_path / "kb_intel"
    kb_intel_dir.mkdir()
    monkeypatch.setattr(config, "KB_INTEL", kb_intel_dir)
    db_store.create_run("old", "Laguna", "Laguna")
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "UPDATE runs SET completed_at='2026-07-01 00:00:00' WHERE id='old'"
    )
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, tier, assessment, final_score) "
        "VALUES ('old', 1, 'MEDIUM', 'stale text', 0.5)"
    )
    conn.execute(
        "INSERT INTO web_intel_cache (municipality_id, business_count, avg_price_level, places_data, web_score) "
        "VALUES (1, 12, 2.5, ?, 0.4)",
        (json.dumps({"business_count": 12, "avg_price_level": 2.5, "avg_rating": 4.1,
                     "total_reviews": 80, "commercial_anchors": 2}),),
    )
    conn.commit()
    conn.close()

    from agents import refresh
    monkeypatch.setattr(
        refresh, "synthesize_municipality",
        lambda municipality, geo, intel: {
            "assessment": "fresh text", "confidence": "HIGH",
            "opportunity": "opp", "risk": "risk",
        },
    )

    result = refresh.maybe_refresh_assessment(1)
    assert result["assessment"] == "fresh text"
    assert result["tier"] == "HIGH"
    assert result["final_score"] is not None


def test_stale_resynthesis_deletes_old_kb_intel_file_for_same_municipality(fresh_db, monkeypatch, tmp_path):
    """After a fresh resynthesis, exactly one kb/intel/*.md file should exist for
    the municipality — the old stale one must be removed (via the kb_docs table's
    supersede-on-register bookkeeping in kb_builder.save_municipality_docs, see
    tests/test_kb_builder.py) so it can never be read alongside the new one."""
    from agents import db_store
    db_store.create_run("old", "Laguna", "Laguna")
    conn = sqlite3.connect(str(fresh_db))
    conn.execute("UPDATE runs SET completed_at='2026-07-01 00:00:00' WHERE id='old'")
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, tier, assessment, final_score) "
        "VALUES ('old', 1, 'MEDIUM', 'stale text', 0.5)"
    )
    conn.execute(
        "INSERT INTO web_intel_cache (municipality_id, business_count, avg_price_level, places_data, web_score) "
        "VALUES (1, 12, 2.5, ?, 0.4)",
        (json.dumps({"business_count": 12, "avg_price_level": 2.5, "avg_rating": 4.1,
                     "total_reviews": 80, "commercial_anchors": 2}),),
    )
    conn.commit()
    conn.close()

    kb_intel_dir = tmp_path / "kb_intel"
    kb_intel_dir.mkdir()
    monkeypatch.setattr(config, "KB_INTEL", kb_intel_dir)

    from agents import db_store, refresh
    old_file = kb_intel_dir / "laguna__biñan__old_run_id.md"
    old_file.write_text("old stale doc")
    db_store.register_kb_doc(1, "Laguna", str(old_file), "old_run_id")

    monkeypatch.setattr(
        refresh, "synthesize_municipality",
        lambda municipality, geo, intel: {
            "assessment": "fresh text", "confidence": "HIGH",
            "opportunity": "opp", "risk": "risk",
        },
    )

    result = refresh.maybe_refresh_assessment(1)
    assert result["assessment"] == "fresh text"

    remaining = sorted(p.name for p in kb_intel_dir.glob("*.md"))
    assert not old_file.exists()
    assert len(remaining) == 1  # only the brand-new Biñan doc
    assert "old_run_id" not in remaining[0]


def test_stale_without_cached_web_intel_stays_geo_only(fresh_db, monkeypatch):
    from agents import db_store
    db_store.create_run("old", "Laguna", "Laguna")
    conn = sqlite3.connect(str(fresh_db))
    conn.execute("UPDATE runs SET completed_at='2026-07-01 00:00:00' WHERE id='old'")
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, tier, assessment, final_score) "
        "VALUES ('old', 1, 'MEDIUM', 'stale text', 0.5)"
    )
    conn.commit()
    conn.close()

    from agents import refresh
    monkeypatch.setattr(refresh, "synthesize_municipality", lambda *a, **k: pytest.fail("must not call LLM without cache"))

    result = refresh.maybe_refresh_assessment(1)
    assert result["assessment"] is None
    assert result["geo_score"] == 0.72
