import secrets
import string
import time

import numpy as np
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from loguru import logger
from sklearn.preprocessing import MinMaxScaler

import config
from api.db import get_db
from api.models import AdminStatsOut

router = APIRouter(prefix="/admin", tags=["admin"])

INCOME_CLASS_MAP = {"1st": 6, "2nd": 5, "3rd": 4, "4th": 3, "5th": 2, "6th": 1, "special": 6}


def _nanoid(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _reindex_kb_task() -> None:
    from agents.chatbot import index_documents_from_kb
    index_documents_from_kb()


def _precompute_geo_scores_task(run_id: str) -> None:
    from agents.geo_scoring import _stable_float
    from api.events import push_event

    t0 = time.monotonic()
    try:
        with get_db() as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))

        push_event(run_id, "geo_scoring", "running", 0)

        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, province, lat, lon, area_km2, population, income_class"
                " FROM municipalities"
            ).fetchall()

        munis = [dict(r) for r in rows]
        if not munis:
            raise RuntimeError("No municipalities in DB — run seed first")

        for m in munis:
            m["solar"] = _stable_float(f"{m['name']}:solar", 4.5, 6.0)
            m["income_score"] = float(INCOME_CLASS_MAP.get(m["income_class"] or "3rd", 3))
            pop = float(m["population"] or 10_000)
            area = float(m["area_km2"] or 100.0)
            m["pop_density"] = pop / area if area > 0 else 100.0

        X = np.array([[m["solar"], m["income_score"], m["pop_density"]] for m in munis])
        X_norm = MinMaxScaler().fit_transform(X)

        w = config.WEIGHTS
        records = []
        for i, m in enumerate(munis):
            solar_norm, income_norm, pop_norm = float(X_norm[i, 0]), float(X_norm[i, 1]), float(X_norm[i, 2])
            geo_score = w["solar"] * solar_norm + w["income"] * income_norm + w["pop_density"] * pop_norm
            records.append((
                m["id"], m["solar"], solar_norm, m["income_score"],
                m["pop_density"], pop_norm, round(geo_score, 6),
            ))

        with get_db() as conn:
            conn.executemany(
                """INSERT INTO geo_scores
                       (municipality_id, solar_irradiance, solar_norm, income_score,
                        pop_density, pop_density_norm, geo_score, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(municipality_id) DO UPDATE SET
                       solar_irradiance = excluded.solar_irradiance,
                       solar_norm       = excluded.solar_norm,
                       income_score     = excluded.income_score,
                       pop_density      = excluded.pop_density,
                       pop_density_norm = excluded.pop_density_norm,
                       geo_score        = excluded.geo_score,
                       computed_at      = excluded.computed_at""",
                records,
            )

        elapsed = int((time.monotonic() - t0) * 1000)
        push_event(run_id, "geo_scoring", "done", elapsed)
        with get_db() as conn:
            conn.execute(
                "UPDATE runs SET status='done', completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (run_id,),
            )
        logger.info(f"precompute_geo_scores: {len(munis)} municipalities scored in {elapsed}ms")

    except Exception as exc:
        logger.error(f"precompute_geo_scores failed: {exc}")
        from api.events import push_event as _push
        _push(run_id, "geo_scoring", "failed", int((time.monotonic() - t0) * 1000))
        with get_db() as conn:
            conn.execute(
                "UPDATE runs SET status='failed', error=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(exc), run_id),
            )


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
def refresh_scores(bg: BackgroundTasks) -> dict:
    run_id = "geo-refresh-" + _nanoid(8)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO runs (id, location, province, status) VALUES (?,?,?,'pending')",
            (run_id, "admin:refresh-scores", "admin"),
        )
    bg.add_task(_precompute_geo_scores_task, run_id)
    return {"run_id": run_id}
