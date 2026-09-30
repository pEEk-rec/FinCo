"""
The single execution choke point for all tools.
Handlers MUST NOT be called directly by any other path in the agent code.
"""
import sqlite3
from datetime import datetime
from typing import Any, Dict

from pydantic import ValidationError

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolError
from copilot.governance.policy import PolicySettings, decide
from copilot.tools.contracts import ToolResult
from copilot.tools.registry import get as get_tool


class ExecutionContext:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        run_id: str,
        policy: PolicySettings,
        clock: datetime | None = None
    ):
        self.conn = conn
        self.user_id = user_id
        self.run_id = run_id
        self.policy = policy
        self.clock = clock

def execute_tool(
    ctx: ExecutionContext,
    tool_name: str,
    raw_input: Dict[str, Any],
    approved: bool = False
) -> ToolResult:
    """
    Execute a tool by name, applying governance, validation, and auditing.
    """
    tool_spec = get_tool(tool_name)
    if tool_spec is None:
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.NOT_FOUND, message=f"Tool '{tool_name}' not found")
        )
        
    decision = decide(ctx.policy, tool_spec)
    
    if decision.outcome == "deny":
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="tool_execution",
            reason=f"Execution denied: {decision.reason}",
            run_id=ctx.run_id,
            entity_type="tool",
            entity_id=tool_name,
            before_data=raw_input,
            policy_decision="deny"
        )
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.DENIED_BY_POLICY, message=decision.reason)
        )
        
    if decision.outcome == "needs_approval" and not approved:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="tool_execution",
            reason=f"Execution requires approval: {decision.reason}",
            run_id=ctx.run_id,
            entity_type="tool",
            entity_id=tool_name,
            before_data=raw_input,
            policy_decision="needs_approval"
        )
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.APPROVAL_REQUIRED, message=decision.reason)
        )
        
    # Input validation
    try:
        validated_input = tool_spec.input_model(**raw_input)
    except ValidationError as e:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="tool_execution",
            reason="Invalid input",
            run_id=ctx.run_id,
            entity_type="tool",
            entity_id=tool_name,
            before_data=raw_input,
            policy_decision=decision.outcome
        )
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.INVALID_INPUT, message=str(e))
        )
        
    # Execution
    try:
        output_data = tool_spec.handler(ctx, **validated_input.model_dump())
        
        # Output validation
        validated_output = tool_spec.output_model(**output_data)
        
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="tool_execution",
            reason="Execution successful",
            run_id=ctx.run_id,
            entity_type="tool",
            entity_id=tool_name,
            before_data=raw_input,
            after_data=validated_output.model_dump(),
            policy_decision=decision.outcome
        )
        
        return ToolResult(ok=True, data=validated_output)
        
    except Exception as e:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="tool_execution",
            reason=f"Execution failed: {str(e)}",
            run_id=ctx.run_id,
            entity_type="tool",
            entity_id=tool_name,
            before_data=raw_input,
            policy_decision=decision.outcome
        )
        return ToolResult(
            ok=False,
            error=ToolError(code=ErrorCode.TOOL_FAILURE, message=str(e))
        )
