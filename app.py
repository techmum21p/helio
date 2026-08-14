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
from agents.db_store import (
    get_latest_scored_municipalities,
    get_latest_report_for_province,
    latest_assessment_time_for_province,
    get_score_breakdown,
)
from agents.refresh import maybe_refresh_assessment
from agents.report_gen import regenerate_province_report

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


TIER_COLORS = {
    "high": "#1a9850",     # green
    "medium": "#f39c12",   # orange
    "low": "#d73027",      # red
    "unscored": "#999999", # gray
}


def _score_tier(row: dict) -> str:
    if row["final_score"] is None:
        return "unscored"
    if row["final_score"] >= 0.65:
        return "high"
    if row["final_score"] >= 0.35:
        return "medium"
    return "low"


def _score_color(row: dict) -> str:
    return TIER_COLORS[_score_tier(row)]


def _render_score_breakdown(breakdown: dict) -> None:
    geo = breakdown["geo"]
    w = breakdown["weights"]
    st.markdown("**Geo Score** (solar irradiance, income, population density)")
    st.dataframe(
        [
            {"Component": "Solar Irradiance", "Raw": f"{geo['solar_irradiance']:.2f} kWh/m²/day" if geo["solar_irradiance"] is not None else "—",
             "Normalized (0-1)": f"{geo['solar_norm']:.3f}" if geo["solar_norm"] is not None else "—",
             "Weight": f"{w['solar']:.0%}"},
            {"Component": "Income Class", "Raw": geo["income_class"] or "—",
             "Normalized (0-1)": f"{geo['income_norm']:.3f}",
             "Weight": f"{w['income']:.0%}"},
            {"Component": "Population Density", "Raw": f"{geo['pop_density']:.1f} ppl/km²" if geo["pop_density"] is not None else "—",
             "Normalized (0-1)": f"{geo['pop_density_norm']:.3f}" if geo["pop_density_norm"] is not None else "—",
             "Weight": f"{w['population']:.0%}"},
        ],
        width="stretch", hide_index=True,
    )
    st.caption(
        f"Geo Score = {w['solar']:.0%}×Solar + {w['income']:.0%}×Income + {w['population']:.0%}×Pop. Density "
        f"= **{geo['geo_score']:.3f}**" if geo["geo_score"] is not None else "Geo Score not available"
    )

    web = breakdown["web"]
    if web is None:
        st.caption("No web intelligence cached yet — Web Score and Solar Opportunity Score not available.")
        return

    st.markdown("**Web Score** (commercial activity signals from Google Places)")
    ww = web["weights"]
    st.dataframe(
        [
            {"Component": "Business Density", "Raw": f"{web['business_count']} businesses (capped at 20)",
             "Normalized (0-1)": f"{web['business_density']:.3f}", "Weight": f"{ww['business_density']:.0%}"},
            {"Component": "Price Signal", "Raw": f"{web['avg_price_level']}/4 avg price level",
             "Normalized (0-1)": f"{web['price_signal']:.3f}", "Weight": f"{ww['price_signal']:.0%}"},
            {"Component": "Rating Signal", "Raw": f"{web['avg_rating']}/5 avg rating",
             "Normalized (0-1)": f"{web['rating_signal']:.3f}", "Weight": f"{ww['rating_signal']:.0%}"},
            {"Component": "Anchor Signal", "Raw": f"{web['commercial_anchors']} commercial/industrial anchors (capped at 5)",
             "Normalized (0-1)": f"{web['anchor_signal']:.3f}", "Weight": f"{ww['anchor_signal']:.0%}"},
        ],
        width="stretch", hide_index=True,
    )
    st.caption(
        f"Web Score = {ww['business_density']:.0%}×Density + {ww['price_signal']:.0%}×Price + "
        f"{ww['rating_signal']:.0%}×Rating + {ww['anchor_signal']:.0%}×Anchors "
        f"= **{web['web_score']:.3f}**" if web["web_score"] is not None else "Web Score not available"
    )

    fw = breakdown["final_weights"]
    if breakdown["final_score"] is not None:
        st.caption(
            f"Solar Opportunity Score = {fw['geo']:.0%}×Geo Score + {fw['web']:.0%}×Web Score "
            f"= **{breakdown['final_score']:.3f}**"
        )


def _legend_html() -> str:
    labels = {
        "high": "High (≥0.65)",
        "medium": "Medium (0.35–0.64)",
        "low": "Low (<0.35)",
        "unscored": "Not yet fully assessed",
    }
    swatches = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:16px;">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{TIER_COLORS[key]};margin-right:6px;"></span>'
        f'{label}</span>'
        for key, label in labels.items()
    )
    return f'<div style="margin-bottom:8px;">Solar Opportunity Score: {swatches}</div>'


col_map, col_chat = st.columns([3, 1.3])

with col_map:
    st.title("☀️ Helio Solar Opportunity Map")
    st.markdown(_legend_html(), unsafe_allow_html=True)

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
        tooltip_lines = [f"<b>{row['name']} ({row['province']})</b>"]
        tooltip_lines.append(
            f"Geo Score: {row['geo_score']:.2f}" if row["geo_score"] is not None else "Geo Score: —"
        )
        if row["final_score"] is not None:
            tooltip_lines.append(f"Web Score: {row['web_score']:.2f}" if row["web_score"] is not None else "Web Score: —")
            tooltip_lines.append(f"Solar Opportunity Score: {row['final_score']:.2f} ({row['tier']})")
        else:
            tooltip_lines.append("Not yet fully assessed")
        tooltip_html = (
            '<div style="font-size:11px; line-height:1.4;">' + "<br>".join(tooltip_lines) + "</div>"
        )

        marker = folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            weight=1,
            tooltip=folium.Tooltip(tooltip_html),
        )
        marker.options["municipality_id"] = row["municipality_id"]
        marker.add_to(m)

    selected_id = st.session_state.selected_municipality_id
    if selected_id is not None:
        selected_row = next((r for r in plottable if r["municipality_id"] == selected_id), None)
        if selected_row:
            base_score = (
                selected_row["final_score"] if selected_row["final_score"] is not None
                else selected_row["geo_score"] or 0
            )
            halo_radius = 4 + base_score * 10 + 8
            folium.CircleMarker(
                location=[selected_row["lat"], selected_row["lon"]],
                radius=halo_radius,
                color="#0000ff",
                weight=3,
                dash_array="4",
                fill=False,
                tooltip=f"Selected: {selected_row['name']} ({selected_row['province']})",
            ).add_to(m)

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
            "Solar Opportunity Score": round(m["final_score"], 3) if m["final_score"] is not None else None,
            "Tier": m["tier"] or "needs synthesis",
        }
        for m in sorted(filtered, key=lambda r: (r["final_score"] or r["geo_score"] or 0), reverse=True)
    ]
    st.dataframe(table_rows, width="stretch", height=300)

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
            c2.metric("Solar Opportunity Score", f"{detail['final_score']:.3f}" if detail["final_score"] is not None else "—")
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

            breakdown = get_score_breakdown(detail["municipality_id"])
            if breakdown:
                with st.expander("🧮 Score breakdown"):
                    _render_score_breakdown(breakdown)

            report = get_latest_report_for_province(detail["province"])
            latest_assessment = latest_assessment_time_for_province(detail["province"])
            is_stale = latest_assessment and (report is None or latest_assessment > report["created_at"])
            if is_stale:
                with st.spinner(f"Regenerating {detail['province']} report with current scores..."):
                    regenerated = regenerate_province_report(detail["province"])
                if regenerated:
                    report = regenerated
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
