# Session Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist pipeline results and chat history to JSON files so users can reload any past run (including the interactive map) from the sidebar.

**Architecture:** A new `agents/session_store.py` module handles all disk I/O. `app.py` calls `save_session` after each pipeline run and after each chat message, and renders a "Load Past Session" expander in the sidebar that calls `load_session` to restore `st.session_state`.

**Tech Stack:** Python stdlib (`json`, `pathlib`, `datetime`), Streamlit session state, existing `config.py` path pattern.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `config.py` | Add `SESSIONS_DIR` constant and auto-create the directory |
| Create | `agents/session_store.py` | `save_session`, `load_session`, `list_sessions` |
| Create | `tests/test_session_store.py` | Unit tests for session_store |
| Modify | `app.py` | Import session_store, add auto-save calls, add Load expander |

---

## Task 1: Add SESSIONS_DIR to config.py

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add SESSIONS_DIR**

Open `config.py`. After the `REPORTS_DIR` line, add:

```python
SESSIONS_DIR = ROOT_DIR / "sessions"
```

Then in the `for d in [...]` loop that creates directories, add `SESSIONS_DIR` to the list:

```python
for d in [DATA_RAW, DATA_PROCESSED, KB_REPORTS, KB_INTEL, KB_INDEX, REPORTS_DIR, SESSIONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Verify the directory is created**

```bash
python -c "import config; print(config.SESSIONS_DIR, config.SESSIONS_DIR.exists())"
```

Expected output: `/path/to/helio/sessions True`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add SESSIONS_DIR to config"
```

---

## Task 2: Create agents/session_store.py (TDD)

**Files:**
- Create: `tests/test_session_store.py`
- Create: `agents/session_store.py`

- [ ] **Step 1: Create tests/test_session_store.py**

```python
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
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
source .venv_helios/bin/activate && python -m pytest tests/test_session_store.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.session_store'` (or similar import failure)

- [ ] **Step 3: Create agents/session_store.py**

```python
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
```

- [ ] **Step 4: Run tests — verify they all pass**

```bash
python -m pytest tests/test_session_store.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/session_store.py tests/test_session_store.py
git commit -m "feat: add session_store module with save/load/list"
```

---

## Task 3: Wire session persistence into app.py

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add the import at the top of app.py**

After the existing imports at the top of `app.py`, add:

```python
from agents.session_store import save_session, load_session, list_sessions
```

- [ ] **Step 2: Auto-save after pipeline run**

In the `if st.button("▶ Analyze", ...)` block, after line 46 (`st.session_state.chat_history = []`), add a save call:

```python
result = run_pipeline(location_input.strip())
st.session_state.pipeline_result = result
st.session_state.chat_history = []
save_session(result, [])          # ← add this line
```

- [ ] **Step 3: Auto-save after each chat message**

In the chatbot page section (around line 188), after `st.session_state.chat_history = updated_history`, add:

```python
st.session_state.chat_history = updated_history
if st.session_state.pipeline_result:                          # ← add these 2 lines
    save_session(st.session_state.pipeline_result, updated_history)
```

- [ ] **Step 4: Add the Load Past Session expander to the sidebar**

In the `with st.sidebar:` block, after the closing `if st.session_state.pipeline_result:` block (after line 60), add:

```python
st.markdown("---")
with st.expander("📂 Load Past Session"):
    sessions = list_sessions()
    if not sessions:
        st.caption("No saved sessions yet.")
    else:
        options = {s["label"]: s for s in sessions}
        chosen_label = st.selectbox(
            "Select session",
            list(options.keys()),
            label_visibility="collapsed",
        )
        if st.button("Load", use_container_width=True):
            loaded_pr, loaded_history = load_session(options[chosen_label]["path"])
            st.session_state.pipeline_result = loaded_pr
            st.session_state.chat_history = loaded_history
            st.rerun()
```

- [ ] **Step 5: Manual smoke test**

```bash
streamlit run app.py
```

1. Enter a location (e.g. `Laguna`) and click **▶ Analyze**
2. Verify `sessions/laguna_<run_id>.json` was created:
   ```bash
   ls sessions/
   ```
3. Refresh the browser — session state clears, map disappears
4. Open the **📂 Load Past Session** expander in the sidebar
5. Select the Laguna session and click **Load**
6. Verify the map, top targets, and report all reappear
7. Ask a question in the chatbot, verify `sessions/laguna_<run_id>.json` is updated with chat history:
   ```bash
   python -c "import json; d=json.load(open('sessions/$(ls sessions/ | head -1)')); print(d['chat_history'])"
   ```

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: persist sessions to disk and add Load Past Session UI"
```
