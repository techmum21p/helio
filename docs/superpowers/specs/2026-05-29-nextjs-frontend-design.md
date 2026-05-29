## Helio v2 — Next.js Frontend Design Spec

**Status:** Approved
**Date:** 2026-05-29
**Branch:** feat-helio-v2

---

## 1. Goal

Replace the Streamlit frontend with a Next.js 14 App Router application. The FastAPI backend (Plan 1) is already complete. This spec covers the frontend build plus two backend enhancements required to support it: SSE step events and streaming chat.

---

## 2. Design Decisions

| Decision | Choice |
|---|---|
| Visual aesthetic | Dark Intelligence — slate background (`#0f172a`/`#1e293b`), amber/orange accents (`#f59e0b`) |
| Explore layout | Full-width table by default; "Show Map" toggle adds map above table |
| Map click interaction | Scroll table to row + expand in-place with score bar |
| Analyze progress | Vertical step tracker (CI-style): spinner → checkmark + elapsed time |
| Reports layout | Three-panel: narrow run list sidebar / center markdown / bottom-pinned chat |
| Chat | Streaming token-by-token output |

---

## 3. Tech Stack

- **Next.js 14** App Router, TypeScript
- **Tailwind CSS** + **shadcn/ui** (Button, Badge, Select, Separator, Skeleton, ScrollArea)
- **react-leaflet** — interactive map, dynamic import (client-only)
- **SWR** — data fetching with caching for municipalities, provinces, run list, chat history
- **react-markdown** + **remark-gfm** — dark-themed report rendering
- Native `EventSource` — SSE for run progress and admin refresh-scores
- Native `fetch()` + `ReadableStream` — streaming chat tokens
- No separate state management library — `useState` / `useContext` is sufficient

---

## 4. Backend Changes

### 4.1 SSE Step Events

**Problem:** `/runs/{id}/stream` currently polls DB status (running/done/failed) every 2s. The frontend step tracker needs per-step events with timing.

**Solution:** In-memory event store keyed by run_id.

- Add `api/events.py`:
  ```python
  _run_events: dict[str, list[dict]] = {}

  def push_event(run_id: str, step: str, status: str, elapsed_ms: int) -> None:
      _run_events.setdefault(run_id, []).append(
          {"step": step, "status": status, "elapsed_ms": elapsed_ms}
      )

  def get_events(run_id: str) -> list[dict]:
      return _run_events.get(run_id, [])

  def clear_events(run_id: str) -> None:
      _run_events.pop(run_id, None)
  ```

- Update `run_pipeline(location)` in `graph/pipeline.py` to accept `run_id: str | None = None` and use `graph.stream(initial_state)` instead of `graph.invoke()`. LangGraph's `stream()` yields `{node_name: updated_state}` dicts for each completed step — use this to call `push_event` with timing:
  ```python
  def run_pipeline(location: str, run_id: str | None = None) -> SolarLeadState:
      pipeline = build_pipeline()
      initial_state = {..., "run_id": run_id or str(uuid.uuid4())[:8]}
      t0 = time.monotonic()
      state = initial_state
      for step_output in pipeline.stream(initial_state):
          node_name = next(iter(step_output))  # e.g. "geo_scoring"
          state = step_output[node_name]
          push_event(run_id, node_name, "done", int((time.monotonic() - t0) * 1000))
      return state
  ```
- Update `_run_pipeline_bg` in `api/routers/runs.py` to emit a `running` event for each step before it starts. Since `stream()` only yields on completion, emit `running` optimistically at the start of the run for the first step, then track transitions:
  ```python
  push_event(run_id, "geo_scoring", "running", 0)  # emit before stream starts
  # each stream yield emits "done" for completed step + "running" for next
  ```

- Update `/runs/{id}/stream` to yield from `get_events(run_id)` as they arrive (async poll every 0.5s), then yield a final `complete` or `failed` event on terminal status. Clear events after terminal event.

**SSE event shape:**
```json
{"step": "geo_scoring", "status": "running", "elapsed_ms": 0}
{"step": "geo_scoring", "status": "done", "elapsed_ms": 4200}
{"step": "complete", "run_id": "abc123", "elapsed_ms": 61300}
```

**Steps (in order):** `geo_scoring`, `web_intel`, `synthesis`, `report_gen`, `update_kb`

### 4.2 Streaming Chat

**Problem:** `POST /chat` returns a blocking `ChatOut` JSON response. The frontend needs token-by-token streaming.

**Solution:**

- Add `chat_stream(message, history)` generator to `agents/chatbot.py` using `stream=True` on the MiMo client. Yields text token chunks.
- Replace `POST /chat` handler with a `StreamingResponse` that:
  1. Loads history from DB
  2. Calls `chat_stream()`
  3. Yields chunks as SSE (`data: <token>\n\n`)
  4. Persists the full assembled reply to `chat_messages` after the stream ends
- Keep `GET /chat/{run_id}/history` unchanged.

**Frontend consumption:** `fetch('/chat', {method:'POST', body})` → `response.body.getReader()` → decode chunks → append to message buffer.

---

## 5. Pages

### `/explore` — Pre-scored Leaderboard

- **Filter bar** (top): Province multi-select (`GET /provinces`), min geo score slider (0–1, step 0.01), free-text search (client-side filter on loaded data)
- **"Show Map" toggle** button: when active, renders `MapView` in a panel above the table
- **`MunicipalityTable`**: columns — Rank, Municipality, Province, Solar / Income / Pop (color-coded mini `ScoreBar`), Geo Score, `TierBadge`. Sorted by geo score descending. Paginated 50/page. Client-side sort on all columns.
- **Map interaction**: clicking a dot calls `setSelectedId(municipality.id)` on the table, which scrolls to that row and expands it with a full-width `ScoreBar` + score numbers. Clicking again collapses.
- Data: `GET /municipalities` (loads all, SWR-cached)

### `/analyze` — Run the Pipeline

- **Location picker**: Province select → Municipality multi-select (cascading). Builds `location` string (`"Municipality, Province"` or `"Muni1|Muni2, Province"`).
- **"Analyze" button**: `POST /runs` → navigates to `/analyze/[runId]`
- **`/analyze/[runId]`**: renders `RunProgress` component consuming SSE on `/runs/{runId}/stream`. On `complete` event, auto-redirects to `/reports/[runId]` after 1.5s.

### `/reports/[runId]` — Report Detail

Three-panel layout (CSS Grid: `180px 1fr`; chat pinned to bottom of center column):

- **Left sidebar** (`RunList`): scrollable list of past runs from `GET /runs`. Each item shows location, date, status badge. Active run highlighted. Clicking navigates to that report.
- **Center** (scrollable): rendered markdown via `react-markdown` + `remark-gfm`. Custom component overrides for dark theme (headings amber, code blocks slate, tables bordered). "Download .md" button triggers client-side blob download of raw markdown.
- **Bottom-pinned** (`ChatPanel`, `runId=currentRunId`): fixed-height chat area (300px). Shows history from `GET /chat/{runId}/history` on mount. Streams new replies. Scoped to this run's context.

### `/reports` — Run List (redirect)

Redirects to `/reports/[most-recent-run-id]`. If no runs exist, shows empty state with link to `/analyze`.

### `/chat` — Global Chat

Full-page layout:
- **Left (75%)**: `ChatPanel` with `runId=null` (global KB search). Full streaming output.
- **Right sidebar (25%)**: scrollable list of past runs. Clicking one sets `runId` on the `ChatPanel` to switch context (clears message buffer, loads that run's history).

### `/admin` — Admin Panel

- **Stats cards**: municipalities, geo_scores, runs, run_results, chat_messages, reports, web_intel_cache counts + last precompute timestamp. Fetched from `GET /admin/stats`, SWR with 30s revalidation.
- **"Refresh Geo Scores"** button: `POST /admin/refresh-scores` → SSE on `/admin/refresh-scores/stream` → inline `RunProgress`-style tracker.
- **"Re-index KB"** button: `POST /admin/reindex-kb` → spinner → success/error toast.

---

## 6. Component Inventory

| Component | File | Responsibility |
|---|---|---|
| `Nav` | `components/nav.tsx` | Top nav bar, active route highlight, amber sun logo |
| `MunicipalityTable` | `components/municipality-table.tsx` | Sortable/filterable/paginated table, expand-on-select |
| `ScoreBar` | `components/score-bar.tsx` | 3-segment horizontal bar: solar (blue), income (green), pop (purple) |
| `TierBadge` | `components/tier-badge.tsx` | Colored pill badge: Tier A (amber), B (green), C (slate), D (red) |
| `MapView` | `components/map-view.tsx` | react-leaflet map, dynamic import, dots colored by score, click emits id |
| `RunProgress` | `components/run-progress.tsx` | SSE-driven 5-step tracker |
| `ChatPanel` | `components/chat-panel.tsx` | Streaming chat, `runId` prop (null = global), markdown in responses |
| `RunList` | `components/run-list.tsx` | Sidebar list with status badges |
| `StatCard` | `components/stat-card.tsx` | Admin stats display card |

---

## 7. Data Flow

**`lib/api.ts`** — typed fetch wrappers for all endpoints. `API_URL` defaults to `http://localhost:8000` via `NEXT_PUBLIC_API_URL` env var.

```
SWR cache:
  /provinces            → Province[]        (explore filter)
  /municipalities       → Municipality[]    (explore table — load all once)
  /runs?limit=50        → Run[]             (run list sidebar)
  /runs/{id}            → RunDetail         (report page)
  /chat/{id}/history    → ChatMessage[]     (chat panel on mount)
  /admin/stats          → AdminStats        (admin page, 30s TTL)

EventSource (raw):
  /runs/{id}/stream     → step events       (RunProgress)
  /admin/refresh-scores/stream → step events (admin progress)

fetch + ReadableStream:
  POST /chat            → token stream      (ChatPanel)
```

---

## 8. File Structure

```
frontend/
├── app/
│   ├── layout.tsx               # Root layout: Nav + dark bg
│   ├── page.tsx                 # Redirect → /explore
│   ├── explore/
│   │   └── page.tsx
│   ├── analyze/
│   │   ├── page.tsx             # Location picker
│   │   └── [runId]/page.tsx     # RunProgress + auto-redirect
│   ├── reports/
│   │   ├── page.tsx             # Redirect to latest run
│   │   └── [runId]/page.tsx     # Three-panel report view
│   ├── chat/
│   │   └── page.tsx
│   └── admin/
│       └── page.tsx
├── components/
│   ├── nav.tsx
│   ├── municipality-table.tsx
│   ├── score-bar.tsx
│   ├── tier-badge.tsx
│   ├── map-view.tsx             # dynamic import, 'use client'
│   ├── run-progress.tsx
│   ├── chat-panel.tsx
│   ├── run-list.tsx
│   └── stat-card.tsx
├── lib/
│   ├── api.ts                   # Typed fetch wrappers
│   └── types.ts                 # Shared TypeScript types
├── .env.local                   # NEXT_PUBLIC_API_URL=http://localhost:8000
├── next.config.ts
├── tailwind.config.ts
└── package.json
```

---

## 9. Backend Files Changed

| File | Change |
|---|---|
| `api/events.py` | New — in-memory event store |
| `api/routers/runs.py` | Update `_run_pipeline_bg` to emit step events; update `/stream` endpoint |
| `api/routers/chat.py` | Replace `POST /chat` with `StreamingResponse` |
| `agents/chatbot.py` | Add `chat_stream()` generator |

---

## 10. Environment

```
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

CORS for `http://localhost:3000` is already configured in `api/main.py`.
