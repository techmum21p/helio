"""
DB I/O for pipeline runs, results, reports, and chat messages.
Replaces agents/session_store.py — all writes go to data/helio.db.
"""
import json
import sqlite3
from datetime import datetime, timezone
from loguru import logger

import config


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema() -> None:
    """Create all tables if they don't exist (idempotent)."""
    schema = """
    CREATE TABLE IF NOT EXISTS municipalities (
        id           INTEGER PRIMARY KEY,
        name         TEXT    NOT NULL,
        province     TEXT    NOT NULL,
        region       TEXT    NOT NULL,
        lat          REAL,
        lon          REAL,
        area_km2     REAL,
        population   INTEGER,
        income_class TEXT
    );
    CREATE TABLE IF NOT EXISTS geo_scores (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        municipality_id   INTEGER NOT NULL UNIQUE REFERENCES municipalities(id),
        solar_irradiance  REAL,
        solar_norm        REAL,
        income_score      REAL,
        pop_density       REAL,
        pop_density_norm  REAL,
        geo_score         REAL,
        computed_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_geo_score ON geo_scores(geo_score DESC);
    CREATE TABLE IF NOT EXISTS runs (
        id           TEXT PRIMARY KEY,
        location     TEXT NOT NULL,
        province     TEXT,
        status       TEXT NOT NULL DEFAULT 'pending',
        created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        error        TEXT
    );
    CREATE TABLE IF NOT EXISTS run_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT    NOT NULL REFERENCES runs(id),
        municipality_id INTEGER REFERENCES municipalities(id),
        geo_score       REAL,
        web_score       REAL,
        final_score     REAL,
        tier            TEXT,
        assessment      TEXT,
        opportunities   TEXT,
        risks           TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_run_results_score ON run_results(run_id, final_score DESC);
    CREATE TABLE IF NOT EXISTS web_intel_cache (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        municipality_id INTEGER NOT NULL UNIQUE REFERENCES municipalities(id),
        business_count  INTEGER,
        avg_price_level REAL,
        places_data     TEXT,
        tavily_snippets TEXT,
        fetched_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at      DATETIME
    );
    CREATE INDEX IF NOT EXISTS idx_web_intel_expires ON web_intel_cache(expires_at);
    CREATE TABLE IF NOT EXISTS chat_messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT NOT NULL REFERENCES runs(id),
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS reports (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT NOT NULL REFERENCES runs(id),
        province     TEXT,
        municipality TEXT,
        slug         TEXT NOT NULL UNIQUE,
        markdown     TEXT NOT NULL,
        file_path    TEXT,
        created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """
    conn = _get_conn()
    try:
        conn.executescript(schema)
        conn.commit()
    except Exception as e:
        logger.warning(f"db_store._create_schema failed: {e}")
    finally:
        conn.close()


def _migrate() -> None:
    """Add missing columns to tables if not present (idempotent)."""
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE web_intel_cache ADD COLUMN web_score REAL")
        conn.commit()
        logger.info("db_store: added web_score column to web_intel_cache")
    except Exception:
        pass  # column already exists
    finally:
        conn.close()


try:
    _create_schema()
    _migrate()
except Exception as e:
    logger.warning(f"db_store initialization failed: {e}")


def create_run(run_id: str, location: str, province: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO runs (id, location, province, status) VALUES (?, ?, ?, 'running')",
            (run_id, location, province),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.create_run failed: {e}")
    finally:
        conn.close()


def complete_run(run_id: str, top_targets: list) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE runs SET status='done', completed_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), run_id),
        )
        for t in top_targets:
            muni_name = t.get("municipality", "")
            province = t.get("province", "")
            region = t.get("region", "")
            # Ensure municipality exists so load_run JOIN can recover the name
            if muni_name:
                conn.execute(
                    """INSERT OR IGNORE INTO municipalities
                       (name, province, region, lat, lon, area_km2, population, income_class)
                       VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)""",
                    (muni_name, province, region,
                     t.get("population"), t.get("income_class")),
                )
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (muni_name, province),
            ).fetchone()
            muni_id = row["id"] if row else None
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, muni_id,
                    t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                    t.get("tier"), t.get("assessment"),
                    json.dumps([t.get("opportunity", "")]),
                    json.dumps([t.get("risk", "")]),
                ),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.complete_run failed: {e}")
    finally:
        conn.close()


def fail_run(run_id: str, error: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE runs SET status='failed', completed_at=?, error=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), error, run_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.fail_run failed: {e}")
    finally:
        conn.close()


def save_report(
    run_id: str,
    province: str,
    municipality: str | None,
    markdown: str,
    file_path: str,
) -> None:
    slug = f"{province}_{run_id}".lower().replace(" ", "_").replace(",", "")
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO reports
               (run_id, province, municipality, slug, markdown, file_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, province, municipality, slug, markdown, file_path),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.save_report failed: {e}")
    finally:
        conn.close()


def save_chat_message(run_id: str, role: str, content: str) -> None:
    if not run_id:
        return
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages (run_id, role, content) VALUES (?, ?, ?)",
            (run_id, role, content),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.save_chat_message failed: {e}")
    finally:
        conn.close()


def load_chat_history(run_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception as e:
        logger.error(f"db_store.load_chat_history failed: {e}")
        return []
    finally:
        conn.close()


def list_runs(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.location, r.province, r.status, r.created_at,
                   COUNT(rr.id) AS target_count,
                   MAX(rr.final_score) AS top_score,
                   (SELECT tier FROM run_results
                    WHERE run_id = r.id ORDER BY final_score DESC LIMIT 1) AS top_tier
            FROM runs r
            LEFT JOIN run_results rr ON rr.run_id = r.id
            WHERE r.status IN ('done', 'failed')
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_store.list_runs failed: {e}")
        return []
    finally:
        conn.close()


def load_run(run_id: str) -> dict | None:
    conn = _get_conn()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run_row:
            return None
        result_rows = conn.execute(
            """SELECT rr.geo_score, rr.web_score, rr.final_score, rr.tier,
                      rr.assessment, rr.opportunities, rr.risks,
                      COALESCE(m.name, '') AS municipality_name,
                      COALESCE(m.province, '') AS province,
                      COALESCE(m.region, '') AS region,
                      m.income_class, m.population
               FROM run_results rr
               LEFT JOIN municipalities m ON m.id = rr.municipality_id
               WHERE rr.run_id = ?
               ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        top_targets = []
        for r in result_rows:
            top_targets.append({
                "municipality": r["municipality_name"] or "",
                "province":     r["province"] or "",
                "region":       r["region"] or "",
                "income_class": r["income_class"] or "",
                "population":   r["population"] or 0,
                "geo_score":    r["geo_score"],
                "web_score":    r["web_score"],
                "final_score":  r["final_score"],
                "tier":         r["tier"],
                "assessment":   r["assessment"] or "",
                "opportunity":  (json.loads(r["opportunities"] or "[]") or [""])[0],
                "risk":         (json.loads(r["risks"] or "[]") or [""])[0],
            })
        report_row = conn.execute(
            "SELECT markdown, file_path FROM reports WHERE run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        return {
            "run_id":          run_row["id"],
            "location":        run_row["location"],
            "top_targets":     top_targets,
            "report_markdown": report_row["markdown"] if report_row else "",
            "report_path":     report_row["file_path"] if report_row else None,
            "errors":          [],
            "status":          run_row["status"],
        }
    except Exception as e:
        logger.error(f"db_store.load_run failed: {e}")
        return None
    finally:
        conn.close()


def list_reports() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, slug, province, municipality, markdown FROM reports ORDER BY created_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_store.list_reports failed: {e}")
        return []
    finally:
        conn.close()


def get_municipality_id(name: str, province: str) -> int | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM municipalities WHERE name=? AND province=?",
            (name, province),
        ).fetchone()
        return row["id"] if row else None
    except Exception as e:
        logger.error(f"db_store.get_municipality_id failed: {e}")
        return None
    finally:
        conn.close()
