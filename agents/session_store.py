import json
from datetime import datetime
from pathlib import Path

import config


def _slug(location: str) -> str:
    return location.lower().strip().replace(" ", "_")


def save_session(pipeline_result: dict, chat_history: list) -> None:
    slug = _slug(pipeline_result["location"])
    run_id = pipeline_result["run_id"]
    path = config.SESSIONS_DIR / f"{slug}_{run_id}.json"
    data = {
        "pipeline_result": pipeline_result,
        "chat_history": chat_history,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(filepath) -> tuple[dict, list]:
    data = json.loads(Path(filepath).read_text(encoding="utf-8"))
    return data["pipeline_result"], data["chat_history"]


def list_sessions() -> list[dict]:
    sessions = []
    for p in sorted(
        config.SESSIONS_DIR.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            pr = data.get("pipeline_result", {})
            saved_at = data.get("saved_at", "")
            try:
                dt = datetime.fromisoformat(saved_at)
                date_label = f"{dt.strftime('%b')} {dt.day} {dt.year}"
            except Exception:
                date_label = saved_at[:10]
            location = pr.get("location", p.stem)
            sessions.append({
                "path": str(p),
                "label": f"{location} — {date_label}",
                "location": location,
                "run_id": pr.get("run_id", ""),
                "saved_at": saved_at,
            })
        except Exception:
            continue
    return sessions
