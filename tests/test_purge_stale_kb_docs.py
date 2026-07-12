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


def test_stale_doc_ids_matches_non_province_location_slug():
    """location_slug can be '{muni}_{province}' (e.g. Streamlit multi-muni runs), not the
    municipality's province column. The middle segment (muni_slug) must still match."""
    from scripts.purge_stale_kb_docs import stale_doc_ids
    collection_ids = [
        "daraga_albay__daraga__abc123_chunk_0",
        "daraga_albay__daraga__abc123_chunk_1",
        "sulu__jolo__def456_chunk_0",
    ]
    stale = [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}]
    matched = stale_doc_ids(collection_ids, stale)
    assert matched == ["daraga_albay__daraga__abc123_chunk_0", "daraga_albay__daraga__abc123_chunk_1"]


def test_stale_doc_ids_does_not_false_positive_on_similar_muni():
    """A different municipality (city_of_tabaco) in the same province must not match
    Daraga, even though the location_slug segment ('albay') looks similar."""
    from scripts.purge_stale_kb_docs import stale_doc_ids
    matched = stale_doc_ids(
        ["albay__city_of_tabaco__ghi789_chunk_0"],
        [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}],
    )
    assert matched == []


def test_stale_doc_ids_excludes_cross_province_same_muni_slug_collision():
    """San Isidro exists in multiple provinces. A stale San Isidro, Nueva Ecija
    must NOT match a doc id belonging to a different, non-stale San Isidro,
    Davao del Sur, even though the muni_slug segment ('san_isidro') is identical."""
    from scripts.purge_stale_kb_docs import stale_doc_ids
    collection_ids = ["davao_del_sur__san_isidro__xyz123_chunk_0"]
    stale = [{"municipality_id": 1, "name": "San Isidro", "province": "Nueva Ecija"}]
    assert stale_doc_ids(collection_ids, stale) == []


def test_stale_doc_ids_matches_historical_multi_muni_location_slug():
    """Historical kb/intel filenames from before this branch may encode a
    multi-municipality location string as the leading segment (e.g. a report
    run against "Tanay|San Mateo, Rizal"). The stale muni's own name-slug
    appearing as a substring of that leading segment must still match."""
    from scripts.purge_stale_kb_docs import stale_doc_ids
    collection_ids = ["tanay_san-mateo_rizal__tanay__abc123_chunk_0"]
    stale = [{"municipality_id": 1, "name": "Tanay", "province": "Rizal"}]
    assert stale_doc_ids(collection_ids, stale) == ["tanay_san-mateo_rizal__tanay__abc123_chunk_0"]


def test_stale_kb_intel_files_matches_and_respects_collision(tmp_path):
    from scripts.purge_stale_kb_docs import stale_kb_intel_files
    stale_file = tmp_path / "albay__daraga__abc123.md"
    stale_file.write_text("x")
    collision_file = tmp_path / "davao_del_sur__san_isidro__xyz123.md"
    collision_file.write_text("x")
    unrelated_file = tmp_path / "sulu__jolo__def456.md"
    unrelated_file.write_text("x")

    stale = [
        {"municipality_id": 1, "name": "Daraga", "province": "Albay"},
        {"municipality_id": 2, "name": "San Isidro", "province": "Nueva Ecija"},
    ]
    matched = stale_kb_intel_files(tmp_path, stale)
    assert matched == [stale_file]


class _FakeCollection:
    def __init__(self, ids):
        self._ids = ids
        self.deleted = None

    def get(self, include=None):
        return {"ids": list(self._ids)}

    def delete(self, ids):
        self.deleted = list(ids)
        self._ids = [i for i in self._ids if i not in ids]


@pytest.fixture
def main_env(tmp_path, db_conn, monkeypatch):
    """Wires config.HELIO_DB / config.KB_INTEL to a temp DB/dir and stubs the
    ChromaDB collection, so main() can be exercised end-to-end."""
    import config
    db_conn.commit()
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(config, "HELIO_DB", db_path)

    kb_intel_dir = tmp_path / "kb_intel"
    kb_intel_dir.mkdir()
    stale_file = kb_intel_dir / "albay__daraga__abc123.md"
    stale_file.write_text("stale doc")
    fresh_file = kb_intel_dir / "sulu__jolo__def456.md"
    fresh_file.write_text("fresh doc")
    monkeypatch.setattr(config, "KB_INTEL", kb_intel_dir)

    fake_collection = _FakeCollection(["albay__daraga__abc123_chunk_0", "sulu__jolo__def456_chunk_0"])
    import agents.chatbot as chatbot
    monkeypatch.setattr(chatbot, "_get_collection", lambda: fake_collection)

    return {
        "stale_file": stale_file,
        "fresh_file": fresh_file,
        "collection": fake_collection,
    }


def test_main_dry_run_deletes_nothing(main_env):
    from scripts.purge_stale_kb_docs import main
    main(dry_run=True)
    assert main_env["stale_file"].exists()
    assert main_env["fresh_file"].exists()
    assert main_env["collection"].deleted is None


def test_main_execute_deletes_chroma_chunks_and_stale_files(main_env):
    from scripts.purge_stale_kb_docs import main
    main(dry_run=False)
    assert not main_env["stale_file"].exists()
    assert main_env["fresh_file"].exists()
    assert main_env["collection"].deleted == ["albay__daraga__abc123_chunk_0"]
