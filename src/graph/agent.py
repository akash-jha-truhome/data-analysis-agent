"""Graph assembly for the code-execution loop (see spec/agent.md > Graph Assembly)."""
from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    prepare,
    profile_quality,
    write_code,
    execute,
    answer,
    build_chart,
    finalize,
    handle_error,
)
from graph.edges import route_after_execute


def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("prepare", prepare)
    graph.add_node("profile_quality", profile_quality)
    graph.add_node("write_code", write_code)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)
    graph.add_node("build_chart", build_chart)
    graph.add_node("finalize", finalize)
    graph.add_node("handle_error", handle_error)

    graph.set_entry_point("prepare")

    # prepare -> profile_quality -> write_code (on prepare error, short-circuit).
    graph.add_conditional_edges(
        "prepare",
        lambda s: "handle_error" if s.get("error") else "profile_quality",
        {"handle_error": "handle_error", "profile_quality": "profile_quality"},
    )
    # profile_quality NEVER errors the run — it always continues to write_code.
    graph.add_edge("profile_quality", "write_code")
    graph.add_conditional_edges(
        "write_code",
        lambda s: "handle_error" if s.get("error") else "execute",
        {"handle_error": "handle_error", "execute": "execute"},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {"answer": "answer", "write_code": "write_code", "handle_error": "handle_error"},
    )
    graph.add_conditional_edges(
        "answer",
        lambda s: "handle_error" if s.get("error") else "build_chart",
        {"handle_error": "handle_error", "build_chart": "build_chart"},
    )
    graph.add_edge("build_chart", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("handle_error", END)

    return graph.compile()


compiled_graph = _build_graph()

# Backwards-compatible alias (skeleton referenced `agentic_ai`).
agentic_ai = compiled_graph
