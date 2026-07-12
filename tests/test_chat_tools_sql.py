import sqlite3

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"row{i}") for i in range(300)])
    conn.commit()
    conn.close()
    import config
    monkeypatch.setattr(config, "HELIO_DB", db)
    return db


def test_select_returns_rows(tmp_db):
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT id, name FROM t WHERE id < 3 ORDER BY id")
    assert out["columns"] == ["id", "name"]
    assert out["rows"] == [[0, "row0"], [1, "row1"], [2, "row2"]]
    assert out["row_count"] == 3 and out["truncated"] is False


def test_row_cap_applied(tmp_db):
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT * FROM t")
    assert out["row_count"] == 200 and out["truncated"] is True


def test_non_select_rejected_by_precheck(tmp_db):
    from agents.chat_tools import run_sql_query
    for sql in ["INSERT INTO t VALUES (999, 'x')",
                "UPDATE t SET name='x'",
                "DELETE FROM t",
                "DROP TABLE t",
                "PRAGMA journal_mode=DELETE"]:
        assert "error" in run_sql_query(sql), sql


def test_write_blocked_at_connection_level_even_if_precheck_fooled(tmp_db):
    # `SELECT` prefix trick with a second statement: sqlite3 refuses multiple
    # statements in execute(), and the connection is mode=ro besides.
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT 1; DROP TABLE t")
    assert "error" in out
    conn = sqlite3.connect(tmp_db)
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 300
    conn.close()


def test_sql_error_returned_not_raised(tmp_db):
    from agents.chat_tools import run_sql_query
    assert "error" in run_sql_query("SELECT * FROM no_such_table")
