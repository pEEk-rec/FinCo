"""
State models and trace data structures for the Phase 2 Agentic Graph (PLAN_PHASE2 Section 5.10).
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

from copilot.workflow.state import TraceEntry


class AgenticState(TypedDict, total=False):
    """
    State model for the Phase 2 autonomous agent graph.
    All keys are serializable to support LangGraph checkpointing and interrupts.
    """

    # Identifiers & Environment
    task_id: str
    run_id: str
    user_id: str
    clock: str | None  # UTC ISO timestamp
    raw_text: str

    # Input Gate & Intent Understanding
    intent: dict[str, Any] | None
    refusal_reason: str | None
    needs_clarification: bool
    clarification_question: str | None
    clarification_options: list[str] | None
    clarification_response: str | None
    clarified: bool

    # Planner & Validator
    planner_mode: Literal["deterministic", "llm"]
    plan: dict[str, Any] | None
    current_step_idx: int
    step_budget: int
    llm_budget: int
    llm_calls_made: int
    steps_executed: int

    # Execution & Memory
    memo_cache: dict[str, Any]
    call_history: list[dict[str, Any]]
    observations: Annotated[list[dict[str, Any]], operator.add]

    # Reflection (bounded re-planning)
    rounds: int
    max_rounds: int
    replan_triggered: bool

    # Synthesis & Recommendations
    findings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    pending_recommendations: list[dict[str, Any]]
    review_decisions: list[dict[str, Any]] | None

    # Lifecycle & Trace
    status: Literal["running", "interrupted", "completed", "failed", "stopped"]
    stop_reason: (
        Literal[
            "completed",
            "step_budget",
            "llm_budget",
            "loop_detected",
            "tool_failure",
            "inconclusive",
        ]
        | None
    )
    error: dict[str, Any] | None
    trace: Annotated[list[TraceEntry], operator.add]
