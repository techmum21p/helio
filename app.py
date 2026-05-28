"""
Solar Lead Intelligence Platform
Streamlit frontend — three pages:
  1. Map & Scores  — run pipeline, view opportunity map
  2. Report        — view and download generated report
  3. Chatbot       — RAG chatbot over generated KB
"""

import json
import streamlit as st
import folium
from streamlit_folium import st_folium

from graph.pipeline import run_pipeline
from agents.chatbot import chat, index_documents_from_kb
from agents.session_store import save_session, load_session, list_sessions

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


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("☀️ Solar Lead Intel")
    st.markdown("---")
    page = st.radio("Navigate", ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot"])

    st.markdown("---")
    st.subheader("Run Pipeline")
    location_input = st.text_input("Province / Region", placeholder="e.g. Laguna")

    if st.button("▶ Analyze", type="primary", use_container_width=True):
        if not location_input.strip():
            st.error("Enter a location first.")
        else:
            with st.spinner(f"Analyzing {location_input}... (this takes ~1-2 mins)"):
                result = run_pipeline(location_input.strip())
                st.session_state.pipeline_result = result
                st.session_state.chat_history = []
                save_session(result, [])
            if result.get("errors"):
                st.warning(f"Completed with {len(result['errors'])} warning(s).")
            else:
                st.success("Done!")

    if st.session_state.pipeline_result:
        result = st.session_state.pipeline_result
        top = result.get("top_targets", [])
        st.markdown(f"**{len(top)} municipalities scored**")
        if top:
            st.markdown(f"🥇 Top target: **{top[0]['municipality']}**")
            st.markdown(f"Score: `{top[0]['final_score']:.3f}` | Tier: `{top[0]['tier']}`")

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


# ── Page: Map & Scores ─────────────────────────────────────────────────────────
if page == "🗺️ Map & Scores":
    st.title("🗺️ Solar Opportunity Map")

    if not st.session_state.pipeline_result:
        st.info("Run the pipeline from the sidebar to see results.")
    else:
        result = st.session_state.pipeline_result
        top_targets = result.get("top_targets", [])
        geo_geojson = result.get("geo_geojson")

        col1, col2 = st.columns([3, 2])

        with col1:
            # Build score lookup for coloring
            score_map = {t["municipality"]: t["final_score"] for t in top_targets}

            # Center map on Philippines
            m = folium.Map(location=[12.5, 122.5], zoom_start=7, tiles="CartoDB positron")

            if geo_geojson:
                geo_data = json.loads(geo_geojson)
                for feature in geo_data.get("features", []):
                    props = feature.get("properties", {})
                    name = props.get("name", "")
                    geom = feature.get("geometry", {})

                    if geom.get("type") != "Point":
                        continue

                    lon, lat = geom["coordinates"]
                    score = score_map.get(name, props.get("geo_score", 0))

                    # Color by score tier
                    if score >= 0.65:
                        color = "#2ecc71"   # green — high opportunity
                    elif score >= 0.35:
                        color = "#f39c12"   # orange — medium
                    else:
                        color = "#e74c3c"   # red — low

                    radius = 6 + score * 14  # bigger circle = higher score

                    folium.CircleMarker(
                        location=[lat, lon],
                        radius=radius,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.75,
                        weight=1.5,
                        popup=folium.Popup(
                            f"<b>{name}</b><br>Score: {score:.3f}",
                            max_width=200,
                        ),
                        tooltip=f"{name}: {score:.3f}",
                    ).add_to(m)

            st_folium(m, width=700, height=500)

        with col2:
            st.subheader(f"Top {min(10, len(top_targets))} Targets")
            for i, t in enumerate(top_targets[:10], 1):
                tier_color = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(t["tier"], "⚪")
                with st.expander(f"{i}. {t['municipality']} {tier_color} — `{t['final_score']:.3f}`"):
                    st.write(f"**Assessment:** {t.get('assessment', 'N/A')}")
                    st.write(f"**Opportunity:** {t.get('opportunity', 'N/A')}")
                    st.write(f"**Risk:** {t.get('risk', 'N/A')}")
                    est_kwh = t.get("solar_kwh_estimate", 0)
                    st.metric("Est. Annual Solar Yield", f"{est_kwh:,.0f} kWh/kWp")

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
                reply, updated_history = chat(user_input, st.session_state.chat_history)
            st.write(reply)
            st.session_state.chat_history = updated_history
            if st.session_state.pipeline_result:
                save_session(st.session_state.pipeline_result, updated_history)
