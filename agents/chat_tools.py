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


def _resolve_field(fragment: str, rows: list[dict], field: str) -> tuple[str | None, list[str]]:
    """Exact case-insensitive match wins; else a unique substring match;
    else (None, candidates). Generic resolver for any string field (e.g.
    "province" or "region") whose values may be prefix-nested (region names
    like "Region XI (Davao Region)" and "Region XII (SOCCSKSARGEN)" would
    otherwise false-positive on plain substring matching)."""
    values = sorted({r[field] for r in rows if r[field]})
    frag = fragment.strip().lower()
    for v in values:
        if v.lower() == frag:
            return v, []
    candidates = [v for v in values if frag in v.lower()]
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


def _resolve_province(fragment: str, rows: list[dict]) -> tuple[str | None, list[str]]:
    return _resolve_field(fragment, rows, "province")


def _resolve_region(fragment: str, rows: list[dict]) -> tuple[str | None, list[str]]:
    return _resolve_field(fragment, rows, "region")


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
        resolved_region, candidates = _resolve_region(region, rows)
        if resolved_region is None:
            return {"error": f"Ambiguous or unknown region {region!r}.",
                    "candidates": candidates,
                    "hint": "Retry with one exact candidate name, or ask the user which they meant."}
        rows = [r for r in rows if r["region"] == resolved_region]
        scope = f"{scope} / {resolved_region}"
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
                "region": {"type": "string", "description": (
                    "Region name or fragment, e.g. 'BARMM' or 'Region XI'. Resolved by exact "
                    "match first, then by unique substring match — an ambiguous fragment (e.g. "
                    "one that matches both 'Region XI (Davao Region)' and 'Region XII "
                    "(SOCCSKSARGEN)') returns a candidates list instead of guessing."
                )},
                "n": {"type": "integer", "description": "How many rows to return (default 5, max 50)"},
                "metric": {"type": "string", "enum": RANKABLE_METRICS,
                           "description": "Ranking basis. final_score = overall solar opportunity score."},
                "ascending": {"type": "boolean", "description": "true for lowest-first ('worst 5')"},
            },
            "required": ["metric"],
        },
    },
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

_EXECUTORS: dict = {
    "get_top_municipalities": get_top_municipalities,
    "get_municipality_profile": get_municipality_profile,
    "compare_municipalities": compare_municipalities,
}
_EXECUTORS["search_kb"] = search_kb
_EXECUTORS["run_sql_query"] = run_sql_query


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
