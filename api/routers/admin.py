from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from api.db import get_db
from api.models import AdminStatsOut

router = APIRouter(prefix="/admin", tags=["admin"])


def _reindex_kb_task() -> None:
    from agents.chatbot import index_documents_from_kb
    index_documents_from_kb()


@router.get("/stats")
def get_stats() -> AdminStatsOut:
    with get_db() as conn:
        municipalities = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
        geo_scores = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        run_results = conn.execute("SELECT COUNT(*) FROM run_results").fetchone()[0]
        chat_messages = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        web_intel_cache = conn.execute("SELECT COUNT(*) FROM web_intel_cache").fetchone()[0]
        last = conn.execute("SELECT MAX(computed_at) FROM geo_scores").fetchone()[0]
    return AdminStatsOut(
        municipalities=municipalities,
        geo_scores=geo_scores,
        runs=runs,
        run_results=run_results,
        chat_messages=chat_messages,
        reports=reports,
        web_intel_cache=web_intel_cache,
        last_precompute=last,
    )


@router.post("/reindex-kb", status_code=202)
def reindex_kb(bg: BackgroundTasks) -> dict:
    bg.add_task(_reindex_kb_task)
    return {"status": "indexing started"}


@router.post("/refresh-scores", status_code=202)
def refresh_scores() -> dict:
    # Full implementation in Plan 2 — precompute_geo_scores.py
    return {"status": "accepted", "note": "precompute job implemented in Plan 2"}


@router.get("/refresh-scores/stream")
async def refresh_scores_stream() -> StreamingResponse:
    async def _gen():
        yield 'data: {"status": "not_implemented"}\n\n'
    return StreamingResponse(_gen(), media_type="text/event-stream")
