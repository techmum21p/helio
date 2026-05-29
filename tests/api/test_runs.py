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


from api.events import push_event, clear_events

def test_stream_emits_step_events(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]

    # Simulate events that the pipeline would have pushed
    push_event(run_id, "geo_scoring", "running", 0)
    push_event(run_id, "geo_scoring", "done", 4200)

    # Mark run as done in DB
    import api.db as db_module
    with db_module.get_db() as conn:
        conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))

    with app_client.stream("GET", f"/runs/{run_id}/stream") as response:
        chunks = b"".join(response.iter_bytes()).decode()

    assert '"step": "geo_scoring"' in chunks
    assert '"status": "done"' in chunks
    assert '"step": "complete"' in chunks
    clear_events(run_id)
