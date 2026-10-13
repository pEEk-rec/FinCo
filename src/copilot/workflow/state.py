"""
State models and trace data structures for the LangGraph workflow.

Maintains JSON-serialisable workflow state and interoperability with Phase 0 RunState.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

from copilot.core.timeutil import now_utc
from copilot.models.domain import Id, UtcTimestamp
from copilot.models.run_state import RunState, ToolCallRecord


class TraceEntry(TypedDict, total=False):
    """Execution trace of a single workflow node."""

    node: str
    started_at: str
    ended_at: str
    duration_ms: float
    tools_called: list[str]
    counts: dict[str, int]
    status: Literal["ok", "skipped", "error"]
    error: str | None


class AgentState(TypedDict, total=False):
    """
    Graph state for the FinCo agent workflow.

    Kept serialisable so LangGraph checkpointers (e.g. MemorySaver)
    can checkpoint and restore cleanly during human-in-the-loop review.
    """

    run_id: str
    user_id: str
    consent_id: str | None
    account_id: str | None
    year: int
    month: int
    clock: str | None  # ISO 8601 UTC timestamp
    on_zero_txns: Literal["analyze", "finalize"]
    status: Literal["running", "interrupted", "completed", "failed"]

    # Structured node results
    node_results: dict[str, Any]
    pending_reviews: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    draft_advice: list[dict[str, Any]]
    review_decisions: list[dict[str, Any]] | None
    decided_advice: list[dict[str, Any]]
    financial_state: dict[str, Any] | None

    # Error payload
    error: dict[str, Any] | None

    # Cumulative node execution trace
    trace: Annotated[list[TraceEntry], operator.add]


def to_run_state(state: AgentState) -> RunState:
    """
    Project AgentState into the Phase 0 RunState model for backwards compatibility.
    """
    tool_results: list[ToolCallRecord] = []
    for entry in state.get("trace", []):
        for tool_name in entry.get("tools_called", []):
            tool_results.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    ok=(entry.get("status") == "ok"),
                    error_message=entry.get("error"),
                    data=entry.get("counts"),
                )
            )

    observations: list[str] = []
    if "ingest" in state.get("node_results", {}):
        ing = state["node_results"]["ingest"]
        observations.append(
            f"Ingested {ing.get('inserted', 0)} new transactions (fetched {ing.get('fetched', 0)})."
        )
    if "categorize" in state.get("node_results", {}):
        cat = state["node_results"]["categorize"]
        n_up = cat.get("updated", 0)
        n_q = cat.get("review_queue", 0)
        observations.append(f"Categorized {n_up} transactions ({n_q} queued for review).")
    if "advise" in state.get("node_results", {}):
        adv = state["node_results"]["advise"]
        observations.append(f"Drafted {adv.get('advice_drafted_count', 0)} advice items.")

    created_at_val: UtcTimestamp = state.get("clock") or now_utc()

    return RunState(
        run_id=Id(state.get("run_id", "run_unknown")),
        user_id=Id(state.get("user_id", "user_unknown")),
        intent="Financial ingestion, categorization, analysis and advice review",
        plan=["ingest", "categorize", "analyze", "advise", "review", "finalize"],
        observations=observations,
        tool_results=tool_results,
        pending_actions=[],
        confidence=1.0 if state.get("status") == "completed" else 0.5,
        created_at=created_at_val,
    )
