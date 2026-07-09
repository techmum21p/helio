"""
Tests for Highly Urbanized City (HUC) resolution in load_municipalities().

Regression coverage for a live incident (2026-07-08): the fuzzy-match
fallback resolved "City of Cebu (Not a Province)" to Cebu *province* (50
municipalities) instead of the single Cebu City HUC, because no exact index
entry existed for the pseudo-province string — a real province name outscored
the correct HUC in rapidfuzz's fallback. Same failure hit Cagayan de Oro
(matched Cagayan province, wrong region entirely) and Iloilo. Burned ~120
wasted Google Places calls before being caught mid-run.
"""
import pytest


@pytest.mark.parametrize("location,expected_name", [
    ("City of Cebu (Not a Province)", "City of Cebu"),
    ("City of Cagayan De Oro (Not a Province)", "City of Cagayan De Oro"),
    ("City of Iloilo (Not a Province)", "City of Iloilo"),
    ("Quezon City (Not a Province)", "Quezon City"),
    ("City of Isabela (Not a Province)", "City of Isabela"),
])
def test_load_municipalities_huc_resolves_to_single_unit(location, expected_name):
    from agents.geo_scoring import load_municipalities
    units = load_municipalities(location)
    assert len(units) == 1, f"expected 1 unit for '{location}', got {len(units)}: {[u['name'] for u in units]}"
    assert units[0]["name"] == expected_name


def test_load_municipalities_huc_bare_name_still_works():
    """The bare city name (no pseudo-province suffix) must keep resolving —
    this is how a plain 'Quezon City' query already worked before the fix."""
    from agents.geo_scoring import load_municipalities
    units = load_municipalities("Quezon City")
    assert len(units) == 1
    assert units[0]["name"] == "Quezon City"


def test_load_municipalities_real_province_unaffected():
    """The fix must not break resolution of the real province sharing a name
    with an HUC (e.g. 'Cebu' the province vs. 'City of Cebu' the HUC)."""
    from agents.geo_scoring import load_municipalities
    units = load_municipalities("Cebu")
    assert len(units) > 40  # Cebu province has ~49 municipalities/cities
