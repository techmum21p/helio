"""
Tests for agents/geocoder.py — query construction and cache behaviour.
"""
import pytest


def test_nominatim_lookup_strips_pseudo_province_suffix(monkeypatch):
    """The '(Not a Province)' annotation is not a real place — including it
    in the query silently breaks every HUC lookup (returns zero results),
    so it must be stripped before querying Nominatim. Since the pseudo-
    province is always '<name> (Not a Province)', stripping the suffix
    collapses province == name, so the query drops the province entirely."""
    from agents import geocoder

    captured = {}

    class FakeResponse:
        def json(self):
            return [{"lat": "14.5547", "lon": "121.0244"}]

    def fake_get(url, params, headers, timeout):
        captured["q"] = params["q"]
        return FakeResponse()

    monkeypatch.setattr(geocoder.time, "sleep", lambda *a: None)
    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    result = geocoder._nominatim_lookup("City of Makati", "City of Makati (Not a Province)")

    assert "(Not a Province)" not in captured["q"]
    assert captured["q"] == "City of Makati, Philippines"
    assert result == (14.5547, 121.0244)


def test_nominatim_lookup_no_dangling_comma_when_province_empty(monkeypatch):
    """If province is nothing but the suffix, the query must not end up
    with an empty middle segment (e.g. 'Name, , Philippines')."""
    from agents import geocoder

    captured = {}

    class FakeResponse:
        def json(self):
            return [{"lat": "1.0", "lon": "2.0"}]

    def fake_get(url, params, headers, timeout):
        captured["q"] = params["q"]
        return FakeResponse()

    monkeypatch.setattr(geocoder.time, "sleep", lambda *a: None)
    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    geocoder._nominatim_lookup("Quezon City", " (Not a Province)")

    assert captured["q"] == "Quezon City, Philippines"


def test_nominatim_lookup_drops_duplicated_huc_province(monkeypatch):
    """A pseudo-province is always '<city name> (Not a Province)' — after
    stripping the suffix it equals the city name itself. Passing it through
    would send Nominatim a duplicated query ("City of Makati, City of
    Makati, Philippines"), which matches unrelated businesses/landmarks
    instead of the city boundary. Must collapse to the name alone."""
    from agents import geocoder

    captured = {}

    class FakeResponse:
        def json(self):
            return [{"lat": "14.5547", "lon": "121.0244"}]

    def fake_get(url, params, headers, timeout):
        captured["q"] = params["q"]
        return FakeResponse()

    monkeypatch.setattr(geocoder.time, "sleep", lambda *a: None)
    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    geocoder._nominatim_lookup("City of Makati", "City of Makati (Not a Province)")

    assert captured["q"] == "City of Makati, Philippines"


def test_nominatim_lookup_normal_province_unaffected(monkeypatch):
    """Ordinary province names (no suffix) must be passed through unchanged."""
    from agents import geocoder

    captured = {}

    class FakeResponse:
        def json(self):
            return [{"lat": "14.2", "lon": "121.4"}]

    def fake_get(url, params, headers, timeout):
        captured["q"] = params["q"]
        return FakeResponse()

    monkeypatch.setattr(geocoder.time, "sleep", lambda *a: None)
    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    geocoder._nominatim_lookup("Santa Rosa", "Laguna")

    assert captured["q"] == "Santa Rosa, Laguna, Philippines"


def test_query_candidates_retries_without_city_of_prefix():
    """Confirmed live (2026-07-08): 'City of Candon, Ilocos Sur' returns zero
    Nominatim results even though Candon is a real, well-known, easily
    mappable city — OSM indexes it by the common name, not the formal PSGC
    'City of X' designation. Must retry with the prefix stripped."""
    from agents.geocoder import _query_candidates
    candidates = _query_candidates("City of Candon", "Ilocos Sur")
    assert "City of Candon, Ilocos Sur, Philippines" in candidates
    assert "Candon, Ilocos Sur, Philippines" in candidates


def test_query_candidates_retries_without_city_of_manila():
    """Same bug, in the province position: 'Binondo, City of Manila' fails,
    'Binondo, Manila' resolves. Affects all of Manila's historic districts."""
    from agents.geocoder import _query_candidates
    candidates = _query_candidates("Binondo", "City of Manila")
    assert "Binondo, Manila, Philippines" in candidates


def test_query_candidates_retries_without_honorific_prefix():
    """'Pres. Manuel A. Roxas' fails; 'Manuel A. Roxas' resolves — same
    formal-vs-common-name pattern as 'City of X'."""
    from agents.geocoder import _query_candidates
    candidates = _query_candidates("Pres. Manuel A. Roxas", "Zamboanga del Norte")
    assert "Manuel A. Roxas, Zamboanga del Norte, Philippines" in candidates


def test_nominatim_lookup_falls_through_candidates_until_one_resolves(monkeypatch):
    """The first candidate query returning zero results must not stop the
    search — it should keep trying subsequent (less formal) variants."""
    from agents import geocoder

    calls = []

    class EmptyResponse:
        def json(self):
            return []

    class HitResponse:
        def json(self):
            return [{"lat": "17.19", "lon": "120.45"}]

    def fake_get(url, params, headers, timeout):
        calls.append(params["q"])
        if len(calls) == 1:
            return EmptyResponse()
        return HitResponse()

    monkeypatch.setattr(geocoder.time, "sleep", lambda *a: None)
    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    result = geocoder._nominatim_lookup("City of Candon", "Ilocos Sur")

    assert result == (17.19, 120.45)
    assert len(calls) == 2
    assert calls[0] == "City of Candon, Ilocos Sur, Philippines"
    assert calls[1] == "Candon, Ilocos Sur, Philippines"


def test_query_candidates_retries_without_sen_honorific():
    """Same honorific pattern as Pres., generalized: 'Sen. Ninoy Aquino' fails
    live, 'Ninoy Aquino' resolves."""
    from agents.geocoder import _query_candidates
    candidates = _query_candidates("Sen. Ninoy Aquino", "Sultan Kudarat")
    assert "Ninoy Aquino, Sultan Kudarat, Philippines" in candidates


def test_query_candidates_tondo_override():
    """The one Roman-numeral-split name in the whole dataset: 'Tondo I/II'
    fails live, plain 'Tondo' resolves."""
    from agents.geocoder import _query_candidates
    candidates = _query_candidates("Tondo I/II", "City of Manila")
    assert "Tondo, Manila, Philippines" in candidates


def test_get_coords_falls_back_when_nominatim_returns_none(monkeypatch, tmp_path):
    from agents import geocoder

    monkeypatch.setattr(geocoder, "_CACHE_FILE", tmp_path / "coords.json")
    monkeypatch.setattr(geocoder, "_nominatim_lookup", lambda name, province: None)

    result = geocoder.get_coords("Nowhere", "Nowhere Province", fallback=(1.0, 2.0))
    assert result == (1.0, 2.0)
