from __future__ import annotations
import threading

_lock = threading.Lock()
_run_events: dict[str, list[dict]] = {}


def push_event(run_id: str, step: str, status: str, elapsed_ms: int) -> None:
    with _lock:
        _run_events.setdefault(run_id, []).append(
            {"step": step, "status": status, "elapsed_ms": elapsed_ms}
        )


def get_events(run_id: str) -> list[dict]:
    with _lock:
        return list(_run_events.get(run_id, []))


def clear_events(run_id: str) -> None:
    with _lock:
        _run_events.pop(run_id, None)
