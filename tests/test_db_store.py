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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL UNIQUE,
    solar_irradiance REAL, solar_norm REAL, income_score REAL,
    pop_density REAL, pop_density_norm REAL, geo_score REAL,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY, location TEXT NOT NULL, province TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME, error TEXT
);
CREATE TABLE run_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    municipality_id INTEGER, geo_score REAL, web_score REAL,
    final_score REAL, tier TEXT, assessment TEXT, opportunities TEXT, risks TEXT
);
CREATE TABLE web_intel_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT, municipality_id INTEGER NOT NULL UNIQUE,
    business_count INTEGER, avg_price_level REAL, places_data TEXT,
    tavily_snippets TEXT, fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME
);
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    province TEXT, municipality TEXT, slug TEXT NOT NULL UNIQUE,
    markdown TEXT NOT NULL, file_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    # Force db_store to re-run _migrate() against fresh DB
    import importlib, agents.db_store as ds
    importlib.reload(ds)
    yield db_path


def test_create_run_inserts_row(fresh_db):
    from agents.db_store import create_run
    create_run("abc123", "Laguna", "Laguna")
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute("SELECT * FROM runs WHERE id='abc123'").fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "Laguna"   # location
    assert row[3] == "running"  # status


def test_create_run_is_idempotent(fresh_db):
    from agents.db_store import create_run
    create_run("abc123", "Laguna", "Laguna")
    create_run("abc123", "Laguna", "Laguna")  # second call must not raise
    conn = sqlite3.connect(str(fresh_db))
    count = conn.execute("SELECT COUNT(*) FROM runs WHERE id='abc123'").fetchone()[0]
    conn.close()
    assert count == 1


def test_complete_run_updates_status(fresh_db):
    from agents.db_store import create_run, complete_run
    create_run("run1", "Pampanga", "Pampanga")
    complete_run("run1", [])
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute("SELECT status FROM runs WHERE id='run1'").fetchone()
    conn.close()
    assert row[0] == "done"


def test_complete_run_inserts_results(fresh_db):
    from agents.db_store import create_run, complete_run
    create_run("run1", "Laguna", "Laguna")
    targets = [
        {"municipality": "San Pablo", "province": "Laguna", "geo_score": 0.7,
         "web_score": 0.4, "final_score": 0.61, "tier": "HIGH",
         "assessment": "Good", "opportunity": "Solar", "risk": "Rain"},
    ]
    complete_run("run1", targets)
    conn = sqlite3.connect(str(fresh_db))
    count = conn.execute("SELECT COUNT(*) FROM run_results WHERE run_id='run1'").fetchone()[0]
    conn.close()
    assert count == 1


def test_fail_run_sets_status_and_error(fresh_db):
    from agents.db_store import create_run, fail_run
    create_run("run2", "Cebu", "Cebu")
    fail_run("run2", "GEE timeout")
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute("SELECT status, error FROM runs WHERE id='run2'").fetchone()
    conn.close()
    assert row[0] == "failed"
    assert row[1] == "GEE timeout"


def test_save_and_load_chat_messages(fresh_db):
    from agents.db_store import create_run, save_chat_message, load_chat_history
    create_run("run3", "Batangas", "Batangas")
    save_chat_message("run3", "user", "Hello")
    save_chat_message("run3", "assistant", "Hi there")
    history = load_chat_history("run3")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Hello"}
    assert history[1] == {"role": "assistant", "content": "Hi there"}


def test_save_chat_message_empty_run_id_is_noop(fresh_db):
    from agents.db_store import save_chat_message
    save_chat_message("", "user", "Hello")  # must not raise or insert
    conn = sqlite3.connect(str(fresh_db))
    count = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    conn.close()
    assert count == 0


def test_save_report_inserts_row(fresh_db):
    from agents.db_store import create_run, save_report
    create_run("run4", "Rizal", "Rizal")
    save_report("run4", "Rizal", None, "# Report\nContent", "/reports/rizal_run4.md")
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute("SELECT province, markdown FROM reports WHERE run_id='run4'").fetchone()
    conn.close()
    assert row[0] == "Rizal"
    assert "# Report" in row[1]


def test_list_runs_returns_done_runs_newest_first(fresh_db):
    import time
    from agents.db_store import create_run, complete_run, save_report, list_runs
    create_run("r1", "Laguna", "Laguna")
    complete_run("r1", [])
    save_report("r1", "Laguna", None, "# R1", "/r1.md")
    time.sleep(1.05)
    create_run("r2", "Cebu", "Cebu")
    complete_run("r2", [])
    save_report("r2", "Cebu", None, "# R2", "/r2.md")
    runs = list_runs()
    assert len(runs) >= 2
    locations = [r["location"] for r in runs]
    assert locations.index("Cebu") < locations.index("Laguna")


def test_load_run_returns_none_for_missing(fresh_db):
    from agents.db_store import load_run
    assert load_run("nonexistent") is None


def test_load_run_reconstructs_pipeline_result(fresh_db):
    from agents.db_store import create_run, complete_run, save_report, load_run
    create_run("run5", "Laguna", "Laguna")
    targets = [
        {"municipality": "Biñan", "province": "Laguna", "region": "IV-A",
         "income_class": "2nd", "population": 80000,
         "geo_score": 0.7, "web_score": 0.4, "final_score": 0.61,
         "tier": "HIGH", "assessment": "Great", "opportunity": "Malls", "risk": "Flooding"},
    ]
    complete_run("run5", targets)
    save_report("run5", "Laguna", None, "# Laguna Report", "/reports/laguna_run5.md")
    result = load_run("run5")
    assert result["run_id"] == "run5"
    assert result["location"] == "Laguna"
    assert len(result["top_targets"]) == 1
    assert result["top_targets"][0]["municipality"] == "Biñan"
    assert result["report_markdown"] == "# Laguna Report"


def test_list_reports_returns_rows(fresh_db):
    from agents.db_store import create_run, save_report, list_reports
    create_run("run6", "Cebu", "Cebu")
    save_report("run6", "Cebu", None, "# Cebu Report", "/reports/cebu.md")
    reports = list_reports()
    assert len(reports) == 1
    assert reports[0]["province"] == "Cebu"
    assert "# Cebu Report" in reports[0]["markdown"]


def test_migrate_adds_web_score_column(fresh_db):
    conn = sqlite3.connect(str(fresh_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(web_intel_cache)").fetchall()]
    conn.close()
    assert "web_score" in cols


def test_get_municipality_id_returns_none_for_unknown(fresh_db):
    from agents.db_store import get_municipality_id
    assert get_municipality_id("Nonexistent", "Nowhere") is None


def test_list_runs_excludes_runs_without_reports(fresh_db):
    from agents.db_store import create_run, complete_run, save_report, list_runs
    create_run("r_report", "Cebu", "Cebu")
    complete_run("r_report", [])
    save_report("r_report", "Cebu", None, "# Cebu", "/r.md")
    create_run("r_noreport", "Davao", "Davao")
    complete_run("r_noreport", [])

    runs = list_runs()
    ids = [r["id"] for r in runs]
    assert "r_report"   in ids
    assert "r_noreport" not in ids


def test_list_runs_default_limit_is_1000(fresh_db):
    from agents import db_store as ds
    import inspect
    sig = inspect.signature(ds.list_runs)
    assert sig.parameters["limit"].default == 1000


def test_migrate_adds_score_component_columns(fresh_db):
    from agents import db_store as ds
    conn = sqlite3.connect(str(fresh_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(run_results)").fetchall()]
    conn.close()
    assert "solar_irradiance" in cols
    assert "solar_yield_kwh" in cols
    assert "pop_density" in cols


def test_complete_run_writes_component_fields(fresh_db):
    from agents.db_store import create_run, complete_run
    create_run("run_comp", "Laguna", "Laguna")
    targets = [{
        "municipality": "Biñan", "province": "Laguna", "region": "IV-A",
        "geo_score": 0.7, "web_score": 0.4, "final_score": 0.61,
        "tier": "HIGH", "assessment": "Good", "opportunity": "Solar", "risk": "Rain",
        "solar_irradiance": 5.42,
        "solar_yield_kwh": 1587.0,
        "pop_density": 850.3,
    }]
    complete_run("run_comp", targets)
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute(
        "SELECT solar_irradiance, solar_yield_kwh, pop_density FROM run_results WHERE run_id='run_comp'"
    ).fetchone()
    conn.close()
    assert row[0] == pytest.approx(5.42)
    assert row[1] == pytest.approx(1587.0)
    assert row[2] == pytest.approx(850.3)


def test_load_run_returns_component_fields(fresh_db):
    from agents.db_store import create_run, complete_run, save_report, load_run
    create_run("run_load", "Laguna", "Laguna")
    targets = [{
        "municipality": "Biñan", "province": "Laguna", "region": "IV-A",
        "income_class": "2nd", "population": 80000,
        "geo_score": 0.7, "web_score": 0.4, "final_score": 0.61,
        "tier": "HIGH", "assessment": "Good", "opportunity": "Solar", "risk": "Rain",
        "solar_irradiance": 5.42,
        "solar_yield_kwh": 1587.0,
        "pop_density": 850.3,
    }]
    complete_run("run_load", targets)
    save_report("run_load", "Laguna", None, "# Report", "/reports/r.md")
    result = load_run("run_load")
    t = result["top_targets"][0]
    assert t["solar_irradiance"] == pytest.approx(5.42)
    assert t["solar_yield_kwh"] == pytest.approx(1587.0)
    assert t["pop_density"] == pytest.approx(850.3)


def test_load_run_fallback_join_for_old_rows(fresh_db):
    """Rows with NULL solar_irradiance in run_results fall back to geo_scores JOIN."""
    import sqlite3 as _sq
    from agents.db_store import load_run
    conn = _sq.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO municipalities (name, province, region) VALUES ('OldTown', 'OldProv', 'R')"
    )
    muni_id = conn.execute("SELECT id FROM municipalities WHERE name='OldTown'").fetchone()[0]
    conn.execute(
        """INSERT INTO geo_scores (municipality_id, solar_irradiance, pop_density)
           VALUES (?, 5.1, 300.0)""",
        (muni_id,),
    )
    conn.execute(
        "INSERT INTO runs (id, location, status) VALUES ('old_run', 'OldProv', 'done')"
    )
    conn.execute(
        """INSERT INTO run_results (run_id, municipality_id, geo_score, web_score,
           final_score, tier)
           VALUES ('old_run', ?, 0.5, 0.3, 0.46, 'MEDIUM')""",
        (muni_id,),
    )
    conn.execute(
        """INSERT INTO reports (run_id, province, slug, markdown, file_path)
           VALUES ('old_run', 'OldProv', 'oldprov_old_run', '# R', '/r.md')"""
    )
    conn.commit()
    conn.close()

    result = load_run("old_run")
    assert result is not None
    t = result["top_targets"][0]
    assert t["solar_irradiance"] == pytest.approx(5.1)
    assert t["pop_density"] == pytest.approx(300.0)
    assert t["solar_yield_kwh"] == pytest.approx(5.1 * 365 * 0.80, abs=1.0)


def test_get_latest_scored_municipalities_excludes_stale_assessment(fresh_db):
    """A run_results row completed BEFORE geo_scores.computed_at must not surface as current."""
    from agents.db_store import get_latest_scored_municipalities
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO municipalities (id, name, province, region, lat, lon, population, income_class) "
        "VALUES (1, 'Biñan', 'Laguna', 'Region IV-A', 14.33, 121.08, 407437, '1st')"
    )
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, geo_score, computed_at) "
        "VALUES (1, 0.72, '2026-07-08 11:37:53')"
    )
    conn.execute(
        "INSERT INTO runs (id, location, province, status, completed_at) "
        "VALUES ('old_run', 'Laguna', 'Laguna', 'done', '2026-07-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, geo_score, web_score, final_score, "
        "tier, assessment, opportunities, risks) "
        "VALUES ('old_run', 1, 0.72, 0.5, 0.65, 'MEDIUM', 'stale text', '[]', '[]')"
    )
    conn.commit()
    conn.close()

    rows = get_latest_scored_municipalities()
    assert len(rows) == 1
    assert rows[0]["name"] == "Biñan"
    assert rows[0]["geo_score"] == 0.72
    assert rows[0]["assessment"] is None
    assert rows[0]["final_score"] is None
    assert rows[0]["opportunities"] == []


def test_get_latest_scored_municipalities_includes_current_assessment(fresh_db):
    """A run_results row completed AFTER geo_scores.computed_at must surface as current."""
    from agents.db_store import get_latest_scored_municipalities
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO municipalities (id, name, province, region, lat, lon, population, income_class) "
        "VALUES (2, 'Jolo', 'Sulu', 'Region IX', 6.05, 121.0, 122831, '2nd')"
    )
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, geo_score, computed_at) "
        "VALUES (2, 0.81, '2026-07-08 11:37:53')"
    )
    conn.execute(
        "INSERT INTO runs (id, location, province, status, completed_at) "
        "VALUES ('new_run', 'Sulu', 'Sulu', 'done', '2026-07-09 01:00:00')"
    )
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, geo_score, web_score, final_score, "
        "tier, assessment, opportunities, risks) "
        "VALUES ('new_run', 2, 0.81, 0.4, 0.71, 'HIGH', 'current text', '[\"opp\"]', '[\"risk\"]')"
    )
    conn.commit()
    conn.close()

    rows = get_latest_scored_municipalities()
    assert rows[0]["assessment"] == "current text"
    assert rows[0]["final_score"] == 0.71
    assert rows[0]["opportunities"] == ["opp"]


def test_get_latest_scored_municipalities_picks_max_completed_at(fresh_db):
    """Two current runs for the same municipality: the later completed_at wins."""
    from agents.db_store import get_latest_scored_municipalities
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO municipalities (id, name, province, region) VALUES (3, 'Davao City', 'Davao del Sur', 'Region XI')"
    )
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, geo_score, computed_at) VALUES (3, 0.6, '2026-07-08 11:37:53')"
    )
    conn.execute(
        "INSERT INTO runs (id, location, province, status, completed_at) VALUES "
        "('r1', 'Davao del Sur', 'Davao del Sur', 'done', '2026-07-08 12:00:00'), "
        "('r2', 'Davao del Sur', 'Davao del Sur', 'done', '2026-07-09 09:00:00')"
    )
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, tier, assessment, final_score) "
        "VALUES ('r1', 3, 'MEDIUM', 'first pass', 0.5)"
    )
    conn.execute(
        "INSERT INTO run_results (run_id, municipality_id, tier, assessment, final_score) "
        "VALUES ('r2', 3, 'HIGH', 'second pass', 0.6)"
    )
    conn.commit()
    conn.close()

    rows = get_latest_scored_municipalities()
    assert rows[0]["assessment"] == "second pass"
    assert rows[0]["tier"] == "HIGH"


def test_get_latest_report_for_province_returns_most_recent(fresh_db):
    from agents.db_store import get_latest_report_for_province
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO runs (id, location, province, status) VALUES ('r1', 'Laguna', 'Laguna', 'done')"
    )
    conn.execute(
        "INSERT INTO runs (id, location, province, status) VALUES ('r2', 'Laguna', 'Laguna', 'done')"
    )
    conn.execute(
        "INSERT INTO reports (run_id, province, municipality, slug, markdown, file_path, created_at) "
        "VALUES ('r1', 'Laguna', NULL, 'laguna_old', '# old report', 'reports/laguna_old.md', '2026-07-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO reports (run_id, province, municipality, slug, markdown, file_path, created_at) "
        "VALUES ('r2', 'Laguna', NULL, 'laguna_new', '# new report', 'reports/laguna_new.md', '2026-07-09 00:00:00')"
    )
    conn.commit()
    conn.close()

    report = get_latest_report_for_province("Laguna")
    assert report is not None
    assert report["markdown"] == "# new report"
    assert report["file_path"] == "reports/laguna_new.md"


def test_get_latest_report_for_province_returns_none_when_missing(fresh_db):
    from agents.db_store import get_latest_report_for_province
    assert get_latest_report_for_province("Nowhere") is None
