"""
Planner-driven Agent Graph compilation with conditional edge routing (PLAN_PHASE2 Section 5.10).

Builds:
`build_planner_agent_graph`:
START -> understand -> (clarify?) -> plan -> act (loop) -> reflect -> synthesize
      -> review (interrupt?) -> finalize
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from copilot.workflow.agentic_nodes import (
    act_node,
    clarify_node,
    error_node,
    finalize_node,
    plan_node,
    reflect_node,
    review_node,
    synthesize_node,
    understand_node,
)
from copilot.workflow.agentic_state import AgenticState

# -------------------------------------------------------------------------------------------------
# Conditional Routing Functions
# -------------------------------------------------------------------------------------------------


def route_after_understand(state: AgenticState) -> str:
    """Route after understand: refused/stopped to finalize, clarification to clarify, else plan."""
    if state.get("status") == "failed":
        return "error"
    if state.get("refusal_reason") or state.get("status") == "stopped":
        return "finalize"
    if state.get("needs_clarification"):
        return "clarify"
    return "plan"


def route_after_clarify(state: AgenticState) -> str:
    """Route after clarify: stopped (inconclusive) to finalize, error to error, else plan."""
    if state.get("status") == "failed":
        return "error"
    if state.get("status") == "stopped":
        return "finalize"
    return "plan"


def route_after_plan(state: AgenticState) -> str:
    """Route after plan: error to error, else act."""
    if state.get("status") == "failed":
        return "error"
    return "act"


def route_after_act(state: AgenticState) -> str:
    """Route after act: stopped to finalize, more steps loop act, else reflect."""
    if state.get("status") == "failed":
        return "error"
    if state.get("status") == "stopped":
        return "finalize"

    plan_dict = state.get("plan") or {}
    steps = plan_dict.get("steps", [])
    current_idx = state.get("current_step_idx", 0)

    if current_idx < len(steps):
        return "act"
    return "reflect"


def route_after_reflect(state: AgenticState) -> str:
    """Route after reflect: if re-planning triggered loop act, else synthesize."""
    if state.get("status") == "failed":
        return "error"
    if state.get("replan_triggered"):
        return "act"
    return "synthesize"


def route_after_synthesize(state: AgenticState) -> str:
    """Route after synthesize: pending recommendations to review interrupt, else finalize."""
    if state.get("status") == "failed":
        return "error"
    if state.get("pending_recommendations"):
        return "review"
    return "finalize"


def route_after_review(state: AgenticState) -> str:
    """Route after review: error to error, else finalize."""
    if state.get("status") == "failed":
        return "error"
    return "finalize"


# -------------------------------------------------------------------------------------------------
# Graph Builder
# -------------------------------------------------------------------------------------------------


def build_planner_agent_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Construct and compile the Phase 2 planner-driven agent graph.

    Topology:
        START -> understand -> [conditional: refused -> finalize]
                               [conditional: clarify -> clarify -> plan]
                               [conditional: understood -> plan]
        plan -> act (loop over plan steps)
        act -> [conditional: budget/loop -> finalize]
               [conditional: all steps done -> reflect]
        reflect -> [conditional: replanned -> act]
                   [conditional: done -> synthesize]
        synthesize -> [conditional: pending recs -> review]
                      [conditional: none -> finalize]
        review -> finalize -> END
        (any node failure routes to error -> END)
    """
    builder = StateGraph(AgenticState)

    # Register thin nodes
    builder.add_node("understand", understand_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("plan", plan_node)
    builder.add_node("act", act_node)
    builder.add_node("reflect", reflect_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("review", review_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("error", error_node)

    # Edges
    builder.add_edge(START, "understand")

    builder.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            "clarify": "clarify",
            "plan": "plan",
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "clarify",
        route_after_clarify,
        {
            "plan": "plan",
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            "act": "act",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "act",
        route_after_act,
        {
            "act": "act",
            "reflect": "reflect",
            "finalize": "finalize",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "act": "act",
            "synthesize": "synthesize",
            "error": "error",
        },
    )

    builder.add_conditional_edges(
        "synthesize",
        route_after_synthesize,
        {
            "review": "review",
            "finalize": "finalize",
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

    return builder.compile(checkpointer=checkpointer)
