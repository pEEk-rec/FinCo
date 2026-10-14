"""Run one `ask` through the planner agent graph and return a JSON-ready result."""

import logging
import sqlite3
import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from copilot.api.state import ApiState
from copilot.core.answers import compose_answer, narrate
from copilot.db.repo import list_categories
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.workflow.agent_graph import build_planner_agent_graph

log = logging.getLogger("copilot.api.agent")


def run_ask(
    state: ApiState, conn: sqlite3.Connection, text: str, use_llm: bool = True
) -> dict[str, Any]:
    """
    Run the planner graph and write the answer. Approvals are left pending, never auto-given.

    With a model configured (and `use_llm`), the model proposes the plan (validated, with the
    deterministic plan as fallback), may help read the question, and rewords the answer. Without
    one, everything is rule-based. The numbers are the same either way.
    """
    llm = state.get_llm() if use_llm else None
    if llm is not None and hasattr(llm, "begin_request"):
        llm.begin_request()
    run_id = f"ask_{uuid.uuid4().hex[:10]}"
    graph = build_planner_agent_graph(checkpointer=MemorySaver())
    config = {
        "configurable": {
            "thread_id": run_id,
            "conn": conn,
            "actor": "agent",
            "llm_client": llm,
        }
    }
    initial = {
        "user_id": state.user_id,
        "run_id": run_id,
        "raw_text": text,
        "clock": to_utc_iso(now_utc(state.clock)),
        "planner_mode": "llm" if llm is not None else "deterministic",
        "step_budget": 10,
    }
    question: str | None = None
    result: dict[str, Any] = {}
    try:
        result = graph.invoke(initial, config=config)
        snap = graph.get_state(config)
        if snap.tasks and snap.tasks[0].interrupts:
            value = snap.tasks[0].interrupts[0].value or {}
            question = value.get("question")
            if "pending_recommendations" in value:
                # Leave for the user: resume with no decisions so the run finishes cleanly.
                result = graph.invoke(Command(resume={}), config=config)
                result["pending_recommendations"] = value["pending_recommendations"]
    except GraphInterrupt as gi:
        value = gi.args[0] if gi.args else {}
        question = value.get("question") if isinstance(value, dict) else None
    conn.commit()
    observations = result.get("observations", [])
    answer = None
    if not result.get("refusal_reason") and not question:
        try:
            names = {c.id: c.name for c in list_categories(conn, state.user_id)}
            answer = compose_answer(
                conn, state.user_id, result.get("intent"), observations, names, state.clock
            )
            if answer is not None and llm is not None and getattr(llm, "available", lambda: True)():
                answer = narrate(llm, text, answer) or answer
        except Exception:  # noqa: BLE001 - the tool results below are still valid and shown
            log.exception("Could not write the answer; showing the tool results only")
            answer = None
    return {
        "answer": answer.model_dump() if answer else None,
        "llm": {
            "available": llm is not None,
            "model": getattr(llm, "model", None) if llm is not None else None,
            "calls": getattr(llm, "calls", 0) if llm is not None else 0,
            "failures": getattr(llm, "failures", 0) if llm is not None else 0,
            "planner": "llm" if llm is not None else "rules",
        },
        "task_id": result.get("task_id"),
        "status": "needs_clarification" if question else str(result.get("status", "completed")),
        "stop_reason": result.get("stop_reason"),
        "question": question,
        "refusal_reason": result.get("refusal_reason"),
        "intent": result.get("intent"),
        "recommendations": result.get("recommendations", []),
        "pending_recommendations": result.get("pending_recommendations", []),
        "observations": result.get("observations", []),
        "investigations": [],
        "plan": [
            {
                "seq": step.get("seq", 0),
                "tool_name": step.get("tool_name", ""),
                "rationale": step.get("rationale", ""),
                "proposed_by": step.get("proposed_by", "deterministic"),
                "status": step.get("status", "proposed"),
            }
            for step in (result.get("plan") or {}).get("steps", [])
        ],
        "trace": [
            {
                "node": t.get("node", ""),
                "status": t.get("status", ""),
                "duration_ms": round(float(t.get("duration_ms", 0.0)), 1),
                "counts": {k: int(v) for k, v in (t.get("counts") or {}).items()},
            }
            for t in result.get("trace", [])
        ],
        "rounds": int(result.get("rounds") or 0),
        "planner_mode": str(result.get("planner_mode") or "deterministic"),
    }
