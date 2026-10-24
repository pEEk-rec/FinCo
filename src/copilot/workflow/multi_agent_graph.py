"""
Multi-Agent LangGraph Subgraph (PLAN_PHASE3 Section 5.13).

Topology:
supervisor/decompose -> fan-out (parallel) -> specialists -> merge
-> reviewer -> (revise <= 1) -> synthesize
"""

import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from copilot.core.timeutil import to_utc_iso
from copilot.db.repo import get_agent_task, update_agent_task_status
from copilot.llm.client import LLMClient
from copilot.models.phase3 import SpecialistReport, SubQuestion
from copilot.tools.executor import ExecutionContext
from copilot.workflow.decomposition import decompose_intent
from copilot.workflow.multi_agent import merge_specialist_reports, run_specialists_fanout
from copilot.workflow.reviewer import run_review_and_revision

logger = logging.getLogger(__name__)


class MultiAgentState(TypedDict, total=False):
    """State slice for the multi-agent planning subgraph."""

    user_id: str
    task_id: str
    intent: dict[str, Any]
    user_data: dict[str, Any]
    clock: str | None
    subquestions: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    gaps: list[str]
    contradictions: list[dict[str, Any]]
    reflections: list[dict[str, Any]]
    final_narration: str | None
    status: str
    stop_reason: str


def decompose_node(state: MultiAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Decompose intent into typed SubQuestions."""
    configurable = config.get("configurable", {}) if config else {}
    conn = configurable.get("conn")
    llm_client: LLMClient | None = configurable.get("llm_client")

    intent = state.get("intent", {})
    user_data = state.get("user_data", {})
    user_id = state["user_id"]
    task_id = state["task_id"]

    subqs = decompose_intent(
        intent=intent,
        user_data=user_data,
        llm_client=llm_client,
        conn=conn,
        user_id=user_id,
        task_id=task_id,
    )
    return {
        "subquestions": [sq.model_dump() for sq in subqs],
        "status": "running",
    }


def fanout_node(state: MultiAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Execute specialists in parallel."""
    configurable = config.get("configurable", {}) if config else {}
    ctx: ExecutionContext = configurable["ctx"]
    delays = configurable.get("delays")

    raw_subqs = state.get("subquestions", [])
    subquestions = [SubQuestion.model_validate(sq) for sq in raw_subqs]

    reports = run_specialists_fanout(
        subquestions=subquestions,
        ctx=ctx,
        task_id=state["task_id"],
        delays=delays,
    )
    return {
        "reports": [r.model_dump() for r in reports],
        "status": "running",
    }


def merge_node(state: MultiAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Deterministically merge reports and detect contradictions."""
    configurable = config.get("configurable", {}) if config else {}
    conn = configurable.get("conn")

    raw_reports = state.get("reports", [])
    reports = [SpecialistReport.model_validate(r) for r in raw_reports]

    merge_res = merge_specialist_reports(
        reports=reports,
        user_id=state["user_id"],
        task_id=state["task_id"],
        conn=conn,
    )
    return {
        "findings": merge_res["findings"],
        "gaps": merge_res["gaps"],
        "contradictions": merge_res["contradictions"],
        "status": merge_res["status"],
    }


def reviewer_node(state: MultiAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Review findings and perform bounded revision."""
    configurable = config.get("configurable", {}) if config else {}
    ctx: ExecutionContext = configurable["ctx"]
    llm_client: LLMClient | None = configurable.get("llm_client")
    max_rounds = configurable.get("max_revision_rounds", 1)

    raw_subqs = state.get("subquestions", [])
    subquestions = [SubQuestion.model_validate(sq) for sq in raw_subqs]

    raw_reports = state.get("reports", [])
    reports = [SpecialistReport.model_validate(r) for r in raw_reports]

    merge_res = {
        "findings": state.get("findings", []),
        "gaps": state.get("gaps", []),
        "contradictions": state.get("contradictions", []),
        "status": state.get("status", "ok"),
    }

    rev_merge, rev_reports, reflections = run_review_and_revision(
        subquestions=subquestions,
        reports=reports,
        merge_result=merge_res,
        ctx=ctx,
        task_id=state["task_id"],
        llm_client=llm_client,
        max_revision_rounds=max_rounds,
    )

    return {
        "findings": rev_merge["findings"],
        "gaps": rev_merge["gaps"],
        "contradictions": rev_merge["contradictions"],
        "reports": [r.model_dump() for r in rev_reports],
        "reflections": [refl.model_dump() for refl in reflections],
        "status": rev_merge["status"],
    }


def synthesize_node(state: MultiAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Synthesize final findings and state summary."""
    findings = state.get("findings", [])
    gaps = state.get("gaps", [])
    status = state.get("status", "ok")

    summary_lines = [f"Status: {status}"]
    if findings:
        summary_lines.append(f"Evaluated {len(findings)} finding(s).")
    if gaps:
        summary_lines.append(f"Missing/unaddressed gaps: {'; '.join(gaps)}")

    narration = "\n".join(summary_lines)
    return {
        "final_narration": narration,
        "status": "completed",
        "stop_reason": "completed" if status != "failed" else "failed",
    }


def build_multi_agent_subgraph() -> CompiledStateGraph:
    """Build and compile the multi-agent StateGraph."""
    builder = StateGraph(MultiAgentState)

    builder.add_node("decompose", decompose_node)
    builder.add_node("fanout", fanout_node)
    builder.add_node("merge", merge_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("synthesize", synthesize_node)

    builder.add_edge(START, "decompose")
    builder.add_edge("decompose", "fanout")
    builder.add_edge("fanout", "merge")
    builder.add_edge("merge", "reviewer")
    builder.add_edge("reviewer", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile()


def run_multi_agent_workflow(
    intent: dict[str, Any] | str,
    user_id: str,
    task_id: str,
    ctx: ExecutionContext,
    llm_client: LLMClient | None = None,
    user_data: dict[str, Any] | None = None,
    delays: dict[str, float] | None = None,
    max_revision_rounds: int = 1,
) -> MultiAgentState:
    """Convenience runner for executing the multi-agent workflow."""
    graph = build_multi_agent_subgraph()
    initial_state: MultiAgentState = {
        "user_id": user_id,
        "task_id": task_id,
        "intent": intent if isinstance(intent, dict) else {"type": str(intent)},
        "user_data": user_data or {},
        "clock": to_utc_iso(ctx.clock) if ctx.clock else None,
        "status": "running",
    }
    config = {
        "configurable": {
            "ctx": ctx,
            "conn": ctx.conn,
            "llm_client": llm_client,
            "delays": delays,
            "max_revision_rounds": max_revision_rounds,
        }
    }
    result = graph.invoke(initial_state, config=config)

    # Update agent task in DB if exists
    if ctx.conn:
        try:
            t = get_agent_task(ctx.conn, user_id, task_id)
            if t:
                update_agent_task_status(
                    ctx.conn,
                    user_id=user_id,
                    task_id=task_id,
                    status="done" if result.get("status") == "completed" else "failed",
                    stop_reason=result.get("stop_reason", "completed"),
                )
        except Exception as exc:
            logger.warning("Could not update agent task: %s", exc)

    return result
