"""
Execution loop helper for autonomous plan steps (PLAN_PHASE2 Section 5.3 & Stage 2.8).

Enforces:
- Every tool call executes STRICTLY through `execute_tool(ctx, tool_name, args)`.
- Memoization: identical (tool, args) returns the earlier result and is
  recorded as 'skipped_memoized'.
- Loop detection: identical or repeated failing tool calls beyond max_repeat end the task
  cleanly with 'loop_detected'.
- Observation summarization: structured data summary appended to task state.
- Database persistence: updates plan_steps rows with status, started_at, finished_at,
  and reject_reason.
"""

import json
from typing import Any

from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo import update_plan_step_status
from copilot.models.agentic import Observation, PlanStep
from copilot.tools.executor import ExecutionContext, execute_tool


def execute_plan_step(
    ctx: ExecutionContext,
    step: PlanStep,
    memo_cache: dict[str, Any],
    call_history: list[dict[str, Any]],
    *,
    max_repeat: int = 3,
) -> tuple[Observation, bool, str | None]:
    """
    Execute a single PlanStep through the executor with memoization and loop protection.
    Returns (observation, should_stop, stop_reason).
    """
    cache_key = f"{step.tool_name}:{json.dumps(step.args, sort_keys=True)}"
    now_ts = to_utc_iso(now_utc(ctx.clock))

    # 1. Memoization check
    if cache_key in memo_cache:
        update_plan_step_status(
            ctx.conn,
            user_id=ctx.user_id,
            step_id=step.id,
            status="skipped_memoized",
            started_at=now_ts,
            finished_at=now_ts,
        )
        memoized_data = memo_cache[cache_key]
        obs = Observation(
            step_seq=step.seq,
            tool_name=step.tool_name,
            ok=True,
            data_summary={"memoized": True, "result": memoized_data},
            error=None,
        )
        return obs, False, None

    # 2. Loop detection check
    same_tool_calls = [c for c in call_history if c.get("tool_name") == step.tool_name]
    if len(same_tool_calls) >= max_repeat:
        update_plan_step_status(
            ctx.conn,
            user_id=ctx.user_id,
            step_id=step.id,
            status="failed",
            reject_reason="loop_detected: tool called beyond max_repeat limit",
            started_at=now_ts,
            finished_at=now_ts,
        )
        obs = Observation(
            step_seq=step.seq,
            tool_name=step.tool_name,
            ok=False,
            data_summary=None,
            error=f"Loop detected: tool '{step.tool_name}' exceeded max_repeat={max_repeat}",
        )
        return obs, True, "loop_detected"

    # 3. Execution through executor
    update_plan_step_status(
        ctx.conn,
        user_id=ctx.user_id,
        step_id=step.id,
        status="running",
        started_at=now_ts,
    )

    result = execute_tool(ctx, step.tool_name, step.args)
    finished_ts = to_utc_iso(now_utc(ctx.clock))

    call_record = {
        "tool_name": step.tool_name,
        "args": step.args,
        "ok": result.ok,
    }
    call_history.append(call_record)

    if result.ok:
        data = result.data.model_dump() if hasattr(result.data, "model_dump") else result.data
        memo_cache[cache_key] = data

        update_plan_step_status(
            ctx.conn,
            user_id=ctx.user_id,
            step_id=step.id,
            status="done",
            finished_at=finished_ts,
        )

        obs = Observation(
            step_seq=step.seq,
            tool_name=step.tool_name,
            ok=True,
            data_summary=data if isinstance(data, dict) else {"data": data},
            error=None,
        )
        return obs, False, None
    else:
        err_msg = result.error.message if result.error else "Unknown execution error"
        update_plan_step_status(
            ctx.conn,
            user_id=ctx.user_id,
            step_id=step.id,
            status="failed",
            reject_reason=err_msg,
            finished_at=finished_ts,
        )

        obs = Observation(
            step_seq=step.seq,
            tool_name=step.tool_name,
            ok=False,
            data_summary=None,
            error=err_msg,
        )
        return obs, False, None
