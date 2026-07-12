"""
Agent 5: Chatbot (RAG over generated KB)
The KB is built from reports and intel summaries written by Agents 3 and 4.
Uses ChromaDB as the vector store and Claude as the response model.

KB grows automatically after every pipeline run — the more locations
you process, the richer the chatbot's answers become.
"""

import re
from pathlib import Path
from loguru import logger
import anthropic
import chromadb
from chromadb.utils import embedding_functions

import config
from graph.state import SolarLeadState
from agents.db_store import get_latest_scored_municipalities

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


def maybe_refresh_assessment(municipality_id: int):
    """Thin wrapper around agents.refresh.maybe_refresh_assessment.

    The import is deferred to call time (rather than module load time) to
    avoid a circular import: agents.refresh imports index_documents_from_kb
    from this module at its own module load time, so this module can only
    reach back into agents.refresh once both modules have finished loading.
    Kept as a module-level name (rather than a local import inside chat())
    so it stays monkeypatchable via `chatbot_mod.maybe_refresh_assessment`.
    """
    from agents.refresh import maybe_refresh_assessment as _maybe_refresh_assessment
    return _maybe_refresh_assessment(municipality_id)


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


_RANKING_WORDS = re.compile(
    r"\btop\s*\d*\b|\bbest\b|\bpriorit\w*\b|\brank\w*\b|\bhighest\b", re.IGNORECASE
)
_TOP_N = re.compile(r"\btop\s*(\d+)\b", re.IGNORECASE)


def detect_province_ranking_query(message: str, municipalities: list[dict]) -> tuple[str | None, int]:
    """If the message asks to rank/prioritize locations within a specific province,
    return (province, n) — n from "top N" phrasing, default 5. Otherwise (None, 0).

    Pure semantic search (retrieve_context) can't be trusted for this: with ~29k
    similarly-worded chunks in the KB, it returns whatever 10 chunks are nearest
    by embedding to the query text — not all of a province's municipalities, and
    not sorted by score. See _exact_municipality_block for the same problem at
    single-municipality granularity.
    """
    if not _RANKING_WORDS.search(message):
        return None, 0
    lower_message = message.lower()
    best: tuple[int, str] | None = None  # (name length, province)
    for province in {m["province"] for m in municipalities}:
        if province and province.lower() in lower_message:
            if best is None or len(province) > best[0]:
                best = (len(province), province)
    if best is None:
        return None, 0
    m = _TOP_N.search(message)
    n = int(m.group(1)) if m else 5
    return best[1], n


def _province_leaderboard_block(province: str, municipalities: list[dict], n: int) -> str:
    """Authoritative current-data ranking for a province, built straight from the
    DB and sorted by final_score — the same source as the map/table."""
    rows = [m for m in municipalities if m["province"] == province]
    scored = sorted(
        (r for r in rows if r["final_score"] is not None),
        key=lambda r: r["final_score"],
        reverse=True,
    )
    lines = [f"[Current Live Data — Top {n} Opportunities in {province} by Solar Opportunity Score]"]
    lines.append(f"({len(scored)} of {len(rows)} municipalities in {province} have a full assessment)")
    for i, r in enumerate(scored[:n], 1):
        lines.append(
            f"{i}. {r['name']} — Solar Opportunity Score: {r['final_score']:.3f}, "
            f"Tier: {r['tier']}, Geo Score: {r['geo_score']:.3f}"
        )
    return "\n".join(lines)


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

You have access to analyzed data on municipalities including:
- Solar irradiance potential
- Population and income signals
- Business density and economic activity
- Ranked opportunity scores and sales tier classifications

Answer questions about target areas, comparisons between locations, sales strategy, and solar potential.
If the context doesn't contain enough information, say so honestly rather than guessing.

Always be direct and practical — your user is a business owner, not an analyst.
"""


def _exact_municipality_block(row: dict) -> str:
    """Authoritative current-data block for a municipality the user explicitly
    named, built straight from the DB (same source as the map/table) rather
    than relying on semantic ChromaDB ranking — with ~29k similarly-worded
    profile chunks in the KB, pure similarity search doesn't reliably surface
    the one exact-name match (e.g. "Pilar, Abra" losing to other Pilars or
    other Abra towns). See docs/superpowers/specs — parked 2026-07-12."""
    lines = [f"[Current Live Data — {row['name']}, {row['province']}]"]
    lines.append(
        f"Geo Score: {row['geo_score']:.3f}" if row["geo_score"] is not None
        else "Geo Score: not available"
    )
    if row["final_score"] is not None:
        lines.append(f"Solar Opportunity Score: {row['final_score']:.3f}")
        lines.append(f"Tier: {row['tier']}")
        if row["assessment"]:
            lines.append(f"Assessment: {row['assessment']}")
        if row["opportunities"]:
            lines.append(f"Opportunity: {row['opportunities'][0]}")
        if row["risks"]:
            lines.append(f"Risk: {row['risks'][0]}")
    else:
        lines.append("This municipality does not yet have a full AI assessment (geo-score only).")
    return "\n".join(lines)


def chat(user_message: str, chat_history: list, run_id: str = "") -> tuple[str, list]:
    """
    Single turn of the chatbot.
    Returns (assistant_response, updated_chat_history).
    Persists both turns to DB if run_id is provided.
    """
    municipalities = get_latest_scored_municipalities()
    municipality_id = detect_municipality_id(user_message, municipalities)
    exact_block = None
    if municipality_id is not None:
        detail = maybe_refresh_assessment(municipality_id)
        if detail is not None:
            exact_block = _exact_municipality_block(detail)

    ranking_province, ranking_n = detect_province_ranking_query(user_message, municipalities)
    leaderboard_block = None
    if ranking_province is not None:
        leaderboard_block = _province_leaderboard_block(ranking_province, municipalities, ranking_n)

    context = retrieve_context(user_message)
    if leaderboard_block:
        context = f"{leaderboard_block}\n\n---\n\n{context}"
    if exact_block:
        context = f"{exact_block}\n\n---\n\n{context}"
    messages = chat_history.copy()
    messages.append({
        "role":    "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}",
    })

    try:
        response = client.messages.create(
            model=config.CHATBOT_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant_reply = next(b.text for b in response.content if hasattr(b, "text"))

        if run_id:
            from agents.db_store import save_chat_message
            save_chat_message(run_id, "user", user_message)
            save_chat_message(run_id, "assistant", assistant_reply)

        updated_history = chat_history + [
            {"role": "user",      "content": user_message},
            {"role": "assistant", "content": assistant_reply},
        ]
        return assistant_reply, updated_history

    except Exception as e:
        error_msg = f"Sorry, I couldn't generate a response: {e}"
        return error_msg, chat_history
