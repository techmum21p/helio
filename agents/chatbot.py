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

client = anthropic.Anthropic(api_key=config.XIAOMI_API_KEY, base_url=config.XIAOMI_BASE_URL)

# ChromaDB setup
_chroma_client = chromadb.PersistentClient(path=str(config.KB_INDEX))
_embed_fn = embedding_functions.OllamaEmbeddingFunction(
    model_name="qwen3-embedding:0.6b",
    url="http://localhost:11434",
)
_collection = _chroma_client.get_or_create_collection(
    name="solar_lead_kb",
    embedding_function=_embed_fn,
)


# ── KB Management ──────────────────────────────────────────────────────────────

def index_documents_from_kb():
    """
    Scan kb/reports/ and kb/intel/ for new markdown files
    and add them to the ChromaDB collection.
    Skips already-indexed files using filename as doc ID.
    """
    existing_ids = set(_collection.get()["ids"])

    for kb_dir in [config.KB_REPORTS, config.KB_INTEL]:
        for md_file in Path(kb_dir).glob("*.md"):
            doc_id = md_file.stem
            if doc_id in existing_ids:
                continue

            text = md_file.read_text(encoding="utf-8")

            # Chunk by paragraph
            chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
            chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            already = set(_collection.get()["ids"])
            new_chunks = [(cid, chunk) for cid, chunk in zip(chunk_ids, chunks) if cid not in already]

            if new_chunks:
                _collection.add(
                    documents=[c for _, c in new_chunks],
                    ids=[cid for cid, _ in new_chunks],
                    metadatas=[{"source": str(md_file)} for _ in new_chunks],
                )
                logger.info(f"Indexed {len(new_chunks)} chunks from {md_file.name}")


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
        return {**state, "kb_updated": True}
    except Exception as e:
        logger.error(f"KB update failed: {e}")
        return {**state, "kb_updated": False, "errors": state["errors"] + [str(e)]}


# ── RAG Retrieval ──────────────────────────────────────────────────────────────

def retrieve_context(query: str, n_results: int = 10) -> str:
    """
    Retrieve relevant chunks from ChromaDB for the user's query.
    Returns chunks with their source file noted so the LLM knows the provenance.
    """
    try:
        results = _collection.query(query_texts=[query], n_results=n_results)
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
            elif "kb/reports" in source:
                label = f"[Province Report: {source.split('/')[-1].replace('.md','')}]\n"
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


def chat_stream(user_message: str, chat_history: list):
    """Generator yielding text chunks for streaming. Caller accumulates the full reply."""
    index_documents_from_kb()
    context = retrieve_context(user_message)

    messages = chat_history.copy()
    messages.append({
        "role": "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}",
    })

    try:
        with client.messages.stream(
            model=config.CHATBOT_MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f"Sorry, I couldn't generate a response: {e}"


def chat(user_message: str, chat_history: list) -> tuple[str, list]:
    """
    Single turn of the chatbot.
    Returns (assistant_response, updated_chat_history).
    """
    index_documents_from_kb()

    context = retrieve_context(user_message)

    messages = chat_history.copy()
    messages.append({
        "role": "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}"
    })

    try:
        response = client.messages.create(
            model=config.CHATBOT_MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant_reply = next(b.text for b in response.content if hasattr(b, "text"))

        # Store clean question (not context-stuffed version) in history
        updated_history = chat_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_reply},
        ]

        return assistant_reply, updated_history

    except Exception as e:
        error_msg = f"Sorry, I couldn't generate a response: {e}"
        return error_msg, chat_history
