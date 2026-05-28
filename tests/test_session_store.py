import json
import pytest
import config


@pytest.fixture(autouse=True)
def patch_sessions_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path)


def test_save_creates_file(tmp_path):
    from agents.session_store import save_session
    pr = {"location": "Laguna", "run_id": "abc12345", "top_targets": []}
    save_session(pr, [])
    assert (tmp_path / "laguna_abc12345.json").exists()


def test_save_slugifies_location(tmp_path):
    from agents.session_store import save_session
    pr = {"location": "Metro Manila", "run_id": "def67890"}
    save_session(pr, [])
    assert (tmp_path / "metro_manila_def67890.json").exists()


def test_load_returns_pipeline_result_and_history(tmp_path):
    from agents.session_store import save_session, load_session
    pr = {"location": "Laguna", "run_id": "abc12345", "top_targets": [{"municipality": "Biñan"}]}
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    save_session(pr, history)
    loaded_pr, loaded_history = load_session(tmp_path / "laguna_abc12345.json")
    assert loaded_pr["top_targets"][0]["municipality"] == "Biñan"
    assert loaded_history[1]["content"] == "hi"


def test_save_overwrites_chat_history(tmp_path):
    from agents.session_store import save_session, load_session
    pr = {"location": "Laguna", "run_id": "abc12345"}
    save_session(pr, [])
    save_session(pr, [{"role": "user", "content": "updated"}])
    _, history = load_session(tmp_path / "laguna_abc12345.json")
    assert len(history) == 1
    assert history[0]["content"] == "updated"


def test_list_sessions_empty(tmp_path):
    from agents.session_store import list_sessions
    assert list_sessions() == []


def test_list_sessions_returns_metadata(tmp_path):
    from agents.session_store import save_session, list_sessions
    pr = {"location": "Laguna", "run_id": "abc12345"}
    save_session(pr, [])
    sessions = list_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s["location"] == "Laguna"
    assert s["run_id"] == "abc12345"
    assert "label" in s
    assert "path" in s
    assert "saved_at" in s


def test_list_sessions_label_format(tmp_path):
    from agents.session_store import save_session, list_sessions
    pr = {"location": "Laguna", "run_id": "abc12345"}
    save_session(pr, [])
    sessions = list_sessions()
    label = sessions[0]["label"]
    assert label.startswith("Laguna")
    assert "—" in label


def test_list_sessions_sorted_newest_first(tmp_path):
    import time
    from agents.session_store import save_session, list_sessions
    pr1 = {"location": "Laguna", "run_id": "aaa00001"}
    pr2 = {"location": "Manila", "run_id": "bbb00002"}
    save_session(pr1, [])
    time.sleep(0.05)  # ensure different mtime
    save_session(pr2, [])
    sessions = list_sessions()
    assert sessions[0]["location"] == "Manila"
    assert sessions[1]["location"] == "Laguna"
