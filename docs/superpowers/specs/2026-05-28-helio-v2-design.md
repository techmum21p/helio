# Helio v2 — Design Spec
**Date:** 2026-05-28  
**Status:** Approved  
**Branch target:** `feat-helio-v2`

---

## 1. Goal

Replace the Streamlit prototype with a production-grade internal web app for a small team (2–5 people). No auth required. Key outcomes:

- Geo scoring becomes a DB lookup (~10ms) instead of on-the-fly computation (~3s)
- UI never feels frozen — SSE streams live progress during pipeline runs
- All flat files consolidated into a single SQLite database
- Hybrid semantic + keyword search (bm25s + ChromaDB + RRF) for the RAG chatbot
- Responsive, data-dense frontend with scoped and global chat

Migration strategy: **big bang** — pause Streamlit, ship v2 complete.

---

## 2. Architecture

```
Browser (Next.js 14 App Router)
    ↕  REST + Server-Sent Events
FastAPI backend (Python 3.11+)
    ↕  Python function calls
LangGraph agents (unchanged interface)
    ↕  SQL + file writes
SQLite (helio.db)   ChromaDB (kb/index/)   KB files (kb/reports/, kb/intel/)
```

### Key constraints
- Single SQLite file (`data/helio.db`) is the source of truth for all structured data
- ChromaDB stays for vector storage — not replaced
- Agent interfaces (`agent_fn(state) -> state`) are unchanged
- No Redis, no Celery, no external queue — FastAPI async background tasks only

---

## 3. Revised Scoring Model

### Geo score (pre-computed, stored in DB)
```
geo_score = 0.35 × solar_norm + 0.45 × income_norm + 0.20 × pop_density_norm
```

Changes from v1:
- **Income**: 35% → 45% — ability to pay is the #1 conversion factor for solar sales
- **Solar**: 40% → 35% — still the core value prop but variance across PH is lower than income variance
- **Population**: raw count → **density** (people/km²), weight unchanged at 20% — urban density is a better proxy than raw headcount

### Final score (computed at synthesis time)
```
final_score = 0.70 × geo_score + 0.30 × web_score
web_score   = (min(business_count/20, 1.0) + min(avg_price_level/4, 1.0)) / 2
```

Changes from v1: web intel weight raised from 20% → 30% — actual market activity is real signal.

### Normalization
All three geo components normalized PH-wide (across all 1,622 municipalities in `geo_scores` table) using `MinMaxScaler` at precompute time, so rankings are stable and consistent regardless of which subset is displayed.

---

## 4. Pre-Computed Score Database

A one-time (or on-demand) script scores all ~1,622 Philippine municipalities and writes to `geo_scores`. This makes `geo_scoring_agent` a DB lookup instead of a computation.

**Script:** `scripts/precompute_geo_scores.py`  
**Trigger:** Admin panel → "Refresh Scores" button → `POST /admin/refresh-scores`  
**Runtime:** ~5–15 min for full PH run (GEE + geocoding). Runs as a background task; progress streamed via SSE to the admin page.  
**Idempotent:** upserts by `municipality_id` — safe to re-run.

---

## 5. Database Schema

Single file: `data/helio.db` (replaces `data/ph_locations.db`, `sessions/`, `data/processed/*.json`).

### `municipalities`
Master reference. 1,622 rows. Built from `barangay` package + Nominatim geocoding.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | Town/city name |
| province | TEXT | |
| region | TEXT | |
| lat, lon | REAL | Nominatim-geocoded |
| area_km2 | REAL | For density calculation |
| population | INTEGER | PSA estimate |
| income_class | TEXT | 1st–6th class |

### `geo_scores`
Pre-computed component scores. One row per municipality.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| municipality_id | FK → municipalities | |
| solar_irradiance | REAL | kWh/m²/day from GEE |
| solar_norm | REAL | 0–1 |
| income_score | REAL | 0–1 |
| pop_density | REAL | people/km² |
| pop_density_norm | REAL | 0–1 |
| geo_score | REAL | Weighted final (indexed) |
| computed_at | DATETIME | |

### `runs`
One row per analysis job.

| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | nanoid run_id |
| location | TEXT | User input string |
| province | TEXT | |
| status | TEXT | pending/running/done/failed |
| created_at | DATETIME | |
| completed_at | DATETIME | |
| error | TEXT | Nullable |

### `run_results`
Per-municipality scores within a run.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| run_id | FK → runs | |
| municipality_id | FK → municipalities | |
| geo_score | REAL | |
| web_score | REAL | |
| final_score | REAL | Indexed |
| tier | TEXT | High/Medium/Low |
| assessment | TEXT | Synthesis summary |
| opportunities | JSON | Array of strings |
| risks | JSON | Array of strings |

### `web_intel_cache`
Tavily + Places results. 30-day TTL.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| municipality_id | FK → municipalities | |
| business_count | INTEGER | |
| avg_price_level | REAL | |
| places_data | JSON | Raw Places API response |
| tavily_snippets | JSON | Search results |
| fetched_at | DATETIME | Indexed for TTL check |
| expires_at | DATETIME | fetched_at + 30 days |

### `chat_messages`
Full history across all runs.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| run_id | FK → runs | |
| role | TEXT | user / assistant |
| content | TEXT | |
| created_at | DATETIME | |

### `reports`
Generated markdown reports.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| run_id | FK → runs | |
| province | TEXT | |
| municipality | TEXT | Nullable (province-level runs) |
| slug | TEXT UNIQUE | e.g. `laguna_san-pablo_abc123` |
| markdown | TEXT | Full report body |
| file_path | TEXT | `kb/reports/{slug}.md` |
| created_at | DATETIME | |

---

## 6. Pipeline Changes

### geo_scoring_agent (major change)
- **Before:** computes GEE irradiance + normalization on every run (~3s)
- **After:** `SELECT * FROM geo_scores JOIN municipalities WHERE municipality_id IN (...)` (~10ms)
- Falls back to on-the-fly computation only if `geo_scores` table is empty (first run before precompute)

### web_intel_agent (minor change)
- Cache lookup moves from JSON file to `web_intel_cache` table
- TTL check: `WHERE municipality_id = ? AND expires_at > NOW()`

### Pipeline parallelization
`geo_scoring` and `web_intel` can run concurrently since geo_scoring is now just a DB lookup. LangGraph graph updated to run both from START:

```
START → [geo_scoring ‖ web_intel] → synthesis → report_gen → update_kb → END
```

Both complete in parallel, synthesis waits for both. Estimated wall time reduction: ~30–40s.

### SSE progress events
FastAPI emits these events during a run:

```
data: {"step": "geo_scoring",  "status": "done",    "ms": 12}
data: {"step": "web_intel",    "status": "running",  "ms": null}
data: {"step": "web_intel",    "status": "done",    "ms": 18400}
data: {"step": "synthesis",    "status": "running",  "ms": null}
data: {"step": "synthesis",    "status": "done",    "ms": 23100}
data: {"step": "report_gen",   "status": "running",  "ms": null}
data: {"step": "report_gen",   "status": "done",    "ms": 19800}
data: {"step": "complete",     "run_id": "abc123",   "ms": 61300}
```

---

## 7. Hybrid RAG Search

### Libraries
- `bm25s` — sparse keyword index (faster than rank-bm25, uses scipy sparse matrices)
- `chromadb` — dense vector store (unchanged)
- Fusion: Reciprocal Rank Fusion (RRF)

### Architecture
```
query
  ├── embed → ChromaDB cosine similarity → top-20 semantic hits
  └── tokenize → bm25s index → top-20 keyword hits
        ↓
  RRF merge (k=60) → top-5 chunks
        ↓
  MiMo LLM with context
```

### BM25 index lifecycle
- Built in-memory at FastAPI startup from all chunks in ChromaDB
- Rebuilt when `update_kb` agent indexes new documents
- At full PH scale (~6,500 chunks): build time <1s, search time <5ms

### ChromaDB metadata (updated)
Each chunk stored with: `{province, municipality, run_id, chunk_index, source}`

### Scoped vs global search
- **Report page chat:** pre-filters ChromaDB by `municipality` metadata before similarity search, then RRF with BM25 filtered to same docs
- **Global Chat tab:** full KB search, no filter

---

## 8. Frontend

### Stack
- Next.js 14 App Router
- Tailwind CSS
- shadcn/ui components
- `react-leaflet` for the interactive map (replaces Folium — Python-only, doesn't belong in Next.js)
- EventSource API for SSE consumption

### Navigation: Top nav + full width
```
[☀️ Helio]  [Explore]  [Analyze]  [Reports]  [Chat]  [Admin]
```

### Pages

**Explore** — pre-scored leaderboard
- Province/municipality filter (multi-select, matches current Streamlit dropdowns)
- Ranked table: municipality, geo_score components, final_score, tier badge
- Score breakdown bar chart per row
- No pipeline run needed — reads directly from `geo_scores` + `municipalities`

**Analyze** — run the full pipeline
- Province/municipality multi-select picker
- "Analyze" button → `POST /runs`
- SSE progress bar: 5 steps with live timing
- Redirects to Report page on completion

**Reports** — split panel
- Left: rendered markdown report
- Right: scoped chat panel (auto-filtered to this run's municipality)
- Download button for raw markdown
- Run history list (all past runs)

**Chat (global)** — full-page
- Full KB search across all runs
- Session list on the right (switch between run contexts)
- Streaming token output via `StreamingResponse`

**Admin**
- "Refresh Geo Scores" button → `POST /admin/refresh-scores` with SSE progress
- DB stats: row counts per table, ChromaDB chunk count, last precompute timestamp
- "Re-index KB" button → triggers `index_documents_from_kb()`

---

## 9. API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/municipalities` | Filtered list with geo scores |
| GET | `/provinces` | All provinces |
| POST | `/runs` | Start analysis, returns run_id |
| GET | `/runs` | List past runs |
| GET | `/runs/{id}` | Run detail + results |
| GET | `/runs/{id}/stream` | SSE progress stream |
| GET | `/runs/{id}/report` | Report markdown |
| POST | `/chat` | Chat message, streaming response |
| GET | `/chat/{run_id}/history` | Chat history for a run |
| POST | `/admin/refresh-scores` | Trigger precompute job |
| GET | `/admin/refresh-scores/stream` | SSE for precompute progress |
| POST | `/admin/reindex-kb` | Re-index ChromaDB |
| GET | `/admin/stats` | DB + ChromaDB stats |

---

## 10. File Structure Changes

```
helio/
├── api/                        # NEW — FastAPI app
│   ├── main.py                 # App factory, router registration
│   ├── routers/
│   │   ├── runs.py
│   │   ├── municipalities.py
│   │   ├── chat.py
│   │   └── admin.py
│   └── db.py                   # SQLite connection + migrations
├── frontend/                   # NEW — Next.js app
│   ├── app/
│   │   ├── explore/page.tsx
│   │   ├── analyze/page.tsx
│   │   ├── reports/[runId]/page.tsx
│   │   ├── chat/page.tsx
│   │   └── admin/page.tsx
│   └── components/
│       ├── ScoreTable.tsx
│       ├── RunProgress.tsx      # SSE consumer
│       ├── ChatPanel.tsx        # Scoped + global
│       └── ScoreBreakdown.tsx
├── scripts/
│   ├── precompute_geo_scores.py # NEW — scores all 1,622 municipalities
│   └── build_location_db.py    # REPLACED by precompute (municipalities table)
├── agents/                     # Unchanged interface
│   ├── geo_scoring.py          # DB lookup instead of compute
│   ├── web_intel.py            # Cache → SQLite
│   └── chatbot.py              # bm25s hybrid search added
├── data/
│   └── helio.db                # NEW consolidated SQLite
└── app.py                      # RETIRED after migration
```

---

## 11. What Gets Retired

| File/dir | Replaced by |
|---|---|
| `app.py` (Streamlit) | Next.js frontend |
| `sessions/*.json` | `runs` + `chat_messages` + `reports` tables |
| `data/processed/web_intel_cache.json` | `web_intel_cache` table |
| `data/processed/municipality_coords.json` | `municipalities.lat/lon` |
| `data/ph_locations.db` | `municipalities` table in `helio.db` |
| `agents/session_store.py` | `api/db.py` |
| `agents/location_db.py` | `api/routers/municipalities.py` |
| `scripts/build_location_db.py` | `scripts/precompute_geo_scores.py` |
