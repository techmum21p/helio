> Last updated: 2026-07-12 | Session 12

# Helio — Solar Lead Intelligence Platform Session Notes

---

## Session 12 — Chatbot Tool-Use Retrieval Rollout, Replaces Regex Intent Detection (2026-07-12)

### The bug this fixes
A user asked "give me top 5 opportunities in sulu that I should prioritize" and got back the wrong municipalities with fabricated scores — the old chatbot relied on fragile ChromaDB semantic search over profile chunks with no ranking guarantee, so "top 5" questions were never actually answered from the DB.

### Tool-use agent loop (`agents/chat_tools.py`, `agents/chatbot.py`)
- Added five typed tools in `agents/chat_tools.py`: `get_top_municipalities` (authoritative DB ranking by `final_score`/`geo_score`/`solar_irradiance`/`population`/`pop_density`, ascending or descending, province/region scoped), `get_municipality_profile` (exact-match lookup with lazy re-synthesis preserved from Session 10/11), `compare_municipalities` (2–6 side-by-side), `search_kb` (semantic search over KB narrative — explicitly NOT authoritative for rankings/scores), and `run_sql_query` (read-only escape hatch over `kb/index`'s SQLite DB for counts/aggregates the other tools can't express, with the staleness-rule documented in its schema so the model applies it itself).
- `agents/chatbot.py`'s `chat()` now runs a real tool-use agent loop against MiMo instead of regex intent detection — regex path removed entirely.
- One-time backfill script (`scripts/backfill_chroma_province.py`) added province metadata onto existing ChromaDB intel chunks so `search_kb`'s province filter works on docs indexed before this change.

### Task 7 live verification (this session)
- Full suite: 169 passed, 0 failures.
- Re-ran the original bug's exact query live against MiMo — correctly returned Jolo (0.842), Siasi (0.791), Indanan (0.784), Patikul (0.773), Talipao (0.749), matching the DB exactly, no fabricated scores.
- Ran 6 adversarial queries (ambiguous province, comparison, wrong-metric-not-in-DB, inverse ranking, count/aggregate, multi-turn disambiguation) — 5 behaved correctly; found one real bug: `get_top_municipalities`'s `region` fragment filter uses plain substring matching, so `"Region XI"` also matches `"Region XII (SOCCSKSARGEN)"`, pulling an out-of-region municipality into a Davao-region ranking. Not fixed in this session (verification-only task) — flagged for follow-up.
- Verified live in Streamlit (`app.py`) via browser automation: chat panel round-trips a live query and renders the correct leaderboard, no exceptions in the server log.

#### Files changed (session 12, tasks 1–6, already committed prior to this verification task)
- `agents/chat_tools.py` — new file: five tools + `execute_tool` dispatcher, province/municipality resolvers
- `agents/chatbot.py` — `chat()` rewritten as tool-use agent loop, regex intent detection removed
- `scripts/backfill_chroma_province.py` — new file: one-time ChromaDB province-metadata backfill
- `tests/test_chat_agent_loop.py`, `tests/test_backfill_province.py` — new test files

---

## Session 11 — Map/Legend Polish, Stale Province Reports, Chatbot RAG Fix, Score Transparency (2026-07-12)

### Map legend & marker styling (`app.py`)
- Legend swatches now render as inline HTML `<span>` circles using the exact same hex values as the markers (`TIER_COLORS` dict), instead of emoji — guarantees legend and map colors can never visually drift apart.
- Iterated on the medium-tier color: green/amber were too close to distinguish → tried blue (`#4575b4`) → user rejected, reverted to orange (`#f39c12`) since that was already fine, the real fix was the exact-match legend.
- Removed black marker outline (`weight=1`, `color=color` — border matches fill) per user request; briefly had a dark `#333333` outline, removed it.
- Renamed "Final Score" → "Solar Opportunity Score" everywhere: map legend, drill-down metric label, data table column header. No existing display name existed before this; `final_score` remains the internal DB/field name.
- Fixed `st.dataframe(..., use_container_width=True)` deprecation warning → `width="stretch"` (Streamlit 1.57.0). `st_folium`'s own `use_container_width` param is unrelated — it converts internally to `width=None`, doesn't forward the deprecated kwarg.
- **Selected-municipality map highlight**: draws a dashed blue `CircleMarker` ring (`color="#0000ff"`, `dash_array="4"`, `fill=False`, radius = marker radius + 8) around whichever municipality is currently drilled into. First attempt used `folium.Marker` + emoji `DivIcon`, which unreliably fell back to Leaflet's default pin icon — abandoned for the CircleMarker ring approach, verified via DOM inspection (`path[stroke="#0000ff"]`) that it renders. Note: ring only appears starting the *rerun after* selection, since the map draws before the selectbox updates `session_state` in the same script pass — expected Streamlit behavior, not a bug.

### Stale province reports — root cause + fix (`agents/db_store.py`, `agents/report_gen.py`, `app.py`)
- **Bug found**: `agents/refresh.maybe_refresh_assessment()` (lazy per-municipality re-synthesis) writes a new `run_results` row and re-indexes the KB, but never touches the `reports` table or `reports/*.md` files. Discovered via Daet, Camarines Norte showing 0.774 live in the app vs 0.569 in the downloadable province report (a snapshot from 2026-06-03, before the real-data geo_score fix).
- `db_store.get_latest_scored_municipalities()` extended to also return `solar_irradiance`, `solar_yield_kwh`, `pop_density` (needed for report tables).
- Added `db_store.latest_assessment_time_for_province(province)` — max `runs.completed_at` across current assessments for that province, used to detect staleness.
- Added `db_store.get_score_breakdown(municipality_id)` — every raw + normalized geo/web component and the weights applied (reads `geo_scores` + `web_intel_cache.places_data` + current `run_results`).
- Added `report_gen.regenerate_province_report(province)` — rebuilds the report from live data; municipalities with a current `final_score` are ranked/profiled, others listed in a **"Not Yet Fully Assessed"** section (geo score only, not fabricated/omitted) ending with a 🔄 prompt telling the user they can drill into that municipality to trigger an on-demand re-assessment.
- `app.py` now checks staleness before showing a province report (`latest_assessment_time_for_province(...) > report["created_at"]`) and auto-regenerates if stale.
- Also added `report_gen._score_breakdown_markdown()` / `_full_score_breakdown_section()` — deterministic (non-LLM) per-municipality Geo Score + Web Score component tables (raw, normalized, weight, formula) appended to every province report's "Full Score Breakdown" section, wired into both `regenerate_province_report()` and the original pipeline's `report_gen_agent()`. Mirrors the app's own per-municipality "🧮 Score breakdown" expander so report numbers are guaranteed to match the DB exactly (no LLM paraphrase risk).

### Score transparency in the app (`agents/db_store.py`, `app.py`)
- New "🧮 Score breakdown" expander under each municipality's drill-down: full Geo Score table (Solar Irradiance, Income Class, Population Density — raw/normalized/weight) and Web Score table (Business Density, Price Signal, Rating Signal, Anchor Signal — raw/normalized/weight), each with its formula and final value, plus the Geo→Web→Solar Opportunity Score blend formula.

### Chatbot RAG retrieval fix (`agents/chatbot.py`) — resolves parked issue from Session 10
- **Bug**: `detect_municipality_id()` correctly identifies the exact municipality named in a chat message and triggers `maybe_refresh_assessment()`, but `retrieve_context()` still did pure semantic ChromaDB search over ~29k similarly-worded profile chunks — didn't reliably rank the one exact-name match at the top. Live repro: asking about "Pilar, Abra" got "I do not have a profile for Pilar, Abra" even though it was correctly indexed, because other Pilars (Sorsogon, Surigao del Norte) and other Abra towns out-ranked it semantically.
- **Fix**: added `_exact_municipality_block()` — when `detect_municipality_id()` finds a match, build an authoritative context block straight from the DB row (same source as the map/table: geo score, final score, tier, assessment, opportunity, risk) and prepend it to the retrieved context, instead of relying on ChromaDB ranking alone. Verified: Pilar, Abra now correctly answers 0.723/MEDIUM.

### Map tooltip labeling (`app.py`)
- Hover tooltip on each map marker previously showed only `{name} ({province}) — {final_score:.2f}, {tier}`, unlabeled — unclear whether that number was geo or total score. Now shows a smaller-font (`font-size:11px`), labeled, multi-line HTML tooltip via `folium.Tooltip`: bold name/province line, then `Geo Score: X.XX`, `Web Score: X.XX`, `Solar Opportunity Score: X.XX (TIER)` (or "Not yet fully assessed" if ungeosynthesized). Verified the click-to-drill-down logic (`clicked_tooltip.split(" (")[0]` in the `last_object_clicked_tooltip` handler) still correctly parses the municipality name out of the new HTML tooltip's returned text.

#### Files changed (session 11)
- `app.py` — legend/marker color+styling changes, "Solar Opportunity Score" renaming, `use_container_width` deprecation fix, selected-municipality map ring, score breakdown expander wiring, stale-report auto-regeneration wiring, labeled multi-line map tooltip
- `agents/db_store.py` — extended `get_latest_scored_municipalities()`, added `latest_assessment_time_for_province()`, added `get_score_breakdown()`
- `agents/report_gen.py` — added `regenerate_province_report()`, `_pending_section()`, `_score_breakdown_markdown()`, `_full_score_breakdown_section()`; wired breakdown section into `report_gen_agent()` too
- `agents/chatbot.py` — added `_exact_municipality_block()`, wired into `chat()`

---

## Session 10 — Dataset-First Explorer: app.py Rewrite, Assessment-Staleness Fix, KB Purge (2026-07-12)

Resolves Session 9's WIP pending question — went with option (a): explorer + live RAG chatbot, zero Google Places/Tavily calls, MiMo LLM only.

### Design + plan
- Design spec: `docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md`
- Implementation plan (5 tasks): `docs/superpowers/plans/2026-07-12-dataset-first-explorer.md`
- Executed via subagent-driven-development in an isolated worktree, one fresh subagent per task + task-level review + final whole-branch review.

### Discovered mid-brainstorm: 390 stored assessments predate the real-data fix
- `run_results.assessment` rows are frozen text written when a province was run — but `geo_scores` was recomputed 2026-07-08 with real GEE solar/PSA data. **390 of 1,487** assessed municipalities had their latest run complete **before** that fix, so their assessment prose (which cites specific score values inline) reflects the old fake numbers.
- **Rule adopted**: a `run_results` row only counts as current if `completed_at >= geo_scores.computed_at` for that municipality. Stale rows are treated identically to "never assessed" (not just flagged) — old rows stay in the DB for audit history but are never shown as current.

### New code
- `agents/db_store.py` — `get_latest_scored_municipalities()` (basis-aware dedup, one row per municipality, current-only assessment fields) and `get_latest_report_for_province()`.
- `agents/refresh.py` (new module) — `maybe_refresh_assessment(municipality_id)`: lazy, on-demand re-synthesis using only the MiMo LLM (`agents.synthesis.synthesize_municipality`) — never calls Google Places/Tavily. Only acts if a `web_intel_cache` row already exists for the municipality (any age); otherwise stays geo-only. Persists the fresh result as a new `run_results` row, regenerates the muni's `kb/intel` doc, deletes the superseded old one, and re-indexes into ChromaDB.
- `scripts/purge_stale_kb_docs.py` (new, one-time) — removes stale-basis municipality docs from both ChromaDB (`kb/index/`) and disk (`kb/intel/*.md`), using a single shared `_doc_key_matches_stale()` predicate so the two deletions can't drift apart. Matches require the muni-slug segment AND a plausible location relationship (province-slug match or muni-slug substring in the location segment) — avoids over-matching same-named municipalities in different provinces (e.g. multiple "San Isidro"). Defaults to `--dry-run`; run as `python -m scripts.purge_stale_kb_docs [--execute]` (not `python scripts/...py` — needs `-m` so `config` resolves).
- `agents/chatbot.py` — `detect_municipality_id(message, municipalities)` (longest-name match) + wired into `chat()`: if a message names a municipality, triggers `maybe_refresh_assessment` before answering. `maybe_refresh_assessment` is re-exported from `chatbot.py` as a thin wrapper with the import deferred to call time (breaks a circular import with `agents/refresh.py`, which imports `index_documents_from_kb` from `chatbot.py` at module load).

### `app.py` full rewrite
- Dropped entirely: `run_pipeline` import, background-thread pipeline runs, the `precompute_geo_scores` trigger, "Run a new province" UI, Admin page, Past Runs page. `graph/pipeline.py` and the individual pipeline agents are untouched in the codebase (still used by `scripts/run_all_provinces.py`).
- New layout: national Folium map (current-assessed colored by `final_score`, needs-synthesis municipalities shown muted/gray, not hidden) + province filter/table + drill-down (triggers `maybe_refresh_assessment`) + province report viewer + persistent "Ask Helio" sidebar chat.

### Real KB purge executed (production data)
- Backed up `kb/index/` → `kb/index.bak-20260712-pre-purge` (287M) before running.
- Dry-run confirmed 390 stale municipalities → 5,560 ChromaDB chunks + 568 `kb/intel/*.md` files.
- Executed `--execute`: deleted all of the above. Re-ran dry-run afterward — 0 remaining matches, confirmed clean.

### Manual smoke test (real data, streamlit on port 8502 to avoid an unrelated pre-existing process on 8501)
- Map loaded with real markers, correct coloring/muting. Drilled into Sumisip (previously "needs synthesis") — `maybe_refresh_assessment` generated a real fresh assessment (Final Score 0.758, MEDIUM) using cached web intel, zero new API calls; confirmed persisted to `data/helio.db` as a new `refresh_*` run superseding the 2026-06-03 pre-fix one. Report viewer and chat both worked, no console/server errors.
- **Chat RAG relevance note (parked, not a bug)**: asking the chatbot about Sumisip right after refreshing it got a "not enough data" answer even though the fresh doc was indexed — pure semantic search over ~29k largely similarly-worded municipality-profile chunks doesn't reliably surface the exact named entity. **Follow-up idea**: `detect_municipality_id()` already identifies the exact municipality before answering — use that to filter/boost `retrieve_context`'s ChromaDB query by municipality metadata instead of relying on pure semantic similarity. Cheap, reuses existing infrastructure. A general hybrid (dense+BM25) retrieval system would be a bigger, more speculative lift — not needed for this specific problem.

### Process notes
- The worktree for this feature was created from `origin/main` (stale — 6 commits behind local `main`, missing the Session 9 real-data-pipeline commit and fixes). Verified via `git diff` that none of the diverged commits touched functions this feature depends on before merging `main` into the branch and re-testing. **Lesson: check `git merge-base` against local `main` (not just origin) right after creating a worktree**, not after the fact.
- Rewrote all 18 unpushed local commits (`git filter-branch --msg-filter`) to drop the `Co-Authored-By: Claude` line per user request — safe since none were pushed yet.
- Final state: `main` fast-forwarded to the feature branch tip, 139/139 tests passing, worktree removed (all commits merged, nothing lost).

#### Files changed (session 10)
- New: `agents/refresh.py`, `scripts/purge_stale_kb_docs.py`, `scripts/__init__.py`, `docs/superpowers/specs/2026-07-12-dataset-first-explorer-design.md`, `docs/superpowers/plans/2026-07-12-dataset-first-explorer.md`, `tests/test_refresh.py`, `tests/test_purge_stale_kb_docs.py`, `tests/test_chatbot_refresh.py`, `tests/test_db_store.py` (additions).
- Modified: `app.py` (full rewrite), `agents/db_store.py` (+2 functions), `agents/chatbot.py` (municipality detection + refresh wiring).
- Data: `kb/index/` purged (390 municipalities' stale docs removed), `kb/intel/*.md` (568 stale files deleted), backup at `kb/index.bak-20260712-pre-purge`.

---

## Session 9 — Real Solar Data, 33 Missing HUCs, Full National Coverage, Dataset Export (2026-07-08 → 2026-07-12)

### ⚠️ WIP — Helio overview document (brainstorming in progress, resume here)
- User asked for a standalone MD doc describing Helio, the datasets used/built, and their locations. **Not a PRD** (that's pre-build) — agreed framing: project overview + dataset catalog + forward-looking roadmap section.
- Decisions made so far: **(1) Audience = general public / portfolio-grade** (recruiter/collaborator on GitHub should get it without running anything). **(2) Include the data-integrity journey** (fake→real data audit story) as a credibility section, not appendix.
- **Pending question (user paused to clear thread)**: shape of the future dataset-first app — options presented were (a) explorer + live RAG chatbot [recommended], (b) pure read-only explorer, (c) cache-first with opt-in refresh button, (d) leave open. User's driver: **no more Google Places/Tavily API calls** — spent ~$50 total; wants Helio to run off the built dataset and become "a useful app".
- Brainstorming skill flow active: after the pending question → propose doc structure → write doc → (spec self-review) → user review. Suggested location when written: repo root `HELIO.md` or `docs/` (not yet decided).

### Solar data was 100% synthetic — root cause + fix (`scripts/precompute_geo_scores.py`)
- **All 1,622 solar_irradiance values matched `_stable_float(f"{name}:solar", 4.5, 6.0)` exactly** (MD5 reproduction test). Session-8 note "GEE precompute IS done" was wrong — 0 NULLs only meant an old script filled fakes.
- Root cause: `reduceRegions` names its output after the **reducer** (`mean`/`max`), not the band — reading `surface_solar_radiation_downwards_sum` returned null for every feature, so everything fell back to hash values; resume logic (`_load_existing_solar`) then treated any non-NULL as real forever.
- Fixed: 3-pass fetch (exact point → 11 km `Reducer.max()` → 25 km max; buffered *mean* near water reads absurdly low — lakeside Biñan 1.63 vs true ~5.0 due to ERA5-Land water-fringe pixels). Synthetic/estimated values are **never persisted** to `solar_irradiance` (stored NULL); ~31 unmappable islets score at **province mean** of real values (not a hash lottery). GEE fetch now uses DB coordinates (`_load_db_coords`), not hash placeholders.
- Result: 1,624/1,655 (98.1%) real GEE solar; mean 4.97 ± 0.25, range 4.44–5.63; correct gradient (Ifugao 4.55 < Ilocos 5.17 < Tawi-Tawi 5.63). Backup: `data/helio.db.bak-20260708-pre-gee-solar`.

### Coordinates: 98 municipalities were in the Sibuyan Sea
- CAR provinces (Abra/Apayao/Benguet/Ifugao/Kalinga/Mountain Province), "City of Manila", "Special Geographic Area" were missing from `PROVINCE_CENTROIDS` → (12.5, 122.5) sea default. Centroids added to both `agents/geo_scoring.py` and precompute.
- New `scripts/geocode_all_municipalities.py` — Nominatim-geocodes every municipality (fallback = corrected hash placeholder), persists to DB. Cache poisoning purged twice (baked-in fallbacks).

### 33 missing Highly Urbanized Cities (Quezon City, Makati, Cebu City, Davao City, …)
- In the `barangay` package HUCs sit at province level with a flat barangay **list**; every `isinstance(prov_data, dict)` check skipped them. Now single municipalities under `"<Name> (Not a Province)"` pseudo-provinces (package's own Isabela City convention). 1,622 → **1,655** municipalities.
- Geocoder was silently broken for all 34: pseudo-province text in the query → zero results → hash fallback (caught because Isabela City landed 1,100 km away in Luzon). Fixed in `agents/geocoder.py`; naive strip produced duplicated queries matching random businesses — province term dropped when it collapses to the name. 4 ambiguous names (Puerto Princesa, Bacolod, Zamboanga, Lapu-Lapu) hand-set from verified reference coords.
- **HUC fuzzy-match incident during batch runs**: `"City of Cebu (Not a Province)"` fuzzy-matched to Cebu *province* (50 munis), CDO to Cagayan province (wrong island), Iloilo to Iloilo province — burned ~120 wrong Places calls before caught mid-run. Fixed by indexing HUCs under both bare and pseudo-province names (exact match beats fuzzy); bad runs + reports + 1,188 Chroma chunks deleted, 3 cities re-run. Tests: `tests/test_geo_scoring_huc.py`.

### Fix #2 — real land area + pop_density normalization
- `scripts/fetch_land_area.py`: geoBoundaries ADM3 polygons (NAMRIA/PSA/OCHA, CC BY 3.0 IGO), true geodesic area via `pyproj.Geod`, matched **point-in-polygon** against real geocoded coords (114/1,647 shapes share names; name-matching unsafe). 1,655/1,655 matched. Output: `data/raw/municipality_land_area.csv`.
- `normalize_and_score()` now `log1p`-transforms pop_density before MinMax. pop_density_norm mean 0.013 → **0.381** (was 96% below 0.05 → 0.4%). Bacoor (fake 23 km² outlier, old #1) → #213; new national #1 = Jolo, Sulu (real 3.0 km², 51,406/km²).

### Full national pipeline coverage — 118/118 province/HUC groupings
- Ran in 5 user-checkpointed batches (billing checks between): 34 HUCs → Albay+Cebu/Iloilo/Palawan/Pampanga/Pangasinan → Davao/Cotabato cluster → Zamboanga/Surigao/Sulu/Tawi-Tawi/SGA → final 13. Albay needed a direct run (stale `province='Albay'` done-flag from an old 3-town run would've made `run_all_provinces.py` skip it).
- `run_all_provinces.py` now sources provinces from **helio.db** municipalities (was `ph_locations.db` via location_db — predates HUC fix, missing all 33).

### PSA footnote + geocoder formal-name fixes (fabricated data 44 → 31 rows)
- PSA appends `*` to reclassified LGUs (`"4th*"`) — broke exact match for 6 real municipalities (Tipo-Tipo, Mankayan, Alfonso Castaneda, Arteche, Lugait, Sultan Sa Barongis). Fixed: strip trailing non-alphanumerics in `_load_psa_lookup`.
- Geocoder retries: strip `"City of "` (both name and province position — "City of Candon" fails, "Candon" resolves; "Binondo, City of Manila" fails, "Binondo, Manila" resolves), honorifics (`Pres./Sen./Gen./Dr.`), `Tondo I/II`→`Tondo` override. Recovered 7/16 fabricated coords.
- **Remaining fabricated (documented, structural)**: 22 income/population (Manila's 14 districts + 8 BARMM SGA barangays — PSA doesn't classify below municipality level) + 9 coordinates (8 SGA + Don Victoriano Chiongbian, deliberately not auto-truncated). Decision context: user asked about NULL vs 0 vs median — 0 rejected ((0,0) is in the Gulf of Guinea; pop 0 = false worst-case claim); median acceptable for scoring if labeled imputed.

### Alphabetical top-20 selection bug (the "arbitrary 20")
- `web_intel_agent` did `list(geo_scores.keys())[:TOP_N_TARGETS]` on a dict in DB row order (= alphabetical insertion order) — "top 20" meant "first 20 alphabetically" in **all 33 provinces with >20 municipalities**. Synthesis sorted only survivors, so output looked ranked. Cavite's two worst (0.41) got paid evaluation; true #13–14 (Silang/Tanza ~0.72) never evaluated anywhere.
- Damage: 169 true-top-20 municipalities never evaluated; 172 wasted slots. Fix: sort by geo_score desc before truncating (`agents/web_intel.py` + regression test).
- Correction: 33 provinces re-run (~$3.60 fresh calls, rest cached). Long background jobs kept getting **killed** (3×) → self-healing 4-province chunk script (recomputes "latest run ≠ true top-20" each invocation; kill costs ≤1 in-flight province; mark stuck `running` row failed and relaunch). Verified: 0/33 mismatched, all 660 true-top-20 slots assessed. 56 old-formula (0.80/0.20-era) run_results rows from 5 day-one legacy runs deleted.

### Dataset export + data dictionary (committed to repo)
- `exports/helio_full_dataset.csv` — 1,655 rows, 20 columns; 1,487 with full AI assessment, 168 geo-only (genuinely below province top-20, by design).
- `exports/helio_dataset_data_dictionary.csv` — per-field definition / basis / source, including honest caveats: area_km2 is **GIS-calculated geodesic area, NOT official PSA/DENR legal area** (Gemini critique incorporated; ~5–20% deviation, worst in mountains; but its UTM-projection critique didn't apply — we use ellipsoidal geodesic, not flat projection), fabricated-row counts, LLM-generated fields flagged.
- User's Google Places spend to date: **~$50 total** — motivates the dataset-first pivot. Future enhancement saved in memory: below-top-20 full coverage ≈ $2.80 (don't run unprompted).

#### Files changed (session 9)
- `scripts/precompute_geo_scores.py` — reduceRegions property fix, 3-pass fetch, solar_synthetic non-persistence, province-mean fallback, DB coords, HUC enumeration, PSA asterisk strip, area lookup, log1p
- `agents/geo_scoring.py` — HUC support (pseudo-provinces, dual indexing), CAR/Manila/SGA centroids
- `agents/geocoder.py` — pseudo-province strip, City-of/honorific candidates, Tondo override, multi-candidate retry
- `agents/web_intel.py` — top-20 sorted by geo_score before truncation
- `agents/db_store.py` — UNIQUE(name, province) in schema (session-8 carryover, committed now)
- `scripts/fetch_psa_data.py`, `scripts/fetch_land_area.py`, `scripts/geocode_all_municipalities.py`, `scripts/run_all_provinces.py` — new
- `tests/test_geocoder.py`, `tests/test_geo_scoring_huc.py` — new; `tests/test_precompute.py`, `tests/test_web_intel_db.py` — extended. **115 tests passing.**
- `exports/helio_full_dataset.csv`, `exports/helio_dataset_data_dictionary.csv` — new, committed
- Git: committed as `819ec5c6` (dataset), `392985ed` (pipeline), `fe6ec0d3` (HUC+geocoder), `9ef3db9d` (top-20 fix), `d31c9980` (chore). Local only, no remote.

---

## Session 8 — DB Audit, Duplicate Municipality Fix, Bulk Province Run Script (2026-07-07)

### Branch
`main`

### DB Audit Findings (`data/helio.db`)
- 68 runs total (67 `done`, 1 stale `running`), 862 `run_results`, 64 reports, 722 `web_intel_cache` rows.
- `geo_scores.solar_irradiance` is fully populated (0 NULLs / 1,622 rows) — GEE precompute had actually already been run; prior memory saying it was pending was stale and has been corrected.
- Province coverage: only 51 of 85 provinces had a completed run as of this session. 35 provinces never run (Abra, Cebu, Cotabato, Davao Oriental/de Oro/del Norte/del Sur, Dinagat Islands, Eastern Samar, Ifugao, Iloilo, Occidental/Oriental Mindoro, Palawan, Pampanga, Pangasinan, Quirino, Romblon, Samar, Sarangani, Siquijor, Sorsogon, South Cotabato, Southern Leyte, Special Geographic Area, Sultan Kudarat, Sulu, Surigao del Norte/del Sur, Tarlac, Tawi-Tawi, Zambales, Zamboanga Sibugay/del Norte/del Sur).

### Duplicate Municipality Rows Bug (`agents/db_store.py`)
- **Bug**: `municipalities` table had no `UNIQUE` constraint on `(name, province)`. `complete_run()` used `INSERT OR IGNORE INTO municipalities (name, province, ...)` expecting dedup, but without the constraint `OR IGNORE` was a no-op — every run silently inserted a fresh duplicate row per municipality touched. Table had grown to 2,428 rows for only 1,622 real municipalities (806 orphan duplicates, worst case Camiguin municipalities ×6 rows each).
- **Verified safe to delete**: confirmed via join that all `run_results` and `web_intel_cache` rows pointed only at the canonical (`geo_scores`-linked) row — 0 references to the duplicate rows.
- **Fix applied**:
  1. Backed up DB to `data/helio.db.bak-20260707` before any changes.
  2. `DELETE FROM municipalities WHERE id NOT IN (SELECT municipality_id FROM geo_scores)` — removed the 806 orphans.
  3. Added `CREATE UNIQUE INDEX idx_municipalities_name_province ON municipalities(name, province)` to the live DB and to `_create_schema()` in `agents/db_store.py` so fresh DBs and future runs get the constraint (making `INSERT OR IGNORE` actually work going forward).
- Post-fix: 1,622 municipality rows (matches reference `ph_locations.db` exactly), 0 rows with NULL lat/lon.

### Stale Stuck Run Cleanup
- `runs` row `7bca67a6` (Capiz, created 2026-06-04) was stuck in `status='running'` for a month with 0 `run_results` — an abandoned/crashed attempt. Capiz was successfully re-run twice afterward under different run_ids (`c9b8709a`, `a86f0e3e`), so no data was lost. Marked `status='failed'` with an explanatory `error` message rather than deleted.

### Bulk Province Run Script (new)
- Added `scripts/run_all_provinces.py` — iterates provinces missing a `done` run and calls the same `create_run` → `run_pipeline` → `complete_run`/`fail_run` path `app.py` uses, so results land in `data/helio.db` and show up in the Streamlit app immediately.
- Resumable: re-checks `runs.status='done'` per province before running, safe to Ctrl+C and restart.
- Flags: `--dry-run` (list only, no API calls), `--delay N` (seconds between provinces, default 5), `--provinces "Cebu,Iloilo"` (run a specific subset instead of all missing ones).
- Must run with `PYTHONPATH=.` — e.g. `PYTHONPATH=. python scripts/run_all_provinces.py`.
- Dry-run verified: correctly lists 35 missing provinces.
- ⚠️ **Needs to be run**: user plans to run this tomorrow (2026-07-08) to build the complete national dataset across all 85 provinces. Watch Tavily/Google Places API quota across a run this size — consider `--delay` bump or splitting into batches via `--provinces` if rate-limited.

### Real PSA Income + Population Data Integration
- **Goal**: replace hash-based synthetic income class (45% of geo_score weight) and population (20% weight) with real PSA data — previously ~65% of geo_score weight was fabricated.
- **PSA's own site blocks scraping**: `psa.gov.ph` returns 403 (Cloudflare) on direct `.xlsx` downloads — not automatable.
- **Source used instead**: `yng-me/psgc` (GitHub, MIT license) — an R package bundling real PSA PSGC publication data (income classification + census population for 2015/2020/2024). Extracted its `R/sysdata.rda` in pure Python via the `rdata` library — no R install needed.
- **New**: `scripts/fetch_psa_data.py` — downloads/caches `data/raw/psgc_sysdata.rda`, extracts the Q1 2026 release + 2024 population, writes `data/raw/psa_income_population.csv` (psgc_code, name, province, income_classification, population_2024). `--refresh` flag re-downloads.
- **Bug found + fixed**: PSGC code layout is 2-digit region + 3-digit province + 3-digit muni + 2-digit barangay. First draft used `psgc_code[:4]` for province prefix (one digit short) — silently collided provinces within the same region (Aklan and Antique, both region 06, both got prefix `0600`, corrupting province attribution for every municipality in region 06+). Fixed to `psgc_code[:5]`.
- **`scripts/precompute_geo_scores.py`** (`_get_all_municipalities()`) now loads the PSA CSV via new `_load_psa_lookup()` / `_match_psa_record()`, exact-matches by (name, province), rapidfuzz fallback (cutoff 85) within-province, else falls back to the old hash-based synthetic. **Match rate: 1,599/1,622 (98.6%)**. The 23 unmatched are `barangay`-package quirks (Manila's districts modeled as pseudo-municipalities, BARMM "Special Geographic Area" barangays, "City of Isabela (Not a Province)") — not real PSA gaps.
- **Near-miss caught**: `upsert_to_db()` was unconditionally overwriting `municipalities.lat/lon` with hash-based placeholder coords on every precompute run — would have clobbered the real Nominatim-geocoded coordinates fixed earlier (session 6/7 and this session's dedup). Fixed: lat/lon now only set on INSERT (new rows); UPDATE path (existing rows) leaves lat/lon untouched.
- **Ran the full precompute** with real data — all 1,622 `geo_scores` rows recomputed. Verified after: row count still 1,622, 0 NULL lat/lon, `City of Biñan` kept its real coords (14.3388, 121.0842).
- **Interesting real finding**: 46% of municipalities (749/1,622) are now PSA-classified "1st class" income — verified against raw CSV, not a bug. Likely reflects RA 11964's 2023+ income-bracket reclassification.
- `data/helio.db.bak-20260707-pre-psa` — second backup, taken before the precompute run.
- New dependency: `rdata>=0.11.2` in `requirements.txt`.
- ⚠️ **Still synthetic**: `area_km2` — PSA source has no land-area column, so `pop_density` = real population ÷ fake area.

#### Files changed (session 8)
- `agents/db_store.py` — added `UNIQUE(name, province)` index to `municipalities` schema
- `scripts/run_all_provinces.py` — new bulk-run script
- `scripts/fetch_psa_data.py` — new, downloads/extracts real PSA income+population data
- `scripts/precompute_geo_scores.py` — consumes PSA CSV for real demographics; fixed lat/lon clobber bug
- `requirements.txt` — added `rdata>=0.11.2`
- `data/raw/psgc_sysdata.rda`, `data/raw/psa_income_population.csv` — new, fetched PSA data
- `data/helio.db` — deduped (806 rows removed), stale run marked failed, geo_scores recomputed with real PSA data
- `data/helio.db.bak-20260707` — pre-dedup backup
- `data/helio.db.bak-20260707-pre-psa` — pre-PSA-precompute backup

---

## Session 7 — KB Indexing Performance, Municipality Slug Bug & Nav Failure Fix (2026-06-05)

### Branch
`main`

### ChromaDB Indexing Performance (`agents/chatbot.py`)
- **Bug**: `collection.get()` with no `include` param was loading full document text + embeddings for all chunks on every call — just to build a set of IDs for the skip check. With 8,800+ chunks this was slow.
- **Fix**: Changed to `collection.get(include=[])["ids"]` — returns IDs only, no document bodies or embeddings.
- **Bug**: `index_documents_from_kb()` was called at the top of `chat()` — every single chat message triggered a full KB scan over all chunks and all reports.
- **Fix**: Removed the call from `chat()` entirely. `update_kb_node` (end of pipeline) is the correct and only trigger. Chatbot picks up new data after the pipeline run completes.

### Municipality Slug Sanitization Bug (`agents/kb_builder.py`)
- **Bug**: Municipality names containing `/` (e.g. "Tondo I/II") were used directly in file paths — `/` became a directory separator, creating a nested path `kb/intel/city_of_manila__tondo_i/ii__<run_id>.md` instead of a flat file. Caused `[Errno 2] No such file or directory` crashing KB update for City of Manila.
- **Fix**: Added `.replace("/", "_")` to `muni_slug` sanitization in `save_municipality_docs()`. "Tondo I/II" → `tondo_i_ii`.

### `nav_page` Session State Fix — Runs Falsely Marked as Failed (`app.py`)
- **Root cause**: `st.radio(..., key="nav_page")` made the widget own `st.session_state.nav_page`. After pipeline completion, `st.session_state.nav_page = "🗺️ Map & Scores"` raised `StreamlitAPIException: st.session_state.nav_page cannot be modified after the widget with key nav_page is instantiated`. This exception was caught by `except Exception as exc:` → `db_store.fail_run(run_id, ...)` — so even successful pipeline runs got marked `failed` in DB.
- **Fix**: Removed `key="nav_page"` from `st.radio`. Instead: initialized `st.session_state.nav_page` before the widget using `if "nav_page" not in st.session_state`, passed `index=_NAV_OPTIONS.index(st.session_state.nav_page)` to `st.radio`, and synced back with `st.session_state.nav_page = page` after widget renders. `nav_page` is now a plain session state key, not widget-owned.

### Failed Runs Made Clickable (`app.py` + DB)
- Three runs (City of Manila, City of Isabela ×2) were stuck as `status='failed'` in DB due to the `nav_page` bug above — but their reports and `run_results` were fully intact.
- **DB patch**: `UPDATE runs SET status='done', error=NULL WHERE status='failed'` — all 3 corrected.
- **Sidebar**: Removed `if run["status"] == "failed": continue` guard from Past Runs sidebar. `list_runs()` already uses `INNER JOIN reports` so only runs with actual data appear — the join is the real guard, not the status check.

### Pipeline Completion Notifications (terminal + UI)

- **Terminal**: Added `logger.info("[Agent 5] KB indexing complete — pipeline finished.")` at end of `update_kb_node` success path — fires after all chunks are indexed, confirming pipeline is truly done.
- **Terminal**: Added `print(f"[helio] Pipeline complete: {location_str} — {top_count} targets scored.")` in `app.py` after `run_pipeline` returns — visible in the Streamlit process terminal.
- **UI**: Replaced `st.spinner(...)` with `st.status(..., expanded=True)` in the pipeline run block:
  - Shows `⚙️ Scoring municipalities (geo + web intel)...` while running
  - Appends `📚 Knowledge base indexed.` once KB step completes
  - Collapses to `✅ Analysis complete — N targets scored.` (`state="complete"`) on success
  - Collapses to `⚠️ Done with N warning(s) — N targets scored.` (`state="error"`) on partial errors
  - Exception path: `status.update(label=..., state="error")` + `st.error()`
- `st.rerun()` still fires after status update → navigates to Map & Scores, remounts map via `key=f"map_{current_run_id}"`

#### Files changed (session 7)
- `agents/chatbot.py` — `collection.get(include=[])` for ID-only fetch; removed `index_documents_from_kb()` from `chat()`; added KB-done terminal log in `update_kb_node`
- `agents/kb_builder.py` — `.replace("/", "_")` added to `muni_slug` sanitization
- `app.py` — `nav_page` widget → plain session state pattern; removed failed-run `continue` skip in sidebar; `st.spinner` → `st.status` with live stage labels; `print()` terminal completion signal

---

## Session 6 — Web Intel Resilience, Map Accuracy, Responsive UI & Pipeline Notifications (2026-06-05)

### Branch
`feat-geo-scoring`

### Web Intel: Tavily → DuckDuckGo Fallback (`agents/web_intel.py`)
- Combined 4 separate Tavily queries per municipality into 1 comprehensive query: `"economic development businesses real estate solar energy {place} Philippines 2024 2025"` — cuts Tavily usage 75%
- Added `_tavily_rate_limited` session-level flag; flips to `True` on first rate-limit/usage-limit error, stays True for rest of session
- Added `_search_ddg()` using `ddgs>=9.0.0` package (was `duckduckgo_search` — upstream renamed it)
- Terminal output: `[Tavily] query…` at INFO level (was DEBUG, invisible) and `[DDG] query…` at INFO on fallback
- `gather_intel_for_municipality` now logs `via Tavily` or `via DDG` per municipality fetch

### Map Circle Placement — Root Cause & Fix (multiple files)
Four compounding bugs, all fixed:

1. **`agents/db_store.py` `complete_run`**: was saving `NULL, NULL` for lat/lon (`VALUES (?, ?, ?, NULL, NULL, NULL, ...)`). Fixed: now passes `t.get("lat"), t.get("lon")` from top_targets. Added backfill UPDATE for rows where lat/lon were previously NULL.
2. **`agents/geo_scoring.py` DB path**: `_load_scores_from_db()` was never calling `geocode_units()` — used hash-based fake coordinates from precompute script. Fixed: DB path now calls `geocode_units()` after loading scores, updates `municipalities` table with real Nominatim coordinates permanently.
3. **`agents/db_store.py` `load_run`**: never returned `geo_geojson` — map showed no circles for any loaded past run. Fixed: `load_run` now selects `m.lat, m.lon`, rebuilds GeoJSON FeatureCollection, returns `geo_geojson` key.
4. **`agents/synthesis.py`**: `lat`/`lon` were present in `geo_scores` but dropped when building `top_targets`. Fixed: added `"lat": geo.get("lat")` and `"lon": geo.get("lon")` to `final_scores` dict.

Note: `agents/geocoder.py` already existed with Nominatim + persistent file cache at `data/processed/municipality_coords.json` — the gap was the DB path never calling it.

### Map Auto-Zoom (`app.py`)
- Map now centers on centroid of top_targets lat/lon — was hardcoded `[12.5, 122.5]` zoom 7 (whole Philippines)
- Calls `m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]], padding=[40, 40])` after all markers are added
- `st_folium` now uses `use_container_width=True` (was fixed `width=700`, caused overflow in narrower layout)

### Responsive Sidebar Metrics (`app.py`)
- Replaced `st.columns(4)` with `st.metric` calls → custom HTML `_bans()` helper at top of `app.py`
- CSS `clamp(0.55rem, 1.1vw, 0.75rem)` for labels, `clamp(0.85rem, 1.8vw, 1.25rem)` for values — scales across laptop to wide monitor
- Layout: 2×2 grid (2 rows of 2 flex cards), `min-width: 0` prevents flex overflow, `text-overflow: ellipsis`
- Outer column ratio changed `[3, 2]` → `[3, 2.5]` to widen the sidebar panel

### Requirements
- `duckduckgo_search>=8.0.0` → `ddgs>=9.0.0` (upstream package rename)

### Pipeline Re-run Behaviour (what updates vs. what's cached)
| Component | On re-run | Reason |
|---|---|---|
| Coordinates | Updated once, then cached | `geocode_units()` → Nominatim → writes to DB + `municipality_coords.json` permanently |
| Web snippets | Updated if 30-day TTL expired | `web_intel_cache` table TTL = `WEB_INTEL_CACHE_TTL_DAYS` (default 30) |
| Assessment / Opportunity / Risk | Always regenerated | Synthesis agent runs LLM every pipeline run, no caching |
| Report markdown | Always regenerated | `report_gen` agent re-generates every run |
| Geo scores (solar, income, pop density) | Reused from DB | Precomputed — no GEE call on re-run |

To force-refresh web intel for a province (bypass TTL cache):
```bash
sqlite3 data/helio.db "DELETE FROM web_intel_cache WHERE municipality_id IN (SELECT id FROM municipalities WHERE province LIKE '%Camiguin%');"
```

### Map Refresh & Pipeline Completion Notification (`app.py`)

Two bugs fixed / features added in the same session (continuation):

#### Map Stale Render Fix
- **Bug**: `st_folium(m, ...)` had no `key` parameter — Streamlit never remounted the component between runs, so the map showed the previous province's circles after a new pipeline run.
- **Fix**: Added `key=f"map_{st.session_state.current_run_id}"` to `st_folium(...)` call. `current_run_id` is a UUID set on every new run and on every past-run load, forcing a full component remount each time.

#### Pipeline Completion Notification + Auto-Navigate
- **Feature**: After pipeline completes, app now auto-navigates to the Map & Scores page and shows a toast notification.
- **Implementation**:
  - `st.radio("Navigate", [...], key="nav_page")` — bound the sidebar radio to `st.session_state.nav_page` so it can be set programmatically
  - After `run_pipeline` succeeds: sets `st.session_state.nav_page = "🗺️ Map & Scores"`, fires `st.toast(...)`, then `st.rerun()`
  - `st.rerun()` is placed **outside** the `with st.spinner()` block using a `should_rerun` flag — calling it inside the spinner can cause teardown issues
  - Clean run toast: `"☀️ Analysis complete — {N} targets scored."` with `✅` icon
  - Partial-error path toast: `"⚠️ Completed with {N} warning(s). {N} targets scored."` with `⚠️` icon — uses `st.toast` (not `st.warning`) so notification survives the `st.rerun()`
  - Exception/failure path: unchanged — stays on current page, shows `st.error`

### Branch Merged
- `feat-geo-scoring` merged to `main` via fast-forward after all 89 tests passed on both branches.
- Branch deleted locally (was never pushed to origin).

### ⚠️ Next session
- Municipalities in DB from runs BEFORE session 6 still have hash-based (fake) lat/lon. On next pipeline run for that province, `geocode_units()` will replace them automatically. No manual migration needed — it's lazy/automatic.
- Nominatim geocoder file cache (`data/processed/municipality_coords.json`) has 88 entries; grows as new provinces are run.
- GEE precompute (`scripts/precompute_geo_scores.py`) still not run with real auth — `geo_scores.solar_irradiance` still NULL in live DB; live runs fall back to synthetic solar data.

#### Files changed (session 6 — full list)
- `agents/web_intel.py` — combined query, DDG fallback, INFO-level provider logging
- `agents/db_store.py` — `complete_run` saves lat/lon; `load_run` selects lat/lon + returns `geo_geojson`
- `agents/geo_scoring.py` — DB path calls `geocode_units()`, writes real coords to DB
- `agents/synthesis.py` — `lat`/`lon` added to `final_scores`/`top_targets`
- `app.py` — `_bans()` responsive metric cards, map auto-zoom + `fit_bounds`, `use_container_width`, column ratio `[3, 2.5]`; `st_folium` run-scoped key; `nav_page` session state binding; `should_rerun` flag pattern; toast notifications on pipeline completion
- `requirements.txt` — `ddgs>=9.0.0`
- `docs/superpowers/specs/2026-06-05-map-refresh-and-pipeline-notification-design.md` — feature spec
- `docs/superpowers/plans/2026-06-05-map-refresh-and-pipeline-notification.md` — implementation plan

---

## Session 5 — Score Transparency, GEE Precompute & Past Runs Page (2026-05-30)

### Branch
`feat-geo-scoring` (off `main`) — 6 commits, 89 tests passing

### DB Migration (`agents/db_store.py`)
- `_migrate()` now adds 3 nullable columns to `run_results` (idempotent `ALTER TABLE IF NOT EXISTS` pattern):
  - `solar_irradiance REAL` — raw irradiance in kWh/m²/day
  - `solar_yield_kwh REAL` — annual yield: `solar_irradiance × 365 × 0.80`
  - `pop_density REAL` — people/km²
- `complete_run()`: writes all 3 new columns from each `top_targets` entry (via `t.get()`)
- `load_run()`: SELECT now includes `rr.solar_irradiance/solar_yield_kwh/pop_density` + LEFT JOIN `geo_scores g ON g.municipality_id = rr.municipality_id`; fallback chain: `rr.solar_irradiance or g.solar_irradiance or 5.0`; `solar_yield_kwh` recomputed if NULL
- `list_runs()`: changed from `LEFT JOIN run_results` to `INNER JOIN reports rep ON rep.run_id = r.id` (only returns runs with saved reports); default `limit` changed from 20 → 1000

### Synthesis Agent (`agents/synthesis.py`)
- `final_scores[municipality]` dict now includes 3 new keys:
  - `"solar_irradiance": geo.get("solar_raw", 5.0)`
  - `"solar_yield_kwh": round(geo.get("solar_raw", 5.0) * 365 * 0.80, 0)`
  - `"pop_density": geo.get("pop_density", round(geo.get("population_raw", 0) / 500, 1))` — fallback divides population by 500 (midpoint area estimate)

### Report Prompt (`agents/report_gen.py`)
- `REPORT_PROMPT` now includes a `## Score Breakdown` section after `## Top Target Areas`:
  - Table columns: `Municipality | Irradiance (kWh/m²/day) | Income Class | Pop Density (ppl/km²) | Annual Yield (kWh/kWp) | Final Score`

### App UI (`app.py`)
- **Map popup** (was `"<b>{name}</b><br>Score: {score:.3f}"`): now rich HTML showing Final Score, Tier, ☀ Irradiance, 📈 Income class, 👥 Population, ⚡ Yield with 5 kWp concrete example (`yield_kwp * 5`); `max_width=260`
- **Map tooltip**: changed from `"{name}: {score:.3f}"` → `"{name}: {score:.3f} | {irr:.1f} kWh/m²/day"`
- **Sidebar expander** (was single `st.metric("Est. Annual Solar Yield"...)`): replaced with 4-column metrics grid — `c1.metric("☀ Irradiance")`, `c2.metric("📈 Income")`, `c3.metric("👥 Population")`, `c4.metric("⚡ Yield")`; LLM assessment/opportunity/risk text follows below
- **Nav radio**: added `"📚 Past Runs"` option (5th page)
- **Past Runs page** (new `elif page == "📚 Past Runs":` block):
  - Fetches `db_store.list_runs(limit=1000)` once; paginates client-side at 20/page
  - `st.session_state.runs_page` (int, default 0) tracks current page
  - Expander header: `"{location} · {date} · {count} targets · top {score} {tier_icon}"`
  - Expander body: `db_store.load_run(run_id)` lazily, `st.markdown(report_markdown)`, download button if `report_path` set
  - Pagination: `← Previous` / `Next →` buttons (disabled at boundaries), `"Page N of M"` centered between them

### Precompute Script (`scripts/precompute_geo_scores.py`)
- **`_init_gee()`** (new): initialises GEE via `ee.Initialize(project=config.GEE_PROJECT_ID)`; returns `ee` module or `None`
- **`fetch_gee_irradiance_batch(ee, units)`** (new): builds `ee.FeatureCollection` of buffered points (11 km radius), calls `ECMWF/ERA5_LAND/DAILY_AGGR` → `filterDate("2023-01-01","2023-12-31")` → `reduceRegions(scale=11132)`, returns `{"province:name": kwh/day or None}`; J/m² → kWh/m²/day divides by 3,600,000
- **`_load_existing_solar()`** (new): returns `{"province:name": float}` for rows where `geo_scores.solar_irradiance IS NOT NULL` — enables resume of interrupted runs
- **`_upsert_solar_batch(conn, units)`** (new): writes `solar_irradiance` to `geo_scores` per batch; commits immediately after each batch
- **`_get_all_municipalities()`**: `solar = None` now (was `_stable_float(f"{muni_name}:solar", 4.5, 6.0)`) — placeholder filled by GEE
- **`precompute_geo_scores()`** rewritten: (1) calls `_init_gee()` — exits with error if GEE auth fails; (2) resumes from `_load_existing_solar()`; (3) batches 200 munis per `reduceRegions()` call (~9 batches, 1s sleep between); (4) synthetic fallback per municipality if GEE returns null; (5) batch commit via `_upsert_solar_batch`; (6) then runs `normalize_and_score` + `upsert_to_db` as before

### Config Fix
- `config.py` (pre-existing uncommitted change): `OLLAMA_EMBED_MODEL` default changed from `"qwen3-embedding"` → `"qwen3-embedding:0.6b"`
- `tests/test_config.py::test_ollama_defaults` updated to match

### New Tests
- `tests/test_db_store.py`: +6 tests (4 for new columns + fallback JOIN, 2 for `list_runs` INNER JOIN/limit)
- `tests/test_synthesis_weights.py`: +1 test (`test_synthesis_agent_top_targets_have_component_fields`)
- `tests/test_precompute.py`: +3 tests (`test_get_all_municipalities_solar_is_none`, `test_fetch_gee_irradiance_batch_uses_reduceRegions`, `test_load_existing_solar_returns_dict`)
- Also updated `test_list_runs_returns_done_runs_newest_first` to call `save_report` (required by new INNER JOIN)
- Total: 89 tests, all passing

### ⚠️ Next session
- `feat-geo-scoring` branch has not been merged to `main` yet (user kept as-is)
- `precompute_geo_scores.py` has real GEE flow but needs `earthengine authenticate` + GEE project set before running
- The precompute script must be run manually to backfill real irradiance into `geo_scores.solar_irradiance`; until then, live `geo_scoring_agent` runs still use synthetic solar values for on-the-fly scoring

#### Files changed (session 5)
- `agents/db_store.py` — `_migrate` + `complete_run` + `load_run` + `list_runs`
- `agents/synthesis.py` — added 3 component fields to `final_scores` dict
- `agents/report_gen.py` — Score Breakdown section in `REPORT_PROMPT`
- `app.py` — rich map popup, 4-col sidebar metrics, Past Runs page, nav radio
- `scripts/precompute_geo_scores.py` — real GEE batch fetch, resume support
- `config.py` — `OLLAMA_EMBED_MODEL` default updated
- `tests/test_db_store.py` — geo_scores table in schema, 6 new tests, updated list_runs test
- `tests/test_synthesis_weights.py` — 1 new test
- `tests/test_precompute.py` — 3 new tests
- `tests/test_config.py` — updated OLLAMA_EMBED_MODEL assertion

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
