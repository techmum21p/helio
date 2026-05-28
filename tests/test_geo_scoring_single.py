"""
Tests for single-municipality mode in geo_scoring.py.
Uses real barangay package data — no mocks.
"""
import pytest


def test_load_single_municipality_finds_known_town():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("Santa Rosa", "Laguna")
    assert len(units) == 1
    assert "Santa Rosa" in units[0]["name"]
    assert units[0]["province"] == "Laguna"
    assert units[0]["region"] == "Region IV-A (CALABARZON)"


def test_load_single_municipality_fuzzy_match():
    from agents.geo_scoring import load_single_municipality
    # Slightly misspelled municipality name — rapidfuzz should still match
    units = load_single_municipality("Alamenos", "Laguna")  # typo: Alamenos → Alaminos
    assert len(units) == 1
    assert "Alaminos" in units[0]["name"]


def test_load_single_municipality_returns_empty_for_unknown():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("NonexistentTownXYZ", "NonexistentProvinceXYZ")
    assert units == []


def test_load_single_municipality_unit_has_required_fields():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("Bay", "Laguna")
    assert len(units) == 1
    u = units[0]
    for field in ["name", "province", "region", "lat", "lon", "income_class", "income_score", "population", "is_urban"]:
        assert field in u, f"Missing field: {field}"


def test_normalize_fixed_midpoint():
    from agents.geo_scoring import _normalize_fixed
    # Midpoint of range should give 0.5
    assert _normalize_fixed(5.25, 4.5, 6.0) == pytest.approx(0.5, abs=0.01)


def test_normalize_fixed_clamps_below_zero():
    from agents.geo_scoring import _normalize_fixed
    assert _normalize_fixed(0.0, 4.5, 6.0) == 0.0


def test_normalize_fixed_clamps_above_one():
    from agents.geo_scoring import _normalize_fixed
    assert _normalize_fixed(100.0, 4.5, 6.0) == 1.0


def test_compute_geo_scores_single_row_no_all_zeros():
    """Single-row scoring must not produce all-zero normalized values."""
    import geopandas as gpd
    from shapely.geometry import Point
    from agents.geo_scoring import compute_geo_scores

    gdf = gpd.GeoDataFrame(
        [{
            "name": "TestTown",
            "province": "Laguna",
            "region": "Region IV-A (CALABARZON)",
            "is_urban": True,
            "income_class": "3rd",
            "income_score": 4,
            "population": 80000,
            "geometry": Point(121.0, 14.2),
        }],
        geometry="geometry",
        crs="EPSG:4326",
    )

    scores = compute_geo_scores(gdf, ee=None)
    assert len(scores) == 1
    muni_scores = scores["TestTown"]
    # With fixed ranges, a mid-range municipality should have non-zero scores
    assert muni_scores["geo_score"] > 0.0
    assert muni_scores["geo_score"] <= 1.0


def test_compute_geo_scores_multi_row_uses_relative_ranking():
    """Multi-row scoring: highest scores should produce higher geo_score."""
    import geopandas as gpd
    from shapely.geometry import Point
    from agents.geo_scoring import compute_geo_scores

    gdf = gpd.GeoDataFrame(
        [
            {
                "name": "LowTown",
                "province": "Laguna", "region": "R4A",
                "is_urban": False, "income_class": "4th", "income_score": 3,
                "population": 10000, "geometry": Point(121.0, 14.0),
            },
            {
                "name": "HighTown",
                "province": "Laguna", "region": "R4A",
                "is_urban": True, "income_class": "1st", "income_score": 6,
                "population": 120000, "geometry": Point(121.1, 14.1),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )

    scores = compute_geo_scores(gdf, ee=None)
    assert scores["HighTown"]["geo_score"] > scores["LowTown"]["geo_score"]
