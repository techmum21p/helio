"""
Tests for get_municipality_profile and compare_municipalities tools.
Covers lazy re-synthesis, name resolution, and comparison workflows.
"""

ROWS = [
    {"municipality_id": 1, "name": "Pilar", "province": "Abra",     "region": "CAR",
     "final_score": 0.61, "geo_score": 0.66, "tier": "MEDIUM",
     "solar_irradiance": 5.0, "population": 10000, "pop_density": 120.0},
    {"municipality_id": 2, "name": "Pilar", "province": "Sorsogon", "region": "Region V",
     "final_score": 0.58, "geo_score": 0.60, "tier": "MEDIUM",
     "solar_irradiance": 5.1, "population": 70000, "pop_density": 200.0},
    {"municipality_id": 3, "name": "Jolo",  "province": "Sulu",     "region": "BARMM",
     "final_score": 0.84, "geo_score": 0.96, "tier": "MEDIUM",
     "solar_irradiance": 5.5, "population": 137000, "pop_density": 900.0},
]


def _patch(monkeypatch, refresh_result="row"):
    import agents.chat_tools as ct
    import agents.refresh as refresh_mod
    monkeypatch.setattr(ct, "get_latest_scored_municipalities", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(ct, "get_score_breakdown", lambda mid: {"geo": {"geo_score": 0.9}})
    calls = []

    def fake_refresh(mid):
        calls.append(mid)
        return dict(next(r for r in ROWS if r["municipality_id"] == mid)) if refresh_result == "row" else None

    monkeypatch.setattr(refresh_mod, "maybe_refresh_assessment", fake_refresh)
    return calls


def test_profile_resolves_and_triggers_refresh(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    calls = _patch(monkeypatch)
    out = get_municipality_profile("Jolo")
    assert calls == [3]                       # lazy re-synthesis fired
    assert out["profile"]["name"] == "Jolo"
    assert out["score_breakdown"] == {"geo": {"geo_score": 0.9}}


def test_profile_ambiguous_name_returns_candidates(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    out = get_municipality_profile("Pilar")
    assert "error" in out
    assert {c["province"] for c in out["candidates"]} == {"Abra", "Sorsogon"}


def test_profile_disambiguated_by_province(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    out = get_municipality_profile("Pilar", province="Abra")
    assert out["profile"]["province"] == "Abra"


def test_profile_unknown_name(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch)
    assert "error" in get_municipality_profile("Atlantis")


def test_profile_survives_refresh_returning_none(monkeypatch):
    from agents.chat_tools import get_municipality_profile
    _patch(monkeypatch, refresh_result=None)
    out = get_municipality_profile("Jolo")
    assert out["profile"]["name"] == "Jolo"   # falls back to the unrefreshed row


def test_compare_splits_name_comma_province(monkeypatch):
    from agents.chat_tools import compare_municipalities
    _patch(monkeypatch)
    out = compare_municipalities(["Jolo", "Pilar, Abra"])
    assert len(out["comparison"]) == 2
    assert out["comparison"][0]["profile"]["name"] == "Jolo"
    assert out["comparison"][1]["profile"]["province"] == "Abra"


def test_compare_rejects_wrong_count(monkeypatch):
    from agents.chat_tools import compare_municipalities
    _patch(monkeypatch)
    assert "error" in compare_municipalities(["Jolo"])
    assert "error" in compare_municipalities([f"m{i}" for i in range(7)])
