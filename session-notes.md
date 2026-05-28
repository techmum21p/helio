> Last updated: 2026-05-28 | Session 4

# Helio — Solar Lead Intelligence Platform Session Notes

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
