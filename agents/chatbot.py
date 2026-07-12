"""
Agent 5: Chatbot (RAG over generated KB)
The KB is built from reports and intel summaries written by Agents 3 and 4.
Uses ChromaDB as the vector store and Claude as the response model.

KB grows automatically after every pipeline run — the more locations
you process, the richer the chatbot's answers become.
"""

from pathlib import Path
from loguru import logger
import anthropic
import chromadb
from chromadb.utils import embedding_functions

import config
from graph.state import SolarLeadState
from agents.chat_tools import TOOLS, execute_tool

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)

# ChromaDB setup
_chroma_client = chromadb.PersistentClient(path=str(config.KB_INDEX))
_embed_fn = embedding_functions.OllamaEmbeddingFunction(
    model_name=config.OLLAMA_EMBED_MODEL,
    url=config.OLLAMA_URL,
)

# Marker file records which embedding model built the current index.
# If it differs from config, the collection is wiped and recreated.
_EMBED_MARKER = config.KB_INDEX / ".embed_model"


def _get_collection() -> chromadb.Collection:
    """Return the ChromaDB collection, recreating it if the embedding model changed."""
    stored = _EMBED_MARKER.read_text().strip() if _EMBED_MARKER.exists() else None
    if stored != config.OLLAMA_EMBED_MODEL:
        logger.info(
            f"Embedding model changed ({stored!r} → {config.OLLAMA_EMBED_MODEL!r}). "
            "Wiping and recreating ChromaDB collection..."
        )
        try:
            _chroma_client.delete_collection("solar_lead_kb")
        except Exception:
            pass
        _EMBED_MARKER.write_text(config.OLLAMA_EMBED_MODEL)
    return _chroma_client.get_or_create_collection(
        name="solar_lead_kb",
        embedding_function=_embed_fn,
    )


_collection = _get_collection()


# ── KB Management ──────────────────────────────────────────────────────────────

def index_documents_from_kb() -> None:
    """
    Index reports from the DB and municipality intel files from kb/intel/.
    Skips already-indexed doc IDs — safe to call repeatedly.
    """
    from agents.db_store import list_reports

    collection = _get_collection()              # always get fresh/current collection
    existing_ids = set(collection.get(include=[])["ids"])

    # ── Reports from DB ────────────────────────────────────────────────────
    for report in list_reports():
        doc_id = report["slug"]
        if f"{doc_id}_chunk_0" in existing_ids:
            continue
        text   = report.get("markdown", "")
        chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        if not chunks:
            continue
        chunk_ids  = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        new_chunks = [(cid, c) for cid, c in zip(chunk_ids, chunks) if cid not in existing_ids]
        if new_chunks:
            collection.add(
                documents=[c for _, c in new_chunks],
                ids=[cid for cid, _ in new_chunks],
                metadatas=[{
                    "source":   f"db:reports:{doc_id}",
                    "province": report.get("province", ""),
                } for _ in new_chunks],
            )
            logger.info(f"Indexed {len(new_chunks)} chunks from report {doc_id}")

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
    """LangGraph node: triggered after report_gen. Builds per-municipality docs then indexes."""
    logger.info("[Agent 5] Updating knowledge base...")
    try:
        # Generate structured per-municipality docs (scores + barangays + web intel)
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

        # Index everything (report + municipality docs)
        index_documents_from_kb()
        logger.info("[Agent 5] KB indexing complete — pipeline finished.")
        return {**state, "kb_updated": True}
    except Exception as e:
        logger.error(f"KB update failed: {e}")
        return {**state, "kb_updated": False, "errors": state["errors"] + [str(e)]}


# ── RAG Retrieval ──────────────────────────────────────────────────────────────

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
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        if not docs:
            return "No relevant information found in knowledge base."

        sections = []
        for doc, meta in zip(docs, metas):
            source = meta.get("source", "")
            label = ""
            if "kb/intel" in source:
                label = f"[Municipality Profile: {source.split('/')[-1].replace('.md','')}]\n"
            elif "kb/reports" in source or source.startswith("db:reports:"):
                label = f"[Province Report: {source.split(':')[-1].replace('.md','')}]\n"
            sections.append(f"{label}{doc}")

        return "\n\n---\n\n".join(sections)
    except Exception as e:
        logger.warning(f"Retrieval failed: {e}")
        return ""


# ── Chatbot ────────────────────────────────────────────────────────────────────

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
