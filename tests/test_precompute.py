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


def test_fetch_gee_irradiance_batch_multipass(monkeypatch):
    """fetch_gee_irradiance_batch reads reducer-named output properties
    ('mean'/'max', NOT the band name) and retries nulls with buffered max passes.

    Town0 resolves on pass 1 (point mean), Town1 on pass 2 (11km max),
    Town2 stays null through all passes → None."""
    from precompute_geo_scores import fetch_gee_irradiance_batch

    call_log = []

    class MockReduceResult:
        def __init__(self, features):
            self._features = features
        def getInfo(self):
            return {"features": self._features}

    class MockDataset:
        def reduceRegions(self, collection, reducer, scale):
            call_log.append(reducer)
            if reducer == "mean":  # pass 1: point sample
                return MockReduceResult([
                    {"properties": {"name": "Town0", "province": "P", "mean": 18_000_000.0}},
                    {"properties": {"name": "Town1", "province": "P", "mean": None}},
                    {"properties": {"name": "Town2", "province": "P", "mean": None}},
                ])
            # passes 2+3: buffered max — Town1 resolves, Town2 never does
            return MockReduceResult([
                {"properties": {"name": "Town1", "province": "P", "max": 20_000_000.0}},
                {"properties": {"name": "Town2", "province": "P", "max": None}},
            ])
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
        @staticmethod
        def max(): return "max"

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
        {"name": "Town2", "province": "P", "lat": 14.2, "lon": 121.2},
    ]
    result = fetch_gee_irradiance_batch(ee, units)
    assert result["P:Town0"] == pytest.approx(18_000_000.0 / 3_600_000)
    assert result["P:Town1"] == pytest.approx(20_000_000.0 / 3_600_000)
    assert result["P:Town2"] is None
    assert call_log == ["mean", "max", "max"]


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


def test_normalize_pop_density_outlier_does_not_crush_others():
    """A single extreme-density outlier must not zero out pop_density_norm
    for everyone else — this is exactly what happened with the old fake-area
    data (City of Bacoor at ~28,000/km² pinned pop_density_norm < 0.05 for
    96% of municipalities). log1p compression should keep mid-range
    municipalities meaningfully above zero even with one huge outlier."""
    from precompute_geo_scores import normalize_and_score

    units = [
        {"name": "Outlier", "province": "P", "region": "R", "income_class": "3rd",
         "income_score": 4, "population": 500000, "area_km2": 20,
         "pop_density": 500000 / 20, "solar": 5.0, "lat": 12.0, "lon": 122.0},
    ]
    # 20 mid-density municipalities, evenly spread
    for i in range(20):
        density = 100 + i * 50  # 100 .. 1050 per km2
        units.append({
            "name": f"Mid{i}", "province": "P", "region": "R", "income_class": "3rd",
            "income_score": 4, "population": int(density * 30), "area_km2": 30,
            "pop_density": density, "solar": 5.0, "lat": 12.0 + i * 0.01, "lon": 122.0,
        })

    result = normalize_and_score(units)
    mid_norms = [u["pop_density_norm"] for u in result if u["name"].startswith("Mid")]
    # With plain MinMax against the outlier, every one of these would be < 0.04.
    assert max(mid_norms) > 0.15, f"pop_density_norm still crushed by outlier: max={max(mid_norms)}"


def test_load_psa_lookup_strips_footnote_markers(tmp_path, monkeypatch):
    """PSA appends footnote markers to a handful of entries (e.g. '4th*' for a
    recently-reclassified LGU) — these must still match '4th', not silently
    fall through to the synthetic fallback (confirmed live: 6 real
    municipalities in the Q1 2026 release were wrongly treated as unmatched
    purely because of this asterisk before the fix)."""
    import precompute_geo_scores as pgs

    csv_path = tmp_path / "psa_income_population.csv"
    csv_path.write_text(
        "name,province,income_classification,population_2024\n"
        "Tipo-Tipo,Basilan,4th*,32734\n"
        "Normal Town,Laguna,1st,50000\n"
    )
    monkeypatch.setattr(pgs, "PSA_CSV_PATH", csv_path)

    lookup = pgs._load_psa_lookup()
    assert lookup[("tipo-tipo", "basilan")] == {"income_class": "4th", "population": 32734}
    assert lookup[("normal town", "laguna")] == {"income_class": "1st", "population": 50000}


def test_upsert_solar_batch_skips_synthetic(temp_db):
    """Synthetic fallback solar must never be persisted as GEE data,
    otherwise resume (_load_existing_solar) treats it as real forever."""
    import sqlite3 as _sq
    from precompute_geo_scores import _upsert_solar_batch

    conn = _sq.connect(str(temp_db))
    conn.execute("INSERT INTO municipalities (name, province, region) VALUES ('A', 'PA', 'R')")
    conn.execute("INSERT INTO municipalities (name, province, region) VALUES ('B', 'PA', 'R')")
    conn.commit()

    units = [
        {"name": "A", "province": "PA", "solar": 5.3},
        {"name": "B", "province": "PA", "solar": 5.1, "solar_synthetic": True},
    ]
    _upsert_solar_batch(conn, units)
    rows = conn.execute(
        """SELECT m.name, g.solar_irradiance FROM geo_scores g
           JOIN municipalities m ON m.id = g.municipality_id"""
    ).fetchall()
    conn.close()
    assert rows == [("A", 5.3)]  # B (synthetic) not written at all


def test_upsert_to_db_stores_null_solar_for_synthetic(temp_db):
    """upsert_to_db writes NULL solar_irradiance for synthetic-scored units."""
    from precompute_geo_scores import normalize_and_score, upsert_to_db

    units = _make_units(2)
    units[1]["solar_synthetic"] = True
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
    rows = dict(conn.execute(
        """SELECT m.name, g.solar_irradiance FROM geo_scores g
           JOIN municipalities m ON m.id = g.municipality_id"""
    ).fetchall())
    conn.close()
    assert rows["Town0"] == pytest.approx(4.5)
    assert rows["Town1"] is None  # synthetic → NULL in DB
    # geo_score itself is still computed (uses the synthetic value transiently)


def test_load_area_lookup_reads_csv(tmp_path, monkeypatch):
    import precompute_geo_scores as pgs

    csv_path = tmp_path / "municipality_land_area.csv"
    csv_path.write_text("name,province,area_km2,match_method\nSanta Rosa,Laguna,54.13,contains\n")
    monkeypatch.setattr(pgs, "AREA_CSV_PATH", csv_path)

    lookup = pgs._load_area_lookup()
    assert lookup.get(("santa rosa", "laguna")) == pytest.approx(54.13)


def test_load_area_lookup_missing_file_returns_empty(tmp_path, monkeypatch):
    import precompute_geo_scores as pgs
    monkeypatch.setattr(pgs, "AREA_CSV_PATH", tmp_path / "does_not_exist.csv")
    assert pgs._load_area_lookup() == {}


def test_load_db_coords_returns_coords(temp_db):
    """_load_db_coords returns {province:name -> (lat, lon)} for rows with coords."""
    import sqlite3 as _sq
    from precompute_geo_scores import _load_db_coords

    conn = _sq.connect(str(temp_db))
    conn.execute(
        "INSERT INTO municipalities (name, province, region, lat, lon) "
        "VALUES ('A', 'PA', 'R', 14.34, 121.08)"
    )
    conn.execute("INSERT INTO municipalities (name, province, region) VALUES ('B', 'PA', 'R')")
    conn.commit()
    conn.close()

    result = _load_db_coords()
    assert result.get("PA:A") == (pytest.approx(14.34), pytest.approx(121.08))
    assert "PA:B" not in result  # NULL coords excluded


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
