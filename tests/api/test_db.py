import sqlite3
import pytest
from api.db import create_tables, seed_municipalities_from_location_db, get_db

EXPECTED_TABLES = {
    "municipalities", "geo_scores", "runs", "run_results",
    "web_intel_cache", "chat_messages", "reports",
}

def test_create_tables_creates_all_tables(tmp_db):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    tables = {r["name"] for r in rows}
    assert EXPECTED_TABLES.issubset(tables)

def test_seed_municipalities_populates_table(tmp_db):
    count = seed_municipalities_from_location_db()
    assert count == 1622
    with get_db() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
    assert db_count == 1622

def test_seed_is_idempotent(tmp_db):
    seed_municipalities_from_location_db()
    seed_municipalities_from_location_db()  # second call should not raise or duplicate
    with get_db() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
    assert db_count == 1622

def test_municipalities_have_province_and_region(tmp_db):
    seed_municipalities_from_location_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT province, region FROM municipalities WHERE name='City of Calamba'"
        ).fetchone()
    assert row is not None
    assert row["province"] == "Laguna"
    assert "CALABARZON" in row["region"] or "Laguna" in row["region"]
