# Chatbot Tool-Use Retrieval — Design

**Date:** 2026-07-12
**Status:** Approved
**Supersedes:** the regex intent-detection approach in `agents/chatbot.py`
(`detect_province_ranking_query`, `_province_leaderboard_block`,
`_exact_municipality_block` injection), parked spec note of 2026-07-12.

## Problem

The chatbot answers structured questions ("top 5 opportunities in Sulu") from
pure ChromaDB semantic similarity. With ~29k similarly-worded profile chunks,
retrieval returns whichever 10 chunks embed nearest to the query — not all of
a province's municipalities, not sorted by score — and the LLM invents a
ranking (and scores) from incomplete context. Verified live: the Sulu query
returned 4 of 19 municipalities plus lookalikes (Sulop, Sual, Sultan Kudarat),
and none of the true top 5 (Jolo 0.842, Siasi 0.791, Indanan 0.784,
Patikul 0.773, Talipao 0.749).

A regex patch (province + ranking-word detection → inject DB leaderboard)
fixed the reported case but validation probes showed it is brittle:

- **Wrong-metric hazard:** "top 5 lowest poverty in Sulu" injects a
  final_score leaderboard — confidently wrong.
- Partial province names fail: "davao", "zamboanga", "negros", "Metro Manila".
- Nationwide/region rankings fall through to semantic garbage.
- Comparisons ("which is better, Jolo or Siasi?") unhandled.
- Inverse/filtered queries ("worst 5", "high tier in Abra") unhandled.

## Decision

Replace context-stuffing heuristics with an **LLM tool-use agent loop**.
Feasibility confirmed live: the MiMo gateway (`mimo-v2.5` via Anthropic-compatible
API) accepts `tools` and correctly emitted
`get_top_municipalities(n=5, metric='final_score', province='Sulu')`.

## Architecture

`chat(user_message, chat_history, run_id) -> (reply, updated_history)` keeps
its exact signature — **no `app.py` changes, no DB schema changes.**

Inside, an agent loop:

1. Send system prompt + history + user message + tool definitions.
2. While the response contains `tool_use` blocks (cap: **5 rounds**):
   execute each against SQLite/Chroma, append `tool_result` blocks, re-send.
3. Final text block is the reply.

Removed: `detect_province_ranking_query`, `_province_leaderboard_block`,
`_exact_municipality_block`, and the `detect_municipality_id` →
`maybe_refresh_assessment` pre-call in `chat()`. The `detect_municipality_id`
function itself is kept (used by name-resolution inside the profile tool and
covered by existing tests); only its call site in `chat()` goes away.

Preserved side effect: **lazy re-synthesis** moves inside the profile tool —
`get_municipality_profile` calls `maybe_refresh_assessment(municipality_id)`
before returning, so stale assessments still refresh when asked about.

## Tools

| Tool | Backs onto | Behavior |
|---|---|---|
| `get_top_municipalities(province?, region?, n=5, metric, ascending=false)` | `get_latest_scored_municipalities()` | `metric` enum limited to columns that exist: `final_score`, `geo_score`, `solar_irradiance`, `population`, `pop_density`. Rows with NULL metric excluded; result notes "X of Y municipalities assessed". Fuzzy province resolution: an ambiguous name ("davao") returns the candidate province list so the model can clarify with the user or query each. No province/region = nationwide. |
| `get_municipality_profile(name, province?)` | `maybe_refresh_assessment()` + `get_score_breakdown()` | Full current row: scores, tier, assessment, opportunity/risk, score breakdown. Ambiguous bare names (multiple Pilars) return the candidate list. |
| `compare_municipalities(names[])` | batch of profiles | Side-by-side rows for 2–6 municipalities; each entry resolves like `get_municipality_profile`. |
| `search_kb(query, province?)` | `retrieve_context()` + Chroma `where` filter | Semantic search over reports + intel profiles, optionally filtered by province metadata. For narrative color: assessments, risks, web intel, poverty context. |

**Honesty rule (system prompt + enum design):** metrics not in the DB (e.g.
poverty incidence) are not rankable. The model must use `search_kb` for
narrative mentions and say the ranking basis is unavailable — never rank on
fabricated numbers.

## Province metadata backfill (included)

Intel chunks currently carry only `{"source": path}`; province is derivable
from the filename slug (`<province>__<municipality>__<runid>.md`). One-off
script `scripts/backfill_chroma_province.py`:

- Iterate collection in batches; for chunks whose metadata lacks `province`,
  parse the slug, map to the canonical province name (via
  `municipalities.province` distinct values; slugify to match), and
  `collection.update(ids, metadatas)`.
- Idempotent; logs count updated/skipped/unmatched.
- `index_documents_from_kb()` updated to write `province` metadata on intel
  chunks going forward.

## History & multi-turn

- Prior user/assistant **text turns flow into `messages` unchanged** —
  multi-turn follow-ups ("what about Basilan?") work as today.
- `tool_use`/`tool_result` blocks live only within the current turn; they are
  not persisted to `chat_history` or the `chat_messages` table. The model
  re-fetches if it needs the same data — always answering from fresh DB state.

## Error handling

- Tool executor never raises: failures return `{"error": "..."}` as the
  `tool_result` so the model can recover or apologize.
- Round cap reached → force a final text answer from data gathered so far.
- Gateway/API failure at any point → fall back to the legacy single-call RAG
  path (`retrieve_context` + one `messages.create`), so the chatbot degrades
  rather than dies. Errors logged via loguru.

## Testing

- Unit tests per tool executor with monkeypatched `db_store` (ranking order,
  ascending, NULL exclusion, ambiguous-province candidates, metric enum).
- Agent-loop test: fake Anthropic client emits `tool_use` then text; assert
  execution, `tool_result` round-trip, and round cap.
- Regression test for the Sulu case: ranking tool returns DB order; final
  reply built from it.
- Fallback test: client raises on first call → legacy RAG path used.
- Existing suite (139 tests) stays green; `test_chatbot_refresh.py` updated
  for the refresh-inside-tool contract.

## Out of scope

- Streaming responses in the Streamlit UI.
- Persisting tool payloads to the DB.
- New DB columns/metrics (poverty incidence ingestion is a separate project).
