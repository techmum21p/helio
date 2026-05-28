# Town-Level Location Selection Design
**Date:** 2026-05-28
**Branch:** feat-town-level
**Status:** Approved

## Problem
The current pipeline only accepts a province or region as input (free-text). Users cannot target a specific municipality. There is no structured location data — the app relies on fuzzy text matching against the `barangay` package at runtime.

## Goal
- Build a persistent SQLite database of all PH regions, provinces, municipalities, and barangays (populated once from the `barangay` package via a build script)
- Replace the free-text location input with cascading Province → Municipality dropdowns
- Enable single-municipality pipeline runs (analyze just one town)
- Store barangays in DB for future use; omit from dropdown for now

## Sequencing Note
This branch (`feat-town-level`) covers only location DB + dropdowns + single-municipality pipeline routing.
Full SQLite consolidation (sessions, chat history, reports, caches) is a separate follow-up branch (`feat-sqlite-consolidation`), planned before the Next.js/FastAPI migration.

---

## Section 1: SQLite Location Database

### Location
`data/ph_locations.db` — added to `config.py` as `LOCATION_DB`.

### Schema (normalized, 4 tables)
```sql
CREATE TABLE regions (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE provinces (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(id)
);

CREATE TABLE municipalities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    province_id INTEGER NOT NULL REFERENCES provinces(id)
);

CREATE TABLE barangays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id)
);

CREATE INDEX idx_provinces_region   ON provinces(region_id);
CREATE INDEX idx_municipalities_prov ON municipalities(province_id);
CREATE INDEX idx_barangays_muni      ON barangays(municipality_id);
```

### Build Script
`scripts/build_location_db.py` — one-time manual run:
```bash
python scripts/build_location_db.py
```
- Reads `barangay.BARANGAY` (Region → Province → Municipality → [barangays])
- Populates all 4 tables in one transaction
- Idempotent: skips if `municipalities` table already has rows
- Prints row counts on completion (~42k barangays, ~1,700 municipalities, ~81 provinces, ~17 regions)

### Query Helpers — `agents/location_db.py`
- `get_provinces() -> list[dict]` — returns `[{id, name}]` sorted by name
- `get_municipalities(province_id) -> list[dict]` — returns `[{id, name}]` for a province
- `get_barangays(municipality_id) -> list[dict]` — returns `[{id, name}]` (for future use)
- `get_province_name(province_id) -> str`
- `get_municipality_name(municipality_id) -> str`

All functions use a module-level `sqlite3` connection to `config.LOCATION_DB`.

---

## Section 2: Cascading Dropdowns in `app.py`

### Replaces
`st.text_input("Province / Region", ...)` + `▶ Analyze` button.

### New sidebar UI
```
[ Select Province ▼ ]         ← required
[ Select Municipality ▼ ]     ← optional; default = "All municipalities"
[ ▶ Analyze ]
```

- Province selectbox: populated from `get_provinces()` on every render (fast — DB query)
- Municipality selectbox: populated from `get_municipalities(selected_province_id)`; first option is always `"— All municipalities —"` (value = None)
- No barangay dropdown (stored in DB for future use only)
- Changing Province resets Municipality selection to default via `st.session_state`

### Location string construction
The `location` string passed to `run_pipeline` is built from the selections:
| Province | Municipality | `location` passed |
|----------|-------------|-------------------|
| Laguna   | All         | `"Laguna"`        |
| Laguna   | Biñan       | `"Biñan, Laguna"` |

### Session state keys added
- `st.session_state.selected_province_id` — int or None
- `st.session_state.selected_municipality_id` — int or None

---

## Section 3: Pipeline Routing for Single-Municipality Mode

### Input detection
`geo_scoring_agent` checks `state["location"]` for a comma:
- No comma → province/region mode (existing `load_municipalities()` path)
- Comma → municipality mode: parse as `"Town, Province"` → call `load_single_municipality(town, province)`

### New function: `load_single_municipality(town, province) -> list[dict]`
In `agents/geo_scoring.py`:
- Searches `barangay.BARANGAY` for the province (fuzzy match, score_cutoff=60)
- Within that province, fuzzy-matches the municipality name
- Returns a single-item list: `[_build_unit(muni_name, prov_name, region_name)]`
- Falls back to `_synthetic_fallback(location)` on failure

### MinMaxScaler fix for single-row case
`compute_geo_scores` — when `len(df) == 1`, skip MinMaxScaler and normalize against fixed PH ranges:
```python
PH_SOLAR_RANGE   = (4.5, 6.0)   # kWh/m²/day
PH_POP_RANGE     = (5_000, 150_000)
PH_INCOME_RANGE  = (1, 6)        # income_score 1–6

def _normalize_fixed(value, lo, hi):
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))
```
Multi-row case keeps MinMaxScaler (relative ranking within the set).

### Downstream agents — no changes needed
`web_intel`, `synthesis`, `report_gen`, `update_kb` all iterate over whatever `geo_scores` contains. A single-entry dict works identically to a 20-entry dict.

---

## Files Changed
| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `config.py` | Add `LOCATION_DB` path |
| Create | `scripts/build_location_db.py` | One-time DB population from barangay package |
| Create | `agents/location_db.py` | DB connection + query helpers |
| Modify | `agents/geo_scoring.py` | `load_single_municipality`, MinMaxScaler fix |
| Modify | `app.py` | Cascading dropdowns, location string construction |

## Out of Scope (this branch)
- Barangay dropdown
- Moving sessions/chat/reports/caches to SQLite (`feat-sqlite-consolidation`)
- FastAPI/Next.js migration
