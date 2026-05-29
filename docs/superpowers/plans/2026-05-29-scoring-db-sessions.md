# Scoring, DB Cache & Session History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix geo scoring weights/normalization, migrate all caches to SQLite, persist sessions/reports/chat to DB, and swap the KB embedding to Ollama qwen3-embedding.

**Architecture:** Nine sequential tasks build on each other — `config.py` and `db_store.py` are foundations that all later tasks depend on. Agents are updated individually then wired together in `app.py`. No FastAPI or Next.js changes; Streamlit stays as the UI.

**Tech Stack:** Python 3.12, SQLite (`data/helio.db`), LangGraph, Streamlit, ChromaDB, Ollama (`qwen3-embedding`), scikit-learn `MinMaxScaler`, sentence-transformers (removed)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Revised weights, `HELIO_DB` path, Ollama config |
| `agents/db_store.py` | **Create** | All DB I/O — runs, results, reports, chat, web cache helpers |
| `scripts/precompute_geo_scores.py` | Rewrite | Enumerate all 1,622 municipalities, normalize, upsert geo_scores |
| `agents/geo_scoring.py` | Modify | Try DB lookup first; fall back to on-the-fly only if table empty |
| `agents/web_intel.py` | Modify | Swap JSON file cache for SQLite; compute + store web_score |
| `agents/synthesis.py` | Modify | `compute_final_score` reads `intel["web_score"]`; new 70/30 weights; returns `(final, web)` tuple |
| `agents/report_gen.py` | Modify | Also writes to `reports` table via db_store |
| `graph/pipeline.py` | Modify | Accept optional `run_id` parameter |
| `agents/chatbot.py` | Modify | Ollama embedding, DB as KB source, chat persistence |
| `app.py` | Modify | Run lifecycle hooks, sidebar history panel, Admin page |
| `tests/test_config.py` | **Create** | Weight sums, path assertions |
| `tests/test_db_store.py` | **Create** | All db_store functions against temp SQLite |
| `tests/test_precompute.py` | **Create** | Normalization, scoring, municipality enumeration |
| `tests/test_geo_scoring_db.py` | **Create** | DB lookup path in geo_scoring_agent |
| `tests/test_web_intel_db.py` | **Create** | SQLite cache read/write/TTL |
| `tests/test_synthesis_weights.py` | **Create** | 70/30 formula, web_score passthrough |

---

## Task 1: config.py — revised weights + new constants

**Files:**
- Modify: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import config

def test_geo_weights_sum_to_one():
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9

def test_income_weight_is_dominant():
    assert config.WEIGHTS["income"] == 0.45

def test_solar_weight_revised():
    assert config.WEIGHTS["solar"] == 0.35

def test_population_weight_revised():
    assert config.WEIGHTS["population"] == 0.20

def test_final_weights_sum_to_one():
    assert abs(config.FINAL_GEO_WEIGHT + config.FINAL_WEB_WEIGHT - 1.0) < 1e-9

def test_final_web_weight_raised():
    assert config.FINAL_WEB_WEIGHT == 0.30

def test_helio_db_path_defined():
    assert config.HELIO_DB.name == "helio.db"
    assert config.HELIO_DB.parent.name == "data"

def test_ollama_defaults():
    assert config.OLLAMA_EMBED_MODEL == "qwen3-embedding"
    assert "11434" in config.OLLAMA_URL
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/aireesm4/Python_Projects/helio && source .venv_helios/bin/activate
pytest tests/test_config.py -v
```

Expected: most tests FAIL (missing attributes).

- [ ] **Step 3: Update config.py**

```python
# config.py — replace the WEIGHTS block and add below it:

# Scoring weights (must sum to 1.0)
WEIGHTS = {
    "solar":      0.35,   # was 0.40
    "income":     0.45,   # was 0.35
    "population": 0.20,   # was 0.25; now applied to pop_density
}

# Final score blend weights
FINAL_GEO_WEIGHT = 0.70   # was 0.80
FINAL_WEB_WEIGHT = 0.30   # was 0.20

# Ollama embedding
OLLAMA_URL         = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding")

# Consolidated DB (helio.db replaces ph_locations.db for all structured data)
HELIO_DB = ROOT_DIR / "data" / "helio.db"
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_config.py -v
```

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: revised scoring weights, HELIO_DB path, Ollama config"
```

---

## Task 2: agents/db_store.py — new DB I/O module

**Files:**
- Create: `agents/db_store.py`
- Create: `tests/test_db_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_store.py
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
    from agents.db_store import create_run, complete_run, list_runs
    create_run("r1", "Laguna", "Laguna")
    complete_run("r1", [])
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_db_store.py -v 2>&1 | head -20
```

Expected: ImportError or AttributeError — `agents.db_store` does not exist.

- [ ] **Step 3: Create agents/db_store.py**

```python
# agents/db_store.py
"""
DB I/O for pipeline runs, results, reports, and chat messages.
Replaces agents/session_store.py — all writes go to data/helio.db.
"""
import json
import sqlite3
from datetime import datetime
from loguru import logger

import config


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate() -> None:
    """Add web_score column to web_intel_cache if not present (idempotent)."""
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE web_intel_cache ADD COLUMN web_score REAL")
        conn.commit()
        logger.info("db_store: added web_score column to web_intel_cache")
    except Exception:
        pass  # column already exists
    finally:
        conn.close()


_migrate()


def create_run(run_id: str, location: str, province: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO runs (id, location, province, status) VALUES (?, ?, ?, 'running')",
            (run_id, location, province),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.create_run failed: {e}")
    finally:
        conn.close()


def complete_run(run_id: str, top_targets: list) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE runs SET status='done', completed_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), run_id),
        )
        for t in top_targets:
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (t.get("municipality", ""), t.get("province", "")),
            ).fetchone()
            muni_id = row["id"] if row else None
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, muni_id,
                    t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                    t.get("tier"), t.get("assessment"),
                    json.dumps([t.get("opportunity", "")]),
                    json.dumps([t.get("risk", "")]),
                ),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.complete_run failed: {e}")
    finally:
        conn.close()


def fail_run(run_id: str, error: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE runs SET status='failed', completed_at=?, error=? WHERE id=?",
            (datetime.utcnow().isoformat(), error, run_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.fail_run failed: {e}")
    finally:
        conn.close()


def save_report(
    run_id: str,
    province: str,
    municipality: str | None,
    markdown: str,
    file_path: str,
) -> None:
    slug = f"{province}_{run_id}".lower().replace(" ", "_").replace(",", "")
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO reports
               (run_id, province, municipality, slug, markdown, file_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, province, municipality, slug, markdown, file_path),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.save_report failed: {e}")
    finally:
        conn.close()


def save_chat_message(run_id: str, role: str, content: str) -> None:
    if not run_id:
        return
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages (run_id, role, content) VALUES (?, ?, ?)",
            (run_id, role, content),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.save_chat_message failed: {e}")
    finally:
        conn.close()


def load_chat_history(run_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception as e:
        logger.error(f"db_store.load_chat_history failed: {e}")
        return []
    finally:
        conn.close()


def list_runs(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.location, r.province, r.status, r.created_at,
                   COUNT(rr.id) AS target_count,
                   MAX(rr.final_score) AS top_score,
                   (SELECT tier FROM run_results
                    WHERE run_id = r.id ORDER BY final_score DESC LIMIT 1) AS top_tier
            FROM runs r
            LEFT JOIN run_results rr ON rr.run_id = r.id
            WHERE r.status IN ('done', 'failed')
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_store.list_runs failed: {e}")
        return []
    finally:
        conn.close()


def load_run(run_id: str) -> dict | None:
    conn = _get_conn()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run_row:
            return None
        result_rows = conn.execute(
            """SELECT rr.geo_score, rr.web_score, rr.final_score, rr.tier,
                      rr.assessment, rr.opportunities, rr.risks,
                      m.name AS municipality_name, m.province, m.region,
                      m.income_class, m.population
               FROM run_results rr
               LEFT JOIN municipalities m ON m.id = rr.municipality_id
               WHERE rr.run_id = ?
               ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        top_targets = []
        for r in result_rows:
            top_targets.append({
                "municipality": r["municipality_name"] or "",
                "province":     r["province"] or "",
                "region":       r["region"] or "",
                "income_class": r["income_class"] or "",
                "population":   r["population"] or 0,
                "geo_score":    r["geo_score"],
                "web_score":    r["web_score"],
                "final_score":  r["final_score"],
                "tier":         r["tier"],
                "assessment":   r["assessment"] or "",
                "opportunity":  (json.loads(r["opportunities"] or "[]") or [""])[0],
                "risk":         (json.loads(r["risks"] or "[]") or [""])[0],
            })
        report_row = conn.execute(
            "SELECT markdown, file_path FROM reports WHERE run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        return {
            "run_id":          run_row["id"],
            "location":        run_row["location"],
            "top_targets":     top_targets,
            "report_markdown": report_row["markdown"] if report_row else "",
            "report_path":     report_row["file_path"] if report_row else None,
            "errors":          [],
            "status":          run_row["status"],
        }
    except Exception as e:
        logger.error(f"db_store.load_run failed: {e}")
        return None
    finally:
        conn.close()


def list_reports() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, slug, province, municipality, markdown FROM reports ORDER BY created_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_store.list_reports failed: {e}")
        return []
    finally:
        conn.close()


def get_municipality_id(name: str, province: str) -> int | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM municipalities WHERE name=? AND province=?",
            (name, province),
        ).fetchone()
        return row["id"] if row else None
    except Exception as e:
        logger.error(f"db_store.get_municipality_id failed: {e}")
        return None
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_db_store.py -v
```

Expected: 14 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/db_store.py tests/test_db_store.py
git commit -m "feat: add db_store module — DB I/O for runs, reports, chat"
```

---

## Task 3: scripts/precompute_geo_scores.py — rewrite with proper normalization

**Files:**
- Rewrite: `scripts/precompute_geo_scores.py`
- Create: `tests/test_precompute.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_precompute.py
import pytest
import sqlite3
import config
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

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
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    return db_path


def _make_units(n=5):
    """Build minimal test unit dicts."""
    import hashlib
    units = []
    for i in range(n):
        name = f"Town{i}"
        province = "TestProvince"
        units.append({
            "name": name, "province": province, "region": "TestRegion",
            "income_class": ["1st","2nd","3rd","4th","5th","6th"][i % 6],
            "income_score": [6, 5, 4, 3, 2, 1][i % 6],
            "population": 5000 * (i + 1),
            "area_km2": 50.0 * (i + 1),
            "pop_density": 5000 * (i + 1) / (50.0 * (i + 1)),
            "solar": 4.5 + i * 0.3,
            "lat": 12.5 + i * 0.1, "lon": 122.5 + i * 0.1,
        })
    return units


def test_normalize_and_score_geo_score_in_range():
    from precompute_geo_scores import normalize_and_score
    units = _make_units(6)
    result = normalize_and_score(units)
    for u in result:
        assert 0.0 <= u["geo_score"] <= 1.0


def test_normalize_highest_income_gets_highest_income_norm():
    from precompute_geo_scores import normalize_and_score
    units = _make_units(6)
    result = normalize_and_score(units)
    # Town0 has income_score=6 (1st class) — should have income_norm=1.0
    town0 = next(u for u in result if u["name"] == "Town0")
    assert town0["income_norm"] == pytest.approx(1.0)


def test_normalize_uses_config_weights():
    from precompute_geo_scores import normalize_and_score
    # Two towns: identical solar and pop_density, different income
    units = [
        {"name": "Rich", "province": "P", "region": "R", "income_class": "1st",
         "income_score": 6, "population": 10000, "area_km2": 100,
         "pop_density": 100, "solar": 5.0, "lat": 12.0, "lon": 122.0},
        {"name": "Poor", "province": "P", "region": "R", "income_class": "6th",
         "income_score": 1, "population": 10000, "area_km2": 100,
         "pop_density": 100, "solar": 5.0, "lat": 12.1, "lon": 122.1},
    ]
    result = normalize_and_score(units)
    rich = next(u for u in result if u["name"] == "Rich")
    poor = next(u for u in result if u["name"] == "Poor")
    # Income contributes 0.45 weight; Rich should score 0.45 higher
    assert rich["geo_score"] - poor["geo_score"] == pytest.approx(0.45, abs=1e-4)


def test_get_all_municipalities_returns_expected_count():
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    assert 1600 <= len(units) <= 1700


def test_get_all_municipalities_each_has_required_fields():
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    required = {"name", "province", "region", "income_class", "income_score",
                "population", "area_km2", "pop_density", "solar", "lat", "lon"}
    for u in units[:10]:
        assert required.issubset(u.keys()), f"Missing fields in {u}"


def test_upsert_to_db_writes_rows(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(3)
    # Insert municipalities first
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()

    units = normalize_and_score(units)
    upsert_to_db(units)

    conn = sqlite3.connect(str(temp_db))
    count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
    conn.close()
    assert count == 3


def test_upsert_is_idempotent(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(2)
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()
    units = normalize_and_score(units)
    upsert_to_db(units)
    upsert_to_db(units)  # second run must not raise or duplicate
    conn = sqlite3.connect(str(temp_db))
    count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
    conn.close()
    assert count == 2


def test_progress_callback_called(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(3)
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()
    units = normalize_and_score(units)
    calls = []
    upsert_to_db(units, progress_callback=lambda done, total: calls.append((done, total)))
    assert len(calls) == 3
    assert calls[-1] == (3, 3)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_precompute.py -v 2>&1 | head -20
```

Expected: ImportError — `precompute_geo_scores` not found.

- [ ] **Step 3: Write scripts/precompute_geo_scores.py**

```python
#!/usr/bin/env python3
"""
Pre-compute geo scores for all Philippine municipalities.
Run once (or via Admin page Refresh button) to populate geo_scores table.
Idempotent — safe to re-run.

Usage: python scripts/precompute_geo_scores.py
"""
import hashlib
import sqlite3
import sys
from pathlib import Path

import numpy as np
from loguru import logger
from sklearn.preprocessing import MinMaxScaler

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

INCOME_CLASS_MAP = {"1st": 6, "2nd": 5, "3rd": 4, "4th": 3, "5th": 2, "6th": 1, "special": 6}
INCOME_CLASSES   = ["1st", "2nd", "3rd", "4th", "5th", "6th"]

# Province centroid lookup — same as agents/geo_scoring.py
PROVINCE_CENTROIDS = {
    "metro manila": (14.5548, 121.0244), "ncr": (14.5548, 121.0244),
    "national capital region": (14.5548, 121.0244),
    "ilocos norte": (18.1647, 120.7116), "ilocos sur": (17.5755, 120.3869),
    "la union": (16.6159, 120.3209), "pangasinan": (15.8949, 120.2863),
    "batanes": (20.4487, 121.9702), "cagayan": (17.6132, 121.7269),
    "isabela": (16.9754, 121.8107), "nueva vizcaya": (16.3301, 121.1710),
    "quirino": (16.2700, 121.5376),
    "bataan": (14.6416, 120.4818), "bulacan": (14.7942, 120.8799),
    "nueva ecija": (15.5784, 121.1116), "pampanga": (15.0794, 120.6200),
    "tarlac": (15.4755, 120.5963), "zambales": (15.5082, 119.9705),
    "aurora": (15.9784, 121.5986),
    "batangas": (13.7565, 121.0583), "cavite": (14.2456, 120.8787),
    "laguna": (14.2691, 121.4113), "quezon": (14.0313, 121.9176),
    "rizal": (14.6042, 121.3084),
    "marinduque": (13.4767, 122.0321), "occidental mindoro": (12.9027, 121.0614),
    "oriental mindoro": (13.0565, 121.4069), "palawan": (9.8349, 118.7384),
    "romblon": (12.5778, 122.2695),
    "camarines norte": (14.1389, 122.7632), "camarines sur": (13.6252, 123.1847),
    "catanduanes": (13.7089, 124.2422), "masbate": (12.3696, 123.6199),
    "sorsogon": (12.9433, 124.0147), "albay": (13.1775, 123.5280),
    "aklan": (11.8166, 122.0942), "antique": (11.3683, 122.0640),
    "capiz": (11.5530, 122.7411), "guimaras": (10.5956, 122.6325),
    "iloilo": (10.7202, 122.5621), "negros occidental": (10.6713, 123.0566),
    "bohol": (9.8500, 124.1435), "cebu": (10.3157, 123.8854),
    "negros oriental": (9.6168, 122.9823), "siquijor": (9.2076, 123.5116),
    "biliran": (11.5835, 124.4633), "eastern samar": (11.8981, 125.0773),
    "leyte": (10.8731, 124.8811), "northern samar": (12.5674, 124.5658),
    "samar": (11.5500, 125.0000), "southern leyte": (10.3332, 125.1717),
    "zamboanga del norte": (8.1527, 123.2577), "zamboanga del sur": (7.8383, 123.2968),
    "zamboanga sibugay": (7.5222, 122.8198),
    "bukidnon": (8.0515, 125.0988), "camiguin": (9.1695, 124.7218),
    "lanao del norte": (8.0730, 124.2873), "misamis occidental": (8.3375, 123.7072),
    "misamis oriental": (8.5046, 124.6220),
    "davao de oro": (7.6728, 126.1742), "compostela valley": (7.6728, 126.1742),
    "davao del norte": (7.5619, 125.6549), "davao del sur": (6.7656, 125.3284),
    "davao occidental": (6.1054, 125.6072), "davao oriental": (7.3172, 126.5420),
    "cotabato": (7.1322, 124.8567), "north cotabato": (7.1322, 124.8567),
    "south cotabato": (6.3344, 124.9010), "sultan kudarat": (6.5069, 124.4186),
    "sarangani": (5.9630, 125.1990),
    "agusan del norte": (8.9456, 125.5320), "agusan del sur": (8.1864, 126.0135),
    "dinagat islands": (10.1280, 125.6083), "surigao del norte": (9.5141, 125.6030),
    "surigao del sur": (8.5120, 126.1144),
    "basilan": (6.4222, 121.9693), "lanao del sur": (7.8232, 124.4198),
    "maguindanao": (6.8416, 124.4330), "sulu": (5.9747, 121.0337),
    "tawi-tawi": (5.1339, 119.9513),
    "ifugao": (16.8325, 121.1710), "benguet": (16.4023, 120.5960),
    "mountain province": (17.0000, 121.1000), "abra": (17.5951, 120.7983),
    "apayao": (18.0127, 121.1710), "kalinga": (17.4766, 121.3544),
    "surigao del norte": (9.5141, 125.6030),
}


def _stable_float(seed: str, lo: float, hi: float) -> float:
    digest = hashlib.md5(seed.encode()).digest()
    frac   = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return lo + frac * (hi - lo)


def _stable_income_class(name: str, province: str) -> str:
    digest  = hashlib.md5(f"{province}:{name}".encode()).digest()
    weights = [1, 2, 3, 3, 2, 1]
    total   = sum(weights)
    pick    = digest[0] % total
    cumulative = 0
    for i, w in enumerate(weights):
        cumulative += w
        if pick < cumulative:
            return INCOME_CLASSES[i]
    return "3rd"


def _province_coord(province: str) -> tuple[float, float]:
    key = province.lower().strip()
    if key in PROVINCE_CENTROIDS:
        return PROVINCE_CENTROIDS[key]
    for k, v in PROVINCE_CENTROIDS.items():
        if k in key or key in k:
            return v
    return (12.5, 122.5)


def _municipality_coord(name: str, province: str) -> tuple[float, float]:
    base_lat, base_lon = _province_coord(province)
    lat_off = _stable_float(f"{name}:lat", -0.30, 0.30)
    lon_off = _stable_float(f"{name}:lon", -0.30, 0.30)
    return (base_lat + lat_off, base_lon + lon_off)


def _get_all_municipalities() -> list[dict]:
    """Enumerate all municipalities from the barangay package with hash-based demographics."""
    import barangay as br
    units = []
    for region_name, region_data in br.BARANGAY.items():
        if not isinstance(region_data, dict):
            continue
        for prov_name, prov_data in region_data.items():
            if not isinstance(prov_data, dict):
                continue
            for muni_name in prov_data.keys():
                income_class = _stable_income_class(muni_name, prov_name)
                income_score = INCOME_CLASS_MAP.get(income_class, 3)
                population   = int(_stable_float(f"{prov_name}:{muni_name}:pop", 5000, 150000))
                area_km2     = round(_stable_float(f"{prov_name}:{muni_name}:area", 20, 500), 2)
                pop_density  = population / area_km2
                solar        = _stable_float(f"{muni_name}:solar", 4.5, 6.0)
                lat, lon     = _municipality_coord(muni_name, prov_name)
                units.append({
                    "name":         muni_name,
                    "province":     prov_name,
                    "region":       region_name,
                    "income_class": income_class,
                    "income_score": income_score,
                    "population":   population,
                    "area_km2":     area_km2,
                    "pop_density":  pop_density,
                    "solar":        solar,
                    "lat":          lat,
                    "lon":          lon,
                })
    return units


def normalize_and_score(units: list[dict]) -> list[dict]:
    """Run MinMaxScaler across all units and compute weighted geo_score."""
    solar_arr   = np.array([[u["solar"]]         for u in units], dtype=float)
    income_arr  = np.array([[u["income_score"]]  for u in units], dtype=float)
    density_arr = np.array([[u["pop_density"]]   for u in units], dtype=float)

    scaler = MinMaxScaler()
    solar_norm   = scaler.fit_transform(solar_arr).flatten()
    income_norm  = scaler.fit_transform(income_arr).flatten()
    density_norm = scaler.fit_transform(density_arr).flatten()

    w = config.WEIGHTS
    for i, u in enumerate(units):
        u["solar_norm"]       = round(float(solar_norm[i]),   6)
        u["income_norm"]      = round(float(income_norm[i]),  6)
        u["pop_density_norm"] = round(float(density_norm[i]), 6)
        u["geo_score"]        = round(
            w["solar"]      * u["solar_norm"]
            + w["income"]   * u["income_norm"]
            + w["population"] * u["pop_density_norm"],
            6,
        )
    return units


def upsert_to_db(units: list[dict], progress_callback=None) -> None:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    total = len(units)
    try:
        for i, u in enumerate(units):
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (u["name"], u["province"]),
            ).fetchone()
            if row:
                muni_id = row["id"]
                conn.execute(
                    """UPDATE municipalities
                       SET region=?, income_class=?, population=?, area_km2=?, lat=?, lon=?
                       WHERE id=?""",
                    (u["region"], u["income_class"], u["population"],
                     u["area_km2"], u["lat"], u["lon"], muni_id),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO municipalities
                       (name, province, region, income_class, population, area_km2, lat, lon)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (u["name"], u["province"], u["region"], u["income_class"],
                     u["population"], u["area_km2"], u["lat"], u["lon"]),
                )
                muni_id = cur.lastrowid

            conn.execute(
                """INSERT INTO geo_scores
                   (municipality_id, solar_irradiance, solar_norm, income_score,
                    pop_density, pop_density_norm, geo_score, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(municipality_id) DO UPDATE SET
                     solar_irradiance = excluded.solar_irradiance,
                     solar_norm       = excluded.solar_norm,
                     income_score     = excluded.income_score,
                     pop_density      = excluded.pop_density,
                     pop_density_norm = excluded.pop_density_norm,
                     geo_score        = excluded.geo_score,
                     computed_at      = excluded.computed_at""",
                (muni_id, u["solar"], u["solar_norm"], u["income_score"],
                 u["pop_density"], u["pop_density_norm"], u["geo_score"]),
            )

            if (i + 1) % 50 == 0:
                conn.commit()
            if progress_callback:
                progress_callback(i + 1, total)

        conn.commit()
        logger.info(f"Precompute: upserted {total} municipalities.")
    finally:
        conn.close()


def precompute_geo_scores(progress_callback=None) -> None:
    logger.info("Precompute: loading municipalities...")
    units = _get_all_municipalities()
    logger.info(f"Precompute: {len(units)} municipalities found. Normalizing...")
    units = normalize_and_score(units)
    logger.info("Precompute: writing to DB...")
    upsert_to_db(units, progress_callback=progress_callback)
    logger.info("Precompute: complete.")


if __name__ == "__main__":
    def _cli_progress(done: int, total: int) -> None:
        if done % 100 == 0 or done == total:
            print(f"\r  {done}/{total} ({done/total*100:.0f}%)", end="", flush=True)

    precompute_geo_scores(progress_callback=_cli_progress)
    print()
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_precompute.py -v
```

Expected: 8 PASSED.

- [ ] **Step 5: Run precompute against real DB to fix the broken data**

```bash
source .venv_helios/bin/activate
python scripts/precompute_geo_scores.py
```

Expected: `1622/1622 (100%)` then done. Verify:

```bash
python -c "
import sqlite3, config
conn = sqlite3.connect(str(config.HELIO_DB))
r = conn.execute('SELECT AVG(geo_score), MAX(geo_score), MIN(geo_score) FROM geo_scores').fetchone()
print(f'avg={r[0]:.3f}  max={r[1]:.3f}  min={r[2]:.3f}')
conn.close()
"
```

Expected: avg around 0.45–0.55, max close to 1.0, min close to 0.0. If avg is still ~0.35, the old bug persists — re-check the `normalize_and_score` function.

- [ ] **Step 6: Commit**

```bash
git add scripts/precompute_geo_scores.py tests/test_precompute.py
git commit -m "feat: rewrite precompute with correct 3-component normalization"
```

---

## Task 4: agents/geo_scoring.py — DB lookup path

**Files:**
- Modify: `agents/geo_scoring.py`
- Create: `tests/test_geo_scoring_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_geo_scoring_db.py
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
    # Patch run_pipeline / GEE to ensure DB path is taken (no GEE call)
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_geo_scoring_db.py -v 2>&1 | head -20
```

Expected: ImportError — `_load_scores_from_db` not defined.

- [ ] **Step 3: Add `_load_scores_from_db` and update `geo_scoring_agent` in agents/geo_scoring.py**

Add this function after the existing helper functions (before `geo_scoring_agent`):

```python
def _load_scores_from_db(units: list[dict]) -> dict:
    """
    Look up pre-computed geo scores from helio.db.
    Returns the same dict shape as compute_geo_scores() so downstream agents
    are unaffected.
    """
    import sqlite3
    if not config.HELIO_DB.exists() or not units:
        return {}

    conditions = " OR ".join(["(m.name=? AND m.province=?)"] * len(units))
    params = []
    for u in units:
        params.extend([u["name"], u.get("province", "")])

    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT m.name, m.province, m.region, m.lat, m.lon,
                       m.income_class, m.population, m.area_km2,
                       g.solar_irradiance, g.solar_norm, g.income_score,
                       g.pop_density, g.pop_density_norm, g.geo_score
                FROM municipalities m
                JOIN geo_scores g ON g.municipality_id = m.id
                WHERE {conditions}""",
            params,
        ).fetchall()
    finally:
        conn.close()

    result = {}
    for r in rows:
        income_norm = (r["income_score"] - 1) / 5.0 if r["income_score"] else 0
        population  = r["population"] or 0
        result[r["name"]] = {
            "province":       r["province"],
            "region":         r["region"],
            "is_urban":       population > 50000,
            "income_class":   r["income_class"] or "3rd",
            "solar_raw":      r["solar_irradiance"] or 5.0,
            "population_raw": population,
            "income_raw":     r["income_score"] or 3,
            "solar_yield_kwh": round((r["solar_irradiance"] or 5.0) * 365 * 0.80, 0),
            "lat":            r["lat"],
            "lon":            r["lon"],
            "solar_norm":     r["solar_norm"] or 0,
            "pop_norm":       r["pop_density_norm"] or 0,
            "income_norm":    income_norm,
            "geo_score":      r["geo_score"] or 0,
        }
    return result


def _db_has_scores() -> bool:
    """Return True if geo_scores table is populated."""
    import sqlite3
    if not config.HELIO_DB.exists():
        return False
    try:
        conn = sqlite3.connect(str(config.HELIO_DB))
        count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False
```

Then update `geo_scoring_agent` to use the DB path. Replace the function body from `try:` onward:

```python
def geo_scoring_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 1] Geo scoring for: {state['location']}")

    try:
        location = state["location"]

        # ── Parse location into unit list (names + provinces only) ──────────
        if location.count(",") == 1:
            parts = location.rsplit(",", 1)
            town_part, province = parts[0].strip(), parts[1].strip()
            if " | " in town_part:
                towns = [t.strip() for t in town_part.split(" | ")]
                units = []
                for town in towns:
                    units.extend(load_single_municipality(town, province))
            else:
                units = load_single_municipality(town_part, province)
        else:
            units = load_municipalities(location)

        if not units:
            logger.warning("[Agent 1] No municipalities found. Using synthetic fallback.")
            units = _synthetic_fallback(state["location"])

        # ── Try DB lookup ────────────────────────────────────────────────────
        if _db_has_scores():
            scores = _load_scores_from_db(units)
            if scores:
                logger.info(
                    f"[Agent 1] DB lookup: {len(scores)} municipalities (no GEE)."
                )
                # Build GeoJSON from DB coordinates
                import geopandas as gpd
                from shapely.geometry import Point
                records = [
                    {**v, "name": k, "geometry": Point(v["lon"], v["lat"])}
                    for k, v in scores.items()
                    if v.get("lat") and v.get("lon")
                ]
                gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
                gdf["geo_score"] = gdf["name"].map(
                    lambda n: scores.get(n, {}).get("geo_score", 0)
                )
                return {**state, "geo_scores": scores, "geo_geojson": gdf.to_json()}

        # ── On-the-fly fallback (DB empty or unit not found) ─────────────────
        logger.info("[Agent 1] DB empty — computing geo scores on the fly.")
        ee = _init_gee()
        from agents.geocoder import geocode_units
        units = geocode_units(units)
        gdf = units_to_geodataframe(units)
        if gdf.empty:
            raise ValueError("No geographic units to score.")
        scores = compute_geo_scores(gdf, ee=ee)
        gdf["geo_score"] = gdf["name"].map(
            lambda n: scores.get(n, {}).get("geo_score", 0)
        )
        logger.info(f"[Agent 1] On-the-fly scored {len(scores)} municipalities.")
        return {**state, "geo_scores": scores, "geo_geojson": gdf.to_json()}

    except Exception as e:
        logger.error(f"[Agent 1] Failed: {e}")
        return {
            **state,
            "geo_scores": {},
            "errors": state["errors"] + [f"Geo scoring error: {str(e)}"],
        }
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_geo_scoring_db.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Confirm existing geo scoring tests still pass**

```bash
pytest tests/test_geo_scoring_single.py -v
```

Expected: all PASSED (fallback path unchanged).

- [ ] **Step 6: Commit**

```bash
git add agents/geo_scoring.py tests/test_geo_scoring_db.py
git commit -m "feat: geo_scoring_agent reads from DB; falls back to on-the-fly"
```

---

## Task 5: agents/web_intel.py — SQLite cache

**Files:**
- Modify: `agents/web_intel.py`
- Create: `tests/test_web_intel_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_web_intel_db.py
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
    from agents.web_intel import _set_db_cache, _get_db_cache
    intel = {"business_count": 5, "avg_price_level": 1.0,
             "avg_rating": 3.0, "commercial_anchors": 0,
             "news_snippet": "", "property_snippet": "",
             "commerce_snippet": "", "solar_news_snippet": "", "total_reviews": 0}
    # Write with already-expired expires_at
    conn = sqlite3.connect(str(fresh_db))
    past = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_web_intel_db.py -v 2>&1 | head -20
```

Expected: ImportError — `_compute_web_score`, `_set_db_cache`, `_get_db_cache` not defined.

- [ ] **Step 3: Update agents/web_intel.py**

Replace the entire cache section (everything from `# ── Persistent web intel cache` through `set_cached_intel`) and update `gather_intel_for_municipality`:

```python
# ── DB-backed web intel cache ──────────────────────────────────────────────────

import sqlite3 as _sqlite3


def _compute_web_score(intel: dict) -> float:
    """Compute web_score from raw intel signals. Range: 0–1."""
    biz_density   = min(intel.get("business_count", 0) / 20, 1.0)
    price_signal  = min(intel.get("avg_price_level", 0) / 4, 1.0)
    rating_raw    = intel.get("avg_rating", 0)
    rating_signal = max((rating_raw - 1.0) / 4.0, 0) if rating_raw else 0
    anchor_signal = min(intel.get("commercial_anchors", 0) / 5, 1.0)
    return round(
        0.35 * biz_density
        + 0.25 * price_signal
        + 0.25 * rating_signal
        + 0.15 * anchor_signal,
        4,
    )


def _get_db_cache(municipality: str, province: str) -> dict | None:
    """Return cached intel dict if fresh, else None."""
    from agents.db_store import get_municipality_id
    muni_id = get_municipality_id(municipality, province)
    if muni_id is None:
        return None
    conn = _sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = _sqlite3.Row
    try:
        row = conn.execute(
            """SELECT places_data, web_score FROM web_intel_cache
               WHERE municipality_id=? AND expires_at > datetime('now')""",
            (muni_id,),
        ).fetchone()
        if row and row["places_data"]:
            result = json.loads(row["places_data"])
            result["web_score"] = row["web_score"]
            return result
        return None
    except Exception as e:
        logger.warning(f"web_intel._get_db_cache failed: {e}")
        return None
    finally:
        conn.close()


def _set_db_cache(municipality: str, province: str, intel: dict, web_score: float) -> None:
    """Write intel + web_score to web_intel_cache table."""
    from agents.db_store import get_municipality_id
    from datetime import datetime, timezone, timedelta
    muni_id = get_municipality_id(municipality, province)
    if muni_id is None:
        logger.warning(f"web_intel: no municipality_id for {municipality}, {province} — skipping DB cache")
        return
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(days=config.WEB_INTEL_CACHE_TTL_DAYS)
    conn = _sqlite3.connect(str(config.HELIO_DB))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO web_intel_cache
               (municipality_id, business_count, avg_price_level, places_data,
                web_score, fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                muni_id,
                intel.get("business_count", 0),
                intel.get("avg_price_level", 0),
                json.dumps(intel),
                web_score,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"web_intel._set_db_cache failed: {e}")
    finally:
        conn.close()
```

Then update `gather_intel_for_municipality` to use the new cache functions:

```python
def gather_intel_for_municipality(municipality: str, geo: dict | None = None) -> dict:
    province = (geo or {}).get("province", "")

    cached = _get_db_cache(municipality, province)
    if cached:
        logger.info(f"  [Web Intel] DB cache hit: {municipality} ({province})")
        return cached

    logger.info(f"  [Web Intel] Fetching: {municipality} ({province})")
    lat = (geo or {}).get("lat")
    lon = (geo or {}).get("lon")
    search_name = f"{municipality}, {province}" if province else municipality

    news             = search_web(f"economic development {search_name} Philippines 2024 2025")
    property_signal  = search_web(f"house prices real estate {search_name} Philippines Lamudi PropertyPro")
    commerce         = search_web(f"business establishments commercial activity {search_name} Philippines")
    solar_news       = search_web(f"solar panel installation {search_name} Philippines")
    places           = get_places_signal(municipality, province=province, lat=lat, lon=lon)

    result = {
        "news_snippet":        news[:500],
        "property_snippet":    property_signal[:500],
        "commerce_snippet":    commerce[:500],
        "solar_news_snippet":  solar_news[:300],
        "business_count":      places["business_count"],
        "avg_price_level":     places["avg_price_level"],
        "avg_rating":          places.get("avg_rating", 0),
        "total_reviews":       places.get("total_reviews", 0),
        "commercial_anchors":  places.get("commercial_anchors", 0),
    }

    web_score = _compute_web_score(result)
    _set_db_cache(municipality, province, result, web_score)
    result["web_score"] = web_score
    return result
```

Also remove the old module-level JSON cache variables and functions (`_CACHE_FILE`, `_CACHE_TTL_DAYS`, `_cache`, `_load_cache`, `_save_cache`, `_cache_key`, `_is_fresh`, `get_cached_intel`, `set_cached_intel`).

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_web_intel_db.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/web_intel.py tests/test_web_intel_db.py
git commit -m "feat: web_intel caches to SQLite; computes and stores web_score"
```

---

## Task 6: agents/synthesis.py — 70/30 weights + web_score passthrough

**Files:**
- Modify: `agents/synthesis.py`
- Create: `tests/test_synthesis_weights.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_synthesis_weights.py
import pytest
import config


def test_compute_final_score_uses_new_weights():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 1.0}
    intel = {"web_score": 0.0}
    final, web = compute_final_score(geo, intel)
    # With geo=1.0, web=0.0 → final = 0.70 * 1.0 + 0.30 * 0.0 = 0.70
    assert final == pytest.approx(0.70, abs=1e-4)


def test_compute_final_score_returns_tuple():
    from agents.synthesis import compute_final_score
    result = compute_final_score({"geo_score": 0.5}, {"web_score": 0.5})
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_compute_final_score_uses_cached_web_score():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 0.6}
    intel = {"web_score": 0.8, "business_count": 0, "avg_price_level": 0}
    final, web = compute_final_score(geo, intel)
    # web_score=0.8 from cache; must use it directly
    assert web == pytest.approx(0.8)
    assert final == pytest.approx(0.70 * 0.6 + 0.30 * 0.8, abs=1e-4)


def test_compute_final_score_falls_back_when_no_cached_web_score():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 0.5}
    intel = {"business_count": 0, "avg_price_level": 0, "avg_rating": 0, "commercial_anchors": 0}
    final, web = compute_final_score(geo, intel)
    # No web_score key → computed inline → should be 0.0 for empty intel
    assert web == pytest.approx(0.0)
    assert final == pytest.approx(0.70 * 0.5, abs=1e-4)


def test_synthesis_agent_stores_web_score_in_final_scores(monkeypatch):
    import agents.synthesis as synth
    monkeypatch.setattr(synth, "synthesize_municipality",
                        lambda m, g, i: {"assessment": "", "confidence": "HIGH",
                                         "opportunity": "", "risk": ""})
    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "Laguna", "run_id": "t1",
        "geo_scores": {
            "Biñan": {"geo_score": 0.7, "province": "Laguna", "region": "IV-A",
                      "income_class": "2nd", "population_raw": 100000,
                      "solar_norm": 0.7, "solar_yield_kwh": 1500,
                      "pop_norm": 0.6, "income_norm": 0.8, "is_urban": True},
        },
        "web_intel": {
            "Biñan": {"web_score": 0.5, "business_count": 10, "avg_price_level": 2.0,
                      "avg_rating": 4.0, "commercial_anchors": 2,
                      "news_snippet": "", "property_snippet": "",
                      "commerce_snippet": "", "solar_news_snippet": ""},
        },
        "final_scores": None, "top_targets": None,
        "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    result = synth.synthesis_agent(state)
    assert "Biñan" in result["final_scores"]
    assert "web_score" in result["final_scores"]["Biñan"]
    assert result["final_scores"]["Biñan"]["web_score"] == pytest.approx(0.5)
    assert "web_score" in result["top_targets"][0]
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_synthesis_weights.py -v 2>&1 | head -20
```

Expected: `compute_final_score` returns a float, not a tuple → fails tuple tests.

- [ ] **Step 3: Update agents/synthesis.py**

Replace `compute_final_score`:

```python
def compute_final_score(geo: dict, intel: dict) -> tuple[float, float]:
    """
    Returns (final_score, web_score).
    Uses intel["web_score"] if pre-computed (DB cache hit), else computes inline.
    """
    geo_score = geo.get("geo_score", 0)

    if "web_score" in intel and intel["web_score"] is not None:
        web_score = intel["web_score"]
    else:
        biz_density   = min(intel.get("business_count", 0) / 20, 1.0)
        price_signal  = min(intel.get("avg_price_level", 0) / 4, 1.0)
        rating_raw    = intel.get("avg_rating", 0)
        rating_signal = max((rating_raw - 1.0) / 4.0, 0) if rating_raw else 0
        anchor_signal = min(intel.get("commercial_anchors", 0) / 5, 1.0)
        web_score = (
            0.35 * biz_density
            + 0.25 * price_signal
            + 0.25 * rating_signal
            + 0.15 * anchor_signal
        )

    final = round(config.FINAL_GEO_WEIGHT * geo_score + config.FINAL_WEB_WEIGHT * web_score, 4)
    return final, round(web_score, 4)
```

Update `synthesis_agent` to unpack the tuple and store `web_score`:

```python
        final_score, web_score = compute_final_score(geo, intel)
        narrative = synthesize_municipality(municipality, geo, intel)

        final_scores[municipality] = {
            "geo_score":          geo.get("geo_score", 0),
            "web_score":          web_score,                  # NEW
            "final_score":        final_score,
            "solar_kwh_estimate": round(geo.get("solar_raw", 5.0) * 365 * 0.8, 0),
            "tier":               narrative["confidence"],
            "assessment":         narrative["assessment"],
            "opportunity":        narrative["opportunity"],
            "risk":               narrative["risk"],
            "province":           geo.get("province", ""),
            "region":             geo.get("region", ""),
            "income_class":       geo.get("income_class", ""),
            "population":         int(geo.get("population_raw", 0)),
            "is_urban":           geo.get("is_urban", False),
        }
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_synthesis_weights.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/synthesis.py tests/test_synthesis_weights.py
git commit -m "feat: synthesis uses 70/30 weights; web_score in final_scores dict"
```

---

## Task 7: agents/report_gen.py + graph/pipeline.py — DB write + run_id param

**Files:**
- Modify: `agents/report_gen.py`
- Modify: `graph/pipeline.py`

No new test file — covered by existing integration and the db_store tests already validate `save_report`.

- [ ] **Step 1: Update agents/report_gen.py**

Add DB write after the file write in `report_gen_agent`:

```python
# agents/report_gen.py — add import at top
from agents import db_store

# In report_gen_agent, after report_path = save_report(...):
    province = top_targets[0].get("province", state["location"]) if top_targets else state["location"]
    db_store.save_report(
        run_id=state["run_id"],
        province=province,
        municipality=None,
        markdown=markdown,
        file_path=report_path,
    )
```

Full updated `report_gen_agent`:

```python
def report_gen_agent(state: SolarLeadState) -> SolarLeadState:
    logger.info(f"[Agent 4] Generating report for: {state['location']}")

    top_targets = state.get("top_targets") or []
    if not top_targets:
        logger.warning("[Agent 4] No targets to report on.")
        return {**state, "report_markdown": "No targets found.", "report_path": None}

    markdown    = generate_report_markdown(state["location"], top_targets)
    report_path = save_report(state["location"], markdown, state["run_id"])

    province = top_targets[0].get("province", state["location"]) if top_targets else state["location"]
    db_store.save_report(
        run_id=state["run_id"],
        province=province,
        municipality=None,
        markdown=markdown,
        file_path=report_path,
    )

    return {**state, "report_markdown": markdown, "report_path": report_path}
```

- [ ] **Step 2: Update graph/pipeline.py — accept optional run_id**

```python
def run_pipeline(location: str, run_id: str | None = None) -> SolarLeadState:
    pipeline = build_pipeline()

    initial_state: SolarLeadState = {
        "location": location,
        "run_id":   run_id or str(uuid.uuid4())[:8],
        "geo_scores": None, "geo_geojson": None,
        "web_intel": None, "final_scores": None, "top_targets": None,
        "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    return pipeline.invoke(initial_state)
```

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
pytest tests/ -v --ignore=tests/api -x
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add agents/report_gen.py graph/pipeline.py
git commit -m "feat: report_gen writes to DB; pipeline accepts external run_id"
```

---

## Task 8: agents/chatbot.py — Ollama embedding + DB KB source + chat persistence

**Files:**
- Modify: `agents/chatbot.py`

Prerequisite: Ollama must be running with the model pulled:
```bash
ollama pull qwen3-embedding
ollama serve   # if not already running
```

- [ ] **Step 1: Update embedding function and add collection-reset logic**

Replace the top of `chatbot.py` (from `# ChromaDB setup` through `_collection = ...`):

```python
# agents/chatbot.py

from pathlib import Path
from loguru import logger
import anthropic
import chromadb
from chromadb.utils import embedding_functions

import config
from graph.state import SolarLeadState

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)

# ChromaDB setup
_chroma_client = chromadb.PersistentClient(path=str(config.KB_INDEX))

_embed_fn = embedding_functions.OllamaEmbeddingFunction(
    model_name=config.OLLAMA_EMBED_MODEL,
    url=config.OLLAMA_URL,
)

# Marker file stores the embedding model name used to build the current index.
# If it differs from config, the collection is wiped and rebuilt.
_EMBED_MARKER = config.KB_INDEX / ".embed_model"


def _get_collection() -> chromadb.Collection:
    """Return the ChromaDB collection, recreating it if the embedding model changed."""
    stored = _EMBED_MARKER.read_text().strip() if _EMBED_MARKER.exists() else None
    if stored != config.OLLAMA_EMBED_MODEL:
        logger.info(
            f"Embedding model changed ({stored!r} → {config.OLLAMA_EMBED_MODEL!r}). "
            "Wiping and recreating ChromaDB collection..."
        )
        try:
            _chroma_client.delete_collection("solar_lead_kb")
        except Exception:
            pass
        _EMBED_MARKER.write_text(config.OLLAMA_EMBED_MODEL)
    return _chroma_client.get_or_create_collection(
        name="solar_lead_kb",
        embedding_function=_embed_fn,
    )


_collection = _get_collection()
```

- [ ] **Step 2: Replace `index_documents_from_kb` with DB source**

```python
def index_documents_from_kb() -> None:
    """
    Index reports from the DB and intel files from kb/intel/.
    Skips already-indexed doc IDs — safe to call repeatedly.
    """
    from agents.db_store import list_reports

    existing_ids = set(_collection.get()["ids"])

    # ── Reports from DB ────────────────────────────────────────────────────
    for report in list_reports():
        doc_id = report["slug"]
        if doc_id in existing_ids:
            continue
        text   = report.get("markdown", "")
        chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        if not chunks:
            continue
        chunk_ids  = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        new_chunks = [(cid, c) for cid, c in zip(chunk_ids, chunks) if cid not in existing_ids]
        if new_chunks:
            _collection.add(
                documents=[c for _, c in new_chunks],
                ids=[cid for cid, _ in new_chunks],
                metadatas=[{
                    "source":   f"db:reports:{doc_id}",
                    "province": report.get("province", ""),
                } for _ in new_chunks],
            )
            logger.info(f"Indexed {len(new_chunks)} chunks from report {doc_id}")

    # ── Municipality intel files from kb/intel/ (not in DB yet) ───────────
    for md_file in Path(config.KB_INTEL).glob("*.md"):
        doc_id = md_file.stem
        if doc_id in existing_ids:
            continue
        text   = md_file.read_text(encoding="utf-8")
        chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        if not chunks:
            continue
        chunk_ids  = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        new_chunks = [(cid, c) for cid, c in zip(chunk_ids, chunks) if cid not in existing_ids]
        if new_chunks:
            _collection.add(
                documents=[c for _, c in new_chunks],
                ids=[cid for cid, _ in new_chunks],
                metadatas=[{"source": str(md_file)} for _ in new_chunks],
            )
            logger.info(f"Indexed {len(new_chunks)} chunks from {md_file.name}")
```

- [ ] **Step 3: Add run_id parameter to `chat()` and persist messages**

```python
def chat(user_message: str, chat_history: list, run_id: str = "") -> tuple[str, list]:
    """
    Single turn of the chatbot.
    Returns (assistant_response, updated_chat_history).
    Persists both turns to DB if run_id is provided.
    """
    index_documents_from_kb()
    context  = retrieve_context(user_message)
    messages = chat_history.copy()
    messages.append({
        "role":    "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}",
    })

    try:
        response = client.messages.create(
            model=config.CHATBOT_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant_reply = next(b.text for b in response.content if hasattr(b, "text"))

        if run_id:
            from agents.db_store import save_chat_message
            save_chat_message(run_id, "user", user_message)
            save_chat_message(run_id, "assistant", assistant_reply)

        updated_history = chat_history + [
            {"role": "user",      "content": user_message},
            {"role": "assistant", "content": assistant_reply},
        ]
        return assistant_reply, updated_history

    except Exception as e:
        error_msg = f"Sorry, I couldn't generate a response: {e}"
        return error_msg, chat_history
```

- [ ] **Step 4: Verify Ollama embedding works**

```bash
source .venv_helios/bin/activate
python -c "
from agents.chatbot import _collection, index_documents_from_kb
print('Collection:', _collection.name)
index_documents_from_kb()
count = _collection.count()
print(f'Indexed chunks: {count}')
"
```

Expected: prints collection name and chunk count (≥0). If Ollama is not running, this will print an error — start Ollama first.

- [ ] **Step 5: Commit**

```bash
git add agents/chatbot.py
git commit -m "feat: chatbot uses Ollama qwen3-embedding; indexes from DB; persists chat"
```

---

## Task 9: app.py — run lifecycle, sidebar history, Admin page

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Update imports and session state defaults**

Replace the old `session_store` import and add new imports at the top:

```python
# Remove:
from agents.session_store import save_session, load_session, list_sessions

# Add:
import threading
import time
import uuid
from datetime import datetime
from agents import db_store
```

Add `current_run_id` to session state defaults:

```python
if "pipeline_result" not in st.session_state:
    st.session_state.pipeline_result = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_run_id" not in st.session_state:
    st.session_state.current_run_id = ""
```

Add module-level progress tracker (outside any function — top level):

```python
# Module-level precompute progress tracker — written by background thread, read by UI
_precompute_state: dict = {"done": 0, "total": 0, "running": False}
```

- [ ] **Step 2: Update the Analyze button — add run lifecycle hooks**

Replace the existing `if st.button("▶ Analyze", ...)` block:

```python
    if st.button("▶ Analyze", type="primary", use_container_width=True):
        if not location_str:
            st.error("Select a province first.")
        else:
            run_id = uuid.uuid4().hex[:8]
            st.session_state.current_run_id = run_id
            db_store.create_run(run_id, location_str, selected_prov_name)

            with st.spinner(f"Analyzing {location_str}... (this takes ~1-2 mins)"):
                try:
                    result = run_pipeline(location_str, run_id=run_id)
                    db_store.complete_run(run_id, result.get("top_targets", []))
                    st.session_state.pipeline_result = result
                    st.session_state.chat_history = []
                    if result.get("errors"):
                        st.warning(f"Completed with {len(result['errors'])} warning(s).")
                    else:
                        st.success("Done!")
                except Exception as exc:
                    db_store.fail_run(run_id, str(exc))
                    st.error(f"Pipeline failed: {exc}")
```

- [ ] **Step 3: Replace the "Load Past Session" expander with DB-backed sidebar history**

Replace the `with st.expander("📂 Load Past Session"):` block entirely:

```python
    st.markdown("---")
    st.subheader("📋 Past Runs")
    runs = db_store.list_runs(limit=10)
    if not runs:
        st.caption("No completed runs yet.")
    else:
        for run in runs:
            if run["status"] == "failed":
                st.caption(f"⚠️ {run['location']} — failed")
                continue
            try:
                dt = datetime.fromisoformat(run["created_at"])
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = str(run["created_at"])[:10]
            top_score = run.get("top_score")
            score_str = f"top {top_score:.2f}" if top_score else "no data"
            tier_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(
                run.get("top_tier", ""), "⚪"
            )
            btn_label = f"🗺️ {run['location']} — {date_str}"
            btn_help  = f"{run.get('target_count', 0)} targets · {score_str} {tier_icon}"
            if st.button(btn_label, key=f"run_{run['id']}",
                         use_container_width=True, help=btn_help):
                loaded = db_store.load_run(run["id"])
                if loaded:
                    st.session_state.pipeline_result = loaded
                    st.session_state.chat_history    = db_store.load_chat_history(run["id"])
                    st.session_state.current_run_id  = run["id"]
                    st.toast(f"Loaded: {run['location']}", icon="📂")
                    st.rerun()
```

- [ ] **Step 4: Update the chat page to pass run_id**

In the `elif page == "💬 Chatbot":` block, change the `chat()` call:

```python
        current_run_id = st.session_state.get("current_run_id", "")
        reply, updated_history = chat(
            user_input,
            st.session_state.chat_history,
            run_id=current_run_id,
        )
```

Also remove the old `save_session` call at the end of the chat block:

```python
        # Remove this line:
        # if st.session_state.pipeline_result:
        #     save_session(st.session_state.pipeline_result, updated_history)
```

- [ ] **Step 5: Add Admin page**

Add `"⚙️ Admin"` to the nav radio options and add the page block at the end of `app.py`:

```python
# In sidebar, add "⚙️ Admin" to the page radio:
page = st.radio("Navigate", ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot", "⚙️ Admin"])
```

```python
# At the end of app.py, add:

# ── Page: Admin ────────────────────────────────────────────────────────────────
elif page == "⚙️ Admin":
    st.title("⚙️ Admin")

    # ── Geo Score Refresh ──────────────────────────────────────────────────
    st.subheader("Geo Scores")

    import sqlite3 as _sq
    try:
        conn = _sq.connect(str(config.HELIO_DB))
        last_ts = conn.execute(
            "SELECT MAX(computed_at) FROM geo_scores"
        ).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
        conn.close()
        st.caption(f"{count:,} municipalities scored · last updated: {last_ts or 'never'}")
    except Exception:
        st.caption("Could not read geo_scores stats.")

    if not _precompute_state["running"]:
        if st.button("🔄 Refresh Geo Scores", type="primary"):
            from scripts.precompute_geo_scores import precompute_geo_scores

            def _run_precompute():
                _precompute_state["running"] = True
                _precompute_state["done"]    = 0
                _precompute_state["total"]   = 0

                def _cb(done: int, total: int) -> None:
                    _precompute_state["done"]  = done
                    _precompute_state["total"] = total

                precompute_geo_scores(progress_callback=_cb)
                _precompute_state["running"] = False

            threading.Thread(target=_run_precompute, daemon=True).start()
            st.rerun()
    else:
        done  = _precompute_state["done"]
        total = _precompute_state["total"] or 1
        st.progress(done / total, text=f"Scoring municipalities... {done}/{total}")
        time.sleep(0.5)
        st.rerun()

    st.markdown("---")

    # ── DB Stats ───────────────────────────────────────────────────────────
    st.subheader("DB Stats")
    try:
        conn = _sq.connect(str(config.HELIO_DB))
        tables = ["municipalities", "geo_scores", "web_intel_cache",
                  "runs", "run_results", "reports", "chat_messages"]
        for tbl in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            st.metric(tbl, f"{n:,}")
        conn.close()
    except Exception as e:
        st.warning(f"Could not read DB stats: {e}")

    st.markdown("---")

    # ── Re-index KB ────────────────────────────────────────────────────────
    st.subheader("Knowledge Base")
    st.caption(
        "Re-index rebuilds the ChromaDB collection from all reports in the DB. "
        "Run this after changing the embedding model."
    )
    if st.button("🔁 Re-index KB"):
        from agents.chatbot import _chroma_client, _get_collection, index_documents_from_kb, _EMBED_MARKER
        with st.spinner("Wiping and rebuilding KB index..."):
            try:
                _chroma_client.delete_collection("solar_lead_kb")
                if _EMBED_MARKER.exists():
                    _EMBED_MARKER.unlink()
                _get_collection()
                index_documents_from_kb()
                st.success("KB re-indexed successfully.")
            except Exception as e:
                st.error(f"Re-index failed: {e}")
```

- [ ] **Step 6: Smoke-test the app manually**

```bash
source .venv_helios/bin/activate
streamlit run app.py
```

Verify:
1. Navigate to each page — no import errors
2. Run a small pipeline (e.g. single municipality: "Santa Rosa, Laguna")
3. Confirm the run appears in "📋 Past Runs" sidebar after completion
4. Click the run to reload it — scores and report should restore
5. Send a chat message — confirm it persists (reload the run → chat history restored)
6. Navigate to Admin → confirm DB stats show rows
7. Confirm "Refresh Geo Scores" button starts and shows a progress bar

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: app.py — run lifecycle hooks, sidebar history, Admin page with precompute progress"
```

---

## Task 10: Final cleanup and full test run

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v --ignore=tests/api -x
```

Expected: all tests pass. Fix any failures before continuing.

- [ ] **Step 2: Verify the old JSON cache file is no longer written**

```bash
# Run a small pipeline
python -c "from graph.pipeline import run_pipeline; run_pipeline('Santa Rosa, Laguna')"

# Confirm JSON cache was NOT updated
ls -la data/processed/web_intel_cache.json 2>/dev/null && \
  python -c "
import json; d = json.load(open('data/processed/web_intel_cache.json'))
print('Entries:', len(d))
" || echo "JSON cache file does not exist — correct."
```

Expected: file either absent or not updated (mtime unchanged since before the run).

- [ ] **Step 3: Remove stale import from app.py if still present**

Check that `from agents.session_store import ...` is gone:

```bash
grep "session_store" app.py
```

Expected: no output.

- [ ] **Step 4: Commit cleanup**

```bash
git add -u
git commit -m "chore: remove stale session_store usage, confirm JSON cache retired"
```

---

## Self-Review Checklist

**Spec coverage:**

| Spec requirement | Covered by |
|---|---|
| Revised geo weights (0.35/0.45/0.20) | Task 1 (config), Task 3 (precompute) |
| 3-component normalization bug fixed | Task 3 |
| `geo_scoring_agent` → DB lookup | Task 4 |
| Web intel cache → SQLite | Task 5 |
| `web_score` computed + stored in DB | Task 5 |
| Final score 70/30 | Task 1 (config), Task 6 |
| `web_score` in `final_scores` dict | Task 6 |
| `db_store.py` with all functions | Task 2 |
| `report_gen` writes to `reports` table | Task 7 |
| `run_pipeline` accepts run_id | Task 7 |
| Chat persisted to `chat_messages` | Task 8 |
| Ollama `qwen3-embedding` | Task 8 |
| KB source: `reports` table not files | Task 8 |
| Embedding model reset on change | Task 8 |
| Admin page with Refresh + progress | Task 9 |
| Sidebar history panel | Task 9 |
| Run lifecycle (create/complete/fail) | Task 9 |
| DB stats in Admin | Task 9 |

**Type consistency:**
- `compute_final_score` returns `tuple[float, float]` — defined Task 6, consumed in same task's `synthesis_agent` update
- `chat(user_message, chat_history, run_id="")` — defined Task 8, called in Task 9
- `run_pipeline(location, run_id=None)` — defined Task 7, called in Task 9
- `_precompute_state` dict — defined Task 9 step 1, written by thread in step 5, read by UI in step 5
- `_get_collection()` — defined Task 8, called in Task 9 (Re-index KB button)
