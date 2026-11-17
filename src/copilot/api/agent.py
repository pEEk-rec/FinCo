"""
Run one `ask` through the planner agent graph.

`ask_events` is the real thing: a generator that reports each step the agent takes, as it takes it
(what it understood, the plan, every tool result, the reviewer's check, the answer being written),
and finishes with the complete result. The live Ask screen reads that stream. `run_ask` consumes
the same generator and returns only the final result, so every other caller is unchanged.

An event is `(kind, data)`: `("step", {...})` for progress, then one `("result", {...})`.
"""

import logging
import sqlite3
import time
import uuid
from collections.abc import Iterator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from copilot.api.state import ApiState
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.conversation.answers import compose_answer, narrate
from copilot.db.repo import list_categories
from copilot.workflow.agent_graph import build_planner_agent_graph

log = logging.getLogger("copilot.api.agent")

Event = tuple[str, dict[str, Any]]


def _words(name: str) -> str:
    return name.replace("_", " ")


def _step_for(node: str, delta: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one graph node's update into a step the person can read. None = nothing to show."""
    if node == "understand":
        if delta.get("refusal_reason"):
            return {
                "stage": "understand",
                "title": "Checked the request against its rules",
                "detail": "FinCo never does this, so no plan was made and no tool ran.",
                "tone": "stop",
            }
        intent = delta.get("intent") or {}
        bits = [
            f"period {intent['period']}" if intent.get("period") else None,
            f"category {intent['category_id']}" if intent.get("category_id") else None,
            f"{intent.get('confidence_label', 'low')} confidence",
            f"read by {intent.get('source', 'rules')}",
        ]
        return {
            "stage": "understand",
            "title": _words(str(intent.get("type", "question"))).capitalize(),
            "detail": " · ".join(b for b in bits if b),
        }
    if node == "clarify":
        return {
            "stage": "clarify",
            "title": "Needs one detail before it can answer",
            "detail": "It asks instead of guessing.",
        }
    if node == "plan":
        steps = (delta.get("plan") or {}).get("steps", [])
        tools = [str(s.get("tool_name", "")) for s in steps]
        mode = str(delta.get("planner_mode") or "")
        return {
            "stage": "plan",
            "title": f"Planned {len(steps)} step{'' if len(steps) == 1 else 's'}",
            "detail": ", ".join(_words(t) for t in tools)
            + (f" · proposed by the {mode} planner" if mode else ""),
            "steps": [
                {
                    "seq": s.get("seq", i),
                    "tool_name": s.get("tool_name", ""),
                    "rationale": s.get("rationale", ""),
                    "proposed_by": s.get("proposed_by", "deterministic"),
                }
                for i, s in enumerate(steps)
            ],
        }
    if node == "act":
        observations = delta.get("observations") or []
        if not observations:
            return None
        obs = observations[-1]
        return {
            "stage": "act",
            "title": f"Ran {_words(str(obs.get('tool_name', 'a tool')))}",
            "detail": "Policy-checked and audited." if obs.get("ok") else "This tool failed.",
            "tool": obs.get("tool_name"),
            "ok": bool(obs.get("ok")),
            "step_seq": obs.get("step_seq"),
            "data": obs.get("data_summary"),
        }
    if node == "reflect":
        again = bool(delta.get("replan_triggered"))
        return {
            "stage": "reflect",
            "title": "Took a second look" if again else "Checked it was good enough",
            "detail": "The first result was not conclusive, so it added one more round."
            if again
            else "Nothing more was needed.",
        }
    if node == "multi_agent":
        return {
            "stage": "multi_agent",
            "title": "Split the question between specialists",
            "detail": "Each one used only its own tools; a reviewer checked the merge.",
        }
    if node == "synthesize":
        waiting = delta.get("pending_recommendations") or []
        return {
            "stage": "synthesize",
            "title": "Drafted a recommendation for you" if waiting else "Put the findings together",
            "detail": "It waits for your decision." if waiting else "",
        }
    return None


def ask_events(
    state: ApiState, conn: sqlite3.Connection, text: str, use_llm: bool = True
) -> Iterator[Event]:
    """
    Run the planner graph, reporting each step, and write the answer. Approvals are left pending,
    never auto-given.

    With a model configured (and `use_llm`), the model proposes the plan (validated, with the
    deterministic plan as fallback), may help read the question, and rewords the answer. Without
    one, everything is rule-based. The numbers are the same either way.
    """
    started = time.perf_counter()

    def step(data: dict[str, Any]) -> Event:
        return "step", {**data, "ms": round((time.perf_counter() - started) * 1000)}

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
    yield step(
        {
            "stage": "start",
            "title": "Reading your question",
            "detail": "With AI help; every plan is still validated by code."
            if llm is not None
            else "By rules; no model is involved.",
        }
    )

    question: str | None = None
    result: dict[str, Any] = {}
    try:
        for update in graph.stream(initial, config=config, stream_mode="updates"):
            for node, delta in update.items():
                if node.startswith("__") or not isinstance(delta, dict):
                    continue
                shown = _step_for(node, delta)
                if shown:
                    yield step(shown)
        snap = graph.get_state(config)
        result = dict(snap.values)
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
            yield step(
                {
                    "stage": "answer",
                    "title": "Writing the answer from the figures",
                    "detail": "Only numbers the tools computed can appear in it.",
                }
            )
            answer = compose_answer(
                conn, state.user_id, result.get("intent"), observations, names, state.clock
            )
            if answer is not None and llm is not None and getattr(llm, "available", lambda: True)():
                yield step(
                    {
                        "stage": "reword",
                        "title": "Rewording it, then checking every figure",
                        "detail": "If any number is not one the tools computed, the reworded "
                        "version is thrown away and the rule-written one is kept.",
                    }
                )
                answer = narrate(llm, text, answer) or answer
        except Exception:  # noqa: BLE001 - the tool results below are still valid and shown
            log.exception("Could not write the answer; showing the tool results only")
            answer = None
    if answer is not None:
        count = len(answer.facts)
        yield step(
            {
                "stage": "verified",
                "title": f"Checked {count} figure{'' if count == 1 else 's'}",
                "detail": "Each one matches a tool result.",
                "tone": "ok",
            }
        )
    yield "result", _payload(llm, answer, result, question)


def _payload(llm: Any, answer: Any, result: dict[str, Any], question: str | None) -> dict[str, Any]:
    """The JSON the API returns for a finished run."""
    plan_steps = (result.get("plan") or {}).get("steps", [])
    planned_by_model = any(step.get("proposed_by") == "llm" for step in plan_steps)
    read_by_model = ((result.get("intent") or {}).get("source")) == "llm"
    wrote_by_model = bool(answer is not None and answer.written_by == "ai")
    if llm is None:
        path, why = "rules", "no model is configured or it was switched off"
    elif planned_by_model or read_by_model or wrote_by_model:
        path, why = "llm", "the model took part and its output passed validation"
    else:
        path, why = "fallback", "the model was unavailable or its output was not accepted"
    return {
        "answer": answer.model_dump() if answer else None,
        "llm": {
            "available": llm is not None,
            "model": getattr(llm, "model", None) if llm is not None else None,
            "calls": getattr(llm, "calls", 0) if llm is not None else 0,
            "failures": getattr(llm, "failures", 0) if llm is not None else 0,
            "planner": "llm" if planned_by_model else "rules",
            "path": path,
            "path_reason": why,
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
            for step in plan_steps
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


def run_ask(
    state: ApiState, conn: sqlite3.Connection, text: str, use_llm: bool = True
) -> dict[str, Any]:
    """Run the planner graph to the end and return the finished result (no progress events)."""
    final: dict[str, Any] = {}
    for kind, data in ask_events(state, conn, text, use_llm):
        if kind == "result":
            final = data
    return final
