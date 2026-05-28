import sqlite3
import pytest
import config
from agents.location_db import (
    get_provinces,
    get_municipalities,
    get_barangays,
    get_province_name,
    get_municipality_name,
)

SCHEMA = """
CREATE TABLE regions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE provinces (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, region_id INTEGER NOT NULL);
CREATE TABLE municipalities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, province_id INTEGER NOT NULL);
CREATE TABLE barangays (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, municipality_id INTEGER NOT NULL);
"""


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_locations.db"
    monkeypatch.setattr(config, "LOCATION_DB", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO regions (name) VALUES ('Region IV-A')")
    conn.execute("INSERT INTO provinces (name, region_id) VALUES ('Laguna', 1)")
    conn.execute("INSERT INTO provinces (name, region_id) VALUES ('Cavite', 1)")
    conn.execute("INSERT INTO municipalities (name, province_id) VALUES ('Biñan', 1)")
    conn.execute("INSERT INTO municipalities (name, province_id) VALUES ('Santa Rosa', 1)")
    conn.execute("INSERT INTO barangays (name, municipality_id) VALUES ('Poblacion', 1)")
    conn.execute("INSERT INTO barangays (name, municipality_id) VALUES ('San Antonio', 1)")
    conn.commit()
    conn.close()
    return db_path


def test_get_provinces_returns_all(test_db):
    provinces = get_provinces()
    assert len(provinces) == 2
    names = [p["name"] for p in provinces]
    assert "Laguna" in names
    assert "Cavite" in names


def test_get_provinces_sorted_by_name(test_db):
    provinces = get_provinces()
    names = [p["name"] for p in provinces]
    assert names == sorted(names)


def test_get_provinces_have_id_and_name_keys(test_db):
    provinces = get_provinces()
    assert "id" in provinces[0]
    assert "name" in provinces[0]


def test_get_municipalities_filters_by_province(test_db):
    munis = get_municipalities(1)
    assert len(munis) == 2
    names = [m["name"] for m in munis]
    assert "Biñan" in names
    assert "Santa Rosa" in names


def test_get_municipalities_empty_for_unknown_province(test_db):
    assert get_municipalities(999) == []


def test_get_municipalities_have_id_and_name_keys(test_db):
    munis = get_municipalities(1)
    assert "id" in munis[0]
    assert "name" in munis[0]


def test_get_municipalities_sorted_by_name(test_db):
    # Fixture inserts Biñan (id=1) then Santa Rosa (id=2)
    # Alphabetical order: Biñan < Santa Rosa → Biñan should come first
    munis = get_municipalities(1)
    names = [m["name"] for m in munis]
    assert names == sorted(names)


def test_get_barangays_filters_by_municipality(test_db):
    brgys = get_barangays(1)
    assert len(brgys) == 2
    names = [b["name"] for b in brgys]
    assert "Poblacion" in names


def test_get_barangays_empty_for_other_municipality(test_db):
    assert get_barangays(2) == []


def test_get_barangays_have_id_and_name_keys(test_db):
    brgys = get_barangays(1)
    assert "id" in brgys[0]
    assert "name" in brgys[0]


def test_get_province_name(test_db):
    assert get_province_name(1) == "Laguna"
    assert get_province_name(2) == "Cavite"


def test_get_province_name_missing_returns_empty(test_db):
    assert get_province_name(999) == ""


def test_get_municipality_name(test_db):
    assert get_municipality_name(1) == "Biñan"


def test_get_municipality_name_missing_returns_empty(test_db):
    assert get_municipality_name(999) == ""


def test_get_provinces_empty_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCATION_DB", tmp_path / "nonexistent.db")
    assert get_provinces() == []
