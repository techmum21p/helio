# Map Refresh & Pipeline Completion Notification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Folium map not re-rendering after a pipeline run, and auto-navigate to the Map & Scores page with a toast notification when the pipeline completes.

**Architecture:** Both changes are isolated to `app.py`. The map fix adds a `key` parameter to `st_folium` so Streamlit remounts the component on each new run. The notification binds the sidebar radio to session state so the active page can be changed programmatically before `st.rerun()`.

**Tech Stack:** Streamlit, streamlit-folium

---

## File Map

| File | Change |
|---|---|
| `app.py` | 3 edits: session state init, radio key binding, st_folium key, post-pipeline nav+toast |

---

### Task 1: Initialize `page` session state key

**Files:**
- Modify: `app.py:72-79` (session state defaults block)

- [ ] **Step 1: Add `page` key to session state defaults**

In `app.py`, find the session state defaults block (around line 72–79):
```python
if "pipeline_result" not in st.session_state:
    st.session_state.pipeline_result = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_run_id" not in st.session_state:
    st.session_state.current_run_id = ""
```

Add one more entry directly after:
```python
if "page" not in st.session_state:
    st.session_state.page = "🗺️ Map & Scores"
```

- [ ] **Step 2: Verify app still starts without errors**

```bash
cd /Users/aireesm4/Python_Projects/helio && source .venv_helios/bin/activate && python -c "import app" 2>&1 | head -20
```

Expected: no output (no import-time errors).

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: initialize page session state key for programmatic navigation"
```

---

### Task 2: Bind sidebar radio to session state key

**Files:**
- Modify: `app.py:87` (sidebar `st.radio` call)

- [ ] **Step 1: Add `key="nav_page"` to the radio widget**

Find the radio call in the sidebar (around line 87):
```python
page = st.radio("Navigate", ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot", "⚙️ Admin", "📚 Past Runs"])
```

Replace with:
```python
page = st.radio(
    "Navigate",
    ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot", "⚙️ Admin", "📚 Past Runs"],
    key="nav_page",
)
```

With `key="nav_page"`, Streamlit stores the selected value in `st.session_state.nav_page`. Writing to `st.session_state.nav_page` before `st.rerun()` will update which page is shown.

- [ ] **Step 2: Verify navigation still works manually**

```bash
streamlit run app.py
```

Click through all 5 pages in the sidebar — each should render correctly. No errors in terminal.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: bind sidebar radio to nav_page session state key"
```

---

### Task 3: Auto-navigate + toast after pipeline success

**Files:**
- Modify: `app.py:132-144` (pipeline execution block in sidebar)

- [ ] **Step 1: Replace post-pipeline success block**

Find the pipeline success block (around line 138–141):
```python
st.session_state.pipeline_result = result
st.session_state.chat_history = []
if result.get("errors"):
    st.warning(f"Completed with {len(result['errors'])} warning(s).")
else:
    st.success("Done!")
```

Replace with:
```python
st.session_state.pipeline_result = result
st.session_state.chat_history = []
if result.get("errors"):
    st.warning(f"Completed with {len(result['errors'])} warning(s).")
top_count = len(result.get("top_targets") or [])
st.session_state.nav_page = "🗺️ Map & Scores"
st.toast(f"☀️ Analysis complete — {top_count} targets scored.", icon="✅")
st.rerun()
```

Note: `st.rerun()` replaces the old implicit rerun that happened naturally after the `with st.spinner` block exited. The explicit call here happens immediately after setting nav_page, ensuring the page switches before the next render. The `st.warning` for partial errors is kept — users still see it on the map page after navigation.

- [ ] **Step 2: Verify the flow**

```bash
streamlit run app.py
```

Select a province, click Analyze. Expected behavior:
1. Spinner shows in sidebar during pipeline run.
2. When done: toast appears in bottom-right corner with target count.
3. App automatically switches to the Map & Scores page.
4. Map renders with circles for the analyzed province.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: auto-navigate to map + toast notification on pipeline completion"
```

---

### Task 4: Fix map stale render with st_folium key

**Files:**
- Modify: `app.py:273` (`st_folium` call)

- [ ] **Step 1: Add `key` parameter to `st_folium`**

Find the `st_folium` call (around line 273):
```python
st_folium(m, height=500, use_container_width=True)
```

Replace with:
```python
st_folium(m, height=500, use_container_width=True, key=f"map_{st.session_state.current_run_id}")
```

When `current_run_id` changes (new pipeline run or loaded past run), Streamlit tears down the Folium iframe and creates a fresh one — eliminating stale map renders.

- [ ] **Step 2: Verify map updates correctly for two consecutive runs**

```bash
streamlit run app.py
```

1. Run pipeline for Province A → map shows Province A's circles.
2. Run pipeline for Province B → map shows Province B's circles (no leftover markers from A).
3. Load a past run from the sidebar → map updates to that run's province.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "fix: add run-scoped key to st_folium to prevent stale map renders"
```

---

## Self-Review

**Spec coverage:**
- ✅ Map not refreshing → Task 4 (st_folium key)
- ✅ Toast notification on completion → Task 3
- ✅ Auto-navigate to Map & Scores → Tasks 1, 2, 3 together
- ✅ Error path unchanged → Task 3 preserves `st.error` in except block, no navigation

**Placeholder scan:** None found.

**Type consistency:** `st.session_state.nav_page` used consistently in Tasks 2 and 3. `current_run_id` already exists in session state (initialized at line 78). No new types introduced.
