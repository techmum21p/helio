import pytest
from api.events import push_event, get_events, clear_events


@pytest.fixture(autouse=True)
def _clean_events():
    from api import events as _ev
    _ev._run_events.clear()
    yield
    _ev._run_events.clear()


def test_push_and_get():
    push_event("run1", "geo_scoring", "running", 0)
    push_event("run1", "geo_scoring", "done", 4200)
    events = get_events("run1")
    assert len(events) == 2
    assert events[0] == {"step": "geo_scoring", "status": "running", "elapsed_ms": 0}
    assert events[1] == {"step": "geo_scoring", "status": "done", "elapsed_ms": 4200}


def test_get_unknown_run_returns_empty():
    assert get_events("nonexistent") == []


def test_clear_removes_events():
    push_event("run2", "web_intel", "done", 1000)
    clear_events("run2")
    assert get_events("run2") == []


def test_clear_unknown_run_is_safe():
    clear_events("never_existed")  # must not raise
