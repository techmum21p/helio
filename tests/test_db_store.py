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
    from agents.db_store import create_run, complete_run, list_runs
    create_run("r1", "Laguna", "Laguna")
    complete_run("r1", [])
    time.sleep(0.01)
    create_run("r2", "Cebu", "Cebu")
    complete_run("r2", [])
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
