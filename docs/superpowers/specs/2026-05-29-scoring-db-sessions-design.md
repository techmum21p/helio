# Helio — Revised Scoring, DB Cache & Session History
**Date:** 2026-05-29  
**Status:** Approved  
**Branch:** `feat-geo-scoring`  
**Base:** Current Streamlit app (`app.py`)

---

## 1. Goal

Four tightly coupled improvements shipped together in one branch:

1. **Fix geo scoring** — revised weights, proper 3-component normalization, `geo_scoring_agent` becomes a DB lookup
2. **Migrate web intel cache** — replace JSON file with `web_intel_cache` table; compute and persist `web_score`
3. **Update final score formula** — `0.70 × geo + 0.30 × web`
4. **Persist sessions, reports, and chat** — DB-backed history panel in the Streamlit sidebar

---

## 2. What Changes and Where

| File | Change |
|---|---|
| `config.py` | Updated score weights |
| `scripts/precompute_geo_scores.py` | Rewrite: proper 3-component normalization |
| `agents/geo_scoring.py` | DB lookup first, on-the-fly fallback |
| `agents/web_intel.py` | SQLite cache instead of JSON; compute + store `web_score` |
| `agents/synthesis.py` | `compute_final_score()` uses new 70/30 weights |
| `agents/report_gen.py` | Also writes to `reports` table |
| `agents/chatbot.py` | Persists each chat turn to `chat_messages` table |
| `agents/db_store.py` | **NEW** — replaces `session_store.py`; owns all DB session/run/chat I/O |
| `app.py` | Run lifecycle hooks; sidebar history panel; Admin page |
| `data/helio.db` | `ALTER TABLE web_intel_cache ADD COLUMN web_score REAL` |

**Retired:** `agents/session_store.py` (stop writing new JSON sessions; old files are ignored)

---

## 3. Revised Scoring Model

### Geo score (pre-computed, stored in `geo_scores`)
```
geo_score = 0.35 × solar_norm + 0.45 × income_norm + 0.20 × pop_density_norm
```

Changes from current:
- Solar: `0.40 → 0.35`
- Income: `0.35 → 0.45` — ability to pay is the #1 conversion factor
- Population: raw count → **density** (people/km²), weight `0.25 → 0.20`

### Final score (computed at synthesis time)
```
final_score = 0.70 × geo_score + 0.30 × web_score
```

Changes from current: web intel weight `0.20 → 0.30` — actual market activity is real signal.

### web_score formula (unchanged from current synthesis.py, now also cached)
```python
web_score = (
    0.35 × min(business_count / 20, 1.0)
  + 0.25 × min(avg_price_level / 4, 1.0)
  + 0.25 × max((avg_rating - 1.0) / 4.0, 0)
  + 0.15 × min(commercial_anchors / 5, 1.0)
)
```

### Normalization
All three geo components run through `MinMaxScaler` across **all 1,622 Philippine municipalities** at precompute time. This makes geo_score rankings stable and consistent regardless of which province subset is displayed.

---

## 4. Precompute Script (`scripts/precompute_geo_scores.py`)

**Trigger:** Admin page → "Refresh Geo Scores" button (background thread) OR CLI:
```bash
python scripts/precompute_geo_scores.py
```

**What it does:**
1. Iterates all municipalities from the `barangay` package (~1,622)
2. For each municipality, computes via hash-based estimates (deterministic per name+province):
   - `income_class` (1st–6th) using weighted distribution biased to 3rd/4th
   - `population` (5,000–150,000)
   - `area_km2` (20–500 km², hash-based)
   - `pop_density = population / area_km2`
   - `solar_irradiance` — real GEE call if available, else synthetic fallback
3. Runs `MinMaxScaler` across all 1,622 rows for `solar`, `income_score (1–6)`, `pop_density`
4. Upserts into `geo_scores` with corrected component values and `geo_score`
5. Upserts into `municipalities` (lat, lon, area_km2, population, income_class — currently all NULL)
6. Yields progress updates (municipality index, total) so the Streamlit bar can poll

**Idempotent:** upserts by `municipality_id` — safe to re-run.

**Runtime:** ~5–15 min with GEE; ~2–3 min with synthetic solar fallback.

---

## 5. Schema Change

One new column added at agent startup (idempotent `ALTER TABLE`):

```sql
ALTER TABLE web_intel_cache ADD COLUMN web_score REAL;
```

No other schema changes — all other tables already exist in `data/helio.db`.

---

## 6. Agent Changes

### `geo_scoring_agent` (major change)

```
1. COUNT(*) FROM geo_scores → if 0, run on-the-fly (first boot before precompute)
2. Otherwise: SELECT g.*, m.* FROM geo_scores g JOIN municipalities m
              WHERE m.name IN (...) AND m.province = ?
3. Build scores dict from rows; skip GEE, barangay, geocoder entirely
4. Return same SolarLeadState shape — interface unchanged
```

Fallback path (empty table) runs the existing `compute_geo_scores()` logic unchanged.

### `web_intel_agent` (cache layer swap)

Replace JSON cache functions with SQLite equivalents:

| Old | New |
|---|---|
| `_load_cache()` from JSON file | `SELECT ... FROM web_intel_cache WHERE municipality_id = ? AND expires_at > ?` |
| `_save_cache()` to JSON file | `INSERT OR REPLACE INTO web_intel_cache (...)` |
| No `web_score` stored | Compute `web_score` from raw signals; write to `web_intel_cache.web_score` |

Cache TTL behavior unchanged: 30 days (`expires_at = fetched_at + 30 days`).

### `synthesis.py` — `compute_final_score()`

```python
# Before
return round(0.80 * geo_score + 0.20 * web_score, 4)

# After
return round(0.70 * geo_score + 0.30 * web_score, 4)
```

Also: if `web_score` already exists in `web_intel_cache` for this municipality, read it directly instead of recomputing from raw signals.

### `report_gen_agent`

After writing markdown files, also call:
```python
db_store.save_report(run_id, province, municipality=None, markdown=markdown, file_path=str(report_path))
```

Files at `reports/` and `kb/reports/` continue to be written (KB RAG still needs them).

### `chatbot.py` — `chat()`

After each turn, call `db_store.save_chat_message(run_id, role, content)` for both user and assistant turns. `chat()` signature gains a `run_id: str = ""` parameter — if empty string, message is not persisted (safe for cases where no pipeline run has been started yet).

---

## 7. New Module: `agents/db_store.py`

Replaces `agents/session_store.py`. Owns all DB I/O for runs, results, reports, and chat.

```python
def create_run(run_id: str, location: str, province: str) -> None
def complete_run(run_id: str, top_targets: list) -> None      # updates runs + upserts run_results
def fail_run(run_id: str, error: str) -> None
def save_report(run_id: str, province: str, municipality: str | None,
                markdown: str, file_path: str) -> None
def save_chat_message(run_id: str, role: str, content: str) -> None
def load_chat_history(run_id: str) -> list[dict]              # [{role, content}, ...]
def list_runs(limit: int = 20) -> list[dict]                  # for sidebar
def load_run(run_id: str) -> dict | None                      # {run_id, location, top_targets, report_markdown, report_path}
```

All functions open/close their own connection (same pattern as `location_db.py`). All errors are caught and logged — never raised.

---

## 8. Streamlit Changes (`app.py`)

### Run lifecycle

```python
# Before pipeline call
db_store.create_run(run_id, location, province)

# After pipeline call (success)
db_store.complete_run(run_id, result["top_targets"])

# After pipeline call (error)
db_store.fail_run(run_id, error_message)
```

`run_id` is generated in `app.py` as `uuid.uuid4().hex[:8]` and injected into `SolarLeadState` before calling `run_pipeline()`. `run_pipeline()` signature gains an optional `run_id: str = None` parameter — if provided it is used, otherwise it generates one internally (preserves existing CLI usage).

### Sidebar history panel

Replaces the current `st.selectbox` session loader. Structure:

```
📋 Past Runs
──────────────────────────
🗺️ Laguna — May 28, 2026
    8 targets · top 0.82 · High
🗺️ Pampanga — May 27, 2026
    12 targets · top 0.74 · Med
[— 8 more —]
──────────────────────────
```

- Shows last 10 runs from `db_store.list_runs(limit=10)`
- Each row is a `st.button` — clicking calls `db_store.load_run(run_id)` and `db_store.load_chat_history(run_id)` to restore session state
- Failed runs shown with ⚠️ icon, not clickable

### New Admin page

New sidebar nav option: `⚙️ Admin`

Contents:
- **Refresh Geo Scores** — button that spawns a `threading.Thread` running `precompute_geo_scores`. Progress is tracked via a `{"done": int, "total": int, "running": bool}` dict stored in `st.session_state["precompute_progress"]`. The main thread calls `st.rerun()` on a 1-second timer loop until `running` goes False, updating `st.progress()` each tick. Shows last computed timestamp from `MAX(computed_at)` in `geo_scores`.
- **DB Stats** — row counts for all tables (`municipalities`, `geo_scores`, `web_intel_cache`, `runs`, `reports`, `chat_messages`).
- **Re-index KB** — button that calls `index_documents_from_kb()` (existing functionality).

---

## 9. config.py Changes

```python
# Geo score weights (revised)
WEIGHTS = {
    "solar":      0.35,   # was 0.40
    "income":     0.45,   # was 0.35
    "population": 0.20,   # was 0.25 (now interpreted as pop_density)
}

# Final score weights (new)
FINAL_GEO_WEIGHT = 0.70   # was 0.80
FINAL_WEB_WEIGHT = 0.30   # was 0.20
```

---

## 10. What Gets Retired

| File/dir | Replaced by |
|---|---|
| `agents/session_store.py` | `agents/db_store.py` |
| `sessions/*.json` | `runs` + `chat_messages` + `reports` tables in `helio.db` |
| `data/processed/web_intel_cache.json` | `web_intel_cache` table in `helio.db` |

Files are not deleted immediately — stop writing new ones; reads fall back gracefully.

---

## 11. Open Questions / Non-Goals

- **No FastAPI migration** — Streamlit stays as the UI for this branch
- **No Next.js frontend** — deferred to a future branch
- **No hybrid RAG (bm25s)** — deferred; chatbot.py interface unchanged
- **No GEE parallelization** — precompute runs sequentially per municipality (acceptable for a background admin job)
- **Old `sessions/` JSON files** — not migrated to DB automatically; only new runs are persisted to DB
