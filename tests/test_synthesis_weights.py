import pytest
import config


def test_compute_final_score_uses_new_weights():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 1.0}
    intel = {"web_score": 0.0}
    final, web = compute_final_score(geo, intel)
    # With geo=1.0, web=0.0 → final = 0.70 * 1.0 + 0.30 * 0.0 = 0.70
    assert final == pytest.approx(0.70, abs=1e-4)


def test_compute_final_score_returns_tuple():
    from agents.synthesis import compute_final_score
    result = compute_final_score({"geo_score": 0.5}, {"web_score": 0.5})
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_compute_final_score_uses_cached_web_score():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 0.6}
    intel = {"web_score": 0.8, "business_count": 0, "avg_price_level": 0}
    final, web = compute_final_score(geo, intel)
    # web_score=0.8 from cache; must use it directly
    assert web == pytest.approx(0.8)
    assert final == pytest.approx(0.70 * 0.6 + 0.30 * 0.8, abs=1e-4)


def test_compute_final_score_falls_back_when_no_cached_web_score():
    from agents.synthesis import compute_final_score
    geo   = {"geo_score": 0.5}
    intel = {"business_count": 0, "avg_price_level": 0, "avg_rating": 0, "commercial_anchors": 0}
    final, web = compute_final_score(geo, intel)
    # No web_score key → computed inline → should be 0.0 for empty intel
    assert web == pytest.approx(0.0)
    assert final == pytest.approx(0.70 * 0.5, abs=1e-4)


def test_synthesis_agent_stores_web_score_in_final_scores(monkeypatch):
    import agents.synthesis as synth
    monkeypatch.setattr(synth, "synthesize_municipality",
                        lambda m, g, i: {"assessment": "", "confidence": "HIGH",
                                         "opportunity": "", "risk": ""})
    from graph.state import SolarLeadState
    state: SolarLeadState = {
        "location": "Laguna", "run_id": "t1",
        "geo_scores": {
            "Biñan": {"geo_score": 0.7, "province": "Laguna", "region": "IV-A",
                      "income_class": "2nd", "population_raw": 100000,
                      "solar_norm": 0.7, "solar_yield_kwh": 1500,
                      "pop_norm": 0.6, "income_norm": 0.8, "is_urban": True,
                      "solar_raw": 5.0},
        },
        "web_intel": {
            "Biñan": {"web_score": 0.5, "business_count": 10, "avg_price_level": 2.0,
                      "avg_rating": 4.0, "commercial_anchors": 2,
                      "news_snippet": "", "property_snippet": "",
                      "commerce_snippet": "", "solar_news_snippet": ""},
        },
        "final_scores": None, "top_targets": None,
        "report_markdown": None, "report_path": None,
        "chat_history": [], "kb_updated": False, "errors": [], "status": "running",
    }
    result = synth.synthesis_agent(state)
    assert "Biñan" in result["final_scores"]
    assert "web_score" in result["final_scores"]["Biñan"]
    assert result["final_scores"]["Biñan"]["web_score"] == pytest.approx(0.5)
    assert "web_score" in result["top_targets"][0]
