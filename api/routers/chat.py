from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from api.db import get_db
from api.models import ChatMessageOut

router = APIRouter(tags=["chat"])


def _stream_chatbot(message: str, history: list[dict]):
    """Thin wrapper so tests can patch streaming without touching the chatbot module."""
    from agents.chatbot import chat_stream
    return chat_stream(message, history)


@router.post("/chat")
def send_message_stream(
    body: dict,  # {"message": str, "run_id": str | None}
) -> StreamingResponse:
    message: str = body.get("message", "")
    run_id: str | None = body.get("run_id")

    history: list[dict] = []
    if run_id:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in rows]

    def _generate():
        chunks: list[str] = []
        for chunk in _stream_chatbot(message, history):
            chunks.append(chunk)
            yield f"data: {chunk}\n\n"
        full_reply = "".join(chunks)
        if run_id:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                    (run_id, "user", message),
                )
                conn.execute(
                    "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                    (run_id, "assistant", full_reply),
                )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/chat/{run_id}/history")
def get_history(run_id: str) -> list[ChatMessageOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages "
            "WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
    return [ChatMessageOut(**dict(r)) for r in rows]
