"""
Model Context Protocol (MCP) Server for FinCo (PLAN_PHASE3 Section 5.17 & Stage 3.15).

Exposes FinCo over stdio or in-process using the official Python MCP SDK.

Enforces:
- Safety Rule 17: Exposes only planner-selectable read/compute tools and skills;
  write tools are NEVER exposed, even if added to the registry.
- Choke Point: Every tool call executes strictly through `execute_tool(ctx, tool_name, args)`
  with `actor = "agent"`.
- Distributed Tracing & Audit: Every call is wrapped in `span(kind="mcp", name=tool_name, ...)`
  and audited.
- Data Minimisation: When `mcp.allow_transaction_detail` is false (the default),
  transaction-level details are suppressed and only aggregated counts and totals are returned.
- Ask Tool: Autonomous multi-domain query tool running the agent graph; can create drafts,
  never user-actor writes.
- Resources: `finco://monthly_review/latest`, `finco://calendar/summary`, `finco://buckets/summary`.
"""

from __future__ import annotations

import inspect
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from mcp.server import MCPServer
from pydantic import BaseModel

from copilot.config.phase2 import load_planner_capabilities
from copilot.config.phase3 import MCPConfig, load_mcp_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.connection import get_connection
from copilot.governance.policy import PolicySettings, load_policy
from copilot.ops.tracing import span
from copilot.planner.capabilities import get_selectable_tools, is_planner_selectable
from copilot.tools.contracts import SideEffect, ToolSpec
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import get as get_tool
from copilot.workflow.agent_graph import build_planner_agent_graph
from copilot.workflow.agentic_state import AgenticState
from copilot.workflow.nodes import ensure_tools_registered

logger = logging.getLogger(__name__)


def _sanitize_for_mcp(value: Any) -> Any:
    """Recursively convert model instances and non-JSON objects to JSON-serializable types."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _sanitize_for_mcp(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_mcp(v) for v in value]
    return value


def _apply_data_minimisation(tool_name: str, raw_data: Any, allow_detail: bool) -> Any:
    """
    Apply data-minimisation policy (PLAN_PHASE3 Section 5.17 & Safety Rule 17).
    When allow_detail is false, suppress row-level transaction items and return aggregates.
    """
    if allow_detail:
        return _sanitize_for_mcp(raw_data)

    # get_transactions minimization
    if tool_name == "get_transactions":
        txs = []
        if isinstance(raw_data, dict):
            txs = raw_data.get("transactions", [])
        elif hasattr(raw_data, "transactions"):
            txs = getattr(raw_data, "transactions", [])

        total_debit = 0
        total_credit = 0
        for tx in txs:
            amt = (
                tx.get("amount_paise", 0)
                if isinstance(tx, dict)
                else getattr(tx, "amount_paise", 0)
            )
            direction = (
                tx.get("direction", "debit")
                if isinstance(tx, dict)
                else getattr(tx, "direction", "debit")
            )
            if direction == "debit":
                total_debit += amt
            else:
                total_credit += abs(amt)

        return {
            "total_count": len(txs),
            "total_debit_paise": total_debit,
            "total_credit_paise": total_credit,
            "notice": (
                "Transaction-level detail omitted per data-minimisation policy. "
                "Enable 'mcp.allow_transaction_detail: true' in config to view "
                "individual transactions."
            ),
        }

    return _sanitize_for_mcp(raw_data)


def _build_mcp_tool_wrapper(
    spec: ToolSpec,
    get_ctx_fn: Callable[[], ExecutionContext],
    allow_detail: bool,
) -> Callable[..., Any]:
    """
    Build a typed MCP tool handler wrapper preserving the ToolSpec's Pydantic input schema
    and routing execution strictly through `execute_tool`.
    """
    input_model = spec.input_model

    # Dynamically build signature from Pydantic input model fields
    parameters = []
    for f_name, f_info in input_model.model_fields.items():
        default = inspect.Parameter.empty if f_info.is_required() else f_info.default
        param = inspect.Parameter(
            name=f_name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=default,
            annotation=f_info.annotation if f_info.annotation is not None else Any,
        )
        parameters.append(param)

    def tool_handler(**kwargs: Any) -> dict[str, Any]:
        ctx = get_ctx_fn()
        with span(
            kind="mcp",
            name=spec.name,
            attrs={"user_id": ctx.user_id, "tool": spec.name},
            user_id=ctx.user_id,
            conn=ctx.conn,
        ):
            # 1. Validate inputs with Pydantic model
            try:
                validated_model = input_model.model_validate(kwargs)
                args_dict = validated_model.model_dump(mode="python")
            except Exception as exc:
                return {
                    "ok": False,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"Invalid arguments for tool '{spec.name}': {exc}",
                    },
                }

            # 2. Single choke point execution
            res = execute_tool(ctx, spec.name, args_dict)

            # 3. Process result
            if not res.ok:
                err_msg = res.error.message if res.error else "Tool execution failed"
                err_code = res.error.code.value if res.error else "EXECUTION_FAILED"
                return {
                    "ok": False,
                    "error": {
                        "code": err_code,
                        "message": err_msg,
                    },
                }

            output_data = _apply_data_minimisation(spec.name, res.data, allow_detail=allow_detail)
            return {
                "ok": True,
                "data": output_data,
            }

    tool_handler.__name__ = f"mcp_{spec.name}"
    tool_handler.__doc__ = spec.description
    tool_handler.__signature__ = inspect.Signature(parameters)
    return tool_handler


def create_mcp_server(
    conn: sqlite3.Connection | None = None,
    user_id: str = "u1",
    config: MCPConfig | None = None,
    policy: PolicySettings | None = None,
    clock: datetime | None = None,
    db_path: Path | str | None = None,
) -> MCPServer:
    """
    Factory function creating an MCP server instance exposing FinCo capabilities.

    Enforces:
    - Safety Rule 17: Only planner-selectable read/compute tools and skills are exposed.
    - Write tools are strictly prohibited.
    - ask tool exposes multi-domain graph inquiry.
    - Resources provide live JSON snapshots of reviews, calendar, and buckets.
    """
    ensure_tools_registered()
    mcp_cfg = config or load_mcp_config()
    pol = policy or load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    capabilities_cfg = load_planner_capabilities()

    server = MCPServer(
        name=mcp_cfg.server_name,
        instructions="FinCo Financial Copilot MCP Server (Read, Compute, and Ask)",
        version="1.0.0",
    )

    # Establish database connection provider
    active_conn = (
        conn
        if conn is not None
        else (
            get_connection(str(db_path), check_same_thread=False)
            if db_path is not None
            else get_connection(":memory:", check_same_thread=False)
        )
    )

    def get_context() -> ExecutionContext:
        return ExecutionContext(
            conn=active_conn,
            user_id=user_id,
            run_id=f"mcp_{uuid.uuid4().hex[:8]}",
            policy=pol,
            actor="agent",  # Safety: MCP calls execute as agent actor
            clock=clock,
        )

    # ---------------------------------------------------------------------------------------------
    # 1. Register Planner-Selectable Read/Compute Tools and Skills
    # ---------------------------------------------------------------------------------------------
    all_selectable = set(get_selectable_tools(capabilities_cfg))

    # Optional restriction list from config
    target_tools = set(mcp_cfg.exposed_tools) if mcp_cfg.exposed_tools else all_selectable
    allowed_to_expose = sorted(target_tools & all_selectable)

    for tool_name in allowed_to_expose:
        spec = get_tool(tool_name)
        if spec is None:
            continue

        # Invariant: Safety Rule 17 check
        if not is_planner_selectable(tool_name, capabilities_cfg):
            continue
        if spec.side_effect != SideEffect.READ:
            continue

        wrapper = _build_mcp_tool_wrapper(
            spec=spec,
            get_ctx_fn=get_context,
            allow_detail=mcp_cfg.allow_transaction_detail,
        )

        server.add_tool(
            fn=wrapper,
            name=spec.name,
            description=spec.description,
        )

    # ---------------------------------------------------------------------------------------------
    # 2. Register 'ask' Agent Tool
    # ---------------------------------------------------------------------------------------------
    def mcp_ask_handler(
        query: str,
        clock_str: str | None = None,
        step_budget: int = 10,
    ) -> dict[str, Any]:
        """
        Ask FinCo a question or financial request.
        Runs the planner-driven agent graph with actor='agent'.
        Can generate findings and unapproved drafts; never executes user-actor writes.
        """
        with span(
            kind="mcp",
            name="ask",
            attrs={"user_id": user_id, "query_length": len(query)},
            user_id=user_id,
            conn=active_conn,
        ):
            now_ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
            run_id = f"mcp_ask_{now_ts}_{uuid.uuid4().hex[:4]}"
            sim_clock = clock_str or (to_utc_iso(clock) if clock else to_utc_iso(now_utc()))

            checkpointer = MemorySaver()
            graph = build_planner_agent_graph(checkpointer=checkpointer)
            thread_id = f"thread_{run_id}"
            thread_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "conn": active_conn,
                    "actor": "agent",
                }
            }

            initial_state: AgenticState = {
                "user_id": user_id,
                "run_id": run_id,
                "raw_text": query,
                "clock": sim_clock,
                "planner_mode": "deterministic",
                "step_budget": step_budget,
            }

            try:
                result = graph.invoke(initial_state, config=thread_config)
                narration = result.get("narration") or "Analysis completed."
                status = result.get("task_status", "completed")
                findings = result.get("findings", [])

                return {
                    "ok": True,
                    "run_id": run_id,
                    "status": status,
                    "answer": narration,
                    "findings_count": len(findings),
                    "intent": result.get("intent"),
                }
            except Exception as exc:
                logger.exception("Error executing MCP ask: %s", exc)
                return {
                    "ok": False,
                    "run_id": run_id,
                    "error": {
                        "code": "AGENT_ERROR",
                        "message": str(exc),
                    },
                }

    server.add_tool(
        fn=mcp_ask_handler,
        name="ask",
        description=(
            "Ask FinCo a financial question. Runs the agent graph; "
            "can create drafts, never user-actor writes."
        ),
    )

    # ---------------------------------------------------------------------------------------------
    # 3. Register MCP Resources (Section 5.17)
    # ---------------------------------------------------------------------------------------------
    @server.resource("finco://monthly_review/latest")
    def get_latest_monthly_review_resource() -> str:
        """Resource: Latest monthly financial review JSON for the user."""
        try:
            sql = (
                "SELECT review_json FROM monthly_reviews "
                "WHERE user_id = ? ORDER BY year DESC, month DESC, version DESC LIMIT 1"
            )
            row = active_conn.execute(sql, (user_id,)).fetchone()
            if row and row[0]:
                return str(row[0])
            return json.dumps(
                {
                    "user_id": user_id,
                    "status": "no_reviews_recorded",
                    "message": "No monthly reviews available yet.",
                },
                indent=2,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @server.resource("finco://calendar/summary")
    def get_calendar_summary_resource() -> str:
        """Resource: Current 30-day projected calendar summary."""
        try:
            ctx = get_context()
            res = execute_tool(ctx, "get_calendar", {"horizon_days": 30})
            if res.ok and res.data:
                return json.dumps(res.data.model_dump(mode="json"), indent=2)
            reason = res.error.message if res.error else "failed"
            return json.dumps({"status": "unavailable", "reason": reason})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @server.resource("finco://buckets/summary")
    def get_buckets_summary_resource() -> str:
        """Resource: Current virtual buckets allocation summary."""
        try:
            ctx = get_context()
            now_dt = clock or now_utc()
            period = f"{now_dt.year:04d}-{now_dt.month:02d}"
            res = execute_tool(ctx, "get_allocation_summary", {"period": period})
            if res.ok and res.data:
                return json.dumps(res.data.model_dump(mode="json"), indent=2)
            reason = res.error.message if res.error else "failed"
            return json.dumps({"status": "unavailable", "reason": reason})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return server


def run_mcp_stdio_server(
    conn: sqlite3.Connection | None = None,
    user_id: str = "u1",
    db_path: Path | str | None = None,
) -> None:
    """Run FinCo MCP server synchronously over stdio transport."""
    server = create_mcp_server(conn=conn, user_id=user_id, db_path=db_path)
    logger.info("Starting FinCo MCP server over stdio for user '%s'", user_id)
    server.run(transport="stdio")
