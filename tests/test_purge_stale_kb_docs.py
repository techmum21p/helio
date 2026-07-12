import sqlite3
import pytest

SCHEMA_SQL = """
CREATE TABLE municipalities (id INTEGER PRIMARY KEY, name TEXT NOT NULL, province TEXT NOT NULL, region TEXT NOT NULL);
CREATE TABLE geo_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, municipality_id INTEGER NOT NULL UNIQUE,
    geo_score REAL, computed_at DATETIME
);
CREATE TABLE runs (id TEXT PRIMARY KEY, location TEXT, province TEXT, status TEXT, completed_at DATETIME);
CREATE TABLE run_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, municipality_id INTEGER, assessment TEXT
);
"""


@pytest.fixture
def db_conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO municipalities (id, name, province, region) VALUES (1, 'Daraga', 'Albay', 'Region V')")
    conn.execute("INSERT INTO municipalities (id, name, province, region) VALUES (2, 'Jolo', 'Sulu', 'Region IX')")
    conn.execute("INSERT INTO geo_scores (municipality_id, geo_score, computed_at) VALUES (1, 0.5, '2026-07-08 11:37:53')")
    conn.execute("INSERT INTO geo_scores (municipality_id, geo_score, computed_at) VALUES (2, 0.8, '2026-07-08 11:37:53')")
    conn.execute("INSERT INTO runs (id, location, province, status, completed_at) VALUES ('old', 'Albay', 'Albay', 'done', '2026-07-01 00:00:00')")
    conn.execute("INSERT INTO runs (id, location, province, status, completed_at) VALUES ('new', 'Sulu', 'Sulu', 'done', '2026-07-09 00:00:00')")
    conn.execute("INSERT INTO run_results (run_id, municipality_id, assessment) VALUES ('old', 1, 'stale')")
    conn.execute("INSERT INTO run_results (run_id, municipality_id, assessment) VALUES ('new', 2, 'current')")
    conn.commit()
    yield conn
    conn.close()


def test_find_stale_municipalities_returns_only_pre_fix_rows(db_conn):
    from scripts.purge_stale_kb_docs import find_stale_municipalities
    stale = find_stale_municipalities(db_conn)
    assert len(stale) == 1
    assert stale[0]["name"] == "Daraga"
    assert stale[0]["province"] == "Albay"


def test_stale_doc_ids_matches_by_province_and_muni_slug():
    from scripts.purge_stale_kb_docs import stale_doc_ids
    collection_ids = [
        "albay__daraga__abc123_chunk_0",
        "albay__daraga__abc123_chunk_1",
        "sulu__jolo__def456_chunk_0",
        "albay__city_of_tabaco__ghi789_chunk_0",
    ]
    stale = [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}]
    matched = stale_doc_ids(collection_ids, stale)
    assert matched == ["albay__daraga__abc123_chunk_0", "albay__daraga__abc123_chunk_1"]


def test_stale_doc_ids_returns_empty_when_no_match():
    from scripts.purge_stale_kb_docs import stale_doc_ids
    assert stale_doc_ids(["sulu__jolo__def456_chunk_0"], [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}]) == []
