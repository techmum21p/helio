import json


ROWS = [
    {"municipality_id": 1, "name": "Jolo",   "province": "Sulu", "region": "BARMM",
     "final_score": 0.84, "geo_score": 0.96, "tier": "MEDIUM",
     "solar_irradiance": 5.5, "population": 137000, "pop_density": 900.0},
    {"municipality_id": 2, "name": "Siasi",  "province": "Sulu", "region": "BARMM",
     "final_score": 0.79, "geo_score": 0.89, "tier": "MEDIUM",
     "solar_irradiance": 5.4, "population": 60000, "pop_density": 300.0},
    {"municipality_id": 3, "name": "Lugus",  "province": "Sulu", "region": "BARMM",
     "final_score": None, "geo_score": 0.55, "tier": None,
     "solar_irradiance": None, "population": 20000, "pop_density": None},
    {"municipality_id": 4, "name": "Digos",  "province": "Davao del Sur", "region": "Region XI",
     "final_score": 0.70, "geo_score": 0.75, "tier": "MEDIUM",
     "solar_irradiance": 5.2, "population": 188000, "pop_density": 650.0},
    {"municipality_id": 5, "name": "Mati",   "province": "Davao Oriental", "region": "Region XI",
     "final_score": 0.65, "geo_score": 0.72, "tier": "MEDIUM",
     "solar_irradiance": 5.1, "population": 141000, "pop_density": 250.0},
]


def _patch_rows(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities", lambda: [dict(r) for r in ROWS])


def test_rank_by_final_score_descending(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", n=5, metric="final_score")
    names = [r["name"] for r in out["results"]]
    assert names == ["Jolo", "Siasi"]          # Lugus excluded: NULL final_score
    assert out["municipalities_in_scope"] == 3
    assert out["municipalities_with_metric"] == 2
    assert out["results"][0]["rank"] == 1


def test_rank_ascending(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", metric="final_score", ascending=True)
    assert [r["name"] for r in out["results"]] == ["Siasi", "Jolo"]


def test_rank_nationwide_when_no_province(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(n=3, metric="population")
    assert out["scope"] == "nationwide"
    assert [r["name"] for r in out["results"]] == ["Digos", "Mati", "Jolo"]


def test_ambiguous_province_returns_candidates(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="davao")
    assert "error" in out
    assert set(out["candidates"]) == {"Davao del Sur", "Davao Oriental"}


def test_exact_province_beats_substring(monkeypatch):
    import agents.chat_tools as ct
    _patch_rows(monkeypatch)
    resolved, candidates = ct._resolve_province("sulu", ct.get_latest_scored_municipalities())
    assert resolved == "Sulu" and candidates == []


def test_invalid_metric_rejected(monkeypatch):
    from agents.chat_tools import get_top_municipalities
    _patch_rows(monkeypatch)
    out = get_top_municipalities(province="Sulu", metric="poverty")
    assert "error" in out and "search_kb" in out["error"]


def test_execute_tool_returns_json_and_never_raises(monkeypatch):
    from agents.chat_tools import execute_tool
    _patch_rows(monkeypatch)
    ok = json.loads(execute_tool("get_top_municipalities", {"province": "Sulu", "n": 1}))
    assert ok["results"][0]["name"] == "Jolo"
    bad_tool = json.loads(execute_tool("nope", {}))
    assert "error" in bad_tool
    bad_args = json.loads(execute_tool("get_top_municipalities", {"bogus_arg": 1}))
    assert "error" in bad_args
