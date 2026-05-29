import time
import uuid
from langgraph.graph import StateGraph, START, END

from graph.state import SolarLeadState
from agents.geo_scoring import geo_scoring_agent
from agents.web_intel import web_intel_agent
from agents.synthesis import synthesis_agent
from agents.report_gen import report_gen_agent
from agents.chatbot import update_kb_node

_STEPS = ["geo_scoring", "web_intel", "synthesis", "report_gen", "update_kb"]


def build_pipeline() -> StateGraph:
    graph = StateGraph(SolarLeadState)
    graph.add_node("geo_scoring", geo_scoring_agent)
    graph.add_node("web_intel", web_intel_agent)
    graph.add_node("synthesis", synthesis_agent)
    graph.add_node("report_gen", report_gen_agent)
    graph.add_node("update_kb", update_kb_node)
    graph.add_edge(START, "geo_scoring")
    graph.add_edge("geo_scoring", "web_intel")
    graph.add_edge("web_intel", "synthesis")
    graph.add_edge("synthesis", "report_gen")
    graph.add_edge("report_gen", "update_kb")
    graph.add_edge("update_kb", END)
    return graph.compile()


def run_pipeline(location: str, run_id: str | None = None) -> SolarLeadState:
    from api.events import push_event  # imported lazily to avoid circular import

    pipeline = build_pipeline()
    pipeline_run_id = run_id or str(uuid.uuid4())[:8]

    initial_state: SolarLeadState = {
        "location": location,
        "run_id": pipeline_run_id,
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

    t0 = time.monotonic()
    if run_id:
        push_event(run_id, _STEPS[0], "running", 0)

    state = initial_state
    for step_output in pipeline.stream(initial_state, stream_mode="updates"):
        node_name = next(iter(step_output))
        state = {**state, **step_output[node_name]}
        elapsed = int((time.monotonic() - t0) * 1000)

        if run_id:
            push_event(run_id, node_name, "done", elapsed)
            idx = _STEPS.index(node_name) if node_name in _STEPS else -1
            if idx >= 0 and idx + 1 < len(_STEPS):
                push_event(run_id, _STEPS[idx + 1], "running", elapsed)

    return state


if __name__ == "__main__":
    result = run_pipeline("Laguna")
    print("Status:", result["status"])
    print("Top targets:", result.get("top_targets", [])[:3])
