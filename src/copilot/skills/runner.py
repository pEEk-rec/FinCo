"""
Skill Runner and Precondition Checker (PLAN_PHASE3 Section 5.12).

Enforces:
- Deterministic precondition verification (e.g. has_transactions)
- Required input validation
- Pure, thin step execution strictly through `execute_tool(ctx, tool_name, resolved_args)`
- Execution state tracking in the `skill_runs` database table
- Absolute prohibition of direct handler execution or unapproved write mutations
"""

import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import insert_skill_run, update_skill_run
from copilot.models.phase3 import SkillManifest, SkillRun
from copilot.ops.tracing import span
from copilot.skills.manifest import load_skill_manifest
from copilot.tools.executor import ExecutionContext, execute_tool


class SkillRunResult(BaseModel):
    """Result of running a skill procedure."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "cannot_run", "failed"]
    skill_name: str
    skill_version: int
    skill_run_id: str
    reason: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


def check_preconditions(
    conn: sqlite3.Connection,
    user_id: str,
    preconditions: list[str],
) -> tuple[bool, str | None]:
    """
    Deterministically check all declared preconditions for a user.
    Returns (True, None) if all satisfied, or (False, reason) if any fails.
    """
    for precond in preconditions:
        if precond == "has_transactions":
            row = conn.execute(
                "SELECT 1 FROM transactions WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if not row:
                return False, "User has no transactions recorded; cannot run skill."
        else:
            return False, f"Unknown or unsatisfied precondition '{precond}'."
    return True, None


def _resolve_placeholders(val: Any, inputs: dict[str, Any]) -> Any:
    """Recursively resolve $placeholder bindings using inputs."""
    if isinstance(val, str):
        if val.startswith("$"):
            key = val[1:]
            return inputs.get(key)
        return val
    elif isinstance(val, dict):
        resolved: dict[str, Any] = {}
        for k, v in val.items():
            r = _resolve_placeholders(v, inputs)
            if r is not None:
                resolved[k] = r
        return resolved
    elif isinstance(val, list):
        return [_resolve_placeholders(item, inputs) for item in val]
    return val


def run_skill(
    ctx: ExecutionContext,
    skill_name: str,
    inputs: dict[str, Any],
    task_id: str | None = None,
    manifest: SkillManifest | None = None,
) -> SkillRunResult:
    """
    Execute a skill workflow deterministically through the tool executor.
    """
    t0 = time.perf_counter()
    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    start_ts = to_utc_iso(now_dt)
    run_id = f"srun_{uuid.uuid4().hex[:12]}"
    resolved_task_id = task_id or ctx.run_id or f"task_{uuid.uuid4().hex[:8]}"

    # 1. Load manifest if not provided
    if manifest is None:
        manifest_path = PROJECT_ROOT / "config" / "skills" / f"{skill_name}.yaml"
        manifest = load_skill_manifest(manifest_path)

    with span(
        kind="skill",
        name=skill_name,
        attrs={"skill_name": skill_name, "version": manifest.version},
        user_id=ctx.user_id,
        trace_id=resolved_task_id,
        conn=ctx.conn,
    ) as sp:
        # 2. Check preconditions
        passed, fail_reason = check_preconditions(ctx.conn, ctx.user_id, manifest.preconditions)
        if not passed:
            sp.status = "error"
            sp.error_code = "PRECONDITION_FAILED"
            duration = round((time.perf_counter() - t0) * 1000.0, 2)
            r = SkillRun(
                id=run_id,
                user_id=ctx.user_id,
                task_id=resolved_task_id,
                skill_name=manifest.name,
                skill_version=manifest.version,
                inputs_json=inputs,
                status="cannot_run",
                outputs_json={"reason": fail_reason},
                started_at=start_ts,
                finished_at=start_ts,
            )
            insert_skill_run(ctx.conn, r)
            return SkillRunResult(
                status="cannot_run",
                skill_name=manifest.name,
                skill_version=manifest.version,
                skill_run_id=run_id,
                reason=fail_reason,
                outputs={},
                duration_ms=duration,
            )

        # 3. Check required inputs
        for input_name, input_req in manifest.inputs.items():
            if input_req == "required" and (input_name not in inputs or inputs[input_name] is None):
                reason = f"Missing required input '{input_name}' for skill '{manifest.name}'"
                duration = round((time.perf_counter() - t0) * 1000.0, 2)
                r = SkillRun(
                    id=run_id,
                    user_id=ctx.user_id,
                    task_id=resolved_task_id,
                    skill_name=manifest.name,
                    skill_version=manifest.version,
                    inputs_json=inputs,
                    status="cannot_run",
                    outputs_json={"reason": reason},
                    started_at=start_ts,
                    finished_at=start_ts,
                )
                insert_skill_run(ctx.conn, r)
                sp.status = "error"
                sp.error_code = "MISSING_REQUIRED_INPUT"
                return SkillRunResult(
                    status="cannot_run",
                    skill_name=manifest.name,
                    skill_version=manifest.version,
                    skill_run_id=run_id,
                    reason=reason,
                    outputs={},
                    duration_ms=duration,
                )

        # 4. Insert initial running SkillRun row
        r = SkillRun(
            id=run_id,
            user_id=ctx.user_id,
            task_id=resolved_task_id,
            skill_name=manifest.name,
            skill_version=manifest.version,
            inputs_json=inputs,
            status="running",
            outputs_json={},
            started_at=start_ts,
            finished_at=None,
        )
        insert_skill_run(ctx.conn, r)

        # 5. Execute steps sequentially through execute_tool
        outputs: dict[str, Any] = {}
        for step in manifest.steps:
            tool_name, raw_args = next(iter(step.items()))

            # Evaluate conditionals if present
            if_status = raw_args.get("if_status") if isinstance(raw_args, dict) else None
            if if_status and if_status != outputs.get("_last_status", "ok"):
                continue

            resolved_args = _resolve_placeholders(raw_args, inputs)
            if isinstance(resolved_args, dict):
                # Clean up internal conditional keys
                resolved_args.pop("if_status", None)
                resolved_args.pop("if_missing", None)

            tool_result = execute_tool(ctx, tool_name, resolved_args or {})
            if not tool_result.ok:
                err_msg = (
                    tool_result.error.message
                    if tool_result.error
                    else f"Tool '{tool_name}' execution failed"
                )
                duration = round((time.perf_counter() - t0) * 1000.0, 2)
                finish_ts = to_utc_iso(now_dt)
                update_skill_run(
                    ctx.conn,
                    user_id=ctx.user_id,
                    run_id=run_id,
                    status="failed",
                    outputs_json={"error": err_msg, "partial_outputs": outputs},
                    finished_at=finish_ts,
                )
                sp.status = "error"
                sp.error_code = "STEP_FAILED"
                return SkillRunResult(
                    status="failed",
                    skill_name=manifest.name,
                    skill_version=manifest.version,
                    skill_run_id=run_id,
                    reason=err_msg,
                    outputs=outputs,
                    duration_ms=duration,
                )

            data = (
                tool_result.data.model_dump()
                if hasattr(tool_result.data, "model_dump")
                else tool_result.data
            )
            outputs[tool_name] = data
            outputs["_last_status"] = "ok"

        # 6. Finish successfully
        duration = round((time.perf_counter() - t0) * 1000.0, 2)
        finish_ts = to_utc_iso(now_dt)
        outputs.pop("_last_status", None)

        update_skill_run(
            ctx.conn,
            user_id=ctx.user_id,
            run_id=run_id,
            status="ok",
            outputs_json=outputs,
            finished_at=finish_ts,
        )

        return SkillRunResult(
            status="ok",
            skill_name=manifest.name,
            skill_version=manifest.version,
            skill_run_id=run_id,
            reason=None,
            outputs=outputs,
            duration_ms=duration,
        )
