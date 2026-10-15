"""
Thin workflow node implementations for the Phase 2 Agentic Graph (PLAN_PHASE2 Section 5.10).

ARCHITECTURE INVARIANT:
No tool handler may ever be imported or executed directly by this or any other workflow module.
All tool calls MUST pass strictly through `execute_tool(ctx, tool_name, params)`
or through the planner's `execute_plan_step` helper.
"""

import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from copilot.audit.events import record_event
from copilot.core.config import PROJECT_ROOT, load_settings
from copilot.core.intent import (
    classify_intent,
    create_agent_task,
    parse_amount_paise,
    parse_period,
    resolve_entities,
)
from copilot.core.recommendations import build_recommendation, find_relevant_memories
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.connection import get_connection
from copilot.db.repo import (
    get_agent_task,
    insert_plan_step,
    insert_recommendation,
    update_agent_task_status,
)
from copilot.governance.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.models.agentic import AgentTask, Intent, Plan, PlanStep
from copilot.planner.deterministic import DeterministicPlanner
from copilot.planner.execution import execute_plan_step
from copilot.planner.llm_planner import LLMPlanner
from copilot.planner.validator import PlanValidator
from copilot.tools.executor import ExecutionContext
from copilot.workflow.agentic_state import AgenticState
from copilot.workflow.nodes import ensure_tools_registered
from copilot.workflow.state import TraceEntry


def _get_exec_ctx(
    state: AgenticState,
    config: RunnableConfig | None = None,
) -> tuple[sqlite3.Connection, ExecutionContext, LLMClient | None]:
    """Resolve database connection, execution context, and LLM client."""
    configurable = config.get("configurable", {}) if config else {}
    conn = configurable.get("conn")
    if conn is None:
        db_path = configurable.get("db_path") or load_settings().db_path
        full_path = (PROJECT_ROOT / db_path).resolve()
        conn = get_connection(str(full_path))

    actor = configurable.get("actor", "agent")
    clock = state.get("clock")
    clock_dt: datetime | None = None
    if clock:
        if isinstance(clock, str):
            try:
                clock_dt = datetime.fromisoformat(clock.replace("Z", "+00:00"))
            except Exception:
                clock_dt = None
        else:
            clock_dt = clock

    policy = configurable.get("policy")
    if policy is None:
        policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")

    ctx = ExecutionContext(
        conn=conn,
        user_id=state["user_id"],
        actor=actor,
        run_id=state.get("run_id", "run_unknown"),
        policy=policy,
        clock=clock_dt,
    )
    llm_client = configurable.get("llm_client")
    return conn, ctx, llm_client


def understand_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Input gate and intent parsing node.
    Refusals are caught deterministically and route to finalize;
    Ambiguous queries generate concrete clarification questions.
    """
    t0 = time.perf_counter()
    ensure_tools_registered()
    conn, ctx, llm_client = _get_exec_ctx(state, config)

    raw_text = state.get("raw_text", "")
    task_id = state.get("task_id") or f"task_{uuid.uuid4().hex[:8]}"

    task: AgentTask = create_agent_task(
        conn=conn,
        user_id=state["user_id"],
        raw_text=raw_text,
        task_id=task_id,
        run_id=state.get("run_id"),
        client=llm_client,
        clock=state.get("clock"),
    )

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "understand",
        "started_at": to_utc_iso(now_utc(state.get("clock"))),
        "ended_at": to_utc_iso(now_utc(state.get("clock"))),
        "duration_ms": duration,
        "tools_called": [],
        "counts": {"refused": 1 if task.status == "refused" else 0},
        "status": "ok",
        "error": None,
    }

    if task.status == "refused":
        refusal_msg = (
            task.intent.clarification
            if task.intent
            else "Request was refused per financial policy."
        )
        return {
            "task_id": task.id,
            "intent": task.intent.model_dump() if task.intent else None,
            "refusal_reason": refusal_msg,
            "status": "stopped",
            "stop_reason": "completed",
            "trace": [trace_entry],
        }

    if task.status == "needs_clarification":
        return {
            "task_id": task.id,
            "intent": task.intent.model_dump() if task.intent else None,
            "needs_clarification": True,
            "clarification_question": task.intent.clarification if task.intent else None,
            "status": "running",
            "trace": [trace_entry],
        }

    return {
        "task_id": task.id,
        "intent": task.intent.model_dump() if task.intent else None,
        "needs_clarification": False,
        "status": "running",
        "trace": [trace_entry],
    }


def clarify_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Human-in-the-loop clarification node.
    Allows at most ONE clarification round before stopping with 'inconclusive'.
    """
    t0 = time.perf_counter()
    conn, ctx, llm_client = _get_exec_ctx(state, config)

    if state.get("clarified"):
        # We already clarified once; second failure is a clean inconclusive stop
        update_agent_task_status(
            conn,
            user_id=state["user_id"],
            task_id=state["task_id"],
            status="stopped",
            stop_reason="inconclusive",
            finished_at=to_utc_iso(now_utc(state.get("clock"))),
        )
        duration = (time.perf_counter() - t0) * 1000.0
        return {
            "status": "stopped",
            "stop_reason": "inconclusive",
            "trace": [
                {
                    "node": "clarify",
                    "started_at": to_utc_iso(now_utc(state.get("clock"))),
                    "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                    "duration_ms": duration,
                    "tools_called": [],
                    "counts": {"clarifications": 1},
                    "status": "ok",
                    "error": None,
                }
            ],
        }

    # First clarification: trigger interrupt
    question = state.get("clarification_question") or "Could you clarify your request?"
    options = state.get("clarification_options") or []
    user_response = interrupt({"question": question, "options": options})

    # Resumed with user's answer
    user_reply = str(user_response) if user_response is not None else ""
    updated_raw = f"{state.get('raw_text', '')} {user_reply}".strip()
    amount_paise = parse_amount_paise(updated_raw)
    clock_dt = now_utc(state.get("clock"))
    period_info = parse_period(updated_raw, reference_date=clock_dt)
    entities = resolve_entities(updated_raw, conn, state["user_id"])
    updated_intent = classify_intent(updated_raw, entities, period_info, amount_paise)

    duration = (time.perf_counter() - t0) * 1000.0
    return {
        "intent": updated_intent.model_dump(),
        "clarified": True,
        "needs_clarification": False,
        "clarification_response": str(user_response),
        "status": "running",
        "trace": [
            {
                "node": "clarify",
                "started_at": to_utc_iso(now_utc(state.get("clock"))),
                "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                "duration_ms": duration,
                "tools_called": [],
                "counts": {"clarifications": 1},
                "status": "ok",
                "error": None,
            }
        ],
    }


def plan_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Planner and plan validator node.
    Enforces that invalid, adversarial or over-long plans are audited and replaced
    by the deterministic template plan.
    """
    t0 = time.perf_counter()
    conn, ctx, llm_client = _get_exec_ctx(state, config)

    intent_data = state.get("intent") or {"type": "summarize_period"}
    intent = Intent.model_validate(intent_data)
    task_id = state["task_id"]
    user_id = state["user_id"]
    planner_mode = state.get("planner_mode", "deterministic")

    det_planner = DeterministicPlanner()
    validator = PlanValidator(max_steps=state.get("step_budget", 5))

    if planner_mode == "llm" and llm_client is not None:
        llm_p = LLMPlanner(client=llm_client, deterministic_fallback=det_planner)
        proposed_plan = llm_p.propose(
            task_id=task_id,
            user_id=user_id,
            intent=intent,
            state_projection=dict(state),
        )
    else:
        proposed_plan = det_planner.propose(
            task_id=task_id,
            user_id=user_id,
            intent=intent,
            state_projection=dict(state),
        )

    # Validate proposed plan strictly
    is_valid, reasons = validator.validate_plan(
        conn=conn,
        user_id=user_id,
        plan=proposed_plan,
        intent=intent,
        audit_on_rejection=True,
    )

    if not is_valid:
        # Fall back cleanly to deterministic plan
        final_plan = det_planner.propose(
            task_id=task_id,
            user_id=user_id,
            intent=intent,
            state_projection=dict(state),
        )
    else:
        final_plan = proposed_plan

    # Persist final plan steps to DB
    for step in final_plan.steps:
        insert_plan_step(conn, step)

    update_agent_task_status(
        conn,
        user_id=user_id,
        task_id=task_id,
        status="running",
    )

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "plan",
        "started_at": to_utc_iso(now_utc(state.get("clock"))),
        "ended_at": to_utc_iso(now_utc(state.get("clock"))),
        "duration_ms": duration,
        "tools_called": [],
        "counts": {"steps_planned": len(final_plan.steps), "rejections": 0 if is_valid else 1},
        "status": "ok",
        "error": None,
    }

    return {
        "plan": final_plan.model_dump(),
        "current_step_idx": 0,
        "steps_executed": 0,
        "memo_cache": state.get("memo_cache") or {},
        "call_history": state.get("call_history") or [],
        "observations": [],
        "rounds": 1,
        "max_rounds": state.get("max_rounds", 2),
        "status": "running",
        "trace": [trace_entry],
    }


def act_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Execution loop node: executes planned steps one-by-one via execute_tool.
    Tracks memoization, repeat loop detection, and step budgets.
    """
    t0 = time.perf_counter()
    conn, ctx, _ = _get_exec_ctx(state, config)

    step_budget = state.get("step_budget", 5)
    steps_executed = state.get("steps_executed", 0)

    if steps_executed >= step_budget:
        # Step budget exhausted
        duration = (time.perf_counter() - t0) * 1000.0
        return {
            "status": "stopped",
            "stop_reason": "step_budget",
            "trace": [
                {
                    "node": "act",
                    "started_at": to_utc_iso(now_utc(state.get("clock"))),
                    "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                    "duration_ms": duration,
                    "tools_called": [],
                    "counts": {"stopped_by_budget": 1},
                    "status": "ok",
                    "error": None,
                }
            ],
        }

    plan_dict = state.get("plan")
    if not plan_dict or "steps" not in plan_dict:
        return {"status": "stopped", "stop_reason": "completed"}

    steps = [PlanStep.model_validate(s) for s in plan_dict["steps"]]
    idx = state.get("current_step_idx", 0)

    if idx >= len(steps):
        # All planned steps completed
        return {"current_step_idx": idx}

    step = steps[idx]
    memo_cache = dict(state.get("memo_cache") or {})
    call_history = list(state.get("call_history") or [])

    obs, should_stop, stop_reason = execute_plan_step(
        ctx=ctx,
        step=step,
        memo_cache=memo_cache,
        call_history=call_history,
        max_repeat=3,
    )

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "act",
        "started_at": to_utc_iso(now_utc(state.get("clock"))),
        "ended_at": to_utc_iso(now_utc(state.get("clock"))),
        "duration_ms": duration,
        "tools_called": [step.tool_name],
        "counts": {
            "executed": 1,
            "memoized": 1 if obs.data_summary and obs.data_summary.get("memoized") else 0,
        },
        "status": "ok" if obs.ok else "error",
        "error": obs.error,
    }

    if should_stop:
        return {
            "current_step_idx": idx + 1,
            "steps_executed": steps_executed + 1,
            "memo_cache": memo_cache,
            "call_history": call_history,
            "observations": [obs.model_dump()],
            "status": "stopped",
            "stop_reason": stop_reason,
            "trace": [trace_entry],
        }

    return {
        "current_step_idx": idx + 1,
        "steps_executed": steps_executed + 1,
        "memo_cache": memo_cache,
        "call_history": call_history,
        "observations": [obs.model_dump()],
        "status": "running",
        "trace": [trace_entry],
    }


def reflect_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Reflection node: bounded re-planning check (PLAN_PHASE2 Section 5.3).
    If an investigation outcome is 'partially_explained' or 'inconclusive' and rounds < max_rounds,
    adds one further round of catalogue hypotheses not yet evaluated.
    """
    t0 = time.perf_counter()
    conn, ctx, _ = _get_exec_ctx(state, config)

    rounds = state.get("rounds", 1)
    max_rounds = state.get("max_rounds", 2)
    observations = state.get("observations") or []
    plan_dict = state.get("plan") or {"steps": []}
    steps = [PlanStep.model_validate(s) for s in plan_dict.get("steps", [])]

    # Check if investigation occurred and yielded inconclusive/partially_explained
    needs_replan = False
    for obs in observations:
        data = obs.get("data_summary") or {}
        if "outcome" in data and data["outcome"] in ("partially_explained", "inconclusive"):
            needs_replan = True
            break

    if needs_replan and rounds < max_rounds and not state.get("replan_triggered", False):
        # Add next round step: explain_change or investigate_anomaly
        new_step = PlanStep(
            id=f"step_{uuid.uuid4().hex[:8]}",
            task_id=state["task_id"],
            user_id=state["user_id"],
            seq=len(steps),
            tool_name="get_transactions",
            args={
                "start_utc": "1970-01-01T00:00:00Z",
                "end_utc": to_utc_iso(now_utc(state.get("clock"))),
            },
            rationale="Second round investigation to test remaining catalogue hypotheses",
            proposed_by="deterministic",
            status="proposed",
        )
        insert_plan_step(conn, new_step)
        steps.append(new_step)
        updated_plan = Plan(task_id=state["task_id"], steps=steps)

        duration = (time.perf_counter() - t0) * 1000.0
        return {
            "rounds": rounds + 1,
            "replan_triggered": True,
            "plan": updated_plan.model_dump(),
            "trace": [
                {
                    "node": "reflect",
                    "started_at": to_utc_iso(now_utc(state.get("clock"))),
                    "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                    "duration_ms": duration,
                    "tools_called": [],
                    "counts": {"replanned": 1},
                    "status": "ok",
                    "error": None,
                }
            ],
        }

    duration = (time.perf_counter() - t0) * 1000.0
    return {
        "replan_triggered": False,
        "trace": [
            {
                "node": "reflect",
                "started_at": to_utc_iso(now_utc(state.get("clock"))),
                "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                "duration_ms": duration,
                "tools_called": [],
                "counts": {"replanned": 0},
                "status": "ok",
                "error": None,
            }
        ],
    }


def synthesize_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Synthesize node: builds findings and draft explainable recommendations (Stage 2.6).
    Enforces causal-claim rules and consequence rules (simulation link) with template fallback.
    """
    t0 = time.perf_counter()
    conn, ctx, _ = _get_exec_ctx(state, config)

    observations = state.get("observations") or []
    intent_data = state.get("intent") or {}
    intent_type = intent_data.get("type", "summarize_period")
    user_id = state["user_id"]
    task_id = state["task_id"]

    # Map observations into evidence and memories
    evidence_ids: list[str] = []
    simulation_id: str | None = None
    investigations_by_id: dict[str, Any] = {}
    simulations_by_id: dict[str, Any] = {}
    tools_used: list[dict[str, Any]] = []

    for obs in observations:
        tool = obs.get("tool_name", "")
        summary = obs.get("data_summary") or {}
        tools_used.append({"tool": tool, "ok": obs.get("ok", True)})

        if tool == "run_whatif" and "id" in summary:
            simulation_id = summary["id"]
            simulations_by_id[simulation_id] = summary
            evidence_ids.append(simulation_id)
        elif tool in ("investigate_anomaly", "explain_change") and "id" in summary:
            inv_id = summary["id"]
            investigations_by_id[inv_id] = summary
            evidence_ids.append(inv_id)

    # Gather memories
    memories = find_relevant_memories(conn, user_id, category_id=intent_data.get("category_id"))

    # Determine origin
    origin_map = {
        "whatif_add_spend": "whatif",
        "whatif_reduce_spend": "whatif",
        "affordability": "whatif",
        "tradeoff_compare": "whatif",
        "investigate_anomaly": "investigation",
        "explain_change": "investigation",
        "alerts_overview": "alert",
        "goal_check": "goal",
        "goal_progress": "goal",
        "trip_planning": "goal",
        "contribution_check": "goal",
    }
    origin = origin_map.get(intent_type, "monthly_review")

    # Draft narration text
    narration_text = f"Analyzed {intent_type} for period {intent_data.get('period', 'current')}."
    if investigations_by_id:
        top_inv = next(iter(investigations_by_id.values()))
        outcome = top_inv.get("outcome", "inconclusive")
        share_pct = top_inv.get("explained_share_bp", 0) / 100
        narration_text = f"Investigation outcome was {outcome} with share {share_pct}%."

    # Build explainable recommendation
    rec = build_recommendation(
        user_id=user_id,
        origin=origin,  # type: ignore[arg-type]
        text=narration_text,
        task_id=task_id,
        run_id=state.get("run_id"),
        evidence=evidence_ids,
        assumptions=["Baseline spend continues at historical run-rate"],
        tools_used=tools_used,
        memories=memories,
        confidence_label="medium",
        simulation_id=simulation_id,
        investigations_by_id=investigations_by_id,
        simulations_by_id=simulations_by_id,
        clock=state.get("clock"),
    )

    insert_recommendation(conn, rec)

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "synthesize",
        "started_at": to_utc_iso(now_utc(state.get("clock"))),
        "ended_at": to_utc_iso(now_utc(state.get("clock"))),
        "duration_ms": duration,
        "tools_called": [],
        "counts": {"recommendations": 1},
        "status": "ok",
        "error": None,
    }

    # Draft recommendations require human review if origin is whatif or goal
    needs_review = origin in ("whatif", "goal")
    return {
        "recommendations": [rec.model_dump()],
        "pending_recommendations": [rec.model_dump()] if needs_review else [],
        "status": "running",
        "trace": [trace_entry],
    }


def review_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Review node: human-in-the-loop approval interrupt for draft recommendations.
    """
    t0 = time.perf_counter()
    pending = state.get("pending_recommendations") or []

    if pending:
        # Trigger review interrupt
        user_decision = interrupt({"pending_recommendations": pending})
        # Resumed with decision
        duration = (time.perf_counter() - t0) * 1000.0
        return {
            "pending_recommendations": [],
            "review_decisions": [user_decision] if isinstance(user_decision, dict) else [],
            "status": "running",
            "trace": [
                {
                    "node": "review",
                    "started_at": to_utc_iso(now_utc(state.get("clock"))),
                    "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                    "duration_ms": duration,
                    "tools_called": [],
                    "counts": {"decided": len(pending)},
                    "status": "ok",
                    "error": None,
                }
            ],
        }

    duration = (time.perf_counter() - t0) * 1000.0
    return {
        "status": "running",
        "trace": [
            {
                "node": "review",
                "started_at": to_utc_iso(now_utc(state.get("clock"))),
                "ended_at": to_utc_iso(now_utc(state.get("clock"))),
                "duration_ms": duration,
                "tools_called": [],
                "counts": {"decided": 0},
                "status": "ok",
                "error": None,
            }
        ],
    }


def finalize_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Finalize node: closes the task in agent_tasks with typed stop_reason and finished_at.
    """
    t0 = time.perf_counter()
    conn, ctx, _ = _get_exec_ctx(state, config)

    stop_reason = state.get("stop_reason") or "completed"
    if state.get("status") == "stopped":
        status = "stopped"
    else:
        status = "completed" if stop_reason == "completed" else "stopped"
    now_ts = to_utc_iso(now_utc(state.get("clock")))

    if state.get("task_id"):
        task_row = get_agent_task(conn, state["user_id"], state["task_id"])
        if task_row and task_row.status == "refused":
            task_status = "refused"
            status = "stopped"
        else:
            task_status = "done" if status == "completed" else "stopped"

        update_agent_task_status(
            conn,
            user_id=state["user_id"],
            task_id=state["task_id"],
            status=task_status,
            stop_reason=stop_reason,
            finished_at=now_ts,
        )

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "finalize",
        "started_at": now_ts,
        "ended_at": now_ts,
        "duration_ms": duration,
        "tools_called": [],
        "counts": {"completed": 1 if status == "completed" else 0},
        "status": "ok",
        "error": None,
    }

    return {
        "status": status,
        "stop_reason": stop_reason,
        "trace": [trace_entry],
    }


def error_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Error node: audited catch-all for uncaught workflow exceptions.
    """
    conn, ctx, _ = _get_exec_ctx(state, config)
    now_ts = to_utc_iso(now_utc(state.get("clock")))

    if state.get("task_id"):
        update_agent_task_status(
            conn,
            user_id=state["user_id"],
            task_id=state["task_id"],
            status="failed",
            stop_reason="tool_failure",
            finished_at=now_ts,
        )

    record_event(
        conn,
        user_id=state.get("user_id", "user_unknown"),
        actor="agent",
        event_type="tool_failure",
        reason="Workflow error node reached",
        entity_type="agent_task",
        entity_id=state.get("task_id", "task_unknown"),
        after_data=state.get("error"),
        clock=state.get("clock"),
    )

    trace_entry: TraceEntry = {
        "node": "error",
        "started_at": now_ts,
        "ended_at": now_ts,
        "duration_ms": 0.0,
        "tools_called": [],
        "counts": {"failed": 1},
        "status": "error",
        "error": str(state.get("error")),
    }

    return {
        "status": "failed",
        "stop_reason": "tool_failure",
        "trace": [trace_entry],
    }


def multi_agent_node(state: AgenticState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Execute the multi-agent planning subgraph for multi-domain intents."""
    t0 = time.perf_counter()
    conn, ctx, llm_client = _get_exec_ctx(state, config)
    from copilot.workflow.multi_agent_graph import run_multi_agent_workflow

    intent = state.get("intent") or {}
    user_id = state["user_id"]
    task_id = state["task_id"]

    subgraph_result = run_multi_agent_workflow(
        intent=intent,
        user_id=user_id,
        task_id=task_id,
        ctx=ctx,
        llm_client=llm_client,
        user_data=dict(state),
    )

    duration = (time.perf_counter() - t0) * 1000.0
    trace_entry: TraceEntry = {
        "node": "multi_agent",
        "started_at": to_utc_iso(now_utc(state.get("clock"))),
        "ended_at": to_utc_iso(now_utc(state.get("clock"))),
        "duration_ms": duration,
        "tools_called": [
            r.get("agent_role")
            for r in subgraph_result.get("reports", [])
            if isinstance(r, dict)
        ],

        "counts": {
            "subquestions": len(subgraph_result.get("subquestions", [])),
            "reports": len(subgraph_result.get("reports", [])),
            "findings": len(subgraph_result.get("findings", [])),
        },
        "status": subgraph_result.get("status", "ok"),
        "error": None,
    }

    return {
        "findings": subgraph_result.get("findings", []),
        "status": "completed" if subgraph_result.get("status") != "failed" else "failed",
        "stop_reason": "completed" if subgraph_result.get("status") != "failed" else "tool_failure",
        "final_narration": subgraph_result.get("final_narration"),
        "trace": [trace_entry],
    }

