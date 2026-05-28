from unittest.mock import patch

def _make_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        return app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]

def test_chat_returns_reply(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="Test reply"):
        r = app_client.post("/chat", json={"run_id": run_id, "message": "Hello"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Test reply"
    assert r.json()["run_id"] == run_id

def test_chat_global_no_run_id(app_client):
    with patch("api.routers.chat._call_chatbot", return_value="Global reply"):
        r = app_client.post("/chat", json={"message": "Best solar towns?"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Global reply"
    assert r.json()["run_id"] is None

def test_chat_persists_messages(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="Stored reply"):
        app_client.post("/chat", json={"run_id": run_id, "message": "What's the score?"})
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What's the score?"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Stored reply"

def test_chat_no_persist_without_run_id(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._call_chatbot", return_value="No-persist reply"):
        app_client.post("/chat", json={"message": "Anything"})
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.json() == []

def test_chat_history_empty_for_new_run(app_client):
    run_id = _make_run(app_client)
    r = app_client.get(f"/chat/{run_id}/history")
    assert r.status_code == 200
    assert r.json() == []
