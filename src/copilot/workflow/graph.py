"""
LangGraph workflow compilation and conditional edge routing.

Builds:
1. `build_agent_graph`: Full end-to-end ingestion, categorization, analysis, advice & review.
2. `build_monthly_review_graph`: Targeted monthly review workflow mode.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from copilot.workflow.nodes import (
    advise_node,
    analyze_node,
    categorize_node,
    error_node,
    finalize_node,
    ingest_node,
    review_node,
)
from copilot.workflow.state import AgentState

# -------------------------------------------------------------------------------------------------
# Conditional Routing
# -------------------------------------------------------------------------------------------------


def route_after_ingest(state: AgentState) -> str:
    """Route after ingest: failure to error, inserted > 0 to categorize, else analyze/finalize."""
    if state.get("status") == "failed":
        return "error"
    ing = state.get("node_results", {}).get("ingest", {})
    if ing.get("inserted", 0) > 0:
        return "categorize"
    # No new transactions: skip to analyze (default) or finalize per configuration
    return state.get("on_zero_txns", "analyze")


def route_after_categorize(state: AgentState) -> str:
    """Route after categorize: error if failed, else analyze."""
    if state.get("status") == "failed":
        return "error"
    return "analyze"


def route_after_analyze(state: AgentState) -> str:
    """Route after analyze: error if failed, else advise."""
    if state.get("status") == "failed":
        return "error"
    return "advise"


def route_after_advise(state: AgentState) -> str:
    """Route after advise: error if failed, else review."""
    if state.get("status") == "failed":
        return "error"
    return "review"


def route_after_review(state: AgentState) -> str:
    """Route after review: error if failed, else finalize."""
    if state.get("status") == "failed":
        return "error"
    return "finalize"


# -------------------------------------------------------------------------------------------------
# Graph Builders
# -------------------------------------------------------------------------------------------------


def build_agent_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """
    Construct and compile the primary end-to-end FinCo agent workflow.

    Flow:
        START -> ingest -> [conditional] -> categorize -> analyze -> advise -> review -> finalize
                                   |                                              ^
                                   +----------> analyze --------------------------+
                                   |
                                   +----------> finalize -> END

        (Any node failure routes to error -> END)
    """
    builder = StateGraph(AgentState)

    # Register thin nodes
    builder.add_node("ingest", ingest_node)
    builder.add_node("categorize", categorize_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("advise", advise_node)
    builder.add_node("review", review_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("error", error_node)

    # Edges
    builder.add_edge(START, "ingest")

    builder.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {
            "categorize": "categorize",
            "analyze": "analyze",
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "categorize",
        route_after_categorize,
        {
            "analyze": "analyze",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "advise": "advise",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "advise",
        route_after_advise,
        {
            "review": "review",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "review",
        route_after_review,
        {
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_edge("finalize", END)
    builder.add_edge("error", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver)


def build_monthly_review_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Construct and compile the monthly review workflow mode.

    Flow:
        START -> analyze -> advise -> review -> finalize -> END
    """
    builder = StateGraph(AgentState)

    builder.add_node("analyze", analyze_node)
    builder.add_node("advise", advise_node)
    builder.add_node("review", review_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("error", error_node)

    builder.add_edge(START, "analyze")

    builder.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "advise": "advise",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "advise",
        route_after_advise,
        {
            "review": "review",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "review",
        route_after_review,
        {
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_edge("finalize", END)
    builder.add_edge("error", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver)
