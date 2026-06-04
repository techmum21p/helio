"""
Solar Lead Intelligence Platform
Streamlit frontend — four pages:
  1. Map & Scores  — run pipeline, view opportunity map
  2. Report        — view and download generated report
  3. Chatbot       — RAG chatbot over generated KB
  4. Admin         — geo score refresh, DB stats, KB re-index
"""

import json
import threading
import time
import uuid
from datetime import datetime

import streamlit as st
import folium
from streamlit_folium import st_folium

import config
from graph.pipeline import run_pipeline
from agents.chatbot import chat, index_documents_from_kb
from agents import db_store
from agents.location_db import get_provinces, get_municipalities


def _score_dot(score: float) -> str:
    """Color dot matching map circle thresholds: green ≥0.65, orange ≥0.35, red <0.35."""
    if score >= 0.65:
        return "🟢"
    elif score >= 0.35:
        return "🟡"
    return "🔴"


def _bans(items: list[tuple[str, str]]) -> str:
    """Responsive BAN cards in a 2×2 grid using CSS clamp — scales from laptop to wide monitor."""
    def card(label, value):
        return (
            f'<div style="flex:1;min-width:0;padding:8px 6px;background:#f8f9fa;'
            f'border-radius:6px;text-align:center;overflow:hidden">'
            f'<div style="font-size:clamp(0.55rem,1.1vw,0.75rem);color:#6c757d;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{label}</div>'
            f'<div style="font-size:clamp(0.85rem,1.8vw,1.25rem);font-weight:700;color:#212529;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{value}</div>'
            f'</div>'
        )
    row_style = 'display:flex;gap:6px;margin-bottom:6px'
    rows = "".join(
        f'<div style="{row_style}">{card(items[i][0], items[i][1])}{card(items[i+1][0], items[i+1][1])}</div>'
        for i in range(0, len(items), 2)
    )
    return rows


@st.cache_data(ttl=3600)
def _cached_provinces() -> list[dict]:
    return get_provinces()


@st.cache_data(ttl=3600)
def _cached_municipalities(province_id: int) -> list[dict]:
    return get_municipalities(province_id)


st.set_page_config(
    page_title="Solar Lead Intelligence",
    page_icon="☀️",
    layout="wide",
)

# ── Session state defaults ─────────────────────────────────────────────────────
if "pipeline_result" not in st.session_state:
    st.session_state.pipeline_result = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_run_id" not in st.session_state:
    st.session_state.current_run_id = ""

# Module-level precompute state — written by background thread, read by Streamlit UI
_precompute_state: dict = {"done": 0, "total": 0, "running": False}

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("☀️ Solar Lead Intel")
    st.markdown("---")
    page = st.radio(
        "Navigate",
        ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot", "⚙️ Admin", "📚 Past Runs"],
        key="nav_page",
    )

    st.markdown("---")
    st.subheader("Run Pipeline")

    provinces = _cached_provinces()
    if not provinces:
        st.warning("⚠️ Location DB not built. Run: `python scripts/build_location_db.py`")
        location_str = None
        selected_prov_name = None
    else:
        prov_by_name = {p["name"]: p["id"] for p in provinces}
        selected_prov_name = st.selectbox(
            "Province",
            options=["— Select province —"] + list(prov_by_name.keys()),
        )

        selected_muni_names: list[str] = []
        if selected_prov_name != "— Select province —":
            prov_id = prov_by_name[selected_prov_name]
            munis = _cached_municipalities(prov_id)
            muni_options = {m["name"]: m["id"] for m in munis}
            selected_muni_names = st.multiselect(
                "Municipalities (leave blank to analyze all)",
                options=list(muni_options.keys()),
            )

        if selected_prov_name == "— Select province —":
            location_str = None
        elif len(selected_muni_names) == 1:
            location_str = f"{selected_muni_names[0]}, {selected_prov_name}"
        elif len(selected_muni_names) > 1:
            towns = " | ".join(selected_muni_names)
            location_str = f"{towns}, {selected_prov_name}"
        else:
            location_str = selected_prov_name

    if st.button("▶ Analyze", type="primary", use_container_width=True):
        if not location_str:
            st.error("Select a province first.")
        else:
            run_id = uuid.uuid4().hex[:8]
            st.session_state.current_run_id = run_id
            db_store.create_run(run_id, location_str, selected_prov_name)

            should_rerun = False
            with st.spinner(f"Analyzing {location_str}... (this takes ~1-2 mins)"):
                try:
                    result = run_pipeline(location_str, run_id=run_id)
                    db_store.complete_run(run_id, result.get("top_targets") or [])
                    st.session_state.pipeline_result = result
                    st.session_state.chat_history = []
                    top_count = len(result.get("top_targets") or [])
                    st.session_state.nav_page = "🗺️ Map & Scores"
                    if result.get("errors"):
                        st.warning(f"Completed with {len(result['errors'])} warning(s). {top_count} targets scored.")
                    else:
                        st.toast(f"☀️ Analysis complete — {top_count} targets scored.", icon="✅")
                    should_rerun = True
                except Exception as exc:
                    db_store.fail_run(run_id, str(exc))
                    st.error(f"Pipeline failed: {exc}")

            if should_rerun:
                st.rerun()

    if st.session_state.pipeline_result:
        result = st.session_state.pipeline_result
        top = result.get("top_targets", [])
        st.markdown(f"**{len(top)} municipalities scored**")
        if top:
            st.markdown(f"🥇 Top target: **{top[0]['municipality']}**")
            st.markdown(f"Score: `{top[0]['final_score']:.3f}` | Tier: `{top[0]['tier']}`")

    st.markdown("---")
    st.subheader("📋 Past Runs")
    runs = db_store.list_runs(limit=10)
    if not runs:
        st.caption("No completed runs yet.")
    else:
        for run in runs:
            if run["status"] == "failed":
                st.caption(f"⚠️ {run['location']} — failed")
                continue
            try:
                dt = datetime.fromisoformat(run["created_at"])
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = str(run["created_at"])[:10]
            top_score = run.get("top_score")
            score_str = f"top {top_score:.2f}" if top_score else "no data"
            tier_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(
                run.get("top_tier", ""), "⚪"
            )
            btn_label = f"🗺️ {run['location']} — {date_str}"
            btn_help  = f"{run.get('target_count', 0)} targets · {score_str} {tier_icon}"
            if st.button(btn_label, key=f"run_{run['id']}",
                         use_container_width=True, help=btn_help):
                loaded = db_store.load_run(run["id"])
                if loaded:
                    st.session_state.pipeline_result = loaded
                    st.session_state.chat_history    = db_store.load_chat_history(run["id"])
                    st.session_state.current_run_id  = run["id"]
                    st.toast(f"Loaded: {run['location']}", icon="📂")
                    st.rerun()
                else:
                    st.error(f"Could not load run {run['id'][:8]}…")


# ── Page: Map & Scores ─────────────────────────────────────────────────────────
if page == "🗺️ Map & Scores":
    st.title("🗺️ Solar Opportunity Map")
    st.markdown(
        "🟢 **High** (score ≥ 0.65) &nbsp;&nbsp; 🟡 **Medium** (0.35 – 0.64) &nbsp;&nbsp; 🔴 **Low** (< 0.35)",
        unsafe_allow_html=True,
    )

    if not st.session_state.pipeline_result:
        st.info("Run the pipeline from the sidebar to see results.")
    else:
        result = st.session_state.pipeline_result
        top_targets = result.get("top_targets", [])
        geo_geojson = result.get("geo_geojson")

        col1, col2 = st.columns([3, 2.5])

        with col1:
            score_map  = {t["municipality"]: t["final_score"] for t in top_targets}
            target_map = {t["municipality"]: t                  for t in top_targets}

            lats = [t["lat"] for t in top_targets if t.get("lat")]
            lons = [t["lon"] for t in top_targets if t.get("lon")]
            center = [sum(lats) / len(lats), sum(lons) / len(lons)] if lats else [12.5, 122.5]
            m = folium.Map(location=center, zoom_start=10, tiles="CartoDB positron")

            if geo_geojson:
                geo_data = json.loads(geo_geojson)
                for feature in geo_data.get("features", []):
                    props = feature.get("properties", {})
                    name  = props.get("name", "")
                    geom  = feature.get("geometry", {})

                    if geom.get("type") != "Point":
                        continue

                    lon, lat = geom["coordinates"]
                    score    = score_map.get(name, props.get("geo_score", 0))
                    target   = target_map.get(name, {})

                    if score >= 0.65:
                        color = "#2ecc71"
                    elif score >= 0.35:
                        color = "#f39c12"
                    else:
                        color = "#e74c3c"

                    radius     = 6 + score * 14
                    irr        = target.get("solar_irradiance", 0)
                    income     = target.get("income_class", "N/A")
                    pop        = target.get("population", 0)
                    yield_kwp  = target.get("solar_yield_kwh", 0)
                    yield_5kwp = int(yield_kwp * 5)
                    tier       = target.get("tier", "")
                    province   = target.get("province", props.get("province", ""))

                    popup_html = (
                        f"<b>{name}</b> ({province})<br>"
                        f"────────────────────<br>"
                        f"Final Score: {score:.3f} &nbsp;|&nbsp; Tier: {tier}<br>"
                        f"&#9728; Irradiance: {irr:.2f} kWh/m&#178;/day<br>"
                        f"&#128200; Income: {income} class<br>"
                        f"&#128101; Population: {pop:,}<br>"
                        f"&#9889; Yield: {yield_kwp:,.0f} kWh/kWp/yr "
                        f"(~{yield_5kwp:,} kWh/yr for 5 kWp)"
                    )

                    folium.CircleMarker(
                        location=[lat, lon],
                        radius=radius,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.75,
                        weight=1.5,
                        popup=folium.Popup(popup_html, max_width=260),
                        tooltip=f"{name}: {score:.3f} | {irr:.1f} kWh/m²/day",
                    ).add_to(m)

            if lats and lons:
                m.fit_bounds(
                    [[min(lats), min(lons)], [max(lats), max(lons)]],
                    padding=[40, 40],
                )
            st_folium(m, height=500, use_container_width=True, key=f"map_{st.session_state.current_run_id}")

        with col2:
            st.subheader(f"Top {min(10, len(top_targets))} Targets")
            for i, t in enumerate(top_targets[:10], 1):
                with st.expander(f"{i}. {t['municipality']} {_score_dot(t['final_score'])} — `{t['final_score']:.3f}`"):
                    st.markdown(_bans([
                        ("☀ Irradiance",  f"{t.get('solar_irradiance', 0):.2f} kWh/m²/day"),
                        ("📈 Income",      f"{t.get('income_class', 'N/A')} class"),
                        ("👥 Population",  f"{t.get('population', 0):,}"),
                        ("⚡ Yield",       f"{t.get('solar_yield_kwh', 0):,.0f} kWh/kWp/yr"),
                    ]), unsafe_allow_html=True)
                    st.write(f"**Assessment:** {t.get('assessment', 'N/A')}")
                    st.write(f"**Opportunity:** {t.get('opportunity', 'N/A')}")
                    st.write(f"**Risk:** {t.get('risk', 'N/A')}")

        if result.get("errors"):
            with st.expander("⚠️ Pipeline warnings"):
                for err in result["errors"]:
                    st.warning(err)


# ── Page: Report ───────────────────────────────────────────────────────────────
elif page == "📄 Report":
    st.title("📄 Intelligence Report")

    if not st.session_state.pipeline_result:
        st.info("Run the pipeline from the sidebar to generate a report.")
    else:
        result = st.session_state.pipeline_result
        markdown = result.get("report_markdown", "")
        report_path = result.get("report_path")

        if markdown:
            st.markdown(markdown)

            if report_path:
                with open(report_path, "r") as f:
                    st.download_button(
                        "⬇️ Download Report (.md)",
                        data=f.read(),
                        file_name=f"solar_report_{result['run_id']}.md",
                        mime="text/markdown",
                    )
        else:
            st.warning("No report generated yet.")


# ── Page: Chatbot ──────────────────────────────────────────────────────────────
elif page == "💬 Chatbot":
    st.title("💬 Solar Intel Chatbot")
    st.caption("Ask questions about target areas, opportunities, and solar potential.")

    # Ensure KB is indexed
    index_documents_from_kb()

    # Display history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Input
    user_input = st.chat_input("Ask me anything about solar opportunities...")
    if user_input:
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                current_run_id = st.session_state.get("current_run_id", "")
                reply, updated_history = chat(user_input, st.session_state.chat_history, run_id=current_run_id)
            st.write(reply)
            st.session_state.chat_history = updated_history


# ── Page: Admin ────────────────────────────────────────────────────────────────
elif page == "⚙️ Admin":
    st.title("⚙️ Admin")

    # ── Geo Score Refresh ──────────────────────────────────────────────────
    st.subheader("Geo Scores")
    import sqlite3 as _sq
    try:
        conn = _sq.connect(str(config.HELIO_DB))
        last_ts = conn.execute("SELECT MAX(computed_at) FROM geo_scores").fetchone()[0]
        count   = conn.execute("SELECT COUNT(*) FROM geo_scores").fetchone()[0]
        conn.close()
        st.caption(f"{count:,} municipalities scored · last updated: {last_ts or 'never'}")
    except Exception:
        st.caption("Could not read geo_scores stats.")

    if not _precompute_state["running"]:
        if st.button("🔄 Refresh Geo Scores", type="primary"):
            from scripts.precompute_geo_scores import precompute_geo_scores

            def _run_precompute():
                _precompute_state["running"] = True
                _precompute_state["done"]    = 0
                _precompute_state["total"]   = 0

                def _cb(done: int, total: int) -> None:
                    _precompute_state["done"]  = done
                    _precompute_state["total"] = total

                try:
                    precompute_geo_scores(progress_callback=_cb)
                finally:
                    _precompute_state["running"] = False

            threading.Thread(target=_run_precompute, daemon=True).start()
            st.rerun()
    else:
        done  = _precompute_state["done"]
        total = _precompute_state["total"] or 1
        st.progress(done / total, text=f"Scoring municipalities... {done}/{total}")
        time.sleep(0.5)
        st.rerun()

    st.markdown("---")

    # ── DB Stats ───────────────────────────────────────────────────────────
    st.subheader("DB Stats")
    try:
        conn = _sq.connect(str(config.HELIO_DB))
        tables = ["municipalities", "geo_scores", "web_intel_cache",
                  "runs", "run_results", "reports", "chat_messages"]
        for tbl in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            st.metric(tbl, f"{n:,}")
        conn.close()
    except Exception as e:
        st.warning(f"Could not read DB stats: {e}")

    st.markdown("---")

    # ── Re-index KB ────────────────────────────────────────────────────────
    st.subheader("Knowledge Base")
    st.caption(
        "Re-index rebuilds the ChromaDB collection from all reports in the DB. "
        "Run this after changing the embedding model."
    )
    if st.button("🔁 Re-index KB"):
        from agents.chatbot import _chroma_client, _get_collection, index_documents_from_kb, _EMBED_MARKER
        with st.spinner("Wiping and rebuilding KB index..."):
            try:
                _chroma_client.delete_collection("solar_lead_kb")
                if _EMBED_MARKER.exists():
                    _EMBED_MARKER.unlink()
                _get_collection()
                index_documents_from_kb()
                st.success("KB re-indexed successfully.")
            except Exception as e:
                st.error(f"Re-index failed: {e}")


# ── Page: Past Runs ────────────────────────────────────────────────────────────
elif page == "📚 Past Runs":
    st.title("📚 Past Runs")

    if "runs_page" not in st.session_state:
        st.session_state.runs_page = 0

    all_runs = db_store.list_runs(limit=1000)

    if not all_runs:
        st.info("No completed runs with reports yet.")
    else:
        page_size   = 20
        total_pages = max(1, (len(all_runs) + page_size - 1) // page_size)
        current_page = min(st.session_state.runs_page, total_pages - 1)
        st.session_state.runs_page = current_page
        page_runs = all_runs[current_page * page_size : (current_page + 1) * page_size]

        for run in page_runs:
            try:
                dt = datetime.fromisoformat(run["created_at"])
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = str(run["created_at"])[:10]

            top_score = run.get("top_score")
            score_str = f"{top_score:.2f}" if top_score else "—"
            tier_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(
                run.get("top_tier", ""), "⚪"
            )
            header = (
                f"{run['location']}  ·  {date_str}  ·  "
                f"{run.get('target_count', 0)} targets  ·  top {score_str} {tier_icon}"
            )

            with st.expander(header):
                loaded = db_store.load_run(run["id"])
                if loaded:
                    md = loaded.get("report_markdown", "")
                    if md:
                        st.markdown(md)
                    report_path = loaded.get("report_path")
                    if report_path:
                        try:
                            with open(report_path, "r", encoding="utf-8") as f:
                                st.download_button(
                                    "⬇️ Download Report (.md)",
                                    data=f.read(),
                                    file_name=f"solar_report_{run['id']}.md",
                                    mime="text/markdown",
                                    key=f"dl_{run['id']}",
                                )
                        except FileNotFoundError:
                            pass

        col_prev, col_mid, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("← Previous", disabled=(current_page == 0), key="runs_prev"):
                st.session_state.runs_page -= 1
                st.rerun()
        with col_mid:
            st.markdown(
                f"<div style='text-align:center'>Page {current_page + 1} of {total_pages}</div>",
                unsafe_allow_html=True,
            )
        with col_next:
            if st.button("Next →", disabled=(current_page >= total_pages - 1), key="runs_next"):
                st.session_state.runs_page += 1
                st.rerun()
