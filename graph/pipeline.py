import uuid
from langgraph.graph import StateGraph, START, END

from graph.state import SolarLeadState
from agents.geo_scoring import geo_scoring_agent
from agents.web_intel import web_intel_agent
from agents.synthesis import synthesis_agent
from agents.report_gen import report_gen_agent
from agents.chatbot import update_kb_node


def build_pipeline() -> StateGraph:
    graph = StateGraph(SolarLeadState)

    graph.add_node("geo_scoring", geo_scoring_agent)
    graph.add_node("web_intel", web_intel_agent)
    graph.add_node("synthesis", synthesis_agent)
    graph.add_node("report_gen", report_gen_agent)
    graph.add_node("update_kb", update_kb_node)

    # Sequential: geo first so web_intel knows which municipalities to search
    graph.add_edge(START, "geo_scoring")
    graph.add_edge("geo_scoring", "web_intel")
    graph.add_edge("web_intel", "synthesis")
    graph.add_edge("synthesis", "report_gen")
    graph.add_edge("report_gen", "update_kb")
    graph.add_edge("update_kb", END)

    return graph.compile()


def run_pipeline(location: str, run_id: str | None = None) -> SolarLeadState:
    pipeline = build_pipeline()

    initial_state: SolarLeadState = {
        "location": location,
        "run_id": run_id or str(uuid.uuid4())[:8],
        "geo_scores": None,
        "geo_geojson": None,
        "web_intel": None,
        "final_scores": None,
        "top_targets": None,
        "report_markdown": None,
        "report_path": None,
        "chat_history": [],
        "kb_updated": False,
        "errors": [],
        "status": "running",
    }

    result = pipeline.invoke(initial_state)
    return result


if __name__ == "__main__":
    result = run_pipeline("Laguna")
    print("Status:", result["status"])
    print("Top targets:", result.get("top_targets", [])[:3])
