"""
Agent 5: Chatbot (tool-use agent over the project DB + generated KB)
Reports and intel profiles are written by Agents 3/4/kb_builder to
kb/reports/ and kb/intel/, indexed in the kb_docs DB table (see
agents/db_store.py::register_kb_doc). There is no vector store: scope is
always resolved to a province (and optionally a municipality) first, then
the matching markdown is loaded straight off disk for the LLM to read —
see agents/chat_tools.py::search_kb.
"""

from loguru import logger
import anthropic

import config
from graph.state import SolarLeadState
from agents.chat_tools import TOOLS, execute_tool

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)


def detect_municipality_id(message: str, municipalities: list[dict]) -> int | None:
    """Return the municipality_id of the longest municipality name found in message, or None."""
    lower_message = message.lower()
    best: tuple[int, int] | None = None  # (name length, municipality_id)
    for m in municipalities:
        name = m["name"]
        if name.lower() in lower_message:
            if best is None or len(name) > best[0]:
                best = (len(name), m["municipality_id"])
    return best[1] if best else None


def update_kb_node(state: SolarLeadState) -> SolarLeadState:
    """LangGraph node: triggered after report_gen. Builds per-municipality docs,
    which registers each one into the kb_docs table as it's written (see
    agents/kb_builder.py::save_municipality_docs) — no separate indexing step."""
    logger.info("[Agent 5] Updating knowledge base...")
    try:
        final_scores = state.get("final_scores") or {}
        web_intel = state.get("web_intel") or {}
        if final_scores:
            from agents.kb_builder import save_municipality_docs
            save_municipality_docs(
                location=state["location"],
                final_scores=final_scores,
                web_intel=web_intel,
                run_id=state["run_id"],
            )
        logger.info("[Agent 5] KB update complete — pipeline finished.")
        return {**state, "kb_updated": True}
    except Exception as e:
        logger.error(f"KB update failed: {e}")
        return {**state, "kb_updated": False, "errors": state["errors"] + [str(e)]}


# ── Chatbot ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a solar installation market intelligence assistant for a solar panel business in the Philippines.

You have tools that query the live project database and knowledge base:
- get_top_municipalities — authoritative rankings. ALWAYS use this for top/best/highest/lowest/worst questions; never rank from memory or from search results.
- get_municipality_profile — current scores, tier, and AI assessment for one municipality.
- compare_municipalities — side-by-side comparison of 2–6 municipalities.
- search_kb — loads the current province report and municipality intel profile(s) for a given scope (province, optionally narrowed to one municipality); use for narrative context (risks, opportunities, web intelligence, poverty/economic conditions).
- run_sql_query — read-only SELECT for counts, filters, and aggregates the other tools can't express; mind the staleness rule in its description.

Rules:
- Scores, rankings, and tiers must come from tool results — never invent, estimate, or rescale numbers.
- If a requested ranking basis is not in the database (e.g. poverty incidence), say so plainly and offer the nearest available metric or narrative context from search_kb.
- If a place name is ambiguous (e.g. "Davao"), ask the user which one they mean, or query each candidate.
- If the tools return no data for a question, say so honestly rather than guessing.
- Be direct and practical — your user is a business owner, not an analyst.
"""

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
        # IMPORTANT: fold the instruction into the trailing user message's content
        # list rather than appending a brand-new user message. The for-loop's
        # last iteration always leaves `working` ending in a user message (the
        # tool_result block just appended above), so appending another
        # {"role": "user", ...} would create two consecutive user-role messages,
        # which most Anthropic-compatible gateways (including MiMo) reject.
        instruction = {
            "type": "text",
            "text": "Answer now using only the data already gathered. Do not request more tools.",
        }
        if working and working[-1]["role"] == "user":
            working[-1]["content"].append(instruction)
        else:
            # Defensive fallback for MAX_TOOL_ROUNDS == 0 or other edge cases
            # where the last message isn't a user message.
            working.append({"role": "user", "content": [instruction]})
        response = client.messages.create(
            model=config.CHATBOT_MODEL, max_tokens=4000,
            system=SYSTEM_PROMPT, messages=working,
        )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return text or "I gathered data but couldn't finish composing an answer — please try rephrasing."


def _toolless_fallback(user_message: str, chat_history: list) -> str:
    """Degraded single-call path used when the tool-use agent loop fails
    (e.g. gateway error). No tools, no KB context — just the plain
    conversation, so the user still gets a best-effort reply."""
    messages = chat_history + [{"role": "user", "content": user_message}]
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
        logger.warning(f"Agent loop failed ({e}); falling back to toolless path")
        try:
            assistant_reply = _toolless_fallback(user_message, chat_history)
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
