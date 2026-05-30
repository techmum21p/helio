# Design: Score Transparency, Annual Yield, GEE Precompute & Past Runs Page
**Date:** 2026-05-30  
**Branch:** feat-geo-scoring  

---

## Overview

Three related improvements to Helio:

1. **Score transparency** — expose all geo-score components (solar irradiance, income class, population density) and estimated annual yield on the map, in report tables, and in the DB, so users understand _why_ a municipality scored the way it did.
2. **Real GEE irradiance precompute** — replace the current hash-based synthetic solar estimates in the precompute script with real NASA POWER satellite data fetched from Google Earth Engine, using batched `reduceRegions()` calls to stay within API limits.
3. **Past Runs page** — a dedicated, paginated history page (20/page) where every previous run can be browsed and its full report read inline.

---

## Feature 1: Score Transparency + Annual Yield

### DB Changes (`agents/db_store.py`)

**Approach B:** Add component columns directly to `run_results` so every run — live or historical — retains the full breakdown without requiring a JOIN to `geo_scores`.

`_migrate()` adds three nullable columns to `run_results` (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern):

| Column | Type | Description |
|---|---|---|
| `solar_irradiance` | REAL | Raw solar irradiance in kWh/m²/day |
| `solar_yield_kwh` | REAL | Annual yield per kWp: `solar_irradiance × 365 × 0.80` |
| `pop_density` | REAL | Population density in people/km² |

For pre-existing `run_results` rows that lack these values, `load_run()` falls back to a LEFT JOIN on `geo_scores` via `municipality_id`.

### Data Flow Fix (`agents/synthesis.py`)

`synthesis_agent` already has `solar_raw` and `population_raw` / `area_km2` in the `geo` dict. Add to each entry in `top_targets`:

```python
"solar_irradiance": geo.get("solar_raw", 5.0),
"solar_yield_kwh":  round(geo.get("solar_raw", 5.0) * 365 * 0.80, 0),
"pop_density":      geo.get("pop_density", 0),
```

Note: `pop_density` is already stored in `geo_scores` via precompute. For on-the-fly runs it comes from `population_raw / area_km2` — `geo` dict may not always carry it directly; fall back to `population_raw / 500` (midpoint area estimate) if absent.

### `complete_run()` (`agents/db_store.py`)

Write the three new columns from each `top_targets` entry alongside existing fields.

### `load_run()` (`agents/db_store.py`)

Read `solar_irradiance`, `solar_yield_kwh`, `pop_density` from `run_results`. For rows where these are NULL (old data), LEFT JOIN `geo_scores g ON g.municipality_id = rr.municipality_id` and use `g.solar_irradiance`, `g.pop_density`, computing yield inline as `g.solar_irradiance * 365 * 0.80`.

### Map Popup (`app.py`)

Compact HTML popup, raw values only — no LLM assessment text in the popup:

```
<b>San Pedro</b> (Laguna)
────────────────────────────
Final Score: 0.742  |  Tier: HIGH
☀ Irradiance: 5.42 kWh/m²/day
📈 Income:    2nd class
👥 Population: 82,450
⚡ Yield: 1,588 kWh/kWp/yr (~7,940 kWh/yr for 5 kWp)
```

Reference system size for the concrete example: **5 kWp** (common PH residential install).

Tooltip (on hover, before click): `{name}: {score:.3f} | {irradiance:.1f} kWh/m²/day`

### Sidebar Score Expander (`app.py`)

Replace the current single `st.metric` with a 4-column metrics grid:

| ☀ Irradiance | 📈 Income | 👥 Population | ⚡ Yield |
|---|---|---|---|
| 5.42 kWh/m²/day | 2nd class | 82,450 | 1,588 kWh/kWp/yr |

Keep LLM assessment/opportunity/risk text below the metrics grid — users can still read it.

### Report Prompt (`agents/report_gen.py`)

Add a "Score Breakdown" section instruction after "Top Target Areas":

```
## Score Breakdown
(Table with columns: Municipality | Irradiance (kWh/m²/day) | Income Class |
 Pop Density (ppl/km²) | Annual Yield (kWh/kWp) | Final Score)
```

The `targets_json` payload passed to the prompt already contains all needed fields after the synthesis fix above.

---

## Feature 2: Real GEE Irradiance Precompute

### Context

The current `scripts/precompute_geo_scores.py` derives solar irradiance from a deterministic hash (`_stable_float(f"{muni_name}:solar", 4.5, 6.0)`). These are synthetic estimates, not real measurements. Since we now surface irradiance explicitly on the map and in reports, synthetic values would mislead users.

The fix: update the precompute script to call GEE's ERA5-Land dataset (same source used by on-the-fly runs) for each municipality. This script is run **manually** by the operator after GEE authentication — it is never called from `app.py`.

### Batched `reduceRegions()` Strategy

Rather than one `getInfo()` per municipality (1,622 separate API calls, ~5+ min with throttle), group municipalities into **batches of 200** and issue one `reduceRegions().getInfo()` per batch:

```
~1,622 municipalities
→ ceil(1622 / 200) = 9 batches
→ one reduceRegions().getInfo() per batch (~3-10 seconds each)
→ 1 second sleep between batches
→ total wall time: ~30-90 seconds
```

GEE computes the mean surface solar radiation across a buffered point (11 km radius) for the 2023 calendar year and returns all values in a single response per batch.

### Resumability

Before querying GEE, check `geo_scores.solar_irradiance IS NOT NULL` for each municipality. Skip any that already have a real value. This makes repeated runs safe and allows interrupted runs to continue from where they left off.

### Fallback

If GEE returns `null` for a specific feature within a batch (point outside coverage, masked pixel, etc.), fall back to the existing hash-based synthetic estimate for that municipality. Log a warning. Do not abort the batch.

### DB Commit Strategy

Commit after each batch (not after each row). If the script dies mid-run, all completed batches are persisted.

### Script Changes (`scripts/precompute_geo_scores.py`)

- Add `fetch_gee_irradiance_batch(ee, units: list[dict]) -> dict[str, float]` — takes a batch of municipality dicts, builds an `ee.FeatureCollection`, calls `reduceRegions()`, returns `{name: kwh_per_day}`.
- Add `_init_gee()` call at script start (already exists in `agents/geo_scoring.py`, copy or import).
- Replace the `_stable_float(f"{muni_name}:solar", ...)` solar line in `_get_all_municipalities()` with a placeholder `None`; fill in real values from GEE after batch fetch.
- If GEE init fails (not authenticated), print a clear error and exit — do not silently fall back to synthetic values during a deliberate precompute run.
- Progress output: print batch number, municipality range, and time per batch.

### No App Changes

`app.py` and `geo_scoring_agent` are unchanged. The `geo_scores` DB table already stores `solar_irradiance`; the precompute script already writes to it. Once the updated script is run, all subsequent DB lookups automatically get real irradiance values.

---

## Feature 3: Past Runs Page

### Navigation

Add `📚 Past Runs` to the sidebar radio list in `app.py`. Existing pages unchanged.


### Page Layout

**Header:** `📚 Past Runs`

**Pagination state:** `st.session_state.runs_page` (int, default 0). Each page shows 20 runs.

**Run list:** fetched via `db_store.list_runs(limit=1000)` once, sliced client-side. Displays as a list of `st.expander` rows — one per run.

**Expander header line:**
```
{location}  ·  {date}  ·  {target_count} targets  ·  top {top_score:.2f}  {tier_icon}
```

**Expanded body:** calls `db_store.load_run(run_id)` lazily (only when expanded), then renders the report markdown inline using `st.markdown()`. Also shows a download button for the `.md` file if `report_path` is set.

**Pagination controls:** `← Previous` / `Next →` buttons below the list, disabled at boundaries. Page number shown between them: `Page {page+1} of {total_pages}`.

### `list_runs()` change

Current `list_runs(limit=20)` — change default limit to 1000 (or accept a high limit from the caller) so the Past Runs page can paginate client-side without multiple DB calls.

Add an `INNER JOIN reports ON reports.run_id = r.id` to the query so only runs that have a saved report are returned. Runs that completed but produced no report (e.g. empty target list, report generation failure) are silently excluded.

---

## Files Changed

| File | Change |
|---|---|
| `agents/db_store.py` | `_migrate()`: add 3 columns to `run_results`; `complete_run()`: write them; `load_run()`: read with fallback JOIN |
| `agents/synthesis.py` | Add `solar_irradiance`, `solar_yield_kwh`, `pop_density` to `top_targets` entries |
| `agents/report_gen.py` | Add Score Breakdown table section to `REPORT_PROMPT` |
| `app.py` | Map popup HTML; sidebar metrics grid; new Past Runs page; nav radio update |
| `scripts/precompute_geo_scores.py` | Add batched GEE fetch (`fetch_gee_irradiance_batch`); replace synthetic solar with real values; resume logic; batch commit |

---

## Out of Scope

- Changing the scoring formula or weights
- Re-running old pipeline runs to backfill component data in `run_results` (fallback JOIN to `geo_scores` handles this)
