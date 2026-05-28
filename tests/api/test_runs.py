import time
from unittest.mock import patch

FAKE_RESULT = {
    "location": "Laguna",
    "top_targets": [
        {
            "municipality": "City of Calamba", "province": "Laguna",
            "geo_score": 0.75, "web_score": 0.60, "final_score": 0.705,
            "tier": "High", "assessment": "Strong opportunity.",
            "opportunities": ["Good solar"], "risks": ["Competition"],
        }
    ],
    "report_markdown": "# Laguna Report\nContent here.",
    "report_path": "reports/laguna_test.md",
    "errors": [],
}

def test_create_run_returns_run_id(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        r = app_client.post("/runs", json={"location": "Laguna"})
    assert r.status_code == 201
    assert "run_id" in r.json()

def test_list_runs_returns_created_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]
    r = app_client.get("/runs")
    assert r.status_code == 200
    ids = [run["id"] for run in r.json()]
    assert run_id in ids

def test_get_run_returns_detail(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Nueva Ecija"}).json()["run_id"]
    r = app_client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == run_id
    assert data["location"] == "Nueva Ecija"
    assert "results" in data
    assert "report" in data

def test_get_run_404_for_unknown(app_client):
    r = app_client.get("/runs/doesnotexist")
    assert r.status_code == 404

def test_run_results_persisted(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]
    from api.routers.runs import _persist_run_results
    _persist_run_results(run_id, FAKE_RESULT)
    r = app_client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1
    assert r.json()["report"] is not None
