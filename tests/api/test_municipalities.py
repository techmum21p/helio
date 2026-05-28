import pytest


def test_list_provinces_returns_all(app_client):
    r = app_client.get("/provinces")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert len(names) >= 80  # PH has 82 provinces
    assert "Laguna" in names
    assert "Nueva Ecija" in names


def test_list_municipalities_no_filter(app_client):
    r = app_client.get("/municipalities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert "name" in data[0]
    assert "province" in data[0]


def test_list_municipalities_filter_by_province(app_client):
    r = app_client.get("/municipalities?province=Laguna")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert all(m["province"] == "Laguna" for m in data)


def test_list_municipalities_search(app_client):
    r = app_client.get("/municipalities?search=Calamba")
    assert r.status_code == 200
    names = [m["name"] for m in r.json()]
    assert any("Calamba" in n for n in names)


def test_municipality_has_expected_fields(app_client):
    r = app_client.get("/municipalities?province=Laguna&limit=1")
    assert r.status_code == 200
    m = r.json()[0]
    for field in ("id", "name", "province", "region"):
        assert field in m
