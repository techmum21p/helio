# Map Refresh & Pipeline Completion Notification — Design Spec

**Date:** 2026-06-05
**Branch:** feat-geo-scoring
**File scope:** `app.py` only

---

## Problem

1. **Map stale after pipeline run:** `st_folium(m, ...)` is called without a `key` parameter. Streamlit treats the component as the same instance across reruns, so the map does not re-render when `pipeline_result` changes. The user sees the previous province (or blank) instead of the new results.

2. **No notification after pipeline completes:** The only feedback is `st.success("Done!")` inside the sidebar spinner block, which is easy to miss and disappears on next interaction. The user has to manually navigate to the Map & Scores page to see results.

---

## Changes

### 1. Map refresh fix (`app.py` line ~273)

Add a `key` tied to the current run ID:

```python
st_folium(m, height=500, use_container_width=True, key=f"map_{st.session_state.current_run_id}")
```

When `current_run_id` changes (new pipeline run or past-run load), Streamlit tears down and recreates the component. This eliminates the stale render.

**Why this works:** `streamlit-folium` uses Streamlit's custom component protocol — without a unique `key`, the component keeps its previous iframe state. A changing key forces a full remount.

### 2. Toast + auto-navigate on completion (`app.py` sidebar block)

**Session state initialization** — add at the top of the file alongside other defaults:

```python
if "page" not in st.session_state:
    st.session_state.page = "🗺️ Map & Scores"
```

**Sidebar radio** — bind to session state key so page can be changed programmatically:

```python
page = st.radio("Navigate", [...], key="nav_page")
```

Streamlit reads the widget's current value from `st.session_state.nav_page`; writing to it before `st.rerun()` changes which option is selected.

**After pipeline completes** — replace `st.success("Done!")` with:

```python
top_count = len(result.get("top_targets", []))
st.session_state.nav_page = "🗺️ Map & Scores"
st.toast(f"☀️ Analysis complete — {top_count} targets scored. Viewing map now.", icon="✅")
st.rerun()
```

**Error path** — on `except`, keep the existing `st.error(...)` with no navigation change.

---

## Non-goals

- No changes to the pipeline, agents, or DB.
- No browser/OS-level notifications.
- No changes to the warning path (`result.get("errors")` — keep existing `st.warning`).

---

## Testing

Manual test:
1. Run pipeline for a province → map should auto-load showing that province's circles.
2. Run pipeline for a different province → map should update to new province (no stale markers from previous run).
3. Load a past run from sidebar → map should update correctly (key changes because `current_run_id` updates).
4. Trigger a pipeline error → stays on current page, shows error, no navigation.
