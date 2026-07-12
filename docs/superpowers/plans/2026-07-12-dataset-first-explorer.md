# Dataset-First Helio Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `app.py`'s live-pipeline UI with a dataset-first explorer (national map + drill-down + RAG chatbot) that reads from the existing `data/helio.db`, never calls Google Places/Tavily at runtime, and lazily re-synthesizes any municipality whose stored AI assessment predates the 2026-07-08 real-data geo_score fix.

**Architecture:** `agents/db_store.py` gains a dedup query that treats any assessment older than its municipality's `geo_scores.computed_at` as absent. A new `agents/refresh.py` module lazily regenerates a single municipality's assessment (LLM-only, reusing cached `web_intel_cache` — zero paid API calls) on demand from the explorer or chatbot. `app.py` is rewritten to a pure read/query Streamlit app. A one-time script purges the 390 stale-basis municipality docs from the ChromaDB `kb/index/`.

**Tech Stack:** Python, SQLite (`data/helio.db`), Streamlit, Folium (`streamlit_folium`), ChromaDB, `anthropic` SDK pointed at the MiMo gateway (`agents/synthesis.py`, `agents/chatbot.py` — unchanged).

## Global Constraints

- No new calls to Google Places or Tavily anywhere in `app.py`, `agents/refresh.py`, or `agents/chatbot.py` — only `agents/synthesis.synthesize_municipality()` (MiMo LLM) may be invoked live.
- The staleness cutoff is exact: a `run_results` row is current only if its run's `completed_at >= geo_scores.computed_at` for that municipality (spec: `docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md`).
- `graph/pipeline.py`, `agents/geo_scoring.py`, `agents/web_intel.py` stay untouched — still used by `scripts/run_all_provinces.py`.
- Every DB-touching function follows the existing `agents/db_store.py` pattern: open connection, try/except with `logger.error`, `finally: conn.close()` — never raise.

---

### Task 1: Dedup query + latest-report lookup in `agents/db_store.py`

**Files:**
- Modify: `agents/db_store.py` (append two new functions at the end of the file)
- Test: `tests/test_db_store.py` (append new test functions; reuses the existing `fresh_db` fixture and `SCHEMA_SQL` at the top of the file)

**Interfaces:**
- Produces: `get_latest_scored_municipalities() -> list[dict]`, each dict:
  `{municipality_id, name, province, region, lat, lon, population, income_class, geo_score, final_score, web_score, tier, assessment, opportunities, risks}`
  (`final_score`/`web_score`/`tier`/`assessment` are `None` and `opportunities`/`risks` are `[]` unless current).
- Produces: `get_latest_report_for_province(province: str) -> dict | None`, returns
  `{"markdown": str, "file_path": str | None, "created_at": str}` for the most recently created report row matching that province, or `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db_store.py -k "get_latest" -v`
Expected: FAIL with `ImportError` / `AttributeError: module 'agents.db_store' has no attribute 'get_latest_scored_municipalities'`

- [ ] **Step 3: Implement the functions**

Append to `agents/db_store.py`:

```python
def get_latest_scored_municipalities() -> list[dict]:
    """
    One row per municipality. Assessment fields (final_score, web_score, tier,
    assessment) are None and opportunities/risks are [] unless the latest 'done'
    run's run_results row for that municipality completed at or after the
    municipality's geo_scores.computed_at — i.e. its basis is current.
    """
    conn = _get_conn()
    try:
        geo_rows = conn.execute(
            """SELECT m.id AS municipality_id, m.name, m.province, m.region,
                      m.lat, m.lon, m.population, m.income_class,
                      g.geo_score, g.computed_at AS geo_computed_at
               FROM municipalities m
               LEFT JOIN geo_scores g ON g.municipality_id = m.id"""
        ).fetchall()

        current_rows = conn.execute(
            """SELECT rr.municipality_id, rr.final_score, rr.web_score, rr.tier,
                      rr.assessment, rr.opportunities, rr.risks, r.completed_at
               FROM run_results rr
               JOIN runs r ON r.id = rr.run_id AND r.status = 'done'
               JOIN geo_scores g ON g.municipality_id = rr.municipality_id
               WHERE rr.assessment IS NOT NULL
                 AND r.completed_at >= g.computed_at"""
        ).fetchall()
    except Exception as e:
        logger.error(f"db_store.get_latest_scored_municipalities failed: {e}")
        return []
    finally:
        conn.close()

    latest: dict[int, sqlite3.Row] = {}
    for row in current_rows:
        mid = row["municipality_id"]
        if mid not in latest or row["completed_at"] > latest[mid]["completed_at"]:
            latest[mid] = row

    result = []
    for g in geo_rows:
        mid = g["municipality_id"]
        cur = latest.get(mid)
        result.append({
            "municipality_id": mid,
            "name":            g["name"],
            "province":        g["province"],
            "region":          g["region"],
            "lat":             g["lat"],
            "lon":             g["lon"],
            "population":      g["population"],
            "income_class":    g["income_class"],
            "geo_score":       g["geo_score"],
            "final_score":     cur["final_score"] if cur else None,
            "web_score":       cur["web_score"] if cur else None,
            "tier":            cur["tier"] if cur else None,
            "assessment":      cur["assessment"] if cur else None,
            "opportunities":   json.loads(cur["opportunities"]) if cur and cur["opportunities"] else [],
            "risks":           json.loads(cur["risks"]) if cur and cur["risks"] else [],
        })
    return result


def get_latest_report_for_province(province: str) -> dict | None:
    """Most recently created report row for a province, or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT markdown, file_path, created_at FROM reports
               WHERE province = ? ORDER BY created_at DESC LIMIT 1""",
            (province,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"db_store.get_latest_report_for_province failed: {e}")
        return None
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db_store.py -k "get_latest" -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full test file to check for regressions**

Run: `pytest tests/test_db_store.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/db_store.py tests/test_db_store.py
git commit -m "feat: add basis-aware municipality/report queries to db_store"
```

---

### Task 2: Lazy staleness-aware re-synthesis in `agents/refresh.py`

**Files:**
- Create: `agents/refresh.py`
- Test: `tests/test_refresh.py`

**Interfaces:**
- Consumes: `agents.db_store.get_latest_scored_municipalities()`, `agents.db_store.create_run(run_id, location, province)`, `agents.db_store.complete_run(run_id, top_targets: list[dict])` (Task 1 / existing), `agents.geo_scoring._load_scores_from_db(units: list[dict]) -> dict` (existing, `agents/geo_scoring.py:507`), `agents.synthesis.synthesize_municipality(municipality, geo, intel) -> dict` and `agents.synthesis.compute_final_score(geo, intel) -> tuple[float, float]` (existing), `agents.kb_builder.save_municipality_docs(location, final_scores, web_intel, run_id)` (existing), `agents.chatbot.index_documents_from_kb()` (existing).
- Produces: `maybe_refresh_assessment(municipality_id: int) -> dict | None` — same row shape as `get_latest_scored_municipalities()`, or `None` if the municipality doesn't exist.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_refresh.py`:

```python
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


def test_stale_with_cached_web_intel_resynthesizes(fresh_db, monkeypatch):
    from agents import db_store
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
    monkeypatch.setattr(refresh, "index_documents_from_kb", lambda: None)

    result = refresh.maybe_refresh_assessment(1)
    assert result["assessment"] == "fresh text"
    assert result["tier"] == "HIGH"
    assert result["final_score"] is not None


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_refresh.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.refresh'`

- [ ] **Step 3: Implement `agents/refresh.py`**

```python
"""
Lazy staleness-aware re-synthesis for a single municipality.

A stored assessment is treated as current only if its run completed at or
after the municipality's geo_scores.computed_at (see
docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md). This
module regenerates a stale or missing assessment on demand using only the
LLM synthesis step — it never calls Google Places or Tavily. It only acts
when a web_intel_cache row already exists for the municipality (any age);
otherwise the municipality stays geo-only.
"""
import json
import uuid

from loguru import logger

import config
from agents import db_store
from agents.geo_scoring import _load_scores_from_db
from agents.synthesis import synthesize_municipality, compute_final_score
from agents.kb_builder import save_municipality_docs
from agents.chatbot import index_documents_from_kb


def _load_cached_intel(municipality_id: int) -> dict | None:
    """Any cached web_intel_cache row for this municipality, ignoring expiry —
    reused regardless of age since no new Places/Tavily call will be made."""
    import sqlite3
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT places_data, web_score FROM web_intel_cache WHERE municipality_id=?",
            (municipality_id,),
        ).fetchone()
        if row and row["places_data"]:
            result = json.loads(row["places_data"])
            result["web_score"] = row["web_score"]
            return result
        return None
    except Exception as e:
        logger.warning(f"refresh._load_cached_intel failed: {e}")
        return None
    finally:
        conn.close()


def maybe_refresh_assessment(municipality_id: int) -> dict | None:
    """
    Ensures the municipality has a current assessment if possible without any
    new Google Places/Tavily calls. Returns the current row (same shape as
    db_store.get_latest_scored_municipalities()) or None if the municipality
    doesn't exist.
    """
    rows = db_store.get_latest_scored_municipalities()
    row = next((r for r in rows if r["municipality_id"] == municipality_id), None)
    if row is None:
        return None
    if row["assessment"] is not None:
        return row  # already current

    intel = _load_cached_intel(municipality_id)
    if intel is None:
        return row  # no cached web intel — stays geo-only, no API call

    geo_map = _load_scores_from_db([{"name": row["name"], "province": row["province"]}])
    geo = geo_map.get(row["name"])
    if geo is None:
        return row

    try:
        final_score, web_score = compute_final_score(geo, intel)
        narrative = synthesize_municipality(row["name"], geo, intel)
    except Exception as e:
        logger.warning(f"refresh.maybe_refresh_assessment synthesis failed for {row['name']}: {e}")
        return row

    run_id = f"refresh_{uuid.uuid4().hex[:8]}"
    top_target = {
        "municipality":     row["name"],
        "province":         row["province"],
        "region":           row["region"],
        "lat":              row["lat"],
        "lon":              row["lon"],
        "population":       row["population"],
        "income_class":     row["income_class"],
        "geo_score":        geo.get("geo_score", 0),
        "web_score":        web_score,
        "final_score":      final_score,
        "tier":             narrative["confidence"],
        "assessment":       narrative["assessment"],
        "opportunity":      narrative["opportunity"],
        "risk":             narrative["risk"],
        "solar_irradiance": geo.get("solar_raw"),
        "solar_yield_kwh":  geo.get("solar_yield_kwh"),
        "pop_density":      geo.get("pop_norm"),
    }
    db_store.create_run(run_id, row["name"], row["province"])
    db_store.complete_run(run_id, [top_target])

    try:
        final_scores = {row["name"]: {
            "final_score":        final_score,
            "tier":               narrative["confidence"],
            "geo_score":          geo.get("geo_score", 0),
            "solar_kwh_estimate": geo.get("solar_yield_kwh", 0),
            "assessment":         narrative["assessment"],
            "opportunity":        narrative["opportunity"],
            "risk":               narrative["risk"],
            "province":           row["province"],
            "region":             row["region"],
            "income_class":       row["income_class"],
            "population":         row["population"] or 0,
            "is_urban":           (row["population"] or 0) > 50000,
        }}
        save_municipality_docs(
            location=row["province"], final_scores=final_scores,
            web_intel={row["name"]: intel}, run_id=run_id,
        )
        index_documents_from_kb()
    except Exception as e:
        logger.warning(f"refresh.maybe_refresh_assessment KB update failed for {row['name']}: {e}")

    refreshed = db_store.get_latest_scored_municipalities()
    return next((r for r in refreshed if r["municipality_id"] == municipality_id), row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_refresh.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/refresh.py tests/test_refresh.py
git commit -m "feat: lazy staleness-aware re-synthesis with zero new API calls"
```

---

### Task 3: One-time KB purge script for the 390 stale-basis municipalities

**Files:**
- Create: `scripts/purge_stale_kb_docs.py`
- Test: `tests/test_purge_stale_kb_docs.py`

**Interfaces:**
- Consumes: `agents.db_store._get_conn()` (existing, private but already used cross-module in this codebase, e.g. `app.py`'s Admin panel reaches into `agents.chatbot` internals the same way).
- Produces: `find_stale_municipalities(conn: sqlite3.Connection) -> list[dict]` (`{municipality_id, name, province}`), `stale_doc_ids(collection_ids: list[str], stale: list[dict]) -> list[str]` (pure function — the actual chunk ids in the Chroma collection whose filename-derived doc_id matches a stale municipality), `main(dry_run: bool = True) -> None` (CLI entry point).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_purge_stale_kb_docs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_purge_stale_kb_docs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.purge_stale_kb_docs'`

- [ ] **Step 3: Implement `scripts/purge_stale_kb_docs.py`**

```python
"""
One-time migration: remove the pre-real-data-fix municipality docs from the
ChromaDB kb/index/ collection (see docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md).

Scope: only the per-municipality kb/intel/*.md chunks. Province-level
kb/reports docs are left alone (out of scope — see spec).

Usage:
    python scripts/purge_stale_kb_docs.py --dry-run   # default, lists what would be removed
    python scripts/purge_stale_kb_docs.py --execute    # actually deletes from ChromaDB
"""
import argparse
import sqlite3

from loguru import logger

import config


def find_stale_municipalities(conn: sqlite3.Connection) -> list[dict]:
    """Municipalities whose latest 'done' run completed before geo_scores.computed_at."""
    rows = conn.execute(
        """SELECT m.id AS municipality_id, m.name, m.province
           FROM municipalities m
           JOIN geo_scores g ON g.municipality_id = m.id
           JOIN run_results rr ON rr.municipality_id = m.id AND rr.assessment IS NOT NULL
           JOIN runs r ON r.id = rr.run_id AND r.status = 'done'
           GROUP BY m.id
           HAVING MAX(r.completed_at) < g.computed_at"""
    ).fetchall()
    return [dict(r) for r in rows]


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace(",", "").replace(".", "").replace("/", "_")


def stale_doc_ids(collection_ids: list[str], stale: list[dict]) -> list[str]:
    """Chunk ids in the Chroma collection whose kb/intel filename prefix matches a stale municipality."""
    prefixes = [f"{_slug(m['province'])}__{_slug(m['name'])}__" for m in stale]
    return [cid for cid in collection_ids if any(cid.startswith(p) for p in prefixes)]


def main(dry_run: bool = True) -> None:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        stale = find_stale_municipalities(conn)
    finally:
        conn.close()
    logger.info(f"Found {len(stale)} stale-basis municipalities.")

    from agents.chatbot import _get_collection
    collection = _get_collection()
    all_ids = collection.get(include=[])["ids"]
    to_delete = stale_doc_ids(all_ids, stale)
    logger.info(f"{len(to_delete)} ChromaDB chunks match stale municipalities.")

    if dry_run:
        logger.info("Dry run — no deletions made. Re-run with --execute to purge.")
        for cid in to_delete[:20]:
            logger.info(f"  would delete: {cid}")
        return

    if to_delete:
        collection.delete(ids=to_delete)
        logger.info(f"Deleted {len(to_delete)} stale chunks from kb/index.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run).")
    args = parser.parse_args()
    main(dry_run=not args.execute)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_purge_stale_kb_docs.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/purge_stale_kb_docs.py tests/test_purge_stale_kb_docs.py
git commit -m "feat: one-time script to purge stale-basis docs from kb/index"
```

- [ ] **Step 6: Back up kb/index/, then dry-run against the real DB**

```bash
cp -r kb/index kb/index.bak-20260712-pre-purge
python scripts/purge_stale_kb_docs.py
```

Review the logged count and sample IDs before proceeding — confirm the count is in the expected ballpark (390 municipalities, though not all may have had a kb/intel doc indexed).

- [ ] **Step 7: Execute the real purge**

```bash
python scripts/purge_stale_kb_docs.py --execute
```

---

### Task 4: Chatbot triggers refresh when a municipality is named

**Files:**
- Modify: `agents/chatbot.py` (add municipality detection + refresh call inside `chat()`)
- Test: `tests/test_chatbot_refresh.py`

**Interfaces:**
- Consumes: `agents.refresh.maybe_refresh_assessment(municipality_id: int)` (Task 2), `agents.db_store.get_latest_scored_municipalities()` (Task 1, for the name list).
- Produces: `agents.chatbot.detect_municipality_id(message: str, municipalities: list[dict]) -> int | None` — pure function, matches the longest municipality name that appears (case-insensitive, word-boundary) in `message`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chatbot_refresh.py`:

```python
def test_detect_municipality_id_matches_exact_name():
    from agents.chatbot import detect_municipality_id
    munis = [
        {"municipality_id": 1, "name": "Biñan"},
        {"municipality_id": 2, "name": "Manila"},
    ]
    assert detect_municipality_id("Tell me about Biñan's solar potential", munis) == 1


def test_detect_municipality_id_prefers_longest_match():
    from agents.chatbot import detect_municipality_id
    munis = [
        {"municipality_id": 1, "name": "Isabela"},
        {"municipality_id": 2, "name": "City of Isabela"},
    ]
    assert detect_municipality_id("What about City of Isabela?", munis) == 2


def test_detect_municipality_id_returns_none_when_no_match():
    from agents.chatbot import detect_municipality_id
    munis = [{"municipality_id": 1, "name": "Biñan"}]
    assert detect_municipality_id("What's the weather like today?", munis) is None


def test_chat_calls_refresh_when_municipality_named(monkeypatch):
    import agents.chatbot as chatbot_mod

    monkeypatch.setattr(
        chatbot_mod, "get_latest_scored_municipalities",
        lambda: [{"municipality_id": 1, "name": "Biñan", "province": "Laguna"}],
    )
    called = {}
    monkeypatch.setattr(
        chatbot_mod, "maybe_refresh_assessment",
        lambda mid: called.setdefault("municipality_id", mid),
    )
    monkeypatch.setattr(chatbot_mod, "retrieve_context", lambda query, n_results=10: "context")

    class _FakeResponse:
        content = [type("Block", (), {"text": "reply"})()]

    monkeypatch.setattr(chatbot_mod.client.messages, "create", lambda **kwargs: _FakeResponse())

    chatbot_mod.chat("Tell me about Biñan", [], run_id="")
    assert called["municipality_id"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chatbot_refresh.py -v`
Expected: FAIL — `detect_municipality_id` does not exist.

- [ ] **Step 3: Implement in `agents/chatbot.py`**

Add near the top of `agents/chatbot.py`, after the existing imports:

```python
from agents.db_store import get_latest_scored_municipalities
from agents.refresh import maybe_refresh_assessment
```

Add this function in the "KB Management" section, after `index_documents_from_kb()`:

```python
def detect_municipality_id(message: str, municipalities: list[dict]) -> int | None:
    """Return the municipality_id of the longest municipality name found in message, or None."""
    lower_message = message.lower()
    best: tuple[int, int] | None = None  # (name length, municipality_id)
    for m in municipalities:
        name = m["name"]
        if name.lower() in lower_message:
            if best is None or len(name) > best[0]:
                best = (len(name), m["municipality_id"])
    return best[1] if best else None
```

Find the `chat()` function (`agents/chatbot.py:182`) and add the refresh call as the first thing it does, before building context. Locate the line that currently starts the function body (right after the `def chat(...)` signature and its docstring, before context retrieval) and insert:

```python
    municipalities = get_latest_scored_municipalities()
    municipality_id = detect_municipality_id(user_message, municipalities)
    if municipality_id is not None:
        maybe_refresh_assessment(municipality_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_chatbot_refresh.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/chatbot.py tests/test_chatbot_refresh.py
git commit -m "feat: chatbot lazily refreshes a municipality's assessment when named"
```

---

### Task 5: Rewrite `app.py` as a dataset-first explorer

**Files:**
- Modify: `app.py` (full rewrite)

**Interfaces:**
- Consumes: `agents.db_store.get_latest_scored_municipalities()`, `agents.db_store.get_latest_report_for_province(province)` (Task 1), `agents.refresh.maybe_refresh_assessment(municipality_id)` (Task 2), `agents.chatbot.chat(user_message, chat_history, run_id="")`, `agents.chatbot.index_documents_from_kb()` (existing, unchanged).

This task has no automated tests — Streamlit apps in this codebase aren't unit tested (see existing `app.py`, which has none). Verify manually per Step 3.

- [ ] **Step 1: Replace the full contents of `app.py`**

```python
"""
Helio — Dataset-First Solar Opportunity Explorer
Reads exclusively from data/helio.db. No live Google Places/Tavily calls.
The only "live" work is an on-demand MiMo LLM re-synthesis (agents/refresh.py)
for a municipality whose stored assessment predates the real-data geo_score fix.
"""
import folium
import streamlit as st
from streamlit_folium import st_folium

from agents.chatbot import chat, index_documents_from_kb
from agents.db_store import get_latest_scored_municipalities, get_latest_report_for_province
from agents.refresh import maybe_refresh_assessment

st.set_page_config(
    page_title="Helio — Solar Opportunity Explorer",
    page_icon="☀️",
    layout="wide",
)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "selected_municipality_id" not in st.session_state:
    st.session_state.selected_municipality_id = None


@st.cache_data(ttl=600)
def _cached_municipalities() -> list[dict]:
    return get_latest_scored_municipalities()


def _score_color(row: dict) -> str:
    """Green/orange/red for a current final_score; muted gray for needs-synthesis rows."""
    if row["final_score"] is None:
        return "#95a5a6"
    if row["final_score"] >= 0.65:
        return "#2ecc71"
    if row["final_score"] >= 0.35:
        return "#f39c12"
    return "#e74c3c"


col_map, col_chat = st.columns([3, 1.3])

with col_map:
    st.title("☀️ Helio Solar Opportunity Map")
    st.markdown(
        "🟢 High (≥0.65) &nbsp; 🟡 Medium (0.35–0.64) &nbsp; 🔴 Low (<0.35) &nbsp; "
        "⚪ Not yet fully assessed",
        unsafe_allow_html=True,
    )

    municipalities = _cached_municipalities()
    plottable = [m for m in municipalities if m["lat"] and m["lon"]]
    lats = [m["lat"] for m in plottable]
    lons = [m["lon"] for m in plottable]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)] if lats else [12.5, 122.5]

    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")
    for row in plottable:
        color = _score_color(row)
        score = row["final_score"] if row["final_score"] is not None else row["geo_score"] or 0
        radius = 4 + score * 10
        opacity = 0.85 if row["final_score"] is not None else 0.35
        tooltip = f"{row['name']} ({row['province']})"
        if row["final_score"] is not None:
            tooltip += f" — {row['final_score']:.2f}, {row['tier']}"
        else:
            tooltip += " — not yet fully assessed"

        marker = folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            weight=1,
            tooltip=tooltip,
        )
        marker.options["municipality_id"] = row["municipality_id"]
        marker.add_to(m)

    map_state = st_folium(m, height=560, use_container_width=True, key="national_map",
                           returned_objects=["last_object_clicked_tooltip"])

    clicked_tooltip = map_state.get("last_object_clicked_tooltip") if map_state else None
    if clicked_tooltip:
        clicked_name = clicked_tooltip.split(" (")[0]
        match = next((r for r in municipalities if r["name"] == clicked_name), None)
        if match:
            st.session_state.selected_municipality_id = match["municipality_id"]

    st.markdown("---")
    st.subheader("Province filter & search")
    provinces = sorted({m["province"] for m in municipalities})
    selected_province = st.selectbox("Province", ["— All —"] + provinces)
    filtered = municipalities if selected_province == "— All —" else [
        m for m in municipalities if m["province"] == selected_province
    ]
    table_rows = [
        {
            "Municipality": m["name"],
            "Province": m["province"],
            "Geo Score": round(m["geo_score"], 3) if m["geo_score"] is not None else None,
            "Final Score": round(m["final_score"], 3) if m["final_score"] is not None else None,
            "Tier": m["tier"] or "needs synthesis",
        }
        for m in sorted(filtered, key=lambda r: (r["final_score"] or r["geo_score"] or 0), reverse=True)
    ]
    st.dataframe(table_rows, use_container_width=True, height=300)

    st.markdown("---")
    st.subheader("Drill into a municipality")
    muni_names = sorted({m["name"] for m in filtered})
    picked_name = st.selectbox("Municipality", ["— Select —"] + muni_names)
    if picked_name != "— Select —":
        match = next(m for m in filtered if m["name"] == picked_name)
        st.session_state.selected_municipality_id = match["municipality_id"]

    selected_id = st.session_state.selected_municipality_id
    if selected_id is not None:
        with st.spinner("Checking assessment freshness..."):
            detail = maybe_refresh_assessment(selected_id)
        if detail is None:
            st.warning("Municipality not found.")
        else:
            st.markdown(f"### {detail['name']}, {detail['province']}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Geo Score", f"{detail['geo_score']:.3f}" if detail["geo_score"] is not None else "—")
            c2.metric("Final Score", f"{detail['final_score']:.3f}" if detail["final_score"] is not None else "—")
            c3.metric("Tier", detail["tier"] or "needs synthesis")
            c4.metric("Population", f"{detail['population']:,}" if detail["population"] else "—")

            if detail["assessment"]:
                st.write(f"**Assessment:** {detail['assessment']}")
                if detail["opportunities"]:
                    st.write(f"**Opportunity:** {detail['opportunities'][0]}")
                if detail["risks"]:
                    st.write(f"**Risk:** {detail['risks'][0]}")
            else:
                st.info("This municipality doesn't yet have a full AI assessment (no cached web intelligence to synthesize from without a new paid API call).")

            report = get_latest_report_for_province(detail["province"])
            if report:
                with st.expander(f"📄 {detail['province']} province report"):
                    st.markdown(report["markdown"])
                    if report.get("file_path"):
                        try:
                            with open(report["file_path"], "r", encoding="utf-8") as f:
                                st.download_button(
                                    "⬇️ Download report (.md)",
                                    data=f.read(),
                                    file_name=f"{detail['province']}_report.md",
                                    mime="text/markdown",
                                )
                        except FileNotFoundError:
                            pass

with col_chat:
    st.subheader("💬 Ask Helio")
    index_documents_from_kb()

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("Ask about any municipality...")
    if user_input:
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply, updated_history = chat(user_input, st.session_state.chat_history, run_id="")
            st.write(reply)
            st.session_state.chat_history = updated_history
```

- [ ] **Step 2: Sanity-check imports**

Run: `python -c "import ast; ast.parse(open('app.py').read())"`
Expected: no output (valid syntax)

- [ ] **Step 3: Manually verify in the browser**

```bash
streamlit run app.py
```

Confirm: the national map loads with all municipalities (colored/muted correctly), clicking a marker or using the province+municipality selectors shows a detail panel, a stale/never-assessed municipality with cached web intel gets a fresh assessment on first view (check `data/helio.db`'s `run_results` table for a new `refresh_*` run afterward), the province report expander shows content, and the sidebar chat answers a question about a specific municipality.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: rewrite app.py as a dataset-first explorer, drop live-pipeline UI"
```

---

## Self-review notes

- **Spec coverage:** national map + drill-down (Task 5), persistent sidebar chat (Task 5 + Task 4), report viewer (Task 1 + Task 5), basis-discard rule (Task 1), lazy re-synthesis with zero new API calls (Task 2), KB purge (Task 3), app.py pipeline-flow removal (Task 5). All spec sections have a task.
- **Out of scope, unchanged:** `graph/pipeline.py`, `agents/geo_scoring.py`, `agents/web_intel.py`, `scripts/run_all_provinces.py` — still used for any future manual national re-run, per the spec.
