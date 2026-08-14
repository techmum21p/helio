# Helio: Streamlit → FastAPI + Frontend Migration Plan

**Status:** Draft for review. No FastAPI/frontend implementation started yet.

**Update (post-draft):** the two biggest open questions below — the embeddings
blocker (§3.1) and the storage/persistence question (§3.1/§7.5) — have since
been resolved and implemented, ahead of the rest of the migration:

- **Embeddings/ChromaDB/Ollama dropped entirely**, not worked around. The KB
  no longer does semantic search. `agents/chat_tools.py::search_kb` now takes
  an explicit `province` (+ optional `municipality`) scope — already required
  info, since the chatbot resolves place names before calling any tool — and
  loads the current province report + municipality intel doc(s) for that
  scope straight off disk for the LLM to synthesize from. A new `kb_docs` DB
  table (`agents/db_store.py`) tracks which `kb/intel/*.md` file is current
  per municipality, replacing the old ChromaDB-index purge script. `chromadb`,
  `sentence-transformers`, `torchvision`, and `reportlab` (confirmed unused)
  are gone from `requirements.txt`. This was driven by two things: the
  Ollama-embeddings dependency was never going to run on a bare Render Web
  Service, and the project's hard cost constraint (no new live Places/Tavily
  calls, ever — see memory) means the KB content itself never needed semantic
  recall over a huge corpus; it's small enough per province to just load in
  full.
- **Storage: SQLite stays, no Render Persistent Disk.** `data/helio.db` (10MB)
  and `kb/intel/*.md` (deduped to ~5.5MB, one current file per municipality)
  are now committed to the repo as seed data — `.gitignore` was updated to
  un-ignore them deliberately. This is a demo/portfolio app on a single Render
  instance; writes since the last commit (refreshed assessments, chat history)
  are accepted to reset on redeploy rather than paying for persistent infra.

## 0. Reality check before you read the rest

`CLAUDE.md` describes Helio as a LangGraph pipeline app (`geo_scoring → web_intel → synthesis → report_gen → update_kb`)
driven from `app.py`. **That's no longer what `app.py` does.** As of the current `main` branch, `app.py` is a
"dataset-first explorer": it reads exclusively from `data/helio.db` (pre-scored municipalities), does no live
Tavily/Google Places calls, and the only "live" work is an on-demand LLM re-synthesis
(`agents/refresh.py::maybe_refresh_assessment`) for stale rows. `graph/pipeline.py` (the LangGraph 5-agent
pipeline) and `pipeline.py` (root-level parallel draft) are **not imported by `app.py`** — they're only used by
offline scripts (`scripts/run_all_provinces.py`, `scripts/precompute_geo_scores.py`) that populate `helio.db` in
batch, outside the request path.

This matters a lot for the migration: the FastAPI backend you actually need is a thin read/query layer over
`helio.db` + the chatbot, **not** a web service that re-runs the 5-agent LangGraph pipeline per request.

Also: `api/` and `frontend/` directories already exist in this repo, but they are **dead artifacts, not a starting
point**. `api/` contains only stale `.pyc` files (May 2026) with no corresponding `.py` source anywhere in git
history — the source was deleted or never committed. `frontend/` is explicitly gitignored
(`# Frontend (Next.js — not used, keeping files locally)`) and contains only `.next` build cache, `tsconfig.tsbuildinfo`,
and `.env.local` — no application source. Treat both as leftovers from an earlier abandoned attempt at this exact
migration; recommend deleting them before starting fresh (see Open Questions §7.1).

---

## 1. Function/Module Inventory

### 1.1 Pure logic — portable as-is into a FastAPI service layer

| Module | What it does | Notes |
|---|---|---|
| `agents/db_store.py` | All SQLite I/O: runs, results, reports, chat messages, `get_latest_scored_municipalities()`, `get_score_breakdown()`, `get_latest_report_for_province()`, `latest_assessment_time_for_province()` | No Streamlit coupling at all. This is already your service layer for "read scored municipalities" endpoints. |
| `agents/chat_tools.py` | Typed tool functions for the chatbot agent loop: `get_top_municipalities`, `get_municipality_profile`, `compare_municipalities`, `search_kb`, `run_sql_query` (read-only SELECT, capped rows) | Pure functions, JSON-serializable returns, never raise. Directly reusable. |
| `agents/chatbot.py` (minus module-level ChromaDB client construction) | `chat()`, `_agent_loop()`, `retrieve_context()`, `index_documents_from_kb()`, `detect_municipality_id()` | Logic is portable; **module-level `chromadb.PersistentClient(...)` + `OllamaEmbeddingFunction(...)` construction at import time is a startup dependency, see §3**. |
| `agents/refresh.py` | `maybe_refresh_assessment()` — lazy staleness-aware re-synthesis of one municipality (LLM-only, no new Places/Tavily calls) | Pure logic, depends only on `db_store`, `geo_scoring._load_scores_from_db`, `synthesis`, `kb_builder`. Portable. |
| `agents/synthesis.py` | `synthesize_municipality()`, `compute_final_score()` | Calls `anthropic.Anthropic(...)` client (Xiaomi gateway). Portable — just an outbound HTTP call. |
| `agents/report_gen.py` | `generate_report_markdown()`, `save_report()`, `regenerate_province_report()`, deterministic score-breakdown markdown builders | Portable. Writes to `reports/` and `kb/reports/` — see filesystem-write note in §3. |
| `agents/kb_builder.py` | `save_municipality_docs()`, `_build_municipality_doc()` — builds per-municipality markdown from scores + web intel | Portable. |
| `agents/geocoder.py` | Nominatim-based geocoding with local JSON cache | Portable; used only by offline scripts, not the live app. |
| `agents/location_db.py` | Read helpers for the legacy `ph_locations.db` (provinces/municipalities/barangays) | Portable but check if still used — `config.py` marks `HELIO_DB` as having replaced `ph_locations.db` for structured data; confirm this file isn't dead code before porting it (§7.2). |
| `agents/geo_scoring.py` — **only** `_load_scores_from_db()`, `_db_has_scores()`, `_normalize_fixed()`, `_stable_float()`, `_huc_province()` | DB-read path used live by `refresh.py` | Portable, but the file also contains the heavy geopandas/GEE compute path — see §3, this needs a split. |
| `graph/state.py` | `SolarLeadState` TypedDict | Portable as a Pydantic/dataclass equivalent if you keep the pipeline for batch jobs. |

### 1.2 Streamlit-specific UI glue — needs to be rebuilt, not ported

All of this lives in **`app.py` only** (confirmed — grepped every other `.py` file in the repo for real
`st.*`/`streamlit` usage; zero hits outside `app.py`):

| Concern | Streamlit construct | Rebuild target |
|---|---|---|
| Page shell | `st.set_page_config`, `st.columns([3, 1.3])`, `st.title`, `st.markdown` | Frontend layout components |
| Client state | `st.session_state.chat_history`, `st.session_state.selected_municipality_id` | Frontend state (React state / URL params) |
| Caching | `@st.cache_data(ttl=600)` around `get_latest_scored_municipalities()` | HTTP cache headers or a short-TTL in-memory/Redis cache on the API side, or frontend fetch caching (SWR/React Query) |
| Map | `folium.Map` + `st_folium`, `CircleMarker` per municipality, tooltip HTML, click → `last_object_clicked_tooltip` → set `selected_municipality_id` | Client-side map (e.g. MapLibre/Leaflet/Mapbox GL) driven by a `/municipalities` JSON payload; click handling becomes a frontend event, not a Streamlit round-trip |
| Legend | `_legend_html()` inline HTML swatches | Frontend legend component |
| Province filter + table | `st.selectbox`, `st.dataframe` | Frontend filter + table component, backed by `/municipalities?province=` |
| Drill-down panel | `st.selectbox`, `st.metric` ×4, `st.write`, `st.expander` ×2 (score breakdown, province report), `st.spinner` | Frontend detail panel, backed by `/municipalities/{id}` (which triggers the same `maybe_refresh_assessment` server-side) |
| Report download | `st.download_button` reading `report["file_path"]` from local disk | Needs a `GET /reports/{slug}` endpoint streaming the markdown (or a signed URL if reports move to object storage — see §3) |
| Chat UI | `st.chat_message`, `st.chat_input`, `st.spinner` | Frontend chat widget calling `POST /chat` |

`_score_tier()`, `_score_color()`, `TIER_COLORS`, `_render_score_breakdown()` are **presentation logic that happens to
be pure Python** (no `st.*` calls except the final `st.dataframe`/`st.caption` render). Recommend porting the tier/color
thresholds as shared constants (duplicate in API response shape as a `tier` string in `TIER_COLORS`'s domain, let the
frontend own the color mapping) rather than porting the HTML-string building — the frontend should own its own rendering.

### 1.3 Data/model loading — cold-start risk on Render

| What | Where | Cold-start impact | Flag |
|---|---|---|---|
| ChromaDB `PersistentClient` + collection get-or-create | `agents/chatbot.py` module level (runs at **import time**, not per-request) | Opens/creates a persistent index at `kb/index/` on every process start. Size depends on accumulated KB (grows with every run). On Render's free/starter tier with an ephemeral filesystem, this either needs a persistent disk add-on or the index gets rebuilt from `kb/reports/` + `kb/intel/` on every cold start. | 🔴 High |
| `OllamaEmbeddingFunction` pointing at `http://localhost:11434` | `agents/chatbot.py` | **This will not work on Render at all** unless Ollama is self-hosted as a sidecar/second service or the embedding function is swapped for a hosted embeddings API. This is the single biggest blocker for a straight lift-and-shift. See §3.1. | 🔴 Critical |
| `sentence-transformers` (`all-MiniLM-L6-v2`) in `requirements.txt` | Listed as a dependency in `CLAUDE.md` but **not actually imported anywhere in current code** — `chatbot.py` uses `OllamaEmbeddingFunction`, not a local sentence-transformers model | If truly unused, drop it — it pulls in `torch`/`torchvision` transitively, which is a multi-hundred-MB image bloat for nothing. Needs confirming (§7.3). | 🟡 Medium (image size) |
| `earthengine-api` init (`agents/geo_scoring.py::_init_gee`) | Only called from the offline compute path (`compute_geo_scores`, used by `scripts/precompute_geo_scores.py`), **not** from `_load_scores_from_db` (the live path used by `refresh.py`) | If the FastAPI service only imports the DB-read functions, GEE auth/init never fires at runtime — good. But if `geo_scoring.py` isn't split, importing the module still requires `geopandas`/`earthengine-api` installed (see §3.2) even though unused at request time. | 🟡 Medium |
| `data/helio.db` (SQLite) | `config.HELIO_DB`, opened per-call via `sqlite3.connect()` in `db_store.py`/`chat_tools.py` | Not loaded into memory at startup — fine. But SQLite-on-Render means the DB file must live on a **persistent disk**, not ephemeral container storage, or writes (new runs, refreshed assessments, chat messages) vanish on every redeploy/restart. | 🔴 High |
| `reports/`, `kb/reports/`, `kb/intel/` (markdown files on local disk) | `config.py` `mkdir`s these at import time; `report_gen.py`/`kb_builder.py` write to them | Same persistent-disk requirement as the DB. Also referenced by file path for the download button — needs an endpoint, not a raw path. | 🔴 High |
| `psgc[geo]` package data | Used by `scripts/` for admin-boundary/population/income lookups at *build time* (populating `helio.db`), not at request time | No live-request cold start impact if the API only reads `helio.db`. | 🟢 Low |

**Bottom line on cold start:** if the FastAPI service is scoped correctly (reads `helio.db` + calls the Xiaomi/Anthropic
gateway + queries ChromaDB), there's no large model loaded into memory at startup — the actual risk is entirely about
**persistent storage** (SQLite file, ChromaDB index, report markdown files) and the **Ollama embedding dependency**,
not about big ML models.

---

## 2. Proposed REST API Surface

Minimal surface matching what `app.py` currently does — no speculative endpoints.

| Method & Path | Maps to | Request | Response (rough shape) |
|---|---|---|---|
| `GET /municipalities` | `db_store.get_latest_scored_municipalities()` | Query param `province` optional (server-side filter instead of client-side, since the frontend won't hold the full list in `st.session_state`) | `[{municipality_id, name, province, region, lat, lon, geo_score, web_score, final_score, tier, population, ...}]` |
| `GET /municipalities/{id}` | `agents.refresh.maybe_refresh_assessment(id)` | — | Same row shape as above, plus `assessment`, `opportunities`, `risks` (triggers lazy re-synthesis server-side, same as today) |
| `GET /municipalities/{id}/score-breakdown` | `db_store.get_score_breakdown(id)` | — | `{geo: {...}, weights: {...}, web: {...} | null, final_weights: {...}, final_score}` |
| `GET /provinces/{province}/report` | `db_store.get_latest_report_for_province()` + `report_gen.regenerate_province_report()` staleness check (mirrors `app.py`'s `is_stale` logic) | — | `{slug, province, markdown, created_at, file_path}` |
| `GET /provinces/{province}/report/download` | Same report row, `file_path` contents | — | `text/markdown` file stream (replaces `st.download_button` reading local disk directly) |
| `POST /chat` | `agents.chatbot.chat()` | `{message: str, history: [{role, content}], run_id?: str}` | `{reply: str, history: [{role, content}]}` — **stateless**: the frontend owns/replays history, same contract `app.py` already uses via `st.session_state.chat_history` |

That's 6 endpoints. Deliberately **not** proposing:
- Any endpoint that triggers the full LangGraph pipeline (`geo_scoring → web_intel → ...`) — the current app doesn't
  expose this; it's an offline/CLI operation (`scripts/run_all_provinces.py`). If you want to trigger new-location runs
  from the frontend later, that's a new feature, not a migration requirement — flag it as an open question (§7.4)
  rather than building it now.
- `/kb/reindex` — `index_documents_from_kb()` is currently called unconditionally on every Streamlit page load
  (`app.py:287`, inside the chat column render). For the API, call this once at startup / on a schedule instead of
  per-request (see §3.1) — no endpoint needed unless you want a manual "reindex now" admin action.

---

## 3. Dependency Risk

### 3.1 Critical — blocks a straight lift-and-shift

- **Ollama embeddings** (`chromadb.utils.embedding_functions.OllamaEmbeddingFunction`, `config.OLLAMA_URL` defaulting
  to `http://localhost:11434`). Render Web Services don't give you a local Ollama daemon. Options: (a) run Ollama as
  a second Render service and point `OLLAMA_URL` at it (adds cost + latency + another moving part), (b) swap to a
  hosted embeddings API (OpenAI/Anthropic-compatible, or Xiaomi's gateway if it offers embeddings), (c) switch to
  `sentence-transformers` running in-process (it's already a listed dependency, just unused — see §7.3) if the model
  size (~80MB for MiniLM) is acceptable for cold start. **This decision blocks backend design and should happen
  before folder-structure work starts.**

- **Persistent storage** for `data/helio.db`, `kb/index/` (ChromaDB), `reports/`, `kb/reports/`, `kb/intel/`. Render
  Web Services have ephemeral local disk by default — anything written there is lost on redeploy/restart/scale event.
  Needs either a Render Persistent Disk (single-instance only, no horizontal scaling) or a migration to managed
  storage (e.g. Postgres for the DB, S3-compatible object storage for reports/KB markdown, a hosted vector DB for
  ChromaDB or swap to pgvector). This is a bigger decision than "which folder" — flag for user decision (§7.5).

### 3.2 Heavy / native-binary packages — compatible with Render Web Service (Docker-based) but worth isolating

| Package | Native deps | Used at request time? | Recommendation |
|---|---|---|---|
| `geopandas`, `shapely`, `pyproj` | GEOS/PROJ C libraries | No — only in `geo_scoring.py`'s offline compute path (`units_to_geodataframe`, `compute_geo_scores`) called from `scripts/precompute_geo_scores.py` | Split `geo_scoring.py` so the FastAPI image doesn't need to import these at all (see §7.2). Standard Render Docker build handles them fine if you do need them (Debian base + `apt-get install libgeos-dev`), but no reason to pay that image-size/build-time cost for a service that never calls the compute path. |
| `earthengine-api` | Requires GEE OAuth credentials at init | No — same offline-only path | Same as above: exclude from the live API's dependency set. |
| `chromadb` | Pulls in `onnxruntime`/`hnswlib` (native) | Yes — `retrieve_context`/`search_kb` | Fine on Render Docker; just budget image size and cold-start-open-index time. |
| `sentence-transformers` (+ `torch`/`torchvision`) | Large native/CUDA-adjacent wheels | Currently unused (see §7.3) | Drop if truly unused — biggest single win for image size/build time. If you go with option (c) in §3.1, keep it but drop `torchvision` (image-model dep, irrelevant to text embeddings). |
| `rdata`, `barangay`, `psgc[geo]` | Pure-Python/data-package, no native compile step beyond their own deps | No — build-time/offline only | Exclude from the API's `requirements.txt`; keep in a separate `scripts/`-only requirements file if you keep the offline pipeline in the same repo. |
| `reportlab` | Pure Python | Not referenced by any current agent (`report_gen.py` writes markdown, not PDF) — check for dead dependency (§7.3) | Drop if unused. |

### 3.3 Fine as-is

`anthropic`, `langgraph`/`langchain*` (only if you keep the offline pipeline), `sqlite3` (stdlib), `loguru`,
`pydantic`, `python-dotenv`, `requests`, `beautifulsoup4`, `tavily-python`, `rapidfuzz` — none of these are
native-binary-heavy or awkward in a standard container.

---

## 4. Proposed Two-Repo / Folder Structure

**Recommendation: two repos**, not one repo with `backend/` + `frontend/` folders — with a caveat below.

Why: Render's Static Site (frontend) and Web Service (backend) deploy independently regardless of repo layout, but
a single monorepo means every backend-only commit still shows up in the frontend's Render build trigger scope (and
vice versa) unless you configure path-based build filters. Given this project's history — `frontend/` already sits
gitignored in this exact repo as a "not used, keeping files locally" experiment — a real separate repo for the
frontend avoids re-creating that ambiguity, keeps `requirements.txt` (Python) and `package.json` (Node) fully
decoupled, and lets the frontend repo have its own CI/lint/type-check pipeline without Python tooling noise.

Caveat: if you'd strongly prefer one repo for atomic PRs across the API/UI boundary, a monorepo with Render's
root-directory + ignored-build-step settings works fine too — this is a judgment call, not a technical blocker either
way. Flagging as open question §7.6 rather than deciding it for you.

### Backend repo (`helio-api`)

```
helio-api/
├── app/
│   ├── main.py                # FastAPI app, router registration, startup (KB index warm)
│   ├── config.py              # ported from config.py — env vars, paths
│   ├── db/
│   │   └── store.py           # ported from agents/db_store.py
│   ├── routers/
│   │   ├── municipalities.py  # GET /municipalities, /municipalities/{id}, /score-breakdown
│   │   ├── reports.py         # GET /provinces/{province}/report[/download]
│   │   └── chat.py            # POST /chat
│   ├── services/
│   │   ├── chatbot.py         # ported from agents/chatbot.py (chat, retrieve_context, index_documents_from_kb)
│   │   ├── chat_tools.py      # ported from agents/chat_tools.py
│   │   ├── refresh.py         # ported from agents/refresh.py
│   │   ├── synthesis.py       # ported from agents/synthesis.py
│   │   ├── report_gen.py      # ported from agents/report_gen.py
│   │   ├── kb_builder.py      # ported from agents/kb_builder.py
│   │   └── geo_scores_read.py # NEW — just _load_scores_from_db + its small helpers, split out of geo_scoring.py
│   └── models/                # Pydantic request/response schemas for the 6 endpoints
├── offline/                    # optional: keep the batch pipeline here if you're not retiring it
│   ├── pipeline/               # ported from graph/
│   ├── geo_scoring_compute.py  # the geopandas/GEE-heavy half of current geo_scoring.py
│   ├── geocoder.py
│   ├── location_db.py
│   └── scripts/                # ported from scripts/
├── tests/
├── requirements.txt             # slim: no geopandas/earthengine/sentence-transformers unless offline/ is deployed too
├── requirements-offline.txt     # heavy deps, only needed if running scripts/ (could be a separate deploy target or just local/CI)
├── Dockerfile
└── render.yaml
```

### Frontend repo (`helio-web`)

```
helio-web/
├── src/
│   ├── app/ or pages/           # framework-dependent (Next.js/Vite/etc — pick one, see §7.7)
│   ├── components/
│   │   ├── Map.tsx              # replaces folium + st_folium
│   │   ├── Legend.tsx           # replaces _legend_html()
│   │   ├── MunicipalityTable.tsx
│   │   ├── DetailPanel.tsx      # replaces the st.metric/st.expander drill-down block
│   │   ├── ScoreBreakdown.tsx   # replaces _render_score_breakdown()
│   │   └── Chat.tsx             # replaces st.chat_message/st.chat_input
│   ├── lib/
│   │   └── api.ts               # typed fetch wrappers for the 6 endpoints
│   └── styles/
├── public/
├── package.json
└── render (Static Site config — build command + output dir)
```

---

## 5. Open Questions / Ambiguities

1. **`api/` and `frontend/` leftovers.** As noted in §0, both directories in *this* repo appear to be a prior,
   abandoned attempt at this same migration (source deleted, only `.pyc`/build-cache remains). Should these be
   deleted outright, or is there something recoverable (e.g. can you find the original `.py` sources elsewhere —
   another machine, an old branch that got deleted, a zip backup)? I did not find them in `git log --all` across any
   local branch.

2. **`agents/location_db.py`** reads from a `ph_locations.db` file that `config.py`'s own comment says was
   *replaced* by `helio.db` ("Consolidated DB (helio.db replaces ph_locations.db for all structured data)"). Is
   `location_db.py` still called from anywhere live, or is it dead code from before the consolidation? If dead,
   it shouldn't be ported at all.

3. **Confirm actually-unused dependencies** before deciding what ships in the API's `requirements.txt`:
   `sentence-transformers`/`torch`/`torchvision` (chatbot uses Ollama embeddings, not sentence-transformers, as far
   as I can find by reading `agents/chatbot.py`) and `reportlab` (report generation produces markdown, not PDF, in
   every code path I read). If these are genuinely dead, dropping them is the single biggest image-size win in this
   whole migration — worth a quick `grep -r` pass before I write the actual requirements split.

4. **Should the API expose a way to kick off new-location analysis** (the full `graph/pipeline.py` LangGraph flow),
   or does that stay a CLI/offline-only operation forever, run by whoever maintains the KB? The current Streamlit
   app doesn't expose this at all, so I scoped the REST surface without it — but if the two-repo split is partly
   motivated by wanting a "run a new province" button in the new frontend, that changes the API surface materially
   (needs a job-queue/async pattern, since a full pipeline run is slow and does paid Tavily/Places calls).

5. **Storage decision** (§3.1): Render Persistent Disk (simplest, but single-instance, no autoscaling) vs. managed
   Postgres + object storage + hosted vector DB (more moving parts, more cost, but scales and survives redeploys
   cleanly). This is a cost/complexity tradeoff only you can make — I'd lean toward Persistent Disk for a v1 given
   this looks like a low-traffic portfolio/demo project (per the recent "portfolio-grade project overview" commit),
   but wanted to flag rather than assume.

6. **One repo vs. two** (§4) — leaning two, but it's a real judgment call given Render's per-service deploy model
   either way works.

7. **Frontend framework** — not specified in the request. The folder structure above is framework-agnostic; I'd
   default to Next.js (static export or SSR, both Render-compatible) unless you have a preference, since it pairs
   well with a Render Static Site deploy and gives you a mature map-library ecosystem, but this wasn't specified so
   flagging rather than assuming.

8. **`st.cache_data(ttl=600)` semantics.** The current app caches `get_latest_scored_municipalities()` for 10 minutes
   per Streamlit session. In a stateless API, the natural equivalent is an HTTP `Cache-Control` header or a small
   server-side cache (e.g. `functools.lru_cache` with manual invalidation, or Redis if you're already adding infra
   for the storage question in #5) — wanted to confirm you're fine with the semantics shifting from "per-user-session
   cache" to "shared server-side cache," since that's a small behavior change (all users would see the same
   10-minute-stale snapshot rather than each getting their own).

9. **`index_documents_from_kb()` runs unconditionally on every Streamlit render** of the chat column today
   (`app.py:287`) — cheap because it's a no-op skip-if-already-indexed check, but still a DB+filesystem scan per
   page load. For the API, I'd move this to a startup hook + optional periodic re-scan rather than per-`/chat`-call.
   Confirming that's the intended behavior change, not an oversight.
