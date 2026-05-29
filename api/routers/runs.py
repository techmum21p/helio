import asyncio
import json
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from api.db import get_db
from api.models import RunCreateIn, RunOut, RunDetailOut

router = APIRouter(tags=["runs"])


def _nanoid(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _persist_run_results(run_id: str, result: dict) -> None:
    with get_db() as conn:
        error  = "; ".join(result.get("errors", [])) or None
        status = "failed" if error and not result.get("top_targets") else "done"
        conn.execute(
            "UPDATE runs SET status=?, completed_at=?, error=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), error, run_id),
        )
        for t in result.get("top_targets", []):
            muni = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (t.get("municipality", ""), t.get("province", "")),
            ).fetchone()
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, muni["id"] if muni else None,
                 t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                 t.get("tier"), t.get("assessment"),
                 json.dumps(t.get("opportunities", [])),
                 json.dumps(t.get("risks", []))),
            )
        if result.get("report_markdown"):
            loc  = (result.get("location", "unknown")
                    .lower().replace(", ", "_").replace(" ", "-").replace("|", "_"))
            slug = f"{loc}_{run_id[:6]}"
            conn.execute(
                """INSERT OR IGNORE INTO reports
                   (run_id, province, slug, markdown, file_path)
                   VALUES (?,?,?,?,?)""",
                (run_id, result.get("location"), slug,
                 result["report_markdown"], result.get("report_path", "")),
            )


def _run_pipeline_bg(run_id: str, location: str) -> None:
    try:
        with get_db() as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
        from graph.pipeline import run_pipeline
        result = run_pipeline(location, run_id=run_id)
        _persist_run_results(run_id, result)
    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                "UPDATE runs SET status='failed', error=?, completed_at=? WHERE id=?",
                (str(exc), datetime.now(timezone.utc).isoformat(), run_id),
            )


@router.post("/runs", status_code=201)
def create_run(body: RunCreateIn, bg: BackgroundTasks) -> dict:
    run_id   = _nanoid()
    province = body.location.rsplit(",", 1)[-1].strip() if "," in body.location else body.location
    with get_db() as conn:
        conn.execute(
            "INSERT INTO runs (id, location, province, status) VALUES (?,?,?,'pending')",
            (run_id, body.location, province),
        )
    bg.add_task(_run_pipeline_bg, run_id, body.location)
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(limit: int = 20) -> list[RunOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [RunOut(**dict(r)) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> RunDetailOut:
    with get_db() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "Run not found")
        results = conn.execute(
            """SELECT rr.*, m.name AS municipality_name, m.province,
                      m.lat, m.lon
               FROM   run_results rr
               LEFT JOIN municipalities m ON rr.municipality_id = m.id
               WHERE  rr.run_id=? ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        report = conn.execute(
            "SELECT slug, markdown, file_path, created_at FROM reports WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return RunDetailOut(
        **dict(run),
        results=[{**dict(r),
                  "opportunities": json.loads(dict(r).get("opportunities") or "[]"),
                  "risks": json.loads(dict(r).get("risks") or "[]")}
                 for r in results],
        report=dict(report) if report else None,
    )


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    from api.events import get_events, clear_events

    async def _events():
        emitted = 0
        while True:
            # Flush any new events
            events = get_events(run_id)
            while emitted < len(events):
                yield f"data: {json.dumps(events[emitted])}\n\n"
                emitted += 1

            with get_db() as conn:
                row = conn.execute(
                    "SELECT status, error FROM runs WHERE id=?", (run_id,)
                ).fetchone()

            if not row:
                yield 'data: {"error": "run not found"}\n\n'
                return

            if row["status"] in ("done", "failed"):
                # Flush remaining events before terminal
                events = get_events(run_id)
                while emitted < len(events):
                    yield f"data: {json.dumps(events[emitted])}\n\n"
                    emitted += 1
                step = "complete" if row["status"] == "done" else "failed"
                payload = json.dumps({"step": step, "run_id": run_id, "error": row["error"]})
                yield f"data: {payload}\n\n"
                clear_events(run_id)
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
