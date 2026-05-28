import sqlite3
from contextlib import contextmanager
from loguru import logger
import config

DB_PATH = config.HELIO_DB


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_tables() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS municipalities (
                id          INTEGER PRIMARY KEY,
                name        TEXT    NOT NULL,
                province    TEXT    NOT NULL,
                region      TEXT    NOT NULL,
                lat         REAL,
                lon         REAL,
                area_km2    REAL,
                population  INTEGER,
                income_class TEXT
            )
        """)
        conn.execute("""
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
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_geo_score ON geo_scores(geo_score DESC)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id           TEXT PRIMARY KEY,
                location     TEXT NOT NULL,
                province     TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                error        TEXT
            )
        """)
        conn.execute("""
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
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_results_score ON run_results(run_id, final_score DESC)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS web_intel_cache (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                municipality_id INTEGER NOT NULL UNIQUE REFERENCES municipalities(id),
                business_count  INTEGER,
                avg_price_level REAL,
                places_data     TEXT,
                tavily_snippets TEXT,
                fetched_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at      DATETIME
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_intel_expires ON web_intel_cache(expires_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id     TEXT NOT NULL REFERENCES runs(id),
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT NOT NULL REFERENCES runs(id),
                province     TEXT,
                municipality TEXT,
                slug         TEXT NOT NULL UNIQUE,
                markdown     TEXT NOT NULL,
                file_path    TEXT,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


def seed_municipalities_from_location_db() -> int:
    """Copy 1,622 municipalities from ph_locations.db into helio.db. Returns count."""
    if not config.LOCATION_DB.exists():
        logger.warning("LOCATION_DB not found at {}; skipping municipality seed", config.LOCATION_DB)
        return 0

    src = sqlite3.connect(str(config.LOCATION_DB))
    src.row_factory = sqlite3.Row
    rows = src.execute("""
        SELECT m.id, m.name, p.name AS province, r.name AS region
        FROM   municipalities m
        JOIN   provinces p ON m.province_id = p.id
        JOIN   regions   r ON p.region_id   = r.id
        ORDER  BY m.id
    """).fetchall()
    src.close()

    with get_db() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO municipalities (id, name, province, region) VALUES (?,?,?,?)",
            [(r["id"], r["name"], r["province"], r["region"]) for r in rows],
        )
    return len(rows)
