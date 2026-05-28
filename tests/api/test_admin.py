from unittest.mock import patch


def test_stats_returns_counts(app_client):
    r = app_client.get("/admin/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["municipalities"] == 1622
    assert data["geo_scores"] == 0     # not precomputed yet
    assert data["runs"] == 0
    assert "last_precompute" in data


def test_reindex_kb_accepted(app_client):
    with patch("api.routers.admin._reindex_kb_task"):
        r = app_client.post("/admin/reindex-kb")
    assert r.status_code == 202
    assert r.json()["status"] == "indexing started"


def test_refresh_scores_accepted(app_client):
    r = app_client.post("/admin/refresh-scores")
    assert r.status_code == 202


def test_refresh_scores_stream_returns_sse(app_client):
    with app_client.stream("GET", "/admin/refresh-scores/stream") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
