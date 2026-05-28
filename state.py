from typing import TypedDict, Optional, List, Dict, Any
import geopandas as gpd


class SolarLeadState(TypedDict):
    # --- Input ---
    location: str                           # e.g. "Laguna" or "Biñan, Laguna"
    run_id: str                             # unique ID for this pipeline run

    # --- Agent 1: Geo + ML ---
    geo_scores: Optional[Dict[str, Any]]    # {municipality: {solar, pop, income, geo_score}}
    geo_geojson: Optional[str]             # GeoJSON string for map rendering

    # --- Agent 2: Web Intel ---
    web_intel: Optional[Dict[str, Any]]    # {municipality: {businesses, news, property, summary}}

    # --- Agent 3: Synthesis ---
    final_scores: Optional[Dict[str, Any]] # {municipality: {final_score, tier, reasoning}}
    top_targets: Optional[List[Dict]]      # ranked list of top N targets

    # --- Agent 4: Report ---
    report_markdown: Optional[str]         # full report as markdown
    report_path: Optional[str]            # path to saved PDF report

    # --- Agent 5: Chatbot ---
    chat_history: List[Dict[str, str]]     # [{"role": "user"|"assistant", "content": "..."}]
    kb_updated: bool                       # whether KB was updated after this run

    # --- Meta ---
    errors: List[str]                      # non-fatal errors collected during run
    status: str                            # "running" | "complete" | "error"
