import sqlite3
import config
from loguru import logger


def _get_conn() -> sqlite3.Connection | None:
    if not config.LOCATION_DB.exists():
        return None
    conn = sqlite3.connect(str(config.LOCATION_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_provinces() -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM provinces ORDER BY name"
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception as e:
        logger.warning(f"location_db.get_provinces failed: {e}")
        return []
    finally:
        conn.close()


def get_municipalities(province_id: int) -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM municipalities WHERE province_id = ? ORDER BY name",
            (province_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception as e:
        logger.warning(f"location_db.get_municipalities failed: {e}")
        return []
    finally:
        conn.close()


def get_barangays(municipality_id: int) -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM barangays WHERE municipality_id = ? ORDER BY name",
            (municipality_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception as e:
        logger.warning(f"location_db.get_barangays failed: {e}")
        return []
    finally:
        conn.close()


def get_province_name(province_id: int) -> str:
    conn = _get_conn()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT name FROM provinces WHERE id = ?", (province_id,)
        ).fetchone()
        return row["name"] if row else ""
    except Exception as e:
        logger.warning(f"location_db.get_province_name failed: {e}")
        return ""
    finally:
        conn.close()


def get_municipality_name(municipality_id: int) -> str:
    conn = _get_conn()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT name FROM municipalities WHERE id = ?", (municipality_id,)
        ).fetchone()
        return row["name"] if row else ""
    except Exception as e:
        logger.warning(f"location_db.get_municipality_name failed: {e}")
        return ""
    finally:
        conn.close()
