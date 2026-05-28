from fastapi import APIRouter, Query
from api.db import get_db
from api.models import ProvinceOut, MunicipalityOut

router = APIRouter(tags=["municipalities"])


@router.get("/provinces")
def list_provinces() -> list[ProvinceOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT province FROM municipalities ORDER BY province"
        ).fetchall()
    return [ProvinceOut(name=r["province"]) for r in rows]


@router.get("/municipalities")
def list_municipalities(
    province: str = Query(None, description="Filter by exact province name"),
    search: str = Query(None, description="Partial name match"),
    limit: int = Query(100, le=2000),
) -> list[MunicipalityOut]:
    sql = """
        SELECT m.id, m.name, m.province, m.region, m.lat, m.lon,
               g.geo_score, g.solar_norm, g.income_score, g.pop_density_norm
        FROM   municipalities m
        LEFT JOIN geo_scores g ON g.municipality_id = m.id
        WHERE  1=1
    """
    params: list = []
    if province:
        sql += " AND m.province = ?"
        params.append(province)
    if search:
        sql += " AND m.name LIKE ?"
        params.append(f"%{search}%")
    sql += " ORDER BY COALESCE(g.geo_score, 0) DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        MunicipalityOut(
            id=r["id"],
            name=r["name"],
            province=r["province"],
            region=r["region"],
            lat=r["lat"],
            lon=r["lon"],
            geo_score=r["geo_score"],
            solar_norm=r["solar_norm"],
            income_score=r["income_score"],
            pop_density_norm=r["pop_density_norm"],
        )
        for r in rows
    ]
