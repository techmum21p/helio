# Chatbot Tool-Use Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chatbot's regex-intent/context-stuffing retrieval with an LLM tool-use agent loop backed by five typed data tools, so structured questions (rankings, profiles, comparisons, analytics) are answered from real DB state instead of semantic-search guesswork.

**Architecture:** `agents/chat_tools.py` (new) holds tool schemas + executors that never raise. `agents/chatbot.py`'s `chat()` keeps its exact signature but internally runs an agent loop (max 5 tool rounds) with a legacy RAG fallback on gateway failure. A one-off script backfills `province` metadata onto existing ChromaDB intel chunks.

**Tech Stack:** anthropic SDK (Anthropic-compatible MiMo gateway), sqlite3, chromadb 1.5.9, pytest, loguru.

**Spec:** `docs/superpowers/specs/2026-07-12-chatbot-tool-use-retrieval-design.md`

## Global Constraints

- `chat(user_message: str, chat_history: list, run_id: str = "") -> tuple[str, list]` signature MUST NOT change (`app.py:11` imports it).
- Agents/tools never raise: executors return `{"error": "..."}` dicts; `chat()` falls back to the legacy RAG path on any gateway failure.
- Rankable metrics enum (exact): `final_score`, `geo_score`, `solar_irradiance`, `population`, `pop_density`. No `poverty` — not in the DB.
- Tool round cap: 5. SQL row cap: 200. SQL connection: `file:{config.HELIO_DB}?mode=ro`, uri=True (read-only enforced at DB level).
- Only text turns persist to `chat_history` / `chat_messages`; `tool_use`/`tool_result` blocks live within a single turn.
- Lazy re-synthesis (`agents.refresh.maybe_refresh_assessment`) must still fire when a municipality profile is requested.
- Logging via `from loguru import logger`. Config values from `config.py` only.
- Working tree note: `agents/chatbot.py` currently contains an uncommitted regex patch (`detect_province_ranking_query`, `_province_leaderboard_block`, `_exact_municipality_block`); Task 5 deletes it — this is intentional, per spec.
- Circular-import rule: `agents/chatbot.py` imports `agents/chat_tools.py` at module level; therefore `chat_tools` must import from `agents.chatbot` and `agents.refresh` ONLY inside function bodies (call time). Same pattern as the existing `maybe_refresh_assessment` wrapper in chatbot.py.
- venv: `source .venv_helios/bin/activate`. Test runner: `python3 -m pytest`.
- Each commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `chat_tools.py` skeleton — dispatcher, resolvers, ranking tool

**Files:**
- Create: `agents/chat_tools.py`
- Test: `tests/test_chat_tools_ranking.py`

**Interfaces:**
- Consumes: `agents.db_store.get_latest_scored_municipalities()` (module-level import OK — no cycle), row shape: dict with keys `municipality_id, name, province, region, lat, lon, population, income_class, geo_score, final_score, web_score, tier, assessment, opportunities, risks, solar_irradiance, solar_yield_kwh, pop_density`.
- Produces (later tasks rely on these exact names):
  - `RANKABLE_METRICS: list[str]`
  - `TOOLS: list[dict]` (Anthropic tool schemas; later tasks append)
  - `_EXECUTORS: dict[str, callable]` (later tasks register into it)
  - `_slugify(name: str) -> str`
  - `province_slug_map() -> dict[str, str]` (slug → canonical province)
  - `_resolve_province(fragment: str, rows: list[dict]) -> tuple[str | None, list[str]]`
  - `get_top_municipalities(province=None, region=None, n=5, metric="final_score", ascending=False) -> dict`
  - `execute_tool(name: str, tool_input: dict) -> str` (JSON string, never raises)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_tools_ranking.py
import json


ROWS = [
    {"municipality_id": 1, "name": "Jolo",   "province": "Sulu", "region": "BARMM",
     "final_score": 0.84, "geo_score": 0.96, "tier": "MEDIUM",
     "solar_irradiance": 5.5, "population": 137000, "pop_density": 900.0},
    {"municipality_id": 2, "name": "Siasi",  "province": "Sulu", "region": "BARMM",
     "final_score": 0.79, "geo_score": 0.89, "tier": "MEDIUM",
     "solar_irradiance": 5.4, "population": 60000, "pop_density": 300.0},
    {"municipality_id": 3, "name": "Lugus",  "province": "Sulu", "region": "BARMM",
     "final_score": None, "geo_score": 0.55, "tier": None,
     "solar_irradiance": None, "population": 20000, "pop_density": None},
    {"municipality_id": 4, "name": "Digos",  "province": "Davao del Sur", "region": "Region XI",
     "final_score": 0.70, "geo_score": 0.75, "tier": "MEDIUM",
     "solar_irradiance": 5.2, "population": 188000, "pop_density": 650.0},
    {"municipality_id": 5, "name": "Mati",   "province": "Davao Oriental", "region": "Region XI",
     "final_score": 0.65, "geo_score": 0.72, "tier": "MEDIUM",
     "solar_irradiance": 5.1, "population": 141000, "pop_density": 250.0},
]


def _patch_rows(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities", lambda: [dict(r) for r in ROWS])


def test_rank_by_final_score_descending(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", n=5, metric="final_score")
    names = [r["name"] for r in out["results"]]
    assert names == ["Jolo", "Siasi"]          # Lugus excluded: NULL final_score
    assert out["municipalities_in_scope"] == 3
    assert out["municipalities_with_metric"] == 2
    assert out["results"][0]["rank"] == 1


def test_rank_ascending(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", metric="final_score", ascending=True)
    assert [r["name"] for r in out["results"]] == ["Siasi", "Jolo"]


def test_rank_nationwide_when_no_province(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(n=3, metric="population")
    assert out["scope"] == "nationwide"
    assert [r["name"] for r in out["results"]] == ["Digos", "Mati", "Jolo"]


def test_ambiguous_province_returns_candidates(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="davao")
    assert "error" in out
    assert set(out["candidates"]) == {"Davao del Sur", "Davao Oriental"}


def test_exact_province_beats_substring(monkeypatch):
    import agents.chat_tools as ct
    _patch_rows(monkeypatch)
    resolved, candidates = ct._resolve_province("sulu", ct.get_latest_scored_municipalities())
    assert resolved == "Sulu" and candidates == []


def test_invalid_metric_rejected(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", metric="poverty")
    assert "error" in out and "search_kb" in out["error"]


def test_execute_tool_returns_json_and_never_raises(monkeypatch):
    from agents.chat_tools import execute_tool
    _patch_rows(monkeypatch)
    ok = json.loads(execute_tool("get_top_municipalities", {"province": "Sulu", "n": 1}))
    assert ok["results"][0]["name"] == "Jolo"
    bad_tool = json.loads(execute_tool("nope", {}))
    assert "error" in bad_tool
    bad_args = json.loads(execute_tool("get_top_municipalities", {"bogus_arg": 1}))
    assert "error" in bad_args
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chat_tools_ranking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.chat_tools'`

- [ ] **Step 3: Implement `agents/chat_tools.py`**

```python
"""
Typed data tools for the chatbot agent loop.
Spec: docs/superpowers/specs/2026-07-12-chatbot-tool-use-retrieval-design.md

Executors return JSON-serializable dicts and NEVER raise; execute_tool()
wraps them into JSON strings for tool_result blocks. Imports from
agents.chatbot / agents.refresh happen at call time only — agents.chatbot
imports this module at load time.
"""
import json
import sqlite3

from loguru import logger

import config
from agents.db_store import get_latest_scored_municipalities, get_score_breakdown

RANKABLE_METRICS = ["final_score", "geo_score", "solar_irradiance", "population", "pop_density"]
SQL_ROW_CAP = 200
MAX_RANK_N = 50


def _slugify(name: str) -> str:
    """Match kb_builder.py's filename slugging (agents/kb_builder.py:117)."""
    return name.lower().replace(" ", "_").replace(",", "")


def province_slug_map() -> dict[str, str]:
    """slug → canonical province name, from current DB rows."""
    return {
        _slugify(p): p
        for p in {r["province"] for r in get_latest_scored_municipalities() if r["province"]}
    }


def _resolve_province(fragment: str, rows: list[dict]) -> tuple[str | None, list[str]]:
    """Exact case-insensitive match wins; else a unique substring match;
    else (None, candidates)."""
    provinces = sorted({r["province"] for r in rows if r["province"]})
    frag = fragment.strip().lower()
    for p in provinces:
        if p.lower() == frag:
            return p, []
    candidates = [p for p in provinces if frag in p.lower()]
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


def get_top_municipalities(province=None, region=None, n=5, metric="final_score", ascending=False) -> dict:
    if metric not in RANKABLE_METRICS:
        return {"error": f"metric must be one of {RANKABLE_METRICS}. Other metrics "
                         "(e.g. poverty incidence) are not in the database — use "
                         "search_kb for narrative context instead."}
    rows = get_latest_scored_municipalities()
    scope = "nationwide"
    if province:
        resolved, candidates = _resolve_province(province, rows)
        if resolved is None:
            return {"error": f"Ambiguous or unknown province {province!r}.",
                    "candidates": candidates,
                    "hint": "Retry with one exact candidate name, or ask the user which they meant."}
        rows = [r for r in rows if r["province"] == resolved]
        scope = resolved
    if region:
        frag = region.strip().lower()
        rows = [r for r in rows if frag in (r["region"] or "").lower()]
        scope = f"{scope} / region matching {region!r}"
    scored = [r for r in rows if r.get(metric) is not None]
    scored.sort(key=lambda r: r[metric], reverse=not ascending)
    n = max(1, min(int(n), MAX_RANK_N))
    results = []
    for i, r in enumerate(scored[:n], 1):
        entry = {"rank": i, "name": r["name"], "province": r["province"],
                 "final_score": r["final_score"], "geo_score": r["geo_score"],
                 "tier": r["tier"]}
        entry[metric] = r[metric]
        results.append(entry)
    return {"scope": scope, "metric": metric, "ascending": ascending,
            "municipalities_in_scope": len(rows),
            "municipalities_with_metric": len(scored),
            "results": results}


TOOLS: list[dict] = [
    {
        "name": "get_top_municipalities",
        "description": (
            "Authoritative ranking of municipalities by a database metric, from live "
            "current data (staleness rules already applied). ALWAYS use this for "
            "top/best/highest/lowest/worst questions — never rank from search results. "
            "Omit province and region for a nationwide ranking. If the province name is "
            "ambiguous you get back a candidate list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "province": {"type": "string", "description": "Province name or fragment, e.g. 'Sulu' or 'davao'"},
                "region": {"type": "string", "description": "Region name fragment, e.g. 'BARMM', 'Region XI'"},
                "n": {"type": "integer", "description": "How many rows to return (default 5, max 50)"},
                "metric": {"type": "string", "enum": RANKABLE_METRICS,
                           "description": "Ranking basis. final_score = overall solar opportunity score."},
                "ascending": {"type": "boolean", "description": "true for lowest-first ('worst 5')"},
            },
            "required": ["metric"],
        },
    },
]

_EXECUTORS: dict = {
    "get_top_municipalities": get_top_municipalities,
}


def execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch one tool call. Never raises — errors come back as JSON."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(fn(**(tool_input or {})), default=str)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
    except Exception as e:
        logger.warning(f"chat_tools.{name} failed: {e}")
        return json.dumps({"error": str(e)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_chat_tools_ranking.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add agents/chat_tools.py tests/test_chat_tools_ranking.py
git commit -m "feat: chat_tools skeleton — execute_tool dispatcher, province resolver, ranking tool

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Profile and compare tools (with lazy re-synthesis)

**Files:**
- Modify: `agents/chat_tools.py`
- Test: `tests/test_chat_tools_profile.py`

**Interfaces:**
- Consumes: Task 1's `_resolve_province`, `_EXECUTORS`, `TOOLS`, `get_score_breakdown` (already imported); `agents.refresh.maybe_refresh_assessment(municipality_id: int) -> dict | None` (returns row in `get_latest_scored_municipalities()` shape, or None) — **import inside the function body**.
- Produces:
  - `get_municipality_profile(name: str, province: str | None = None) -> dict`
  - `compare_municipalities(names: list[str]) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_tools_profile.py
ROWS = [
    {"municipality_id": 1, "name": "Pilar", "province": "Abra",     "region": "CAR",
     "final_score": 0.61, "geo_score": 0.66, "tier": "MEDIUM",
     "solar_irradiance": 5.0, "population": 10000, "pop_density": 120.0},
    {"municipality_id": 2, "name": "Pilar", "province": "Sorsogon", "region": "Region V",
     "final_score": 0.58, "geo_score": 0.60, "tier": "MEDIUM",
     "solar_irradiance": 5.1, "population": 70000, "pop_density": 200.0},
    {"municipality_id": 3, "name": "Jolo",  "province": "Sulu",     "region": "BARMM",
     "final_score": 0.84, "geo_score": 0.96, "tier": "MEDIUM",
     "solar_irradiance": 5.5, "population": 137000, "pop_density": 900.0},
]


def _patch(monkeypatch, refresh_result="row"):
    import agents.chat_tools as ct
    import agents.refresh as refresh_mod
    monkeypatch.setattr(ct, "get_latest_scored_municipalities", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(ct, "get_score_breakdown", lambda mid: {"geo": {"geo_score": 0.9}})
    calls = []

    def fake_refresh(mid):
        calls.append(mid)
        return dict(next(r for r in ROWS if r["municipality_id"] == mid)) if refresh_result == "row" else None

    monkeypatch.setattr(refresh_mod, "maybe_refresh_assessment", fake_refresh)
    return calls


def test_profile_resolves_and_triggers_refresh(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    calls = _patch(monkeypatch)
    out = get_municipality_profile("Jolo")
    assert calls == [3]                       # lazy re-synthesis fired
    assert out["profile"]["name"] == "Jolo"
    assert out["score_breakdown"] == {"geo": {"geo_score": 0.9}}


def test_profile_ambiguous_name_returns_candidates(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    out = get_municipality_profile("Pilar")
    assert "error" in out
    assert {c["province"] for c in out["candidates"]} == {"Abra", "Sorsogon"}


def test_profile_disambiguated_by_province(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    out = get_municipality_profile("Pilar", province="Abra")
    assert out["profile"]["province"] == "Abra"


def test_profile_unknown_name(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    assert "error" in get_municipality_profile("Atlantis")


def test_profile_survives_refresh_returning_none(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch, refresh_result=None)
    out = get_municipality_profile("Jolo")
    assert out["profile"]["name"] == "Jolo"   # falls back to the unrefreshed row


def test_compare_splits_name_comma_province(monkeypatch):
    from agents.chat_tools import compare_municipalities
    _patch(monkeypatch)
    out = compare_municipalities(["Jolo", "Pilar, Abra"])
    assert len(out["comparison"]) == 2
    assert out["comparison"][0]["profile"]["name"] == "Jolo"
    assert out["comparison"][1]["profile"]["province"] == "Abra"


def test_compare_rejects_wrong_count(monkeypatch):
    from agents.chat_tools import compare_municipalities
    _patch(monkeypatch)
    assert "error" in compare_municipalities(["Jolo"])
    assert "error" in compare_municipalities([f"m{i}" for i in range(7)])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chat_tools_profile.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_municipality_profile'`

- [ ] **Step 3: Implement — append to `agents/chat_tools.py`** (before the `TOOLS` list; then extend `TOOLS` and `_EXECUTORS` as shown)

```python
def _resolve_municipality(name: str, province: str | None, rows: list[dict]) -> list[dict]:
    frag = name.strip().lower()
    matches = [r for r in rows if r["name"].lower() == frag]
    if province and matches:
        resolved, _ = _resolve_province(province, rows)
        if resolved:
            matches = [r for r in matches if r["province"] == resolved]
        else:
            pfrag = province.strip().lower()
            matches = [r for r in matches if pfrag in r["province"].lower()]
    return matches


def get_municipality_profile(name: str, province: str | None = None) -> dict:
    rows = get_latest_scored_municipalities()
    matches = _resolve_municipality(name, province, rows)
    if not matches:
        where = f" in a province matching {province!r}" if province else ""
        return {"error": f"No municipality named {name!r} found{where}."}
    if len(matches) > 1:
        return {"error": f"{len(matches)} municipalities are named {name!r}.",
                "candidates": [{"name": m["name"], "province": m["province"]} for m in matches],
                "hint": "Retry with the province parameter, or ask the user which one."}
    m = matches[0]
    # Call-time import: agents.refresh imports from agents.chatbot at load
    # time, and agents.chatbot imports this module at load time.
    from agents.refresh import maybe_refresh_assessment
    detail = maybe_refresh_assessment(m["municipality_id"]) or m
    return {"profile": detail,
            "score_breakdown": get_score_breakdown(m["municipality_id"])}


def compare_municipalities(names: list[str]) -> dict:
    if not isinstance(names, list) or not 2 <= len(names) <= 6:
        return {"error": "Provide a list of 2 to 6 municipality names. "
                         "Use 'Name, Province' to disambiguate (e.g. 'Pilar, Abra')."}
    comparison = []
    for raw in names:
        if "," in raw:
            nm, prov = raw.split(",", 1)
            entry = get_municipality_profile(nm.strip(), prov.strip())
        else:
            entry = get_municipality_profile(raw.strip())
        comparison.append({"query": raw, **entry})
    return {"comparison": comparison}
```

Extend `TOOLS`:

```python
TOOLS += [
    {
        "name": "get_municipality_profile",
        "description": (
            "Full current profile of one municipality: solar opportunity score, geo score, "
            "tier, AI assessment, opportunity/risk, and a transparent score breakdown. "
            "Automatically refreshes a stale assessment first. If the bare name is ambiguous "
            "(several municipalities share it) you get back a candidate list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Municipality name, e.g. 'Jolo'"},
                "province": {"type": "string", "description": "Optional province to disambiguate"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "compare_municipalities",
        "description": "Side-by-side profiles of 2–6 municipalities. "
                       "Use 'Name, Province' entries to disambiguate shared names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"},
                          "description": "e.g. ['Jolo', 'Pilar, Abra']"},
            },
            "required": ["names"],
        },
    },
]

_EXECUTORS.update({
    "get_municipality_profile": get_municipality_profile,
    "compare_municipalities": compare_municipalities,
})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_chat_tools_profile.py tests/test_chat_tools_ranking.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add agents/chat_tools.py tests/test_chat_tools_profile.py
git commit -m "feat: profile + compare chat tools with lazy re-synthesis preserved

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `search_kb` tool + province-filtered retrieval + metadata at index time

**Files:**
- Modify: `agents/chat_tools.py`
- Modify: `agents/chatbot.py` (`retrieve_context` signature at `agents/chatbot.py:163`; intel-indexing metadata at `agents/chatbot.py:105`)
- Test: `tests/test_chat_tools_search.py`

**Interfaces:**
- Consumes: `agents.chatbot.retrieve_context` (call-time import), Task 1's `province_slug_map`, `_resolve_province`.
- Produces:
  - `search_kb(query: str, province: str | None = None) -> dict`
  - Changed signature: `retrieve_context(query: str, n_results: int = 10, province: str | None = None) -> str` (backward-compatible — existing callers pass no `province`).
  - Intel chunks indexed from now on carry metadata `{"source": <path>, "province": <canonical name or "">}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_tools_search.py
def test_search_kb_passes_province_filter(monkeypatch):
    import agents.chat_tools as ct
    import agents.chatbot as chatbot_mod
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"}])
    seen = {}

    def fake_retrieve(query, n_results=10, province=None):
        seen.update(query=query, province=province)
        return "chunks"

    monkeypatch.setattr(chatbot_mod, "retrieve_context", fake_retrieve)
    out = ct.search_kb("poverty conditions", province="sulu")
    assert out == {"results": "chunks"}
    assert seen["province"] == "Sulu"          # canonicalized, not raw fragment


def test_search_kb_without_province(monkeypatch):
    import agents.chat_tools as ct
    import agents.chatbot as chatbot_mod
    monkeypatch.setattr(chatbot_mod, "retrieve_context",
                        lambda query, n_results=10, province=None: f"p={province}")
    assert ct.search_kb("solar trends") == {"results": "p=None"}


def test_search_kb_ambiguous_province(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "A", "province": "Davao del Sur"},
                                 {"municipality_id": 2, "name": "B", "province": "Davao Oriental"}])
    out = ct.search_kb("anything", province="davao")
    assert "error" in out and len(out["candidates"]) == 2


def test_retrieve_context_builds_where_clause(monkeypatch):
    import agents.chatbot as chatbot_mod
    captured = {}

    class FakeCollection:
        def query(self, **kwargs):
            captured.update(kwargs)
            return {"documents": [["doc1"]], "metadatas": [[{"source": "kb/intel/x.md"}]]}

    monkeypatch.setattr(chatbot_mod, "_get_collection", lambda: FakeCollection())
    chatbot_mod.retrieve_context("q", province="Sulu")
    assert captured["where"] == {"province": "Sulu"}


def test_retrieve_context_no_filter_omits_where(monkeypatch):
    import agents.chatbot as chatbot_mod
    calls = []

    class FakeCollection:
        def query(self, **kwargs):
            calls.append(kwargs)
            return {"documents": [["doc1"]], "metadatas": [[{"source": "kb/intel/x.md"}]]}

    monkeypatch.setattr(chatbot_mod, "_get_collection", lambda: FakeCollection())
    chatbot_mod.retrieve_context("q")
    assert "where" not in calls[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chat_tools_search.py -v`
Expected: FAIL — `AttributeError: module 'agents.chat_tools' has no attribute 'search_kb'`

- [ ] **Step 3a: Implement `search_kb` in `agents/chat_tools.py`** (append; extend `TOOLS`/`_EXECUTORS`)

```python
def search_kb(query: str, province: str | None = None) -> dict:
    # Call-time import — agents.chatbot imports this module at load time.
    import agents.chatbot as chatbot_mod
    resolved = None
    if province:
        rows = get_latest_scored_municipalities()
        resolved, candidates = _resolve_province(province, rows)
        if resolved is None:
            return {"error": f"Ambiguous or unknown province {province!r}.",
                    "candidates": candidates}
    return {"results": chatbot_mod.retrieve_context(query, n_results=8, province=resolved)}
```

```python
TOOLS += [
    {
        "name": "search_kb",
        "description": (
            "Semantic search over generated province reports and municipality intelligence "
            "profiles. Use for narrative context: assessments, risks, opportunities, web "
            "intelligence, poverty/economic conditions. NOT authoritative for rankings or "
            "exact scores — use get_top_municipalities / get_municipality_profile for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "province": {"type": "string", "description": "Optional: restrict results to one province"},
            },
            "required": ["query"],
        },
    },
]
_EXECUTORS["search_kb"] = search_kb
```

- [ ] **Step 3b: Modify `retrieve_context` in `agents/chatbot.py`**

Replace the signature and query call (currently `agents/chatbot.py:163-169`):

```python
def retrieve_context(query: str, n_results: int = 10, province: str | None = None) -> str:
    """
    Retrieve relevant chunks from ChromaDB for the user's query.
    Returns chunks with their source file noted so the LLM knows the provenance.
    Pass province to restrict results to chunks carrying that province metadata.
    """
    try:
        kwargs = {"query_texts": [query], "n_results": n_results}
        if province:
            kwargs["where"] = {"province": province}
        results = _get_collection().query(**kwargs)
```

(The rest of the function body is unchanged.)

- [ ] **Step 3c: Write province metadata for newly indexed intel chunks**

In `index_documents_from_kb()`, the intel-file loop (currently `agents/chatbot.py:91-107`) — replace the `collection.add(...)` metadata line:

```python
    # ── Municipality intel files from kb/intel/ (not in DB yet) ───────────
    from agents.chat_tools import province_slug_map
    slug_map = province_slug_map()
    for md_file in Path(config.KB_INTEL).glob("*.md"):
        doc_id = md_file.stem
        if f"{doc_id}_chunk_0" in existing_ids:
            continue
        text   = md_file.read_text(encoding="utf-8")
        chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        if not chunks:
            continue
        chunk_ids  = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        new_chunks = [(cid, c) for cid, c in zip(chunk_ids, chunks) if cid not in existing_ids]
        if new_chunks:
            province = slug_map.get(doc_id.split("__")[0], "")
            collection.add(
                documents=[c for _, c in new_chunks],
                ids=[cid for cid, _ in new_chunks],
                metadatas=[{"source": str(md_file), "province": province} for _ in new_chunks],
            )
            logger.info(f"Indexed {len(new_chunks)} chunks from {md_file.name}")
```

(`from agents.chat_tools import province_slug_map` is inside the function — `index_documents_from_kb` is imported by `agents.refresh` at its module load, keep load order safe.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_chat_tools_search.py tests/test_chat_tools_ranking.py tests/test_chat_tools_profile.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add agents/chat_tools.py agents/chatbot.py tests/test_chat_tools_search.py
git commit -m "feat: search_kb tool with province-filtered Chroma retrieval

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `run_sql_query` escape hatch

**Files:**
- Modify: `agents/chat_tools.py`
- Test: `tests/test_chat_tools_sql.py`

**Interfaces:**
- Consumes: `config.HELIO_DB`, Task 1's `SQL_ROW_CAP`, `TOOLS`, `_EXECUTORS`.
- Produces: `run_sql_query(sql: str) -> dict` with keys `columns, rows, row_count, truncated` on success or `error`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_tools_sql.py
import sqlite3

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"row{i}") for i in range(300)])
    conn.commit()
    conn.close()
    import config
    monkeypatch.setattr(config, "HELIO_DB", db)
    return db


def test_select_returns_rows(tmp_db):
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT id, name FROM t WHERE id < 3 ORDER BY id")
    assert out["columns"] == ["id", "name"]
    assert out["rows"] == [[0, "row0"], [1, "row1"], [2, "row2"]]
    assert out["row_count"] == 3 and out["truncated"] is False


def test_row_cap_applied(tmp_db):
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT * FROM t")
    assert out["row_count"] == 200 and out["truncated"] is True


def test_non_select_rejected_by_precheck(tmp_db):
    from agents.chat_tools import run_sql_query
    for sql in ["INSERT INTO t VALUES (999, 'x')",
                "UPDATE t SET name='x'",
                "DELETE FROM t",
                "DROP TABLE t",
                "PRAGMA journal_mode=DELETE"]:
        assert "error" in run_sql_query(sql), sql


def test_write_blocked_at_connection_level_even_if_precheck_fooled(tmp_db):
    # `SELECT` prefix trick with a second statement: sqlite3 refuses multiple
    # statements in execute(), and the connection is mode=ro besides.
    from agents.chat_tools import run_sql_query
    out = run_sql_query("SELECT 1; DROP TABLE t")
    assert "error" in out
    conn = sqlite3.connect(tmp_db)
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 300
    conn.close()


def test_sql_error_returned_not_raised(tmp_db):
    from agents.chat_tools import run_sql_query
    assert "error" in run_sql_query("SELECT * FROM no_such_table")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chat_tools_sql.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_sql_query'`

- [ ] **Step 3: Implement — append to `agents/chat_tools.py`** (extend `TOOLS`/`_EXECUTORS`)

```python
_SQL_SCHEMA_DOC = """Tables:
- municipalities(id, name, province, region, lat, lon, area_km2, population, income_class)
- geo_scores(municipality_id UNIQUE, solar_irradiance, solar_norm, income_score, pop_density, pop_density_norm, geo_score, computed_at)
- runs(id TEXT, location, province, status, created_at, completed_at, error)
- run_results(run_id, municipality_id, geo_score, web_score, final_score, tier, assessment, opportunities JSON, risks JSON, solar_irradiance, solar_yield_kwh, pop_density)
- web_intel_cache(municipality_id UNIQUE, business_count, avg_price_level, places_data JSON, tavily_snippets, web_score, fetched_at, expires_at)
- reports(run_id, province, municipality, slug, markdown, file_path, created_at)

CRITICAL STALENESS RULE: run_results holds MULTIPLE historical rows per
municipality, including superseded assessments. A row is CURRENT only when its
run has status='done' AND runs.completed_at >= geo_scores.computed_at for that
municipality; if several qualify, the one with the latest completed_at wins.
Prefer get_top_municipalities / get_municipality_profile — they already apply
this rule. Use this tool only for counts, filters, and aggregates they cannot
express."""


def run_sql_query(sql: str) -> dict:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.lower().startswith("select"):
        return {"error": "Only a single SELECT statement is allowed (read-only connection)."}
    conn = None
    try:
        conn = sqlite3.connect(f"file:{config.HELIO_DB}?mode=ro", uri=True)
        cur = conn.execute(stripped)
        rows = cur.fetchmany(SQL_ROW_CAP + 1)
        truncated = len(rows) > SQL_ROW_CAP
        rows = rows[:SQL_ROW_CAP]
        return {"columns": [d[0] for d in cur.description] if cur.description else [],
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
                "truncated": truncated}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn is not None:
            conn.close()
```

```python
TOOLS += [
    {
        "name": "run_sql_query",
        "description": ("Run one read-only SELECT against the project SQLite database, for "
                        "analytics the typed tools can't express (counts, filters, aggregates). "
                        f"Results capped at {SQL_ROW_CAP} rows.\n\n{_SQL_SCHEMA_DOC}"),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["sql"],
        },
    },
]
_EXECUTORS["run_sql_query"] = run_sql_query
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_chat_tools_sql.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/chat_tools.py tests/test_chat_tools_sql.py
git commit -m "feat: read-only run_sql_query escape hatch with staleness-rule docs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Agent loop in `chat()` — remove regex heuristics, add fallback

**Files:**
- Modify: `agents/chatbot.py`
- Modify: `tests/test_chatbot_refresh.py` (drop the superseded `chat()`-refresh test; keep the 3 `detect_municipality_id` tests)
- Test: `tests/test_chat_agent_loop.py`

**Interfaces:**
- Consumes: Task 1's `TOOLS` and `execute_tool` (module-level `from agents.chat_tools import TOOLS, execute_tool` in chatbot.py — safe: chat_tools has no load-time import of chatbot).
- Produces: `chat()` unchanged signature; new internals `_agent_loop(messages: list) -> str`, `_rag_fallback(user_message: str, chat_history: list) -> str`, `MAX_TOOL_ROUNDS = 5`.
- Deletes: `detect_province_ranking_query`, `_province_leaderboard_block`, `_exact_municipality_block`, `_RANKING_WORDS`, `_TOP_N`, the `maybe_refresh_assessment` wrapper, the `import re`, and the `from agents.db_store import get_latest_scored_municipalities` import if no longer used. Keeps `detect_municipality_id` (tested; harmless).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_agent_loop.py
import json


class _Block:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    """Feed a queue of responses; records every create() kwargs."""
    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.queue[0], Exception):
            raise self.queue.pop(0)
        return self.queue.pop(0)


def _wire(monkeypatch, queue):
    import agents.chatbot as chatbot_mod
    fake = _FakeMessages(queue)
    monkeypatch.setattr(chatbot_mod.client, "messages", fake)
    monkeypatch.setattr(chatbot_mod, "execute_tool",
                        lambda name, tool_input: json.dumps({"echo": name, "input": tool_input}))
    monkeypatch.setattr(chatbot_mod, "retrieve_context",
                        lambda query, n_results=10, province=None: "fallback-context")
    return fake, chatbot_mod


def test_loop_executes_tool_then_returns_text(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [
        _Resp([_Block("tool_use", id="t1", name="get_top_municipalities",
                      input={"metric": "final_score", "province": "Sulu"})]),
        _Resp([_Block("text", text="Jolo leads with 0.84.")]),
    ])
    reply, history = chatbot_mod.chat("top 5 in sulu", [], run_id="")
    assert reply == "Jolo leads with 0.84."
    # second call carried the tool_result back
    second = fake.calls[1]["messages"]
    assert second[-1]["role"] == "user"
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"
    # tools offered on every round
    assert fake.calls[0]["tools"] and fake.calls[1]["tools"]


def test_history_gets_only_text_turns(monkeypatch):
    _, chatbot_mod = _wire(monkeypatch, [
        _Resp([_Block("tool_use", id="t1", name="search_kb", input={"query": "x"})]),
        _Resp([_Block("text", text="answer")]),
    ])
    reply, history = chatbot_mod.chat("question", [{"role": "user", "content": "old"},
                                                   {"role": "assistant", "content": "old reply"}], run_id="")
    assert history == [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


def test_prior_history_sent_to_model(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [_Resp([_Block("text", text="hi")])])
    chatbot_mod.chat("follow-up", [{"role": "user", "content": "earlier q"},
                                   {"role": "assistant", "content": "earlier a"}], run_id="")
    sent = fake.calls[0]["messages"]
    assert sent[0]["content"] == "earlier q" and sent[1]["content"] == "earlier a"


def test_round_cap_forces_final_answer(monkeypatch):
    tool_resp = lambda: _Resp([_Block("tool_use", id="t", name="search_kb", input={"query": "x"})])
    fake, chatbot_mod = _wire(monkeypatch, [
        tool_resp(), tool_resp(), tool_resp(), tool_resp(), tool_resp(),   # 5 rounds of tool_use
        _Resp([_Block("text", text="best effort answer")]),                # forced final
    ])
    reply, _ = chatbot_mod.chat("q", [], run_id="")
    assert reply == "best effort answer"
    assert len(fake.calls) == 6


def test_gateway_failure_falls_back_to_rag(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [
        RuntimeError("gateway down"),
        _Resp([_Block("text", text="rag answer")]),
    ])
    reply, history = chatbot_mod.chat("q", [], run_id="")
    assert reply == "rag answer"
    # fallback call is toolless and context-stuffed
    assert "tools" not in fake.calls[1]
    assert "fallback-context" in fake.calls[1]["messages"][-1]["content"]


def test_total_failure_returns_apology_not_exception(monkeypatch):
    _, chatbot_mod = _wire(monkeypatch, [RuntimeError("down"), RuntimeError("still down")])
    reply, history = chatbot_mod.chat("q", [], run_id="")
    assert "couldn't generate a response" in reply
    assert history == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chat_agent_loop.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'execute_tool'` (chatbot.py doesn't import it yet)

- [ ] **Step 3: Rewrite `agents/chatbot.py`**

3a. Imports: delete `import re` and `from agents.db_store import get_latest_scored_municipalities`; add after the existing imports:

```python
from agents.chat_tools import TOOLS, execute_tool
```

3b. Delete these definitions entirely: `_RANKING_WORDS`, `_TOP_N`, `detect_province_ranking_query`, `_province_leaderboard_block`, `_exact_municipality_block`, `maybe_refresh_assessment` (the wrapper). Keep `detect_municipality_id` as-is.

3c. Replace `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = """You are a solar installation market intelligence assistant for a solar panel business in the Philippines.

You have tools that query the live project database and knowledge base:
- get_top_municipalities — authoritative rankings. ALWAYS use this for top/best/highest/lowest/worst questions; never rank from memory or from search results.
- get_municipality_profile — current scores, tier, and AI assessment for one municipality.
- compare_municipalities — side-by-side comparison of 2–6 municipalities.
- search_kb — semantic search over generated reports and profiles; use for narrative context (risks, opportunities, web intelligence, poverty/economic conditions).
- run_sql_query — read-only SELECT for counts, filters, and aggregates the other tools can't express; mind the staleness rule in its description.

Rules:
- Scores, rankings, and tiers must come from tool results — never invent, estimate, or rescale numbers.
- If a requested ranking basis is not in the database (e.g. poverty incidence), say so plainly and offer the nearest available metric or narrative context from search_kb.
- If a place name is ambiguous (e.g. "Davao"), ask the user which one they mean, or query each candidate.
- If the tools return no data for a question, say so honestly rather than guessing.
- Be direct and practical — your user is a business owner, not an analyst.
"""
```

3d. Replace the body of `chat()` and add the two helpers:

```python
MAX_TOOL_ROUNDS = 5


def _agent_loop(messages: list) -> str:
    """Run the tool-use loop. Raises on gateway failure (caller handles fallback)."""
    working = list(messages)
    response = None
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=config.CHATBOT_MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=working,
        )
        tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            break
        logger.info(f"[Chatbot] tool round: {[t.name for t in tool_uses]}")
        working.append({"role": "assistant", "content": response.content})
        working.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": t.id,
             "content": execute_tool(t.name, t.input)}
            for t in tool_uses
        ]})
    else:
        # Round cap hit — demand a final answer from what was gathered.
        working.append({"role": "user", "content":
                        "Answer now using only the data already gathered. Do not request more tools."})
        response = client.messages.create(
            model=config.CHATBOT_MODEL, max_tokens=4000,
            system=SYSTEM_PROMPT, tools=TOOLS, messages=working,
        )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return text or "I gathered data but couldn't finish composing an answer — please try rephrasing."


def _rag_fallback(user_message: str, chat_history: list) -> str:
    """Legacy single-call RAG path, used when the agent loop fails."""
    context = retrieve_context(user_message)
    messages = chat_history.copy()
    messages.append({
        "role":    "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}",
    })
    response = client.messages.create(
        model=config.CHATBOT_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return next(b.text for b in response.content if hasattr(b, "text"))


def chat(user_message: str, chat_history: list, run_id: str = "") -> tuple[str, list]:
    """
    Single turn of the chatbot.
    Returns (assistant_response, updated_chat_history).
    Persists both turns to DB if run_id is provided.
    Tool_use/tool_result blocks live only within this turn — history carries text only.
    """
    try:
        assistant_reply = _agent_loop(chat_history + [{"role": "user", "content": user_message}])
    except Exception as e:
        logger.warning(f"Agent loop failed ({e}); falling back to RAG-only path")
        try:
            assistant_reply = _rag_fallback(user_message, chat_history)
        except Exception as e2:
            return f"Sorry, I couldn't generate a response: {e2}", chat_history

    if run_id:
        from agents.db_store import save_chat_message
        save_chat_message(run_id, "user", user_message)
        save_chat_message(run_id, "assistant", assistant_reply)

    updated_history = chat_history + [
        {"role": "user",      "content": user_message},
        {"role": "assistant", "content": assistant_reply},
    ]
    return assistant_reply, updated_history
```

3e. In `tests/test_chatbot_refresh.py`: delete `test_chat_calls_refresh_when_municipality_named` (its behavior now lives in `tests/test_chat_tools_profile.py::test_profile_resolves_and_triggers_refresh`). Keep the three `detect_municipality_id` tests unchanged.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (139 existing − 1 removed + 30 new so far = 168). If any pre-existing test imports the deleted names (`grep -rn "detect_province_ranking_query\|_exact_municipality_block\|maybe_refresh_assessment" tests/`), update it to the new module layout before proceeding.

- [ ] **Step 5: Commit**

```bash
git add agents/chatbot.py tests/test_chat_agent_loop.py tests/test_chatbot_refresh.py
git commit -m "feat: chat() runs a tool-use agent loop; regex intent detection removed

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Province metadata backfill script + execution

**Files:**
- Create: `scripts/backfill_chroma_province.py`
- Test: `tests/test_backfill_province.py` (unit-tests the pure mapping helper only; the Chroma walk is exercised by the live run in Step 4)

**Interfaces:**
- Consumes: `agents.chatbot._get_collection()`, Task 1's `province_slug_map()`.
- Produces: standalone script; safe to re-run (skips chunks that already have `province`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill_province.py
def test_province_for_source():
    from scripts.backfill_chroma_province import province_for_source
    slug_map = {"sulu": "Sulu", "davao_del_sur": "Davao del Sur"}
    assert province_for_source("/x/kb/intel/sulu__jolo__4ff64ef9.md", slug_map) == "Sulu"
    assert province_for_source("/x/kb/intel/davao_del_sur__digos__ab.md", slug_map) == "Davao del Sur"
    assert province_for_source("/x/kb/intel/unknown_prov__town__ab.md", slug_map) is None
    assert province_for_source("db:reports:sulu_4ff64ef9", slug_map) is None      # not an intel file
    assert province_for_source("", slug_map) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_backfill_province.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_chroma_province'`

- [ ] **Step 3: Implement `scripts/backfill_chroma_province.py`**

```python
#!/usr/bin/env python3
"""
One-off backfill: add `province` metadata to existing kb/intel chunks in
ChromaDB so search_kb can filter by province. Idempotent — chunks that
already carry province metadata are skipped. Safe to re-run.

Run: python scripts/backfill_chroma_province.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

BATCH = 500


def province_for_source(source: str, slug_map: dict[str, str]) -> str | None:
    """Canonical province for an intel-file source path, else None."""
    if not source or "kb/intel" not in source:
        return None
    stem = Path(source).stem
    return slug_map.get(stem.split("__")[0])


def main() -> None:
    from agents.chatbot import _get_collection
    from agents.chat_tools import province_slug_map

    slug_map = province_slug_map()
    logger.info(f"Loaded {len(slug_map)} province slugs from DB")
    col = _get_collection()
    updated = skipped = unmatched = 0
    offset = 0
    while True:
        page = col.get(include=["metadatas"], limit=BATCH, offset=offset)
        ids, metas = page["ids"], page["metadatas"]
        if not ids:
            break
        upd_ids, upd_metas = [], []
        for cid, meta in zip(ids, metas):
            meta = dict(meta or {})
            if meta.get("province"):
                skipped += 1
                continue
            province = province_for_source(meta.get("source", ""), slug_map)
            if province is None:
                if "kb/intel" in meta.get("source", ""):
                    unmatched += 1
                    logger.warning(f"No province match for {meta.get('source')}")
                else:
                    skipped += 1
                continue
            meta["province"] = province
            upd_ids.append(cid)
            upd_metas.append(meta)
        if upd_ids:
            col.update(ids=upd_ids, metadatas=upd_metas)
            updated += len(upd_ids)
        offset += len(ids)
        logger.info(f"...scanned {offset} chunks (updated so far: {updated})")
    logger.info(f"Backfill complete: updated={updated} skipped={skipped} unmatched={unmatched}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run unit test, then the live backfill, then verify filtering works**

```bash
python3 -m pytest tests/test_backfill_province.py -v          # expected: 1 passed
python3 scripts/backfill_chroma_province.py                    # expect updated ≈ intel-chunk count, unmatched ≈ 0
python3 - <<'EOF'
from agents.chatbot import _get_collection
col = _get_collection()
res = col.query(query_texts=["solar opportunity"], n_results=5, where={"province": "Sulu"})
sources = [m.get("source", "") for m in res["metadatas"][0]]
assert sources and all("sulu__" in s for s in sources), sources
print("province filter OK:", sources)
EOF
```

Expected: the assertion passes — every filtered result is a Sulu intel chunk. If `unmatched` is large, inspect the logged slugs; province naming drift between `runs.location` values and `municipalities.province` (e.g. "City of Davao (Not a Province)") is expected for a handful of files — acceptable, those chunks simply stay unfiltered.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_chroma_province.py tests/test_backfill_province.py
git commit -m "feat: backfill province metadata onto existing ChromaDB intel chunks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Live end-to-end verification

**Files:**
- None created (verification only; fixes go in the file they belong to).

**Interfaces:**
- Consumes: everything above, plus the live MiMo gateway and production `data/helio.db`.

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest tests/ -q`
Expected: all tests pass, 0 failures.

- [ ] **Step 2: Live smoke — the original bug's exact query**

```bash
python3 - <<'EOF'
from agents.chatbot import chat
reply, _ = chat("give me top 5 opportunities in sulu that I should prioritize", [], run_id="")
print(reply)
EOF
```

Expected: the reply names Jolo, Siasi, Indanan, Patikul, Talipao (the true DB top 5 by final_score) — NOT Panglima Estino/Kalingalan Caluang/Old Panamao/Pangutaran, and no fabricated "35.10"-style scores. If the model asked a clarifying question instead, re-run once; if it still fails, debug with `logger` output showing which tools were called.

- [ ] **Step 3: Live smoke — the failure modes the regex patch couldn't handle**

Run each through the same snippet, checking the described behavior:

| Query | Expected behavior |
|---|---|
| `"top 3 in davao"` | Asks which Davao province, or presents all candidates — no garbage ranking |
| `"which is better, Jolo or Siasi?"` | Compares both with real final_scores (0.84 vs 0.79) |
| `"top 5 lowest poverty in Sulu"` | States poverty is not a database metric; offers narrative context or an alternative metric — does NOT return a final_score list dressed as poverty |
| `"worst 5 municipalities in Sulu"` | Ascending final_score ranking (Hadji Panglima Tahil ≈ 0.518 at rank 1) |
| `"how many municipalities have a final score above 0.7?"` | A count from run_sql_query or the ranking tool — a specific number, not a guess |
| `"tell me about Pilar"` (multi-turn: then `"the one in Abra"`) | First turn asks which Pilar; second turn resolves via history |

- [ ] **Step 4: Streamlit sanity check**

Run: `streamlit run app.py` — open the chat panel, send "top 5 opportunities in Sulu", confirm the reply matches the DB leaderboard and the UI renders normally (no signature/API drift).

- [ ] **Step 5: Update docs and commit**

Add a line to `session-notes.md` under today's date describing the change (tool-use agent loop, five tools, backfill). Then:

```bash
git add session-notes.md
git commit -m "docs: session notes for chatbot tool-use retrieval rollout

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
