"""
Agent 5: Chatbot (RAG over generated KB)
The KB is built from reports and intel summaries written by Agents 3 and 4.
Uses ChromaDB as the vector store and Claude as the response model.

KB grows automatically after every pipeline run — the more locations
you process, the richer the chatbot's answers become.
"""

import os
from pathlib import Path
from loguru import logger
import anthropic
import chromadb
from chromadb.utils import embedding_functions

import config
from graph.state import SolarLeadState

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ChromaDB setup
_chroma_client = chromadb.PersistentClient(path=str(config.KB_INDEX))
_embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
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

            # Chunk by paragraph (simple strategy — Claude Code can improve this)
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
    """LangGraph node: triggered after report_gen. Updates the vector store."""
    logger.info("[Agent 5] Updating knowledge base...")
    try:
        index_documents_from_kb()
        return {**state, "kb_updated": True}
    except Exception as e:
        logger.error(f"KB update failed: {e}")
        return {**state, "kb_updated": False, "errors": state["errors"] + [str(e)]}


# ── RAG Retrieval ──────────────────────────────────────────────────────────────

def retrieve_context(query: str, n_results: int = 5) -> str:
    """Retrieve relevant chunks from ChromaDB for the user's query."""
    try:
        results = _collection.query(query_texts=[query], n_results=n_results)
        docs = results.get("documents", [[]])[0]
        return "\n\n---\n\n".join(docs) if docs else "No relevant information found in knowledge base."
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


def chat(user_message: str, chat_history: list) -> tuple[str, list]:
    """
    Single turn of the chatbot.
    Returns (assistant_response, updated_chat_history).
    """
    # Ensure KB is up to date
    index_documents_from_kb()

    # Retrieve relevant context
    context = retrieve_context(user_message)

    # Build messages for Claude
    messages = chat_history.copy()
    messages.append({
        "role": "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}"
    })

    try:
        response = client.messages.create(
            model=config.CHATBOT_MODEL,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant_reply = response.content[0].text

        # Update history (store clean question, not the context-stuffed version)
        updated_history = chat_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_reply},
        ]

        return assistant_reply, updated_history

    except Exception as e:
        error_msg = f"Sorry, I couldn't generate a response: {e}"
        return error_msg, chat_history
