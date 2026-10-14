"""
The single execution choke point for all tools.

RULE: tool handlers must never be called by any other path in the agent code. The agent only
ever calls `execute_tool`, which:
  1. looks the tool up (unknown -> NOT_FOUND),
  2. asks governance for a decision (deny -> DENIED_BY_POLICY; needs_approval without
     `approved=True` -> APPROVAL_REQUIRED); the handler is not called in either case,
  3. validates input (-> INVALID_INPUT), runs the handler, validates output,
  4. turns every failure into a ToolResult (it never raises),
  5. audits every call, whatever the outcome.

The handler, output validation and the success audit event share one savepoint: if any part
fails, the handler's writes are rolled back, so nothing changes without an audit record.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from copilot.audit.events import Actor, record_event
from copilot.core.errors import ErrorCode, ToolError, ToolFailure
from copilot.db.connection import savepoint
from copilot.governance.policy import Decision, PolicySettings, decide
from copilot.tools.contracts import ToolResult, ToolSpec
from copilot.tools.registry import get as get_tool

EVENT_TYPE = "tool_call"


@dataclass
class ExecutionContext:
    """Everything a tool call needs: DB connection, who is asking, policy and clock."""

    conn: sqlite3.Connection
    user_id: str
    run_id: str
    policy: PolicySettings
    clock: datetime | None = None
    actor: Actor = "agent"


def _json_safe(value: Any) -> Any:
    """Return a JSON-compatible copy of `value`; unknown objects become their repr."""
    return json.loads(json.dumps(value, default=repr))


def _audit(
    ctx: ExecutionContext,
    tool_name: str,
    raw_input: Any,
    decision: Decision | None,
    reason: str,
    approved: bool,
    output: BaseModel | None = None,
    error: ToolError | None = None,
    event_type: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Write the audit event for one tool call. Does not commit."""
    meta: dict[str, Any] = {
        "approved": approved,
        "error_code": error.code.value if error is not None else None,
    }
    if extra_metadata:
        meta.update(extra_metadata)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type=event_type or EVENT_TYPE,
        reason=reason,
        run_id=ctx.run_id,
        entity_type="tool",
        entity_id=tool_name,
        before_data=_json_safe(raw_input),
        after_data=output.model_dump(mode="json") if output is not None else None,
        policy_decision=decision.outcome if decision is not None else None,
        metadata=meta,
        clock=ctx.clock,
    )


def _fail(
    ctx: ExecutionContext,
    tool_name: str,
    raw_input: Any,
    decision: Decision | None,
    approved: bool,
    error: ToolError,
    event_type: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> ToolResult:
    """Audit a failed or blocked call in its own savepoint and return the failure result."""
    try:
        with savepoint(ctx.conn):
            _audit(
                ctx,
                tool_name,
                raw_input,
                decision,
                error.message,
                approved,
                error=error,
                event_type=event_type,
                extra_metadata=extra_metadata,
            )
    except Exception as exc:  # noqa: BLE001 - the executor must never raise
        error = ToolError(
            code=ErrorCode.INTERNAL,
            message=f"{error.code.value}: {error.message} (and audit failed: {exc})",
        )
    return ToolResult(ok=False, error=error)


def _run(
    ctx: ExecutionContext, spec: ToolSpec, raw_input: Any, decision: Decision, approved: bool
) -> ToolResult:
    """Validate, run and audit an allowed call."""
    if not isinstance(raw_input, dict):
        error = ToolError(code=ErrorCode.INVALID_INPUT, message="Tool input must be an object.")
        return _fail(ctx, spec.name, raw_input, decision, approved, error)
    try:
        params = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        error = ToolError(code=ErrorCode.INVALID_INPUT, message=str(exc))
        return _fail(ctx, spec.name, raw_input, decision, approved, error)

    try:
        with savepoint(ctx.conn):
            raw_output = spec.handler(ctx, **dict(params))
            output = spec.output_model.model_validate(raw_output)
            _audit(ctx, spec.name, raw_input, decision, decision.reason, approved, output=output)
    except ToolFailure as exc:
        return _fail(
            ctx,
            spec.name,
            raw_input,
            decision,
            approved,
            exc.error,
            event_type=exc.audit_event_type,
            extra_metadata=exc.audit_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - handler bugs become TOOL_FAILURE
        error = ToolError(code=ErrorCode.TOOL_FAILURE, message=f"{type(exc).__name__}: {exc}")
        return _fail(ctx, spec.name, raw_input, decision, approved, error)
    return ToolResult(ok=True, data=output)


def execute_tool(
    ctx: ExecutionContext, tool_name: str, raw_input: Any, approved: bool = False
) -> ToolResult:
    """Execute a tool by name through governance, validation and audit. Never raises."""
    try:
        spec = get_tool(tool_name)
        if spec is None:
            error = ToolError(code=ErrorCode.NOT_FOUND, message=f"Tool '{tool_name}' not found.")
            return _fail(ctx, str(tool_name), raw_input, None, approved, error)

        decision = decide(ctx.policy, spec, ctx.actor)
        if decision.outcome == "deny":
            error = ToolError(code=ErrorCode.DENIED_BY_POLICY, message=decision.reason)
            return _fail(ctx, spec.name, raw_input, decision, approved, error)
        if decision.outcome == "needs_approval" and not approved:
            error = ToolError(code=ErrorCode.APPROVAL_REQUIRED, message=decision.reason)
            return _fail(ctx, spec.name, raw_input, decision, approved, error)

        return _run(ctx, spec, raw_input, decision, approved)
    except Exception as exc:  # noqa: BLE001 - last line of defence
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.INTERNAL, message=f"{type(exc).__name__}: {exc}"),
        )
