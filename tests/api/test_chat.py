from unittest.mock import patch


def _make_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        return app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]


def _read_sse(response) -> str:
    """Collect all SSE data lines from a streaming response into one string."""
    return b"".join(response.iter_bytes()).decode()


def test_chat_returns_stream(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Hello", " world"])):
        with app_client.stream("POST", "/chat", json={"run_id": run_id, "message": "Hi"}
        ) as r:
            body = _read_sse(r)
    assert "data: Hello\n\n" in body
    assert "data:  world\n\n" in body
    assert "data: [DONE]\n\n" in body


def test_chat_global_no_run_id(app_client):
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Global reply"])):
        with app_client.stream("POST", "/chat", json={"message": "Best solar towns?"}) as r:
            body = _read_sse(r)
    assert "data: Global reply\n\n" in body
    assert "data: [DONE]\n\n" in body


def test_chat_persists_messages(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Stored", " reply"])):
        with app_client.stream(
            "POST", "/chat", json={"run_id": run_id, "message": "What's the score?"}
        ) as r:
            _read_sse(r)  # exhaust the stream so persistence runs
    r2 = app_client.get(f"/chat/{run_id}/history")
    msgs = r2.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What's the score?"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Stored reply"


def test_chat_no_persist_without_run_id(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["No-persist"])):
        with app_client.stream("POST", "/chat", json={"message": "Anything"}) as r:
            _read_sse(r)
    assert app_client.get(f"/chat/{run_id}/history").json() == []


def test_chat_history_empty_for_new_run(app_client):
    run_id = _make_run(app_client)
    assert app_client.get(f"/chat/{run_id}/history").json() == []
