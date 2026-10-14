"""Run one `ask` through the planner agent graph and return a JSON-ready result."""

import sqlite3
import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from copilot.api.state import ApiState
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.workflow.agent_graph import build_planner_agent_graph


def run_ask(state: ApiState, conn: sqlite3.Connection, text: str) -> dict[str, Any]:
    """Execute the deterministic planner graph. Approvals are left pending, never auto-given."""
    run_id = f"ask_{uuid.uuid4().hex[:10]}"
    graph = build_planner_agent_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": run_id, "conn": conn, "actor": "agent"}}
    initial = {
        "user_id": state.user_id,
        "run_id": run_id,
        "raw_text": text,
        "clock": to_utc_iso(now_utc(state.clock)),
        "planner_mode": "deterministic",
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
    return {
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
    }
