from fastapi import APIRouter
from api.db import get_db
from api.models import ChatIn, ChatOut, ChatMessageOut

router = APIRouter(tags=["chat"])


def _call_chatbot(message: str, history: list[dict]) -> str:
    """Thin wrapper so tests can patch it without touching the chatbot module."""
    from agents.chatbot import chat as _chat
    reply, _ = _chat(message, history)
    return reply


@router.post("/chat")
def send_message(body: ChatIn) -> ChatOut:
    history: list[dict] = []
    if body.run_id:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
                (body.run_id,),
            ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in rows]

    reply = _call_chatbot(body.message, history)

    if body.run_id:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                (body.run_id, "user", body.message),
            )
            conn.execute(
                "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                (body.run_id, "assistant", reply),
            )

    return ChatOut(reply=reply, run_id=body.run_id)


@router.get("/chat/{run_id}/history")
def get_history(run_id: str) -> list[ChatMessageOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages "
            "WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
    return [ChatMessageOut(**dict(r)) for r in rows]
