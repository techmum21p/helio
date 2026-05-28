# Helio v2 — Plan 1: Backend Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `data/helio.db` (7-table SQLite schema), a FastAPI backend with all REST + SSE endpoints, and seed the municipalities table from the existing `ph_locations.db`.

**Architecture:** FastAPI app in `api/` with four routers (municipalities, runs, chat, admin). SQLite accessed directly via `sqlite3` + a context-manager helper in `api/db.py` — no ORM. Pipeline runs as a FastAPI `BackgroundTask`; SSE polls run status every 2 s. Chat and admin endpoints call existing agents unchanged.

**Tech Stack:** Python 3.11, FastAPI 0.110+, uvicorn[standard], httpx (TestClient), pytest, pytest-asyncio, nanoid via `secrets` (stdlib).

**This plan is 1 of 4:**
- **Plan 1 (this)** — DB schema + FastAPI + all endpoints
- Plan 2 — Precompute script + agent DB lookups + pipeline parallelization + SSE step events
- Plan 3 — bm25s + RRF hybrid RAG + streaming chat
- Plan 4 — Next.js 14 frontend

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `api/__init__.py` | Package marker |
| Create | `api/db.py` | Connection manager, `create_tables()`, `seed_municipalities_from_location_db()` |
| Create | `api/models.py` | All Pydantic request/response models |
| Create | `api/main.py` | App factory, CORS, startup hook, router registration |
| Create | `api/routers/__init__.py` | Package marker |
| Create | `api/routers/municipalities.py` | `GET /provinces`, `GET /municipalities` |
| Create | `api/routers/runs.py` | `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/stream` |
| Create | `api/routers/chat.py` | `POST /chat`, `GET /chat/{run_id}/history` |
| Create | `api/routers/admin.py` | `GET /admin/stats`, `POST /admin/reindex-kb`, `POST /admin/refresh-scores` (stub), `GET /admin/refresh-scores/stream` (stub) |
| Create | `tests/api/__init__.py` | Package marker |
| Create | `tests/api/conftest.py` | Shared `client` fixture with temp DB |
| Create | `tests/api/test_db.py` | Table creation + seeding |
| Create | `tests/api/test_municipalities.py` | Endpoint tests |
| Create | `tests/api/test_runs.py` | Endpoint tests |
| Create | `tests/api/test_chat.py` | Endpoint tests |
| Create | `tests/api/test_admin.py` | Endpoint tests |
| Modify | `config.py` | Add `HELIO_DB`, update `WEIGHTS` to v2 values |
| Modify | `requirements.txt` | Add fastapi, uvicorn, httpx, pytest-asyncio |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add backend packages to requirements.txt**

Find the `# Frontend` section and add below the existing block:

```
# API backend
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
pytest-asyncio>=0.23.0
anyio>=4.4.0
```

- [ ] **Step 2: Install**

```bash
source .venv_helios/bin/activate
pip install fastapi "uvicorn[standard]" httpx pytest-asyncio anyio
```

Expected: no errors, `fastapi` visible in `pip list`.

- [ ] **Step 3: Verify import**

```bash
python -c "import fastapi; print(fastapi.__version__)"
```

Expected: version string like `0.11x.x`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add fastapi/uvicorn/httpx dependencies"
```

---

## Task 2: Update config.py

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_config.py`:

```python
import config

def test_helio_db_path_defined():
    assert hasattr(config, "HELIO_DB")
    assert str(config.HELIO_DB).endswith("helio.db")

def test_weights_v2():
    assert config.WEIGHTS["solar"] == 0.35
    assert config.WEIGHTS["income"] == 0.45
    assert config.WEIGHTS["pop_density"] == 0.20
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9

def test_weights_no_population_key():
    assert "population" not in config.WEIGHTS
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv_helios/bin/activate
pytest tests/api/test_config.py -v
```

Expected: FAIL — `AttributeError: module 'config' has no attribute 'HELIO_DB'`

- [ ] **Step 3: Update config.py**

In `config.py`, replace:

```python
LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"
```

with:

```python
LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"   # source — not retired yet
HELIO_DB    = ROOT_DIR / "data" / "helio.db"           # consolidated store (v2)
```

And replace the `WEIGHTS` dict:

```python
# Scoring weights (must sum to 1.0) — v2 values
WEIGHTS = {
    "solar":       0.35,
    "income":      0.45,
    "pop_density": 0.20,
}
```

Also add `HELIO_DB` parent to the dir-creation loop:

```python
for d in [DATA_RAW, DATA_PROCESSED, KB_REPORTS, KB_INTEL, KB_INDEX,
          REPORTS_DIR, SESSIONS_DIR, HELIO_DB.parent]:
    d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/api/test_config.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/api/test_config.py
git commit -m "feat: add HELIO_DB path and update scoring weights to v2"
```

---

## Task 3: Database Setup (api/db.py)

**Files:**
- Create: `api/__init__.py`
- Create: `api/db.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_db.py`

- [ ] **Step 1: Create package markers**

```bash
touch api/__init__.py api/routers/__init__.py tests/api/__init__.py
mkdir -p api/routers
```

- [ ] **Step 2: Write the failing test**

Create `tests/api/test_db.py`:

```python
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
            "SELECT province, region FROM municipalities WHERE name='Calamba'"
        ).fetchone()
    assert row is not None
    assert row["province"] == "Laguna"
    assert "CALABARZON" in row["region"] or "Laguna" in row["region"]
```

Create `tests/api/conftest.py`:

```python
import pytest
import tempfile
from pathlib import Path
import api.db as db_module

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and create tables fresh."""
    db_file = tmp_path / "test_helio.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    db_module.create_tables()
    yield db_file
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/api/test_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'api.db'`

- [ ] **Step 4: Implement api/db.py**

Create `api/db.py`:

```python
import sqlite3
from contextlib import contextmanager
import config

DB_PATH = config.HELIO_DB


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_tables() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS municipalities (
                id          INTEGER PRIMARY KEY,
                name        TEXT    NOT NULL,
                province    TEXT    NOT NULL,
                region      TEXT    NOT NULL,
                lat         REAL,
                lon         REAL,
                area_km2    REAL,
                population  INTEGER,
                income_class TEXT
            );

            CREATE TABLE IF NOT EXISTS geo_scores (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                municipality_id   INTEGER NOT NULL UNIQUE REFERENCES municipalities(id),
                solar_irradiance  REAL,
                solar_norm        REAL,
                income_score      REAL,
                pop_density       REAL,
                pop_density_norm  REAL,
                geo_score         REAL,
                computed_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_geo_score
                ON geo_scores(geo_score DESC);

            CREATE TABLE IF NOT EXISTS runs (
                id           TEXT PRIMARY KEY,
                location     TEXT NOT NULL,
                province     TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                error        TEXT
            );

            CREATE TABLE IF NOT EXISTS run_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT    NOT NULL REFERENCES runs(id),
                municipality_id INTEGER REFERENCES municipalities(id),
                geo_score       REAL,
                web_score       REAL,
                final_score     REAL,
                tier            TEXT,
                assessment      TEXT,
                opportunities   TEXT,
                risks           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_run_results_score
                ON run_results(run_id, final_score DESC);

            CREATE TABLE IF NOT EXISTS web_intel_cache (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                municipality_id INTEGER NOT NULL UNIQUE REFERENCES municipalities(id),
                business_count  INTEGER,
                avg_price_level REAL,
                places_data     TEXT,
                tavily_snippets TEXT,
                fetched_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at      DATETIME
            );
            CREATE INDEX IF NOT EXISTS idx_web_intel_expires
                ON web_intel_cache(expires_at);

            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id     TEXT NOT NULL REFERENCES runs(id),
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT NOT NULL REFERENCES runs(id),
                province     TEXT,
                municipality TEXT,
                slug         TEXT NOT NULL UNIQUE,
                markdown     TEXT NOT NULL,
                file_path    TEXT,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)


def seed_municipalities_from_location_db() -> int:
    """Copy 1,622 municipalities from ph_locations.db into helio.db. Returns count."""
    if not config.LOCATION_DB.exists():
        return 0

    src = sqlite3.connect(str(config.LOCATION_DB))
    src.row_factory = sqlite3.Row
    rows = src.execute("""
        SELECT m.id, m.name, p.name AS province, r.name AS region
        FROM   municipalities m
        JOIN   provinces p ON m.province_id = p.id
        JOIN   regions   r ON p.region_id   = r.id
        ORDER  BY m.id
    """).fetchall()
    src.close()

    with get_db() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO municipalities (id, name, province, region) VALUES (?,?,?,?)",
            [(r["id"], r["name"], r["province"], r["region"]) for r in rows],
        )
    return len(rows)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/api/test_db.py -v
```

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/__init__.py api/db.py api/routers/__init__.py \
        tests/api/__init__.py tests/api/conftest.py tests/api/test_db.py
git commit -m "feat: helio.db schema — 7 tables + municipality seeding"
```

---

## Task 4: Pydantic Models + FastAPI App

**Files:**
- Create: `api/models.py`
- Create: `api/main.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_health.py`:

```python
from fastapi.testclient import TestClient

def test_health(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "Helio" in data["app"]
```

Add `app_client` fixture to `tests/api/conftest.py` (append to existing file):

```python
from fastapi.testclient import TestClient

@pytest.fixture
def app_client(tmp_db):
    """TestClient with fresh DB. Uses context manager so startup events (seed) run."""
    from api.main import create_app
    with TestClient(create_app()) as client:
        yield client
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/api/test_health.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'api.main'`

- [ ] **Step 3: Implement api/models.py**

Create `api/models.py`:

```python
from pydantic import BaseModel
from typing import Optional


class ProvinceOut(BaseModel):
    name: str


class MunicipalityOut(BaseModel):
    id: int
    name: str
    province: str
    region: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    geo_score: Optional[float] = None
    solar_norm: Optional[float] = None
    income_score: Optional[float] = None
    pop_density_norm: Optional[float] = None


class RunCreateIn(BaseModel):
    location: str  # "Laguna" | "San Pablo, Laguna" | "San Pablo|Calamba, Laguna"


class RunOut(BaseModel):
    id: str
    location: str
    province: Optional[str] = None
    status: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class RunDetailOut(RunOut):
    results: list[dict] = []
    report: Optional[dict] = None


class ChatIn(BaseModel):
    run_id: Optional[str] = None   # None = global KB search
    message: str


class ChatOut(BaseModel):
    reply: str
    run_id: Optional[str] = None


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: str


class AdminStatsOut(BaseModel):
    municipalities: int
    geo_scores: int
    runs: int
    run_results: int
    chat_messages: int
    reports: int
    web_intel_cache: int
    last_precompute: Optional[str] = None
```

- [ ] **Step 4: Implement api/main.py**

Create `api/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.db import create_tables, seed_municipalities_from_location_db


def create_app() -> FastAPI:
    app = FastAPI(title="Helio — Solar Opportunity Intelligence", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup():
        create_tables()
        seed_municipalities_from_location_db()

    from api.routers import municipalities, runs, chat, admin
    app.include_router(municipalities.router)
    app.include_router(runs.router)
    app.include_router(chat.router)
    app.include_router(admin.router)

    @app.get("/")
    def health():
        return {"status": "ok", "app": "Helio v2 — Solar Opportunity Intelligence"}

    return app


app = create_app()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/api/test_health.py -v
```

Expected: 1 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/models.py api/main.py tests/api/test_health.py tests/api/conftest.py
git commit -m "feat: fastapi app factory + pydantic models"
```

---

## Task 5: Municipalities Endpoints

**Files:**
- Create: `api/routers/municipalities.py`
- Create: `tests/api/test_municipalities.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_municipalities.py`:

```python
def test_list_provinces_returns_all(app_client):
    r = app_client.get("/provinces")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert len(names) >= 80  # PH has 82 provinces
    assert "Laguna" in names
    assert "Nueva Ecija" in names

def test_list_municipalities_no_filter(app_client):
    r = app_client.get("/municipalities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert "name" in data[0]
    assert "province" in data[0]

def test_list_municipalities_filter_by_province(app_client):
    r = app_client.get("/municipalities?province=Laguna")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert all(m["province"] == "Laguna" for m in data)

def test_list_municipalities_search(app_client):
    r = app_client.get("/municipalities?search=Calamba")
    assert r.status_code == 200
    names = [m["name"] for m in r.json()]
    assert any("Calamba" in n for n in names)

def test_municipality_has_expected_fields(app_client):
    r = app_client.get("/municipalities?province=Laguna&limit=1")
    assert r.status_code == 200
    m = r.json()[0]
    for field in ("id", "name", "province", "region"):
        assert field in m
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_municipalities.py -v
```

Expected: FAIL — `404 Not Found` (routes not registered yet).

- [ ] **Step 3: Implement api/routers/municipalities.py**

Create `api/routers/municipalities.py`:

```python
from fastapi import APIRouter, Query
from api.db import get_db
from api.models import ProvinceOut, MunicipalityOut

router = APIRouter(tags=["municipalities"])


@router.get("/provinces")
def list_provinces() -> list[ProvinceOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT province FROM municipalities ORDER BY province"
        ).fetchall()
    return [ProvinceOut(name=r["province"]) for r in rows]


@router.get("/municipalities")
def list_municipalities(
    province: str = Query(None, description="Filter by exact province name"),
    search: str  = Query(None, description="Partial name match"),
    limit: int   = Query(100, le=2000),
) -> list[MunicipalityOut]:
    sql = """
        SELECT m.id, m.name, m.province, m.region, m.lat, m.lon,
               g.geo_score, g.solar_norm, g.income_score, g.pop_density_norm
        FROM   municipalities m
        LEFT JOIN geo_scores g ON g.municipality_id = m.id
        WHERE  1=1
    """
    params: list = []
    if province:
        sql += " AND m.province = ?"
        params.append(province)
    if search:
        sql += " AND m.name LIKE ?"
        params.append(f"%{search}%")
    sql += " ORDER BY COALESCE(g.geo_score, 0) DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        MunicipalityOut(
            id=r["id"], name=r["name"], province=r["province"], region=r["region"],
            lat=r["lat"], lon=r["lon"],
            geo_score=r["geo_score"], solar_norm=r["solar_norm"],
            income_score=r["income_score"], pop_density_norm=r["pop_density_norm"],
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_municipalities.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/municipalities.py tests/api/test_municipalities.py
git commit -m "feat: GET /provinces and GET /municipalities endpoints"
```

---

## Task 6: Runs Endpoints

**Files:**
- Create: `api/routers/runs.py`
- Create: `tests/api/test_runs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_runs.py`:

```python
import time
from unittest.mock import patch

FAKE_RESULT = {
    "location": "Laguna",
    "top_targets": [
        {
            "municipality": "Calamba", "province": "Laguna",
            "geo_score": 0.75, "web_score": 0.60, "final_score": 0.705,
            "tier": "High", "assessment": "Strong opportunity.",
            "opportunities": ["Good solar"], "risks": ["Competition"],
        }
    ],
    "report_markdown": "# Laguna Report\nContent here.",
    "report_path": "reports/laguna_test.md",
    "errors": [],
}

def test_create_run_returns_run_id(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        r = app_client.post("/runs", json={"location": "Laguna"})
    assert r.status_code == 201
    assert "run_id" in r.json()

def test_list_runs_returns_created_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]
    r = app_client.get("/runs")
    assert r.status_code == 200
    ids = [run["id"] for run in r.json()]
    assert run_id in ids

def test_get_run_returns_detail(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Nueva Ecija"}).json()["run_id"]
    r = app_client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == run_id
    assert data["location"] == "Nueva Ecija"
    assert "results" in data
    assert "report" in data

def test_get_run_404_for_unknown(app_client):
    r = app_client.get("/runs/doesnotexist")
    assert r.status_code == 404

def test_run_results_persisted(app_client):
    with patch("api.routers.runs._run_pipeline_bg") as mock_bg:
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]
        # Simulate background task completing synchronously
        from api.routers.runs import _persist_run_results
        _persist_run_results(run_id, FAKE_RESULT)
    r = app_client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1
    assert r.json()["report"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_runs.py -v
```

Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Implement api/routers/runs.py**

Create `api/routers/runs.py`:

```python
import asyncio
import json
import secrets
import string
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from api.db import get_db
from api.models import RunCreateIn, RunOut, RunDetailOut

router = APIRouter(tags=["runs"])


def _nanoid(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _persist_run_results(run_id: str, result: dict) -> None:
    with get_db() as conn:
        error   = "; ".join(result.get("errors", [])) or None
        status  = "failed" if error and not result.get("top_targets") else "done"
        conn.execute(
            "UPDATE runs SET status=?, completed_at=?, error=? WHERE id=?",
            (status, datetime.utcnow().isoformat(), error, run_id),
        )
        for t in result.get("top_targets", []):
            muni = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (t.get("municipality", ""), t.get("province", "")),
            ).fetchone()
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, muni["id"] if muni else None,
                 t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                 t.get("tier"), t.get("assessment"),
                 json.dumps(t.get("opportunities", [])),
                 json.dumps(t.get("risks", []))),
            )
        if result.get("report_markdown"):
            loc  = (result.get("location", "unknown")
                    .lower().replace(", ", "_").replace(" ", "-").replace("|", "_"))
            slug = f"{loc}_{run_id[:6]}"
            conn.execute(
                """INSERT OR IGNORE INTO reports
                   (run_id, province, slug, markdown, file_path)
                   VALUES (?,?,?,?,?)""",
                (run_id, result.get("location"), slug,
                 result["report_markdown"], result.get("report_path", "")),
            )


def _run_pipeline_bg(run_id: str, location: str) -> None:
    try:
        with get_db() as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
        from graph.pipeline import run_pipeline
        result = run_pipeline(location)
        _persist_run_results(run_id, result)
    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                "UPDATE runs SET status='failed', error=?, completed_at=? WHERE id=?",
                (str(exc), datetime.utcnow().isoformat(), run_id),
            )


@router.post("/runs", status_code=201)
def create_run(body: RunCreateIn, bg: BackgroundTasks) -> dict:
    run_id   = _nanoid()
    province = body.location.rsplit(",", 1)[-1].strip() if "," in body.location else body.location
    with get_db() as conn:
        conn.execute(
            "INSERT INTO runs (id, location, province, status) VALUES (?,?,?,'pending')",
            (run_id, body.location, province),
        )
    bg.add_task(_run_pipeline_bg, run_id, body.location)
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(limit: int = 20) -> list[RunOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [RunOut(**dict(r)) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> RunDetailOut:
    with get_db() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "Run not found")
        results = conn.execute(
            """SELECT rr.*, m.name AS municipality_name, m.province
               FROM   run_results rr
               LEFT JOIN municipalities m ON rr.municipality_id = m.id
               WHERE  rr.run_id=? ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        report = conn.execute(
            "SELECT slug, markdown, file_path, created_at FROM reports WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return RunDetailOut(
        **dict(run),
        results=[dict(r) for r in results],
        report=dict(report) if report else None,
    )


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    async def _events():
        while True:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT status, error FROM runs WHERE id=?", (run_id,)
                ).fetchone()
            if not row:
                yield 'data: {"error": "run not found"}\n\n'
                return
            if row["status"] in ("done", "failed"):
                payload = json.dumps(
                    {"status": row["status"], "run_id": run_id, "error": row["error"]}
                )
                yield f"data: {payload}\n\n"
                return
            yield f'data: {{"status": "{row["status"]}"}}\n\n'
            await asyncio.sleep(2)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_runs.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/runs.py tests/api/test_runs.py
git commit -m "feat: POST /runs, GET /runs, GET /runs/{id}, GET /runs/{id}/stream"
```

---

## Task 7: Chat Endpoints

**Files:**
- Create: `api/routers/chat.py`
- Create: `tests/api/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_chat.py`:

```python
from unittest.mock import patch

def _make_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        return app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]

def test_chat_returns_reply(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="Test reply"):
        r = app_client.post("/chat", json={"run_id": run_id, "message": "Hello"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Test reply"
    assert r.json()["run_id"] == run_id

def test_chat_global_no_run_id(app_client):
    with patch("api.routers.chat._call_chatbot", return_value="Global reply"):
        r = app_client.post("/chat", json={"message": "Best solar towns?"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Global reply"
    assert r.json()["run_id"] is None

def test_chat_persists_messages(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="Stored reply"):
        app_client.post("/chat", json={"run_id": run_id, "message": "What's the score?"})
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What's the score?"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Stored reply"

def test_chat_no_persist_without_run_id(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="No-persist reply"):
        app_client.post("/chat", json={"message": "Anything"})
    # The run we created should have no messages
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.json() == []

def test_chat_history_empty_for_new_run(app_client):
    run_id = _make_run(app_client)
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_chat.py -v
```

Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Implement api/routers/chat.py**

Create `api/routers/chat.py`:

```python
from fastapi import APIRouter
from api.db import get_db
from api.models import ChatIn, ChatOut, ChatMessageOut

router = APIRouter(tags=["chat"])


def _call_chatbot(message: str, history: list[dict]) -> str:
    """Thin wrapper so tests can patch it without touching the chatbot module."""
    from agents.chatbot import chat as _chat
    reply, _ = _chat(message, history)
    return reply


@router.post("/chat")
def send_message(body: ChatIn) -> ChatOut:
    history: list[dict] = []
    if body.run_id:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
                (body.run_id,),
            ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in rows]

    reply = _call_chatbot(body.message, history)

    if body.run_id:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                (body.run_id, "user", body.message),
            )
            conn.execute(
                "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                (body.run_id, "assistant", reply),
            )

    return ChatOut(reply=reply, run_id=body.run_id)


@router.get("/chat/{run_id}/history")
def get_history(run_id: str) -> list[ChatMessageOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages "
            "WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
    return [ChatMessageOut(**dict(r)) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_chat.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/chat.py tests/api/test_chat.py
git commit -m "feat: POST /chat and GET /chat/{run_id}/history"
```

---

## Task 8: Admin Endpoints

**Files:**
- Create: `api/routers/admin.py`
- Create: `tests/api/test_admin.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_admin.py`:

```python
from unittest.mock import patch

def test_stats_returns_counts(app_client):
    r = app_client.get("/admin/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["municipalities"] == 1622
    assert data["geo_scores"] == 0     # not precomputed yet
    assert data["runs"] == 0
    assert "last_precompute" in data

def test_reindex_kb_accepted(app_client):
    with patch("api.routers.admin._reindex_kb_task"):
        r = app_client.post("/admin/reindex-kb")
    assert r.status_code == 202
    assert r.json()["status"] == "indexing started"

def test_refresh_scores_accepted(app_client):
    r = app_client.post("/admin/refresh-scores")
    assert r.status_code == 202

def test_refresh_scores_stream_returns_sse(app_client):
    with app_client.stream("GET", "/admin/refresh-scores/stream") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_admin.py -v
```

Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Implement api/routers/admin.py**

Create `api/routers/admin.py`:

```python
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from api.db import get_db
from api.models import AdminStatsOut

router = APIRouter(prefix="/admin", tags=["admin"])


def _reindex_kb_task() -> None:
    from agents.chatbot import index_documents_from_kb
    index_documents_from_kb()


@router.get("/stats")
def get_stats() -> AdminStatsOut:
    with get_db() as conn:
        def count(t: str) -> int:
            return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        last = conn.execute("SELECT MAX(computed_at) FROM geo_scores").fetchone()[0]
    return AdminStatsOut(
        municipalities=count("municipalities"),
        geo_scores=count("geo_scores"),
        runs=count("runs"),
        run_results=count("run_results"),
        chat_messages=count("chat_messages"),
        reports=count("reports"),
        web_intel_cache=count("web_intel_cache"),
        last_precompute=last,
    )


@router.post("/reindex-kb", status_code=202)
def reindex_kb(bg: BackgroundTasks) -> dict:
    bg.add_task(_reindex_kb_task)
    return {"status": "indexing started"}


@router.post("/refresh-scores", status_code=202)
def refresh_scores() -> dict:
    # Full implementation in Plan 2 — precompute_geo_scores.py
    return {"status": "accepted", "note": "precompute job implemented in Plan 2"}


@router.get("/refresh-scores/stream")
async def refresh_scores_stream() -> StreamingResponse:
    async def _gen():
        yield 'data: {"status": "not_implemented"}\n\n'
    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_admin.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/admin.py tests/api/test_admin.py
git commit -m "feat: admin endpoints — stats, reindex-kb, refresh-scores stub"
```

---

## Task 9: Full Test Suite + Smoke-Test Server

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

```bash
source .venv_helios/bin/activate
pytest tests/api/ -v --tb=short
```

Expected: All tests PASS. If any fail, fix before proceeding.

- [ ] **Step 2: Start the API server**

```bash
source .venv_helios/bin/activate
uvicorn api.main:app --reload --port 8000
```

Expected: Server starts. Terminal shows:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

- [ ] **Step 3: Verify endpoints in browser / curl**

```bash
curl http://localhost:8000/
curl http://localhost:8000/provinces | python -m json.tool | head -20
curl "http://localhost:8000/municipalities?province=Laguna&limit=5" | python -m json.tool
curl http://localhost:8000/admin/stats | python -m json.tool
```

Expected: Valid JSON responses, 82 provinces, ≥1 Laguna municipality.

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: plan 1 complete — helio.db + full FastAPI backend"
```

---

## Plan 1 Complete

**What's working after this plan:**
- `data/helio.db` with all 7 tables, seeded with 1,622 PH municipalities
- FastAPI server running on port 8000
- All REST + SSE endpoints functional and tested
- Pipeline still runs synchronously in background (1–2 min) — Plan 2 parallelizes it
- Chat uses existing `agents/chatbot.py` without hybrid search — Plan 3 upgrades it
- Score refresh is a stub — Plan 2 implements `precompute_geo_scores.py`

**Next:** Plan 2 — Precompute Script + Agent DB Lookups + Pipeline Parallelization + SSE Step Events
