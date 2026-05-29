# Helio Frontend Fixes — Design Spec
Date: 2026-05-29

## Goal
Bring the Next.js app to parity with the Streamlit version by consolidating to 3 pages, fixing 7 reported bugs, and backfilling missing map coordinates.

## Navigation restructure
- Sidebar nav: **Map & Scores | Reports | Chat** only
- Remove Explore and Admin from the sidebar (Admin still reachable at /admin by URL)
- "Maps & Scores" nav link redirects to most recent completed run

## Page 1 — Map & Scores (`/map/[runId]`)
- **Fix coords (critical):** `_persist_run_results()` in `api/routers/runs.py` must parse `result["geo_geojson"]` and `UPDATE municipalities SET lat=?, lon=? WHERE name=? AND province=? AND lat IS NULL`. Backfill existing 2 runs from session files.
- **Expand town cards:** Right-sidebar cards become click-to-expand, showing full assessment + opportunity + risk + population/income class (Streamlit-style expander).
- **Map zoom/center:** Change `zoom=10` → `zoom=7`; center derived from run results' average lat/lon.

## Page 2 — Reports (`/reports` + `/reports/[runId]`)
- `/reports/page.tsx`: fetch runs list, display as clickable cards (location, date, status). Navigate to `/reports/[runId]` on click.
- `/reports/[runId]/page.tsx`: already works — no changes needed.

## Page 3 — Chat (`/chat`)
- Auto-select most recent completed run as default context instead of "Global KB".

## Backend
- `api/routers/runs.py` — `_persist_run_results`: add lat/lon backfill from geo_geojson.
- One-time migration: backfill lat/lon for existing municipalities from session files or by re-computing via `_municipality_coord`.

## Out of scope
- Explore page (removed from nav, kept in codebase)
- Admin page (removed from nav, kept at /admin URL)
- Any new features or API changes beyond coord backfill
