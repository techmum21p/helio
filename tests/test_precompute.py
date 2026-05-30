import pytest
import sqlite3
import config
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

SCHEMA_SQL = """
CREATE TABLE municipalities (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, province TEXT NOT NULL,
    region TEXT NOT NULL, lat REAL, lon REAL, area_km2 REAL,
    population INTEGER, income_class TEXT
);
CREATE TABLE geo_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_id INTEGER NOT NULL UNIQUE,
    solar_irradiance REAL, solar_norm REAL, income_score REAL,
    pop_density REAL, pop_density_norm REAL, geo_score REAL,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    return db_path


def _make_units(n=5):
    """Build minimal test unit dicts."""
    units = []
    for i in range(n):
        units.append({
            "name": f"Town{i}", "province": "TestProvince", "region": "TestRegion",
            "income_class": ["1st","2nd","3rd","4th","5th","6th"][i % 6],
            "income_score": [6, 5, 4, 3, 2, 1][i % 6],
            "population": 5000 * (i + 1),
            "area_km2": 50.0 * (i + 1),
            "pop_density": 5000 * (i + 1) / (50.0 * (i + 1)),
            "solar": 4.5 + i * 0.3,
            "lat": 12.5 + i * 0.1, "lon": 122.5 + i * 0.1,
        })
    return units


def test_normalize_and_score_geo_score_in_range():
    from precompute_geo_scores import normalize_and_score
    units = _make_units(6)
    result = normalize_and_score(units)
    for u in result:
        assert 0.0 <= u["geo_score"] <= 1.0


def test_normalize_highest_income_gets_highest_income_norm():
    from precompute_geo_scores import normalize_and_score
    units = _make_units(6)
    result = normalize_and_score(units)
    # Town0 has income_score=6 (1st class) — should have income_norm=1.0
    town0 = next(u for u in result if u["name"] == "Town0")
    assert town0["income_norm"] == pytest.approx(1.0)


def test_normalize_uses_config_weights():
    from precompute_geo_scores import normalize_and_score
    # Two towns: identical solar and pop_density, different income
    units = [
        {"name": "Rich", "province": "P", "region": "R", "income_class": "1st",
         "income_score": 6, "population": 10000, "area_km2": 100,
         "pop_density": 100, "solar": 5.0, "lat": 12.0, "lon": 122.0},
        {"name": "Poor", "province": "P", "region": "R", "income_class": "6th",
         "income_score": 1, "population": 10000, "area_km2": 100,
         "pop_density": 100, "solar": 5.0, "lat": 12.1, "lon": 122.1},
    ]
    result = normalize_and_score(units)
    rich = next(u for u in result if u["name"] == "Rich")
    poor = next(u for u in result if u["name"] == "Poor")
    # Income contributes 0.45 weight; Rich should score 0.45 higher
    assert rich["geo_score"] - poor["geo_score"] == pytest.approx(0.45, abs=1e-4)


def test_get_all_municipalities_returns_expected_count():
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    assert 1600 <= len(units) <= 1700


def test_get_all_municipalities_each_has_required_fields():
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    required = {"name", "province", "region", "income_class", "income_score",
                "population", "area_km2", "pop_density", "solar", "lat", "lon"}
    for u in units[:10]:
        assert required.issubset(u.keys()), f"Missing fields in {u}"


def test_upsert_to_db_writes_rows(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(3)
    # Insert municipalities first
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()

    units = normalize_and_score(units)
    upsert_to_db(units)

    conn = sqlite3.connect(str(temp_db))
    count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
    conn.close()
    assert count == 3


def test_upsert_is_idempotent(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(2)
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()
    units = normalize_and_score(units)
    upsert_to_db(units)
    upsert_to_db(units)  # second run must not raise or duplicate
    conn = sqlite3.connect(str(temp_db))
    count = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
    conn.close()
    assert count == 2


def test_get_all_municipalities_solar_is_none():
    """After Task 6 change, _get_all_municipalities returns solar=None (to be filled by GEE)."""
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    assert all(u["solar"] is None for u in units[:20]), \
        "Expected solar=None for all units; GEE fill hasn't happened yet"


def test_fetch_gee_irradiance_batch_uses_reduceRegions(monkeypatch):
    """fetch_gee_irradiance_batch calls ee.FeatureCollection().reduceRegions()."""
    from precompute_geo_scores import fetch_gee_irradiance_batch

    class MockReduceResult:
        def getInfo(self):
            return {
                "features": [
                    {"properties": {"name": "Town0", "province": "P",
                                    "surface_solar_radiation_downwards_sum": 18_000_000.0}},
                    {"properties": {"name": "Town1", "province": "P",
                                    "surface_solar_radiation_downwards_sum": None}},
                ]
            }

    class MockDataset:
        def reduceRegions(self, **kwargs):
            return MockReduceResult()
        def filterDate(self, *a): return self
        def select(self, *a): return self
        def mean(self): return self

    class MockFC:
        def __init__(self, *a): pass

    class MockGeometry:
        def buffer(self, *a): return self

    class MockReducer:
        @staticmethod
        def mean(): return "mean"

    class MockEE:
        class Geometry:
            @staticmethod
            def Point(coords):
                return MockGeometry()
        FeatureCollection = MockFC
        @staticmethod
        def Feature(*a, **kw): return {"geometry": None, "properties": kw.get("properties", {})}
        Reducer = MockReducer
        def ImageCollection(self, *a): return MockDataset()

    ee = MockEE()
    units = [
        {"name": "Town0", "province": "P", "lat": 14.0, "lon": 121.0},
        {"name": "Town1", "province": "P", "lat": 14.1, "lon": 121.1},
    ]
    result = fetch_gee_irradiance_batch(ee, units)
    assert "P:Town0" in result
    assert result["P:Town0"] == pytest.approx(18_000_000.0 / 3_600_000)
    assert result["P:Town1"] is None


def test_load_existing_solar_returns_dict(temp_db):
    """_load_existing_solar returns {province:name -> float} for rows with solar set."""
    import sqlite3 as _sq
    from precompute_geo_scores import _load_existing_solar

    conn = _sq.connect(str(temp_db))
    conn.execute(
        "INSERT INTO municipalities (name, province, region) VALUES ('A', 'PA', 'R')"
    )
    mid = conn.execute("SELECT id FROM municipalities WHERE name='A'").fetchone()[0]
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, solar_irradiance) VALUES (?, 5.3)",
        (mid,),
    )
    conn.commit()
    conn.close()

    result = _load_existing_solar()
    assert result.get("PA:A") == pytest.approx(5.3)


def test_progress_callback_called(temp_db):
    from precompute_geo_scores import normalize_and_score, upsert_to_db
    units = _make_units(3)
    conn = sqlite3.connect(str(temp_db))
    for u in units:
        conn.execute(
            "INSERT INTO municipalities (name, province, region) VALUES (?, ?, ?)",
            (u["name"], u["province"], u["region"]),
        )
    conn.commit()
    conn.close()
    units = normalize_and_score(units)
    calls = []
    upsert_to_db(units, progress_callback=lambda done, total: calls.append((done, total)))
    assert len(calls) == 3
    assert calls[-1] == (3, 3)
