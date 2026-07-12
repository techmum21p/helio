# Dataset-First Helio Explorer — Design

## Why

Helio's national dataset is now complete (1,655 municipalities, all 118 provinces run at least
once). The user has spent ~$50 on Google Places API and wants Helio to stop calling paid external
APIs (Google Places, Tavily) at runtime entirely — the app should become a product built on top of
what's already been scored, not a tool that re-fetches on every use.

This replaces `app.py`'s current "pick a province, run the live pipeline" flow with a dataset-first
explorer + RAG chatbot, both reading from `data/helio.db`. The only "live" work still allowed is an
LLM call (MiMo, cheap, core to the product) to re-synthesize a single municipality's assessment
on demand — never a Places or Tavily call.

## Discovered problem: assessment/geo_score basis mismatch

While designing this, we found `run_results.assessment` rows are frozen text written at the time a
province was run — but `geo_scores` has since been recomputed (real GEE solar + real PSA
income/population replacing hash-fake values, 2026-07-08). Checked directly against
`data/helio.db`:

- **390 of 1,487** assessed municipalities have their latest `run_results.completed_at` **before**
  `geo_scores.computed_at` (`2026-07-08 11:37:53`) — their assessment prose (which cites specific
  score values inline, e.g. "0.79 score", "1st-class income") was written against since-corrected
  numbers and its basis is wrong.
- **1,097** were generated at/after the fix and are trustworthy as-is.
- **168** municipalities were never assessed at all (ranked below their province's top-20 cutoff).

**Decision: discard, don't just flag.** A `run_results` row only counts as current if
`completed_at >= geo_scores.computed_at` for that municipality. The 390 pre-fix rows are treated
identically to "never assessed" for every display and retrieval purpose — old rows stay in the DB
for audit history, but are never shown as current truth. This collapses "stale" and "missing" into
one bucket: **needs-synthesis** (390 + 168 = 558 municipalities, minus 42 of the geo-only set that
already have cached `web_intel_cache` entries and can get a full assessment for free).

## Architecture & data flow

```
Streamlit app.py  (no run_pipeline import, no threading, no live Places/Tavily/GEE calls)
 ├─ agents/db_store.get_latest_scored_municipalities()   [new]
 │    → one row per municipality; assessment fields NULL unless the row is current
 │      (completed_at >= geo_scores.computed_at)
 ├─ agents/location_db                                    [unchanged]
 │    → province/municipality filters for drill-down
 ├─ agents/refresh.maybe_refresh_assessment(municipality_id)  [new module]
 │    ├─ current?  → no-op, return stored assessment
 │    ├─ needs-synthesis + web_intel_cache exists → call
 │    │    agents/synthesis.synthesize_municipality() directly (no Places/Tavily call),
 │    │    persist new run_results row, regenerate kb/intel doc, re-index into ChromaDB
 │    └─ needs-synthesis + no cache → stays geo-only, no action (would require a paid Places call)
 ├─ reports/<slug>.md  → existing province reports, viewed/downloaded inline (unchanged)
 └─ agents/chatbot.chat()  → sidebar RAG chat (unchanged call signature); before answering,
      detects a municipality name in the question and calls maybe_refresh_assessment() first
```

## One-time migration: purge stale docs from kb/index

Before launch, a one-off script removes the 390 stale-basis municipalities' `kb/intel/*.md`
chunks from ChromaDB (matched by municipality name/run_id in the doc filename), so the chatbot's
RAG retrieval can't surface wrong-basis narrative even before a user triggers a refresh.
Province-level `kb/reports` docs (each bundles a whole province's top-20 towns into one file) are
**left alone** for now — invalidating those would require re-synthesizing entire provinces, which
is out of scope here; a province's report doc may reference a stale town alongside valid ones
until that province is fully re-run. Back up `kb/index/` before running the purge (same pattern as
prior DB backups in this project).

## UI layout

- **National map (default view)**: Folium map, all 1,655 municipalities. Colored by `final_score`
  where current; muted/grayed styling for needs-synthesis towns (visibly distinct, not hidden).
- **Drill-down**: clicking a town calls `maybe_refresh_assessment()`, then shows
  tier/assessment/opportunity/risk (or "not yet assessed" if no cache exists) plus a link to its
  province's report.
- **Persistent sidebar chat**: always visible next to the map. Calls the same refresh hook when it
  recognizes a specific municipality name in the user's message before composing its answer.
- **Report viewer**: inline view/download of the existing per-province markdown report.

## Error handling

`maybe_refresh_assessment()` never raises. Any failure (LLM error, malformed cache entry) is
logged via loguru and falls back to the last-known state (stored assessment if current, otherwise
geo-only display) — same non-fatal pattern as every other agent in this codebase.

## What's removed from app.py

`run_pipeline` import/call, the background-thread run trigger, the `precompute_geo_scores`
trigger, and the "Run a new province" UI flow. `graph/pipeline.py` and the individual pipeline
agents (`geo_scoring`, `web_intel`) are untouched in the codebase — still used by
`scripts/run_all_provinces.py` and any future manual national re-run — only `app.py`'s dependency
on them is cut.

## Testing

- `get_latest_scored_municipalities()`: dedup correctness across multiple runs per municipality;
  correct current-vs-needs-synthesis bucketing against `geo_scores.computed_at`.
- `maybe_refresh_assessment()`: current / stale-with-cache / stale-without-cache / never-assessed
  branches, and that it never calls Places/Tavily.
- KB purge script: correctly identifies and removes only the 390 stale muni-level docs, leaves
  province-level report docs untouched.

## Out of scope

- Re-synthesizing entire provinces to clean up `kb/reports` docs.
- Raising `TOP_N_TARGETS` / full below-top-20 coverage (separate, previously-parked, costs money).
- Barangay-level granularity (previously decided against).
