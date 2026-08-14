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
    CREATE UNIQUE INDEX IF NOT EXISTS idx_municipalities_name_province
        ON municipalities(name, province);
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
    CREATE TABLE IF NOT EXISTS kb_docs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        municipality_id INTEGER NOT NULL REFERENCES municipalities(id),
        province        TEXT NOT NULL,
        file_path       TEXT NOT NULL,
        run_id          TEXT NOT NULL,
        generated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_current      INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_kb_docs_current
        ON kb_docs(province, municipality_id, is_current);
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
        pass
    for col, typedef in [
        ("solar_irradiance", "REAL"),
        ("solar_yield_kwh",  "REAL"),
        ("pop_density",      "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE run_results ADD COLUMN {col} {typedef}")
            conn.commit()
            logger.info(f"db_store: added {col} column to run_results")
        except Exception:
            pass
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
                       VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
                    (muni_name, province, region,
                     t.get("lat"), t.get("lon"),
                     t.get("population"), t.get("income_class")),
                )
                # Backfill coords for rows inserted without them (prior runs)
                if t.get("lat") and t.get("lon"):
                    conn.execute(
                        """UPDATE municipalities SET lat=?, lon=?
                           WHERE name=? AND province=? AND (lat IS NULL OR lon IS NULL)""",
                        (t["lat"], t["lon"], muni_name, province),
                    )
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (muni_name, province),
            ).fetchone()
            muni_id = row["id"] if row else None
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks,
                    solar_irradiance, solar_yield_kwh, pop_density)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, muni_id,
                    t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                    t.get("tier"), t.get("assessment"),
                    json.dumps([t.get("opportunity", "")]),
                    json.dumps([t.get("risk", "")]),
                    t.get("solar_irradiance"),
                    t.get("solar_yield_kwh"),
                    t.get("pop_density"),
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


def list_runs(limit: int = 1000) -> list[dict]:
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
            INNER JOIN reports rep ON rep.run_id = r.id
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
                      rr.solar_irradiance, rr.solar_yield_kwh, rr.pop_density,
                      COALESCE(m.name, '')     AS municipality_name,
                      COALESCE(m.province, '') AS province,
                      COALESCE(m.region, '')   AS region,
                      m.income_class, m.population,
                      m.lat, m.lon,
                      g.solar_irradiance AS gs_solar_irradiance,
                      g.pop_density      AS gs_pop_density
               FROM run_results rr
               LEFT JOIN municipalities m ON m.id = rr.municipality_id
               LEFT JOIN geo_scores g    ON g.municipality_id = rr.municipality_id
               WHERE rr.run_id = ?
               ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        top_targets = []
        geojson_features = []
        for r in result_rows:
            solar_irr   = r["solar_irradiance"] or r["gs_solar_irradiance"] or 5.0
            pop_dens    = r["pop_density"]       or r["gs_pop_density"]       or 0.0
            solar_yield = r["solar_yield_kwh"]   or round(solar_irr * 365 * 0.80, 0)
            muni_name   = r["municipality_name"] or ""
            province    = r["province"] or ""
            top_targets.append({
                "municipality":     muni_name,
                "province":         province,
                "region":           r["region"] or "",
                "income_class":     r["income_class"] or "",
                "population":       r["population"] or 0,
                "geo_score":        r["geo_score"],
                "web_score":        r["web_score"],
                "final_score":      r["final_score"],
                "tier":             r["tier"],
                "assessment":       r["assessment"] or "",
                "opportunity":      (json.loads(r["opportunities"] or "[]") or [""])[0],
                "risk":             (json.loads(r["risks"] or "[]") or [""])[0],
                "solar_irradiance": solar_irr,
                "solar_yield_kwh":  solar_yield,
                "pop_density":      pop_dens,
                "lat":              r["lat"],
                "lon":              r["lon"],
            })
            if r["lat"] and r["lon"]:
                geojson_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "name":      muni_name,
                        "province":  province,
                        "geo_score": r["geo_score"],
                    },
                })
        geo_geojson = json.dumps({"type": "FeatureCollection", "features": geojson_features}) if geojson_features else None
        report_row = conn.execute(
            "SELECT markdown, file_path FROM reports WHERE run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        return {
            "run_id":          run_row["id"],
            "location":        run_row["location"],
            "top_targets":     top_targets,
            "geo_geojson":     geo_geojson,
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


def get_latest_scored_municipalities() -> list[dict]:
    """
    One row per municipality. Assessment fields (final_score, web_score, tier,
    assessment) are None and opportunities/risks are [] unless the latest 'done'
    run's run_results row for that municipality completed at or after the
    municipality's geo_scores.computed_at — i.e. its basis is current.
    """
    conn = _get_conn()
    try:
        geo_rows = conn.execute(
            """SELECT m.id AS municipality_id, m.name, m.province, m.region,
                      m.lat, m.lon, m.population, m.income_class,
                      g.geo_score, g.computed_at AS geo_computed_at
               FROM municipalities m
               LEFT JOIN geo_scores g ON g.municipality_id = m.id"""
        ).fetchall()

        current_rows = conn.execute(
            """SELECT rr.municipality_id, rr.final_score, rr.web_score, rr.tier,
                      rr.assessment, rr.opportunities, rr.risks, r.completed_at,
                      rr.solar_irradiance, rr.solar_yield_kwh, rr.pop_density
               FROM run_results rr
               JOIN runs r ON r.id = rr.run_id AND r.status = 'done'
               JOIN geo_scores g ON g.municipality_id = rr.municipality_id
               WHERE rr.assessment IS NOT NULL
                 AND r.completed_at >= g.computed_at"""
        ).fetchall()
    except Exception as e:
        logger.error(f"db_store.get_latest_scored_municipalities failed: {e}")
        return []
    finally:
        conn.close()

    latest: dict[int, sqlite3.Row] = {}
    for row in current_rows:
        mid = row["municipality_id"]
        if mid not in latest or row["completed_at"] > latest[mid]["completed_at"]:
            latest[mid] = row

    result = []
    for g in geo_rows:
        mid = g["municipality_id"]
        cur = latest.get(mid)
        result.append({
            "municipality_id": mid,
            "name":            g["name"],
            "province":        g["province"],
            "region":          g["region"],
            "lat":             g["lat"],
            "lon":             g["lon"],
            "population":      g["population"],
            "income_class":    g["income_class"],
            "geo_score":       g["geo_score"],
            "final_score":     cur["final_score"] if cur else None,
            "web_score":       cur["web_score"] if cur else None,
            "tier":            cur["tier"] if cur else None,
            "assessment":      cur["assessment"] if cur else None,
            "opportunities":   json.loads(cur["opportunities"]) if cur and cur["opportunities"] else [],
            "risks":           json.loads(cur["risks"]) if cur and cur["risks"] else [],
            "solar_irradiance": cur["solar_irradiance"] if cur else None,
            "solar_yield_kwh":  cur["solar_yield_kwh"] if cur else None,
            "pop_density":      cur["pop_density"] if cur else None,
        })
    return result


def register_kb_doc(municipality_id: int, province: str, file_path: str, run_id: str) -> list[str]:
    """Insert a new current kb_doc row for a municipality, marking any previously
    current row(s) for that municipality as superseded. Returns the file_path(s)
    of the rows just superseded, so the caller can delete those files from disk."""
    conn = _get_conn()
    try:
        superseded = [
            r["file_path"] for r in conn.execute(
                "SELECT file_path FROM kb_docs WHERE municipality_id=? AND is_current=1",
                (municipality_id,),
            ).fetchall()
        ]
        conn.execute(
            "UPDATE kb_docs SET is_current=0 WHERE municipality_id=? AND is_current=1",
            (municipality_id,),
        )
        conn.execute(
            "INSERT INTO kb_docs (municipality_id, province, file_path, run_id) VALUES (?,?,?,?)",
            (municipality_id, province, file_path, run_id),
        )
        conn.commit()
        return superseded
    except Exception as e:
        logger.error(f"db_store.register_kb_doc failed: {e}")
        return []
    finally:
        conn.close()


def get_current_kb_docs(province: str | None = None, municipality_id: int | None = None) -> list[dict]:
    """Current (is_current=1) kb_docs rows, optionally filtered by province and/or municipality_id."""
    conn = _get_conn()
    try:
        query = "SELECT * FROM kb_docs WHERE is_current=1"
        params: list = []
        if province is not None:
            query += " AND province=?"
            params.append(province)
        if municipality_id is not None:
            query += " AND municipality_id=?"
            params.append(municipality_id)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    except Exception as e:
        logger.error(f"db_store.get_current_kb_docs failed: {e}")
        return []
    finally:
        conn.close()


def get_latest_report_for_province(province: str) -> dict | None:
    """Most recently created report row for a province, or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT markdown, file_path, created_at FROM reports
               WHERE province = ? ORDER BY created_at DESC LIMIT 1""",
            (province,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"db_store.get_latest_report_for_province failed: {e}")
        return None
    finally:
        conn.close()


def latest_assessment_time_for_province(province: str) -> str | None:
    """Completion time of the most recent current assessment among the province's
    municipalities, or None if none are assessed yet. Used to detect a stale report."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT MAX(r.completed_at) AS latest
               FROM run_results rr
               JOIN runs r ON r.id = rr.run_id AND r.status = 'done'
               JOIN municipalities m ON m.id = rr.municipality_id
               JOIN geo_scores g ON g.municipality_id = rr.municipality_id
               WHERE m.province = ?
                 AND rr.assessment IS NOT NULL
                 AND r.completed_at >= g.computed_at""",
            (province,),
        ).fetchone()
        return row["latest"] if row else None
    except Exception as e:
        logger.error(f"db_store.latest_assessment_time_for_province failed: {e}")
        return None
    finally:
        conn.close()


def get_score_breakdown(municipality_id: int) -> dict | None:
    """Every raw and normalized input behind a municipality's geo_score, web_score,
    and final_score, plus the weights applied — for a transparent score breakdown
    in the UI. Returns None if the municipality has no geo_scores row yet."""
    conn = _get_conn()
    try:
        geo_row = conn.execute(
            """SELECT g.solar_irradiance, g.solar_norm, g.income_score,
                      g.pop_density, g.pop_density_norm, g.geo_score,
                      m.income_class
               FROM geo_scores g JOIN municipalities m ON m.id = g.municipality_id
               WHERE g.municipality_id = ?""",
            (municipality_id,),
        ).fetchone()
        if geo_row is None:
            return None

        web_row = conn.execute(
            """SELECT business_count, avg_price_level, places_data, web_score
               FROM web_intel_cache WHERE municipality_id = ?""",
            (municipality_id,),
        ).fetchone()

        current = next(
            (r for r in get_latest_scored_municipalities() if r["municipality_id"] == municipality_id),
            None,
        )
    except Exception as e:
        logger.error(f"db_store.get_score_breakdown failed: {e}")
        return None
    finally:
        conn.close()

    income_norm = (geo_row["income_score"] - 1) / 5.0 if geo_row["income_score"] else 0.0
    breakdown = {
        "weights": {"solar": config.WEIGHTS["solar"], "income": config.WEIGHTS["income"],
                    "population": config.WEIGHTS["population"]},
        "geo": {
            "solar_irradiance": geo_row["solar_irradiance"],
            "solar_norm":       geo_row["solar_norm"],
            "income_class":     geo_row["income_class"],
            "income_score":     geo_row["income_score"],
            "income_norm":      income_norm,
            "pop_density":      geo_row["pop_density"],
            "pop_density_norm": geo_row["pop_density_norm"],
            "geo_score":        geo_row["geo_score"],
        },
        "web": None,
        "final_weights": {"geo": config.FINAL_GEO_WEIGHT, "web": config.FINAL_WEB_WEIGHT},
        "final_score": current["final_score"] if current else None,
    }

    if web_row is not None:
        places = json.loads(web_row["places_data"]) if web_row["places_data"] else {}
        business_count     = places.get("business_count", web_row["business_count"] or 0)
        avg_price_level    = places.get("avg_price_level", web_row["avg_price_level"] or 0)
        avg_rating         = places.get("avg_rating", 0)
        commercial_anchors = places.get("commercial_anchors", 0)
        biz_density   = min(business_count / 20, 1.0)
        price_signal  = min(avg_price_level / 4, 1.0)
        rating_signal = max((avg_rating - 1.0) / 4.0, 0) if avg_rating else 0
        anchor_signal = min(commercial_anchors / 5, 1.0)
        breakdown["web"] = {
            "weights": {"business_density": 0.35, "price_signal": 0.25,
                        "rating_signal": 0.25, "anchor_signal": 0.15},
            "business_count":     business_count,
            "business_density":   biz_density,
            "avg_price_level":    avg_price_level,
            "price_signal":       price_signal,
            "avg_rating":         avg_rating,
            "rating_signal":      rating_signal,
            "commercial_anchors": commercial_anchors,
            "anchor_signal":      anchor_signal,
            "web_score":          web_row["web_score"],
        }

    return breakdown
