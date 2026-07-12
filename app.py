"""
Helio — Dataset-First Solar Opportunity Explorer
Reads exclusively from data/helio.db. No live Google Places/Tavily calls.
The only "live" work is an on-demand MiMo LLM re-synthesis (agents/refresh.py)
for a municipality whose stored assessment predates the real-data geo_score fix.
"""
import folium
import streamlit as st
from streamlit_folium import st_folium

from agents.chatbot import chat, index_documents_from_kb
from agents.db_store import get_latest_scored_municipalities, get_latest_report_for_province
from agents.refresh import maybe_refresh_assessment

st.set_page_config(
    page_title="Helio — Solar Opportunity Explorer",
    page_icon="☀️",
    layout="wide",
)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "selected_municipality_id" not in st.session_state:
    st.session_state.selected_municipality_id = None


@st.cache_data(ttl=600)
def _cached_municipalities() -> list[dict]:
    return get_latest_scored_municipalities()


def _score_color(row: dict) -> str:
    """Green/orange/red for a current final_score; muted gray for needs-synthesis rows."""
    if row["final_score"] is None:
        return "#95a5a6"
    if row["final_score"] >= 0.65:
        return "#2ecc71"
    if row["final_score"] >= 0.35:
        return "#f39c12"
    return "#e74c3c"


col_map, col_chat = st.columns([3, 1.3])

with col_map:
    st.title("☀️ Helio Solar Opportunity Map")
    st.markdown(
        "🟢 High (≥0.65) &nbsp; 🟡 Medium (0.35–0.64) &nbsp; 🔴 Low (<0.35) &nbsp; "
        "⚪ Not yet fully assessed",
        unsafe_allow_html=True,
    )

    municipalities = _cached_municipalities()
    plottable = [m for m in municipalities if m["lat"] and m["lon"]]
    lats = [m["lat"] for m in plottable]
    lons = [m["lon"] for m in plottable]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)] if lats else [12.5, 122.5]

    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")
    for row in plottable:
        color = _score_color(row)
        score = row["final_score"] if row["final_score"] is not None else row["geo_score"] or 0
        radius = 4 + score * 10
        opacity = 0.85 if row["final_score"] is not None else 0.35
        tooltip = f"{row['name']} ({row['province']})"
        if row["final_score"] is not None:
            tooltip += f" — {row['final_score']:.2f}, {row['tier']}"
        else:
            tooltip += " — not yet fully assessed"

        marker = folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            weight=1,
            tooltip=tooltip,
        )
        marker.options["municipality_id"] = row["municipality_id"]
        marker.add_to(m)

    map_state = st_folium(m, height=560, use_container_width=True, key="national_map",
                           returned_objects=["last_object_clicked_tooltip"])

    clicked_tooltip = map_state.get("last_object_clicked_tooltip") if map_state else None
    if clicked_tooltip:
        clicked_name = clicked_tooltip.split(" (")[0]
        match = next((r for r in municipalities if r["name"] == clicked_name), None)
        if match:
            st.session_state.selected_municipality_id = match["municipality_id"]

    st.markdown("---")
    st.subheader("Province filter & search")
    provinces = sorted({m["province"] for m in municipalities})
    selected_province = st.selectbox("Province", ["— All —"] + provinces)
    filtered = municipalities if selected_province == "— All —" else [
        m for m in municipalities if m["province"] == selected_province
    ]
    table_rows = [
        {
            "Municipality": m["name"],
            "Province": m["province"],
            "Geo Score": round(m["geo_score"], 3) if m["geo_score"] is not None else None,
            "Final Score": round(m["final_score"], 3) if m["final_score"] is not None else None,
            "Tier": m["tier"] or "needs synthesis",
        }
        for m in sorted(filtered, key=lambda r: (r["final_score"] or r["geo_score"] or 0), reverse=True)
    ]
    st.dataframe(table_rows, use_container_width=True, height=300)

    st.markdown("---")
    st.subheader("Drill into a municipality")
    muni_names = sorted({m["name"] for m in filtered})
    picked_name = st.selectbox("Municipality", ["— Select —"] + muni_names)
    if picked_name != "— Select —":
        match = next(m for m in filtered if m["name"] == picked_name)
        st.session_state.selected_municipality_id = match["municipality_id"]

    selected_id = st.session_state.selected_municipality_id
    if selected_id is not None:
        with st.spinner("Checking assessment freshness..."):
            detail = maybe_refresh_assessment(selected_id)
        if detail is None:
            st.warning("Municipality not found.")
        else:
            st.markdown(f"### {detail['name']}, {detail['province']}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Geo Score", f"{detail['geo_score']:.3f}" if detail["geo_score"] is not None else "—")
            c2.metric("Final Score", f"{detail['final_score']:.3f}" if detail["final_score"] is not None else "—")
            c3.metric("Tier", detail["tier"] or "needs synthesis")
            c4.metric("Population", f"{detail['population']:,}" if detail["population"] else "—")

            if detail["assessment"]:
                st.write(f"**Assessment:** {detail['assessment']}")
                if detail["opportunities"]:
                    st.write(f"**Opportunity:** {detail['opportunities'][0]}")
                if detail["risks"]:
                    st.write(f"**Risk:** {detail['risks'][0]}")
            else:
                st.info("This municipality doesn't yet have a full AI assessment (no cached web intelligence to synthesize from without a new paid API call).")

            report = get_latest_report_for_province(detail["province"])
            if report:
                with st.expander(f"📄 {detail['province']} province report"):
                    st.markdown(report["markdown"])
                    if report.get("file_path"):
                        try:
                            with open(report["file_path"], "r", encoding="utf-8") as f:
                                st.download_button(
                                    "⬇️ Download report (.md)",
                                    data=f.read(),
                                    file_name=f"{detail['province']}_report.md",
                                    mime="text/markdown",
                                )
                        except FileNotFoundError:
                            pass

with col_chat:
    st.subheader("💬 Ask Helio")
    index_documents_from_kb()

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("Ask about any municipality...")
    if user_input:
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply, updated_history = chat(user_input, st.session_state.chat_history, run_id="")
            st.write(reply)
            st.session_state.chat_history = updated_history
