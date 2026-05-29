> Last updated: 2026-05-29 | Session 7

# Helio — Solar Lead Intelligence Platform Session Notes

---

## Session 7 — Next.js App Bug Fixes: Map Coords, Expandable Cards, Reports, Nav Consolidation (2026-05-29)

### Branch
`feat-helio-v2` (continuing from session 6)

### What Was Fixed
User reported 7 issues with the new Next.js app compared to the Streamlit version. Brainstormed, wrote spec + plan, executed via 6-task subagent-driven development with spec/quality reviews per task.

### Bug 1 — Towns not showing on map (CRITICAL)
- **Root cause**: All 1,622 municipalities had `lat=NULL, lon=NULL` in `data/helio.db`. The municipalities table is seeded from `ph_locations.db` which never had coords. The pipeline computed coords in `geo_scoring.py` via `_municipality_coord(name, province)` and stored them in `geo_geojson` — but `_persist_run_results` in `api/routers/runs.py` never saved them to the DB.
- **Fix 1**: Modified `_persist_run_results` to parse `result["geo_geojson"]` after saving run results, and `UPDATE municipalities SET lat=?, lon=? WHERE name=? AND province=? AND lat IS NULL`. Wrapped in `try/except` with `logger.warning` (best-effort, never fails a run). Also hardened geometry parsing: `geom = feature.get("geometry") or {}`, `coords = geom.get("coordinates", [])` with `len < 2` guard.
- **Fix 2**: Created `scripts/backfill_coords.py` — one-time migration that imports `_municipality_coord` from `agents/geo_scoring` and backfills all `lat IS NULL` rows. Run once: `python scripts/backfill_coords.py` → `Backfilled 1622 municipalities.`

### Bug 2 — Can't open town analysis in sidebar
- **Root cause**: Right-sidebar town cards in `app/map/[runId]/page.tsx` showed a clipped assessment snippet but clicking did nothing.
- **Fix**: Added `useState<number | null>(null)` for `expandedId`. Cards are now click-to-expand (amber-50 bg, amber-300 border when open). Expanded section shows: **Assessment** (full text), **Opportunity** (emerald-600 label, `r.opportunities[0]`), **Risk** (red-500 label, `r.risks[0]`). Sidebar width increased 240px → 260px. Header label updated to "Top Targets — click to expand".

### Bug 3 — Reports page empty
- **Root cause**: `app/reports/page.tsx` was hardcoded to show "No reports yet." with no API call at all.
- **Fix**: Replaced with `useSWR("runs", getRuns(50))`, filters `status === "done"` and `!location.startsWith("admin:")`, renders clickable `<Link href="/reports/${run.id}">` cards with location name, formatted date, "✓ Done" badge. SWR key unified to `"runs"` (was mistakenly `"runs-reports"` initially, fixed in cleanup commit).

### Bug 4 — Nav had 5 pages (Explore + Admin cluttered)
- **Fix**: `NAV_LINKS` in `components/sidebar.tsx` reduced to 3: Map & Scores (`/map`), Reports (`/reports`), Chat (`/chat`). Explore and Admin still exist at their URLs but are hidden from nav.

### Bug 5 — Map zoom too close
- **Fix**: `components/run-map-view.tsx` changed `zoom={10}` → `zoom={7}`. Map center now computed from run results average lat/lon (passed as `center` prop from `app/map/[runId]/page.tsx`).

### Bug 6 — Chat defaulted to Global KB
- **Fix**: `app/chat/page.tsx` now uses `useEffect` with `initialized` flag to auto-select the most recent completed run on first mount. Admin runs (`location.startsWith("admin:")`) filtered from context switcher list. Placeholder text shows selected run's location.

### Type Fixes (cleanup commit)
- `frontend/lib/types.ts`: `RunResult.municipality_id: number | null` (was non-nullable but DB column is nullable); `RunResult.assessment: string | null`
- `app/map/[runId]/page.tsx`: card `key` → `r.municipality_id ?? r.municipality_name`; expand comparator guards null municipality_id

### Commits (8 total on feat-helio-v2 this session)
- `2eda1d2` fix: backfill municipalities lat/lon — map markers were all NULL
- `c271a52` fix: harden geo_geojson coord backfill against null geometry and bad coordinates
- `38c9fd2` feat: collapse nav to 3 pages (Map, Reports, Chat)
- `fac0037` fix: reports index now lists past runs instead of hardcoded empty state
- `3ee0f14` feat: expandable town cards on Map & Scores page
- `3365f38` fix: map zoom 7 + center on run results
- `6f55c42` fix: chat defaults to most recent run context, hides admin runs
- `f45d2ae` fix: nullable RunResult fields, card key fallback, unify SWR key

### Spec + Plan Written
- `docs/superpowers/specs/2026-05-29-helio-frontend-fixes-design.md`
- `docs/superpowers/plans/2026-05-29-helio-frontend-fixes.md`

### Start the App
```bash
# Terminal 1
source .venv_helios/bin/activate && uvicorn api.main:app --reload

# Terminal 2
cd frontend && npm run dev
# Open http://localhost:3000
```

#### Files changed (session 7)
- `api/routers/runs.py` — `_persist_run_results` now saves lat/lon from geo_geojson; hardened coord parsing
- `scripts/backfill_coords.py` — **new**: one-time migration to populate lat/lon for all 1,622 municipalities
- `frontend/components/sidebar.tsx` — NAV_LINKS reduced to 3 (removed Explore, Admin)
- `frontend/app/reports/page.tsx` — replaced hardcoded empty state with live run list (useSWR)
- `frontend/app/map/[runId]/page.tsx` — expandable town cards (assessment/opportunity/risk), map center computed from results
- `frontend/components/run-map-view.tsx` — zoom 10→7
- `frontend/app/chat/page.tsx` — auto-select most recent run context on mount; admin run filter
- `frontend/lib/types.ts` — `municipality_id: number | null`, `assessment: string | null` in RunResult
- `docs/superpowers/specs/2026-05-29-helio-frontend-fixes-design.md` — **new**
- `docs/superpowers/plans/2026-05-29-helio-frontend-fixes.md` — **new**

### ⚠️ Still pending
- `feat-helio-v2` not yet merged to `main`
- Plan 2 still pending: `scripts/precompute_geo_scores.py` (scores all 1,622 municipalities)
- `/admin/refresh-scores` and `/admin/refresh-scores/stream` are stubs until Plan 2
- Hybrid RAG (bm25s + ChromaDB + RRF) not yet implemented

---

## Session 6 — Frontend UI Redesign: Warm Stone Sidebar App (2026-05-29)

### Branch
`feat-helio-v2` (continuing from session 5)

### What Was Built
Full UI redesign of the Next.js frontend — replaced the dark top-nav (`slate-950`) with a warm stone collapsible sidebar. Design was brainstormed interactively with a visual companion (browser mockups). Implemented via 14 subagent tasks with spec + quality review per task.

### Design Decisions
- **Palette**: Warm Stone — cream base `#faf9f6`, stone text `#1c1917`, amber accent `#d97706`. Replaces the dark `slate-950` / `amber-400` dark theme.
- **Layout**: Persistent collapsible sidebar (228px expanded → 56px icon-only). State persisted to `localStorage` key `helio-sidebar-collapsed`.
- **Pipeline controls in sidebar**: Province dropdown → municipality multiselect → Analyze button always visible (like Streamlit). Moved from the dedicated `/analyze` page which was deleted.
- **Map style**: Switched to CartoDB Positron (light) tile layer. Kept Streamlit-matching color/radius: green `#2ecc71` ≥0.65, orange `#f39c12` ≥0.35, red `#e74c3c` <0.35; radius = `6 + score × 14`.
- **Map & Scores page**: New `/map/[runId]` landing after a run completes. Shows stat cards + `RunMapView` (pipeline results) + top-15 targets list. Previous flow redirected to `/reports`; now redirects to `/map`.
- **Prose**: Added `@tailwindcss/typography` with warm stone CSS variable overrides. Reports use `prose max-w-none` (no `prose-invert`).

### New Components
- `components/app-shell.tsx` — client component managing `collapsed` state with localStorage persistence
- `components/sidebar.tsx` — nav links (5 items), collapse toggle, last-run badge (amber-50), pipeline card at bottom
- `components/sidebar-pipeline-card.tsx` — province `<select>` (SWR), municipality checklist (scrollable, checkboxes, shows geo_score), selected count badge, ▶ Analyze → `createRun` → `/analyze/${run_id}`
- `components/run-map-view.tsx` — react-leaflet map for `RunResult[]`, Positron tile, uses `final_score` for color/radius
- `lib/score-color.ts` — `scoreColor(score)` + `scoreRadius(score)` shared utilities (Streamlit-matching)

### Modified Components
- `components/map-view.tsx` — switched to Positron tile, uses `scoreColor`/`scoreRadius` from shared utility, added `<Popup>`
- `components/run-progress.tsx` — stone-300/amber-600/stone-700 warm stone palette
- `components/tier-badge.tsx` — amber/emerald/blue/stone solid badges (replaced opacity shims)
- `components/stat-card.tsx` — `bg-white border-stone-200 shadow-sm`
- `components/score-bar.tsx` — amber gradient, stone-100 track (preserved 3-bar API for municipality-table)
- `components/run-list.tsx` — amber-50 active, stone dividers
- `components/municipality-table.tsx` — hover:bg-amber-50, stone borders
- `components/chat-panel.tsx` — user bubble `bg-amber-600 text-white`; assistant `bg-stone-100`; `prose prose-sm` (no invert)

### New Pages
- `app/map/page.tsx` — server component, redirects to `/map/${latestRunId}` or shows empty state
- `app/map/[runId]/page.tsx` — client component: 4 stat cards (Top Score/Tier/Count/Avg), RunMapView (ssr:false), top-15 targets list (local TierBadge for HIGH/MEDIUM/LOW strings)

### Modified Pages
- `app/layout.tsx` — removed `className="dark"` from `<html>`, replaced `<Nav>` with `<AppShell>`
- `app/globals.css` — warm stone HSL CSS variables replacing dark slate tokens
- `app/analyze/[runId]/page.tsx` — on complete now redirects to `/map/${id}` (was `/reports/${id}`), 1200ms delay (was 1500ms)
- `app/explore/page.tsx` — `h-full` (was `h-[calc(100vh-56px)]`), warm stone inputs/filter bar
- `app/reports/page.tsx` — static empty state linking to `/map` (removed server-side getRuns redirect)
- `app/reports/[runId]/page.tsx` — `h-full`, warm prose, stone download button
- `app/chat/page.tsx` — `h-full`, amber active context item, stone aside
- `app/admin/page.tsx` — amber-600 primary buttons, white/stone card containers

### Deleted Files
- `components/nav.tsx` — replaced by sidebar
- `app/analyze/page.tsx` — province/muni selector moved into `SidebarPipelineCard`

### API Fix
- `api/routers/runs.py` — run results query now selects `m.lat, m.lon` from municipalities JOIN (was missing; required for `RunMapView` to position markers)
- `frontend/lib/types.ts` — `RunResult` now has `lat: number | null`, `lon: number | null`

### Dependency Added
- `@tailwindcss/typography ^0.5.19` — registered in `tailwind.config.ts` with warm stone prose variable overrides

### Specs + Plans Written
- `docs/superpowers/specs/2026-05-29-frontend-redesign.md` — full redesign spec (brainstorm output)
- `docs/superpowers/plans/2026-05-29-frontend-redesign.md` — 14-task implementation plan

### Start the App
```bash
# Terminal 1
source .venv_helios/bin/activate && uvicorn api.main:app --reload

# Terminal 2
cd frontend && npm run dev
# Open http://localhost:3000
```

#### Files changed (session 6)
- `api/routers/runs.py` — added `m.lat, m.lon` to run results query
- `frontend/lib/types.ts` — `RunResult` gains `lat`/`lon` fields
- `frontend/tailwind.config.ts` — `@tailwindcss/typography` plugin + warm stone prose config
- `frontend/app/globals.css` — full warm stone token replacement
- `frontend/app/layout.tsx` — AppShell replaces Nav, removed dark class
- `frontend/app/map/page.tsx` — **new**: redirect to latest run or empty state
- `frontend/app/map/[runId]/page.tsx` — **new**: Map & Scores page
- `frontend/app/analyze/[runId]/page.tsx` — redirect to /map, warm stone restyle
- `frontend/app/explore/page.tsx` — warm stone restyle, h-full
- `frontend/app/reports/page.tsx` — static empty state
- `frontend/app/reports/[runId]/page.tsx` — warm stone, prose fix, h-full
- `frontend/app/chat/page.tsx` — warm stone restyle, h-full
- `frontend/app/admin/page.tsx` — warm stone restyle
- `frontend/components/app-shell.tsx` — **new**
- `frontend/components/sidebar.tsx` — **new**
- `frontend/components/sidebar-pipeline-card.tsx` — **new**
- `frontend/components/run-map-view.tsx` — **new**
- `frontend/lib/score-color.ts` — **new**
- `frontend/components/map-view.tsx` — Positron tile + shared score-color
- `frontend/components/run-progress.tsx` — warm stone
- `frontend/components/tier-badge.tsx` — warm stone
- `frontend/components/stat-card.tsx` — warm stone
- `frontend/components/score-bar.tsx` — warm stone amber gradient
- `frontend/components/run-list.tsx` — warm stone
- `frontend/components/municipality-table.tsx` — warm stone
- `frontend/components/chat-panel.tsx` — warm stone
- `frontend/components/nav.tsx` — **deleted**
- `frontend/app/analyze/page.tsx` — **deleted**
- `docs/superpowers/specs/2026-05-29-frontend-redesign.md` — **new**
- `docs/superpowers/plans/2026-05-29-frontend-redesign.md` — **new**

---

## Session 5 — Helio v2: Next.js Frontend + Backend SSE/Streaming (2026-05-29)

### Branch
`feat-helio-v2` (off `main`, building on Plan 1 FastAPI backend from prior session)

### What Was Built
Full Next.js 14 App Router frontend (15 tasks) plus two FastAPI backend enhancements. All code reviewed via subagent-driven development (spec compliance + code quality review per task). 66/66 Python tests passing. `npm run build` clean.

### Backend Enhancements

#### In-Memory SSE Event Store (`api/events.py`)
- Thread-safe `dict[str, list[dict]]` with `threading.Lock`
- `push_event(run_id, step, status, elapsed_ms)`, `get_events(run_id)`, `clear_events(run_id)`
- `get_events` returns `[dict(e) for e in ...]` (deep copy — callers can't mutate stored events)
- Tests: `tests/api/test_events.py` (4 tests, autouse isolation fixture)

#### Pipeline SSE Step Events (`graph/pipeline.py`)
- `run_pipeline(location, run_id=None)` — added `run_id` param (optional, backward-compatible)
- Switched from `pipeline.invoke()` → `pipeline.stream(initial_state, stream_mode="updates")`
- Emits `push_event(run_id, step, "running", 0)` before stream starts
- Per step: emits "done" for completed node + "running" for next node
- `_STEPS = ["geo_scoring", "web_intel", "synthesis", "report_gen", "update_kb"]`
- Lazy import: `from api.events import push_event` inside `run_pipeline()` (avoids circular import)

#### Updated SSE Stream Endpoint (`api/routers/runs.py`)
- `_run_pipeline_bg` now passes `run_id=run_id` to `run_pipeline()`
- `/runs/{id}/stream`: event-flushing loop (0.5s sleep, was 2s) — yields step events as they arrive
- Terminal event: `{"step": "complete"|"failed", "run_id": ..., "error": ...}` then calls `clear_events`

#### Streaming Chat (`agents/chatbot.py` + `api/routers/chat.py`)
- Added `chat_stream(user_message, chat_history)` generator to chatbot — uses `client.messages.stream()`, yields from `stream.text_stream`. Original `chat()` untouched.
- `POST /chat` replaced with `StreamingResponse` SSE: yields `data: {chunk}\n\n` per token, `data: [DONE]\n\n` at end
- Persistence (user + assistant to `chat_messages`) happens after stream exhausted, only if `run_id` set
- Testable via `_stream_chatbot` wrapper (patchable without touching chatbot module)
- `tests/api/test_chat.py` fully replaced — 5 tests using `app_client.stream()` + `_read_sse()` helper

#### Bug Fix: `api/routers/runs.py`
- `get_run` now parses `opportunities` and `risks` from JSON strings back to Python lists before returning
- These were stored via `json.dumps(...)` in SQLite — frontend was receiving string instead of array

### Frontend (`frontend/`)

#### Scaffold
- Next.js 14.2.35, App Router, TypeScript, Tailwind v3, ESLint
- shadcn/ui v0.x (Radix UI based — shadcn@latest v4 would have broken Tailwind v3)
- `react-leaflet@4` (v5 requires React 19; pinned for React 18 compat)
- `swr`, `react-markdown`, `remark-gfm`, `leaflet`, `@types/leaflet`
- `frontend/.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8000`
- CORS already configured in `api/main.py` for `localhost:3000`

#### Shared Types + API Client
- `frontend/lib/types.ts` — all TS interfaces mirroring Pydantic models: Province, Municipality, Run, RunDetail, RunResult, Report, ChatMessage, AdminStats, StepEvent, Tier; `getTier(score)` function (A≥0.8, B≥0.65, C≥0.5, D<0.5)
- `frontend/lib/api.ts` — typed fetch wrappers for all 11 endpoints; `openRunStream(runId)` + `openRefreshStream()` EventSource factories; `streamChat(message, runId)` async generator (parses `data: <token>` SSE lines, stops on `[DONE]`)

#### Components (all in `frontend/components/`)
- `nav.tsx` — `"use client"`, `usePathname()` active detection, amber ☀ HELIO logo, 5 links
- `score-bar.tsx` — 3 horizontal bars: solar (blue-400), income (emerald-400), pop (violet-400); `showLabels` prop
- `tier-badge.tsx` — colored pill for A/B/C/D; amber/emerald/blue/slate; null → "—"
- `municipality-table.tsx` — sortable by 5 columns, 50/page pagination, expand-on-click with ScoreBar
- `map-view.tsx` — react-leaflet dark tiles (CARTO), CircleMarker per municipality, score-colored dots, click → `onSelect(id)`; leaflet CSS + icon fix in useEffect; dynamic import required (`ssr: false`)
- `run-progress.tsx` — SSE step tracker: waiting/running/done/failed states with spinner/checkmark/X icons, elapsed time display
- `chat-panel.tsx` — streaming chat via `streamChat` async generator, `bufferRef` accumulation, ReactMarkdown responses (wrapped in `<div className="prose...">` due to react-markdown v10 removing className prop), cursor ▌ while streaming
- `run-list.tsx` — sidebar list with STATUS_STYLES badge colors, exact pathname active detection, `basePath` prop (default `/reports`)
- `stat-card.tsx` — label/value/sub card, null→"—", number→`toLocaleString()`

#### Pages (all in `frontend/app/`)
- `page.tsx` — `redirect("/explore")`
- `explore/page.tsx` — province filter, text search, min-score slider, Show/Hide Map toggle (`h-64` MapView via dynamic import), MunicipalityTable; shared `selectedId` state links map clicks to row expand
- `analyze/page.tsx` — province → municipality cascading SWR selects, multi-select checkboxes, builds `"Muni, Province"` or `"M1|M2, Province"` location strings, POSTs `/runs`
- `analyze/[runId]/page.tsx` — RunProgress with SSE, auto-redirects to `/reports/{id}` after 1.5s on complete
- `reports/page.tsx` — Server Component, redirects to latest run or shows empty state
- `reports/[runId]/page.tsx` — CSS Grid `180px 1fr`; RunList sidebar / scrollable markdown / `h-72` ChatPanel pinned bottom; download .md button (blob URL)
- `chat/page.tsx` — CSS Grid `1fr 220px`; ChatPanel + context switcher sidebar (Global KB + per-run buttons)
- `admin/page.tsx` — 8 StatCards (30s SWR refresh), Refresh Geo Scores (RunProgress with synthetic runId), Re-index KB (spinner + message)

#### `.gitignore` fix
- Changed `reports/` → `/reports/` to prevent matching `frontend/app/reports/`

### Design Decisions (session 5)
- **Dark Intelligence** aesthetic: `slate-950` background, amber-400 accents throughout
- **Explore layout**: full-width table, map toggle (not split panel)
- **Map click**: scroll-to + expand row in table (not popup, not detail strip)
- **Analyze progress**: vertical step tracker (CI-style), not horizontal bar or log view
- **Reports layout**: three-panel (180px run list / center report / bottom-pinned chat)
- **react-markdown v10**: className prop removed — wrap in `<div className="prose...">` instead
- **`opportunities`/`risks` in SQLite**: stored as `json.dumps(list)` → must deserialize in `get_run()` before returning to frontend

### Specs + Plans Written
- `docs/superpowers/specs/2026-05-29-helio-v2-design.md` — visual design spec (brainstorm output)
- `docs/superpowers/specs/2026-05-29-nextjs-frontend-design.md` — full frontend + backend spec
- `docs/superpowers/plans/2026-05-29-nextjs-frontend.md` — 15-task implementation plan

### Start the App
```bash
# Terminal 1
source .venv_helios/bin/activate && uvicorn api.main:app --reload

# Terminal 2
cd frontend && npm run dev
```

#### Files changed (session 5)
- `api/events.py` — **new**: in-memory SSE event store
- `api/routers/runs.py` — SSE stream rewrite + `get_run` JSON parse fix + `_run_pipeline_bg` passes run_id
- `api/routers/chat.py` — streaming SSE response
- `agents/chatbot.py` — added `chat_stream()` generator
- `graph/pipeline.py` — `run_id` param, `stream()` mode, step event emission
- `tests/api/test_events.py` — **new**: 4 tests
- `tests/api/test_chat.py` — replaced: 5 streaming tests
- `tests/api/test_runs.py` — added stream step event test
- `frontend/` — **new**: entire Next.js app (scaffold + 2 lib files + 9 components + 8 pages)
- `docs/superpowers/specs/2026-05-29-helio-v2-design.md` — **new**
- `docs/superpowers/specs/2026-05-29-nextjs-frontend-design.md` — **new**
- `docs/superpowers/plans/2026-05-29-nextjs-frontend.md` — **new**
- `.gitignore` — anchored `/reports/` (was `reports/`)

### ⚠️ Remaining (next session)
- `feat-helio-v2` not yet merged to `main`
- Plan 2 still pending: `scripts/precompute_geo_scores.py` (scores all 1,622 municipalities into `helio.db`)
- `/admin/refresh-scores` and `/admin/refresh-scores/stream` are stubs until Plan 2
- Hybrid RAG (bm25s + ChromaDB + RRF) not yet implemented
- Pipeline parallelization (geo_scoring ‖ web_intel) not yet implemented

---

## Session 4 — Town-Level Location Selection + SQLite Location DB (2026-05-28)

### Branch
`feat-town-level` (off `main`)

### Architecture Decisions Made
- **SQLite as future foundation**: Agreed to consolidate all app persistence into SQLite across multiple branches: `feat-town-level` (location DB), `feat-sqlite-consolidation` (sessions/chat/reports), then FastAPI/Next.js migration
- **Barangay dropdown omitted** from UI for now — stored in DB for future use; pipeline only analyzes at province or municipality level
- **Build script approach**: Location DB populated via one-time manual script (`python scripts/build_location_db.py`), not auto-populated on app start
- **Model name fix**: `config.py` had regressed to `mimo-v2.5` — corrected back to `mimo-v2.5` for both `REPORT_MODEL` and `CHATBOT_MODEL`

### New File: `scripts/build_location_db.py`
- One-time script: `python scripts/build_location_db.py`
- Reads `barangay.BARANGAY` → populates `data/ph_locations.db`
- 4 tables: `regions` (18), `provinces` (85), `municipalities` (1622), `barangays` (39883)
- Indices: `idx_provinces_region`, `idx_municipalities_prov`, `idx_barangays_muni`
- Idempotent — skips if municipalities table has rows; delete file to rebuild
- Has FK pragma, import error handling, `executemany` for barangays

### New File: `agents/location_db.py`
- Query helpers backed by `data/ph_locations.db`
- `get_provinces() -> list[{id, name}]` — sorted by name, cached via `@st.cache_data(ttl=3600)` in app.py
- `get_municipalities(province_id) -> list[{id, name}]` — cached
- `get_barangays(municipality_id) -> list[{id, name}]` — for future use
- `get_province_name(province_id) -> str` / `get_municipality_name(municipality_id) -> str`
- All functions return `[]`/`""` gracefully if DB missing; log warnings via loguru

### `agents/geo_scoring.py` Changes
- Added `PH_SOLAR_RANGE = (4.5, 6.0)`, `PH_POP_RANGE = (5_000, 150_000)`, `PH_INCOME_RANGE = (1, 6)`
- Added `_normalize_fixed(value, lo, hi) -> float` — clamps to [0,1] for single-row scoring
- Added `load_single_municipality(town, province) -> list[dict]` — fuzzy-matches province then municipality in `barangay.BARANGAY` via rapidfuzz (score_cutoff=60); returns `[_build_unit(...)]` or `[]`
- `compute_geo_scores`: when `len(df) == 1`, uses `_normalize_fixed` with PH ranges instead of MinMaxScaler (prevents all-zeros on single-row)
- `geo_scoring_agent` routing: `if location.count(",") == 1` → single-municipality mode (rsplit on last comma); otherwise province mode. Guards against multi-comma inputs like `"Town, Province, Philippines"`

### `app.py` Changes
- Added `from agents.location_db import get_provinces, get_municipalities`
- Added `@st.cache_data(ttl=3600)` wrapped helpers `_cached_provinces()` and `_cached_municipalities(province_id)` — prevents SQLite hit on every Streamlit re-render
- Replaced `st.text_input("Province / Region", ...)` with cascading selectboxes:
  - Province: `["— Select province —"] + province names` (dict keyed as `prov_by_name`)
  - Municipality: `["— All municipalities —"] + muni names` (only shown when province selected)
  - Shows `st.warning("⚠️ Location DB not built. Run: python scripts/build_location_db.py")` if DB missing
- `location_str` built as: `None` / `"Laguna"` / `"City of Biñan, Laguna"` passed to `run_pipeline`

### New Tests
- `tests/test_location_db.py` — 15 tests for all location_db helpers (with `test_db` fixture using monkeypatched `config.LOCATION_DB`)
- `tests/test_geo_scoring_single.py` — 9 tests for `load_single_municipality`, `_normalize_fixed`, single/multi-row `compute_geo_scores`
- Total test suite: 34 tests, all passing

### `config.py` Changes
- Added `LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"` after `SESSIONS_DIR`
- Fixed `REPORT_MODEL` and `CHATBOT_MODEL` defaults back to `"mimo-v2.5"` (had regressed to `"mimo-v2.5"`)

#### Files changed (session 4)
- `scripts/build_location_db.py` — **new**: one-time DB build script
- `agents/location_db.py` — **new**: SQLite query helpers for location data
- `agents/geo_scoring.py` — added single-municipality support, fixed-range normalizer, comma routing
- `app.py` — cascading Province/Municipality dropdowns, cached DB queries
- `config.py` — added `LOCATION_DB`, restored `mimo-v2.5` model defaults
- `tests/test_location_db.py` — **new**: 15 tests
- `tests/test_geo_scoring_single.py` — **new**: 9 tests

### ⚠️ Action required next session
- Run `python scripts/build_location_db.py` once if not already done (creates `data/ph_locations.db`)
- Branch `feat-town-level` not yet merged to `main` — needs PR/merge

### Next planned branches
- `feat-sqlite-consolidation` — move sessions/chat/reports/caches to SQLite
- `feat-nextjs-migration` — FastAPI backend + Next.js frontend (after consolidation)

---

## Session 3 — Session Persistence: Save & Load Pipeline Results + Chat History (2026-05-28)

### New Feature: Session Persistence

Every pipeline run and every chat message is now auto-saved to disk. Users can reload any past session (including the interactive map) from the sidebar without re-running the pipeline.

### New File: `agents/session_store.py`
- `_slug(location)` — lowercases, strips, removes commas, replaces spaces with `_`
- `save_session(pipeline_result, chat_history)` — writes `sessions/{slug}_{run_id}.json` with keys `pipeline_result`, `chat_history`, `saved_at`; overwrites on each call (idempotent snapshot)
- `load_session(filepath)` — returns `(pipeline_result, chat_history)` using `.get()` defaults for robustness
- `list_sessions()` — globs `sessions/*.json`, sorted by mtime newest-first; each entry: `{path, label, location, run_id, saved_at}`; label format: `"Laguna — May 28 2026 [abc123]"` (run_id suffix prevents same-day collision)

### New File: `tests/test_session_store.py`
- 10 unit tests covering: file creation, slug, comma stripping, round-trip, overwrite, empty list, metadata shape, label format + run_id disambiguator, same-day uniqueness, sort order
- All pass via `pytest tests/test_session_store.py -v`

### `config.py` changes
- Added `SESSIONS_DIR = ROOT_DIR / "sessions"` after `REPORTS_DIR`
- Added `SESSIONS_DIR` to the `for d in [...]` auto-create loop
- Also committed pre-existing uncommitted changes: `XIAOMI_API_KEY`, `XIAOMI_BASE_URL` (`token-plan-sgp`), `WEB_INTEL_CACHE_TTL_DAYS`

### `app.py` changes
- Import: `from agents.session_store import save_session, load_session, list_sessions`
- Auto-save after `▶ Analyze` completes: `save_session(result, [])` (line ~49)
- Auto-save after each chat message: `save_session(pipeline_result, updated_history)` guarded by `if st.session_state.pipeline_result` (line ~209)
- Sidebar **📂 Load Past Session** expander (after the existing pipeline summary block):
  - `st.selectbox` with `label_visibility="collapsed"` listing all sessions
  - "Load" button: calls `load_session`, sets both `pipeline_result` + `chat_history` in session_state, shows `st.toast(f"Loaded: {label}", icon="📂")`, then `st.rerun()`
  - Try/except around `load_session` — shows `st.error(f"Could not load session: {exc}")` on failure

### Design docs written
- `docs/superpowers/specs/2026-05-28-session-persistence-design.md`
- `docs/superpowers/plans/2026-05-28-session-persistence.md`

#### Files changed (session 3)
- `agents/session_store.py` — **new file**: save/load/list session JSON
- `tests/test_session_store.py` — **new file**: 10 unit tests for session_store
- `tests/__init__.py` — **new file**: makes tests/ a package
- `config.py` — added `SESSIONS_DIR`, pre-existing key/URL changes committed
- `app.py` — session persistence wiring + Load Past Session sidebar UI
- `docs/superpowers/specs/2026-05-28-session-persistence-design.md` — **new**
- `docs/superpowers/plans/2026-05-28-session-persistence.md` — **new**

### ⚠️ Still pending
- `config.py` has `XIAOMI_BASE_URL = "token-plan-sgp.xiaomimimo.com"` but CLAUDE.md documents `ams` endpoint — verify which region is correct
- GEE NASA/POWER solar fallback still active (carried from session 2)

---

## Session 2 — Web Intel Upgrade, Geocoding, KB Enhancement (2026-05-28)

### Nominatim Geocoding — Real Map Coordinates
- **New file:** `agents/geocoder.py`
- Replaced hash-offset coordinates (province centroid ± random offset) with Nominatim/OSM geocoding
- Persistent disk cache: `data/processed/municipality_coords.json` — first run geocodes, subsequent runs instant
- Rate-limited to 1.1s between requests (Nominatim ToS)
- `geocode_units(units)` only queries uncached municipalities; logs "Geocoding N municipalities via Nominatim (cached: M)"
- `get_coords(name, province, fallback)` checks cache → Nominatim → stores result
- Called at end of `geo_scoring_agent()` after building municipality list

### Tavily Rate Limiting Fix
- **File:** `agents/web_intel.py`
- Added `_TAVILY_DELAY = 0.4` — `time.sleep(_TAVILY_DELAY)` before every `tavily.search()` call
- Prevents bursts of 80–120 rapid requests that caused 429 errors on dev key

### Google Places — Richer Signals + Location Bias
- **File:** `agents/web_intel.py`
- Added `locationBias` circle (8km radius) using real municipality coordinates from Agent 1
- Second Places query: "shopping mall factory industrial warehouse..." → `commercial_anchors` count
- New signals returned: `avg_rating` (1-5 scale), `total_reviews` (sum of userRatingCount), `commercial_anchors`
- `_PLACES_FIELDS` expanded: added `places.rating`, `places.userRatingCount`, `places.types`

### Web Intel Persistent Cache
- **File:** `agents/web_intel.py`
- Cache file: `data/processed/web_intel_cache.json`, TTL: 30 days (configurable via `WEB_INTEL_CACHE_TTL_DAYS`)
- Cache key: `{province}::{municipality}`
- Functions: `get_cached_intel()`, `set_cached_intel()`, `_load_cache()`, `_save_cache()`, `_is_fresh()`
- Cache hit = 0ms fetch (vs 7–10s live fetch). Survives app restarts.

### Scoring Formula Updated
- **File:** `agents/synthesis.py` — `compute_final_score()`
- Old: `web_score = (biz_density × 0.5 + price_signal × 0.5)`
- New: `web_score = 0.35×biz_density + 0.25×price_signal + 0.25×rating_signal + 0.15×anchor_signal`
- `rating_signal = max((avg_rating - 1.0) / 4.0, 0)` — normalizes 1–5 → 0–1
- `anchor_signal = min(commercial_anchors / 5, 1.0)` — caps at 5 anchor venues
- Final: `0.80×geo_score + 0.20×web_score` (unchanged ratio)

### KB Builder — Per-Municipality Intel Docs
- **New file:** `agents/kb_builder.py`
- Generates one rich markdown file per municipality to `kb/intel/`
- Filename: `{province_slug}__{muni_slug}__{run_id}.md`
- Each doc contains: scores table (final/geo/tier/solar_kwh), commercial activity (Places signals), AI assessment/opportunity/risk, web intel snippets, **full barangay list**
- `_get_barangays(municipality, province)` traverses `barangay.BARANGAY` dict to find barangay names
- `save_municipality_docs(location, final_scores, web_intel, run_id)` saves one doc per municipality

### Chatbot KB Enhancements
- **File:** `agents/chatbot.py`
- `update_kb_node` now calls `kb_builder.save_municipality_docs()` before `index_documents_from_kb()`
- `index_documents_from_kb()` now scans both `kb/reports/` AND `kb/intel/` (was reports-only)
- `retrieve_context` n_results: 5 → 10
- Source labels added: `[Municipality Profile: ...]` for kb/intel, `[Province Report: ...]` for kb/reports

### config.py
- Added: `WEB_INTEL_CACHE_TTL_DAYS = int(os.getenv("WEB_INTEL_CACHE_TTL_DAYS", 30))`
- `KB_INTEL = KB_DIR / "intel"` path added; dir auto-created on startup

#### Files changed (session 2)
- `agents/geocoder.py` — **new file**: Nominatim geocoding with persistent disk cache
- `agents/kb_builder.py` — **new file**: per-municipality KB doc generator with barangay lists
- `agents/web_intel.py` — Places v2 signals, location bias, Tavily delay, persistent cache
- `agents/synthesis.py` — updated `compute_final_score()` with 4-signal web_score
- `agents/chatbot.py` — update_kb_node calls kb_builder, retrieve_context n=10, source labels
- `agents/geo_scoring.py` — calls `geocode_units()` at end of agent
- `config.py` — added `WEB_INTEL_CACHE_TTL_DAYS`, `KB_INTEL` path

### ⚠️ Still pending next session
- GEE `NASA/POWER/V9/DAILY` dataset not found — solar scores using hash-based synthetic fallback
- Population and income are hash-estimated, not real census data
- Full end-to-end test with kb_builder integration pending (background run started)

---

## Session 1 — Initial Setup & Full Stack Fix (2026-05-28)

### API Keys & Connectivity
- `.env` now has all 4 keys: `XIAOMI_TOKEN_PLAN_KEY`, `TAVILY_API_KEY`, `GOOGLE_PLACES_API_KEY`, `GEE_PROJECT_ID`
- Xiaomi key format must start with `tp-...` (not `sk-...`)
- `GEE_PROJECT_ID` must be a GCP project ID (e.g. `my-project-123`), NOT a Google API key

### Google Places API — Updated to New API
- **File:** `agents/web_intel.py`
- Old endpoint `maps.googleapis.com/maps/api/place/textsearch/json` → **REQUEST_DENIED** with "Places API (New)" key
- New endpoint: `POST https://places.googleapis.com/v1/places:searchText`
- Headers: `X-Goog-Api-Key`, `X-Goog-FieldMask: places.displayName,places.priceLevel`
- New price level mapping: `PRICE_LEVEL_FREE=0, PRICE_LEVEL_INEXPENSIVE=1, PRICE_LEVEL_MODERATE=2, PRICE_LEVEL_EXPENSIVE=3, PRICE_LEVEL_VERY_EXPENSIVE=4`
- Added `_PRICE_LEVEL_MAP` dict for conversion

### MiMo Model — Thinking Blocks Fix
- **Files:** `agents/synthesis.py`, `agents/report_gen.py`, `agents/chatbot.py`
- Model returns `ThinkingBlock` before `TextBlock` → `content[0].text` crashed
- Fix: `next(b.text for b in response.content if hasattr(b, "text"))`
- Increased `max_tokens`: synthesis 400→2000, report_gen 2000→4000, chatbot 800→2000

### psgc → barangay Package Migration
- **File:** `agents/geo_scoring.py` (complete rewrite of data loading section)
- `psgc 2026.1.13.0` wheel ships **no data files** — `barangays.json` missing → all lookups fail
- Replaced with `barangay 2026.1.13.1` which bundles real PSGC data
- New function: `load_municipalities(location)` uses `barangay.BARANGAY` (Region→Province→City/Muni dict)
- Fuzzy matching via `rapidfuzz.process.extractOne` (score_cutoff=60)
- Removed `units_to_geodataframe(psgc_objects)` → replaced with dict-based `_build_unit()`

### Province Coordinate Lookup
- **File:** `agents/geo_scoring.py` — added `PROVINCE_CENTROIDS` dict (all 81 PH provinces)
- Municipalities get coordinates: province centroid ± hash-based offset (±0.30°)
- `_municipality_coord(name, province)` → deterministic placement within province bounds
- Fallback: central Philippines (12.5, 122.5) for unknown provinces

### Stable Synthetic Demographics
- Population and income class now hash-based (deterministic per municipality name) via `hashlib.md5`
- `_stable_float(seed, lo, hi)` → consistent float in range from string seed
- `_stable_income_class(name, province)` → weighted distribution (3rd/4th most common)
- Replaces `random.randint` which gave different results each run

### Synthesis Prompt — Richer Grounding
- **File:** `agents/synthesis.py`
- Added to prompt: province, region, urban/rural status, income class (labeled), actual population, solar kWh estimate
- AI explicitly asked to draw on knowledge of the specific municipality
- Prompt now passes: `province`, `region`, `urban_rural`, `income_class`, `population`, `solar_kwh`
- `final_scores` dict now includes: `province`, `region`, `income_class`, `population`, `is_urban`

### Streamlit Noise Fix
- Installed `torchvision 0.27.0` — silences hundreds of `ModuleNotFoundError: No module named 'torchvision'` from Streamlit's module watcher scanning `transformers` submodules
- Installed `watchdog 6.0.0`
- Created `.streamlit/config.toml`: `fileWatcherType = "watchdog"`, `logger.level = "warning"`

### requirements.txt additions
- `torchvision>=0.18.0`
- `barangay>=2026.1.13.1`
- `rapidfuzz>=3.0.0`
- `watchdog` (implicit via streamlit config)

### Pipeline Test Results (end of session)
- Location: Laguna → 20 real municipalities scored (Alaminos, Bay, Calauan, City of Biñan, etc.)
- Report references real places: Santa Rosa as "automotive capital", Cabuyao as "Enterprise City", UPLB in Los Baños
- 0 errors end-to-end

#### Files changed (session 1)
- `agents/web_intel.py` — Google Places v1 (New API) endpoint + price level map
- `agents/geo_scoring.py` — full rewrite: barangay package, province centroids, stable hash demographics
- `agents/synthesis.py` — thinking block fix, richer prompt with province/income/population context
- `agents/report_gen.py` — thinking block fix, max_tokens 4000
- `agents/chatbot.py` — thinking block fix, max_tokens 2000
- `requirements.txt` — added torchvision, barangay, rapidfuzz
- `.streamlit/config.toml` — created (watchdog watcher, warning log level)
- `.env` — all 4 API keys populated (not committed)

### ⚠️ Still pending next session
- GEE `NASA/POWER/V9/DAILY` dataset not found — solar scores using hash-based synthetic fallback
  - Need to verify GCP project has Earth Engine API + NASA POWER dataset access
- `GEE_PROJECT_ID` in `.env` may need to be the actual GCP project ID string (not an API key)
- Population and income are estimated, not real census data — consider integrating PSA 2020 Census CSV
