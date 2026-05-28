def test_health(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "Helio" in data["app"]
