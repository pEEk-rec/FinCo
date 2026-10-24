"""
Thin workflow node implementations for the FinCo agent graph.

ARCHITECTURE INVARIANT:
No tool handler may ever be imported or executed directly by this or any other workflow module.
All tool calls MUST pass strictly through `execute_tool(ctx, tool_name, params)`.
"""

import sqlite3
import threading
import time
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from copilot.audit.events import Actor, record_event
from copilot.core.categorisation import load_aliases, load_rules
from copilot.core.config import PROJECT_ROOT, load_settings
from copilot.core.pipeline import run_categorization_pipeline
from copilot.core.timeutil import now_utc
from copilot.governance.policy import PolicySettings, load_policy
from copilot.llm.client import FakeLLMClient
from copilot.models.findings import Finding
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import get as get_tool
from copilot.workflow.findings import build_findings_from_analysis
from copilot.workflow.state import AgentState, TraceEntry

_REGISTRATION_LOCK = threading.RLock()


def ensure_tools_registered() -> None:
    """
    Make sure every tool is registered, safely from several threads at once.

    Parallel specialists each call this first. Without the lock two threads could both see a
    tool missing and both register it, and one would fail with "already registered", which
    silently dropped that specialist's findings.
    """
    with _REGISTRATION_LOCK:
        _register_missing_tools()


def _register_missing_tools() -> None:
    """Ensure all tool specifications are registered in the global registry."""
    if get_tool("get_financial_state") is None:
        from copilot.tools.financial import register_financial_tools

        register_financial_tools()

    if get_tool("create_goal") is None:
        from copilot.tools.goals import register_goals_tools

        register_goals_tools()

    if get_tool("run_whatif") is None:
        from copilot.tools.whatif import register_whatif_tools

        register_whatif_tools()

    if get_tool("investigate_anomaly") is None:
        from copilot.tools.investigation import register_investigation_tools

        register_investigation_tools()

    if get_tool("evaluate_alerts") is None:
        from copilot.tools.alerts import register_alert_tools

        register_alert_tools()

    if get_tool("create_commitment") is None:
        from copilot.tools.commitments import register_commitment_tools

        register_commitment_tools()

    if get_tool("create_bucket") is None:
        from copilot.tools.buckets import register_bucket_tools

        register_bucket_tools()

    if get_tool("get_calendar") is None:
        from copilot.tools.calendar import register_calendar_tools

        register_calendar_tools()

    if get_tool("assess_investment_readiness") is None:
        from copilot.tools.readiness import register_readiness_tools

        register_readiness_tools()

    if get_tool("plan_contributions") is None:
        from copilot.tools.contributions import register_contributions_tools

        register_contributions_tools()

    if get_tool("list_memories") is None:
        from copilot.tools.memory import register_memory_tools

        register_memory_tools()

    if get_tool("affordability_check") is None:
        from copilot.skills.tools import register_skill_tools

        register_skill_tools()

    if get_tool("design_experiment") is None:
        from copilot.tools.experiments import register_experiment_tools

        register_experiment_tools()

    if get_tool("record_payment_event") is None:
        from copilot.tools.capture import register_capture_tools

        register_capture_tools()

    if get_tool("aa_status") is None:
        from copilot.tools.aa import register_aa_tools

        register_aa_tools()

    if get_tool("list_adjustments") is None:
        from copilot.tools.adjustments import register_adjustment_tools

        register_adjustment_tools()

    if get_tool("list_offers") is None:
        from copilot.tools.challenges import register_challenge_tools

        register_challenge_tools()

    if get_tool("get_user_progress") is None:
        from copilot.tools.rewards import register_rewards_tools

        register_rewards_tools()


def _get_exec_ctx(
    state: AgentState,
    config: RunnableConfig | None = None,
    actor: Actor = "agent",
) -> tuple[ExecutionContext, sqlite3.Connection]:
    """
    Resolve ExecutionContext and sqlite connection from config or state.
    """
    ensure_tools_registered()
    configurable = config.get("configurable", {}) if config else {}
    ctx = configurable.get("exec_ctx")
    if ctx is not None:
        if ctx.actor != actor:
            ctx = ExecutionContext(
                conn=ctx.conn,
                user_id=ctx.user_id,
                run_id=ctx.run_id,
                policy=ctx.policy,
                clock=ctx.clock,
                actor=actor,
            )
        return ctx, ctx.conn

    conn = configurable.get("conn")
    if conn is None:
        raise ValueError("Neither 'exec_ctx' nor 'conn' provided in RunnableConfig.")

    policy: PolicySettings = configurable.get("policy")
    if policy is None:
        policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")

    clock_dt: datetime | None = None
    if state.get("clock"):
        try:
            clock_dt = datetime.fromisoformat(state["clock"].replace("Z", "+00:00"))
        except Exception:
            clock_dt = None

    ctx = ExecutionContext(
        conn=conn,
        user_id=state.get("user_id", "u_default"),
        run_id=state.get("run_id", "run_default"),
        policy=policy,
        clock=clock_dt,
        actor=actor,
    )
    return ctx, conn


# -------------------------------------------------------------------------------------------------
# 1. Ingest Node
# -------------------------------------------------------------------------------------------------


def ingest_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Ingest statements from account aggregator / mock connector.
    Calls tool: ingest_statements
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = []

    try:
        ctx, conn = _get_exec_ctx(state, config, actor="agent")
        consent_id = state.get("consent_id")

        if not consent_id:
            counts = {
                "fetched": 0,
                "inserted": 0,
                "skipped_existing": 0,
                "duplicates_flagged": 0,
            }
            entry: TraceEntry = {
                "node": "ingest",
                "started_at": start_iso,
                "ended_at": now_utc(),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tools_called": [],
                "counts": counts,
                "status": "skipped",
                "error": None,
            }
            return {
                "node_results": {"ingest": counts},
                "trace": [entry],
            }

        tools_called.append("ingest_statements")
        account_id = state.get("account_id")
        if not account_id:
            row = conn.execute(
                "SELECT id FROM accounts WHERE user_id = ? LIMIT 1", (ctx.user_id,)
            ).fetchone()
            account_id = row[0] if row else "a1"
        params: dict[str, Any] = {"consent_id": consent_id, "account_id": account_id}

        result = execute_tool(ctx, "ingest_statements", params)
        if not result.ok:
            err_msg = result.error.message if result.error else "Failed to ingest statements"
            entry_err: TraceEntry = {
                "node": "ingest",
                "started_at": start_iso,
                "ended_at": now_utc(),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tools_called": tools_called,
                "counts": {"inserted": 0},
                "status": "error",
                "error": err_msg,
            }
            return {
                "status": "failed",
                "error": {"node": "ingest", "message": err_msg},
                "trace": [entry_err],
            }

        data = result.data
        counts = {
            "fetched": getattr(data, "fetched", 0),
            "inserted": getattr(data, "inserted", 0),
            "skipped_existing": getattr(data, "skipped_existing", 0),
            "duplicates_flagged": getattr(data, "duplicates_flagged", 0),
        }
        entry = {
            "node": "ingest",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"ingest": counts},
            "trace": [entry],
        }
    except Exception as exc:
        entry_exc: TraceEntry = {
            "node": "ingest",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"inserted": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "ingest", "message": str(exc)},
            "trace": [entry_exc],
        }


# -------------------------------------------------------------------------------------------------
# 2. Categorize Node
# -------------------------------------------------------------------------------------------------


def categorize_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Categorize uncategorized transactions via rules, overrides, cache, and LLM.
    Pending items are placed in the review queue as clarifications without blocking.
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = ["categorize_batch"]

    try:
        ctx, conn = _get_exec_ctx(state, config, actor="agent")

        cfg_settings = load_settings()
        rules_path = PROJECT_ROOT / getattr(
            cfg_settings, "categorization_rules_path", "config/categorization_rules.yaml"
        )
        aliases_path = PROJECT_ROOT / getattr(
            cfg_settings, "merchant_aliases_path", "config/merchant_aliases.yaml"
        )

        configurable = config.get("configurable", {}) if config else {}
        llm = configurable.get("llm") or FakeLLMClient([])

        rules = load_rules(rules_path) if rules_path.exists() else []
        aliases = load_aliases(aliases_path) if aliases_path.exists() else {}

        model_name = getattr(cfg_settings, "gemini_model", "gemini-1.5-flash")
        prompt_version = "v1"

        report = run_categorization_pipeline(
            ctx=ctx,
            llm=llm,
            rules=rules,
            aliases=aliases,
            model_name=model_name,
            prompt_version=prompt_version,
            settings=cfg_settings,
        )

        # Retrieve any transactions marked for user review
        review_rows = conn.execute(
            """
            SELECT id, merchant_raw, merchant_normalized,
                   amount_paise, direction, category_confidence
            FROM transactions
            WHERE user_id = ? AND needs_review = 1
            ORDER BY occurred_at DESC
            """,
            (ctx.user_id,),
        ).fetchall()

        pending_reviews = [
            {
                "transaction_id": row[0],
                "merchant_raw": row[1],
                "merchant_normalized": row[2],
                "amount_paise": row[3],
                "direction": row[4],
                "confidence": row[5],
            }
            for row in review_rows
        ]

        counts = {
            "considered": report.considered,
            "updated": report.updated,
            "review_queue": report.review_queue,
            "llm_calls": report.llm_calls,
        }
        entry: TraceEntry = {
            "node": "categorize",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"categorize": counts},
            "pending_reviews": pending_reviews,
            "trace": [entry],
        }
    except Exception as exc:
        entry_err: TraceEntry = {
            "node": "categorize",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"updated": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "categorize", "message": str(exc)},
            "trace": [entry_err],
        }


# -------------------------------------------------------------------------------------------------
# 3. Analyze Node
# -------------------------------------------------------------------------------------------------


def analyze_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Run transfer detection, recurring detection, budget checks, forecasting, and anomaly detection.
    Produces deterministic findings for advice.
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = []

    try:
        ctx, _ = _get_exec_ctx(state, config, actor="agent")
        year = state.get("year", 2026)
        month = state.get("month", 10)

        # 1. detect_transfers
        tools_called.append("detect_transfers")
        res_transfers = execute_tool(ctx, "detect_transfers", {})
        transfers_count = getattr(res_transfers.data, "links_created", 0) if res_transfers.ok else 0

        # 2. detect_recurring
        tools_called.append("detect_recurring")
        res_recurring = execute_tool(ctx, "detect_recurring", {})
        recurring_count = (
            getattr(res_recurring.data, "series_detected", 0) if res_recurring.ok else 0
        )

        # 3. check_budgets
        tools_called.append("check_budgets")
        res_budgets = execute_tool(ctx, "check_budgets", {"year": year, "month": month})
        budgets_list = []
        if res_budgets.ok and res_budgets.data:
            statuses = getattr(res_budgets.data, "statuses", []) or getattr(
                res_budgets.data, "budgets", []
            )
            budgets_list = [b.model_dump(mode="json") for b in statuses]

        # 4. forecast_month
        tools_called.append("forecast_month")
        res_forecast = execute_tool(ctx, "forecast_month", {"year": year, "month": month})
        forecast_data = (
            res_forecast.data.model_dump(mode="json")
            if (res_forecast.ok and res_forecast.data)
            else {}
        )

        # 5. detect_anomalies
        tools_called.append("detect_anomalies")
        res_anomalies = execute_tool(ctx, "detect_anomalies", {})
        anomalies_list = getattr(res_anomalies.data, "anomalies", []) if res_anomalies.ok else []

        analysis_bundle = {
            "transfers_linked": transfers_count,
            "recurring_count": recurring_count,
            "budgets": budgets_list,
            "forecast": forecast_data,
            "anomalies": anomalies_list,
        }

        # Build typed findings
        findings = build_findings_from_analysis(year, month, analysis_bundle)
        findings_json = [f.model_dump(mode="json") for f in findings]

        counts = {
            "transfers_linked": transfers_count,
            "recurring_detected": recurring_count,
            "budgets_evaluated": len(budgets_list),
            "anomalies_detected": len(anomalies_list),
            "findings_generated": len(findings),
        }
        entry: TraceEntry = {
            "node": "analyze",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"analyze": counts},
            "findings": findings_json,
            "trace": [entry],
        }
    except Exception as exc:
        entry_err: TraceEntry = {
            "node": "analyze",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"findings_generated": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "analyze", "message": str(exc)},
            "trace": [entry_err],
        }


# -------------------------------------------------------------------------------------------------
# 4. Advise Node
# -------------------------------------------------------------------------------------------------


def advise_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Draft advice based strictly on validated findings.
    Calls tool: draft_advice
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = ["draft_advice"]

    try:
        ctx, _ = _get_exec_ctx(state, config, actor="agent")
        raw_findings = state.get("findings") or []
        findings = [Finding.model_validate(f) for f in raw_findings]

        if not findings:
            counts = {"findings_count": 0, "advice_drafted_count": 0}
            entry: TraceEntry = {
                "node": "advise",
                "started_at": start_iso,
                "ended_at": now_utc(),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tools_called": tools_called,
                "counts": counts,
                "status": "ok",
                "error": None,
            }
            return {
                "node_results": {"advise": counts},
                "draft_advice": [],
                "trace": [entry],
            }

        result = execute_tool(ctx, "draft_advice", {"findings": [f.model_dump() for f in findings]})
        if not result.ok:
            err_msg = result.error.message if result.error else "Failed to draft advice"
            entry_err: TraceEntry = {
                "node": "advise",
                "started_at": start_iso,
                "ended_at": now_utc(),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tools_called": tools_called,
                "counts": {"advice_drafted_count": 0},
                "status": "error",
                "error": err_msg,
            }
            return {
                "status": "failed",
                "error": {"node": "advise", "message": err_msg},
                "trace": [entry_err],
            }

        drafts = getattr(result.data, "advice_items", [])
        counts = {
            "findings_count": len(findings),
            "advice_drafted_count": len(drafts),
        }
        entry = {
            "node": "advise",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"advise": counts},
            "draft_advice": drafts,
            "trace": [entry],
        }
    except Exception as exc:
        entry_err = {
            "node": "advise",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"advice_drafted_count": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "advise", "message": str(exc)},
            "trace": [entry_err],
        }


# -------------------------------------------------------------------------------------------------
# 5. Review Node (Human-in-the-loop interrupt)
# -------------------------------------------------------------------------------------------------


def review_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Human-in-the-loop review node.
    If draft advice exists and decisions are not pre-supplied, interrupts execution.
    When resumed with decisions, calls decide_advice tool as 'user'.
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = []

    try:
        drafts = state.get("draft_advice") or []
        decisions = state.get("review_decisions")

        # Interrupt if drafts exist and no decisions have been supplied yet
        if decisions is None and drafts:
            resume_data = interrupt(
                {
                    "message": "Review pending advice drafts",
                    "drafts": drafts,
                }
            )

            # Extract decisions from resume command
            if isinstance(resume_data, dict) and "decisions" in resume_data:
                decisions = resume_data["decisions"]
            elif isinstance(resume_data, list):
                decisions = resume_data
            elif isinstance(resume_data, dict):
                decisions = [{"advice_id": k, "decision": v} for k, v in resume_data.items()]
            else:
                decisions = []

        ctx_user, _ = _get_exec_ctx(state, config, actor="user")

        approved = 0
        rejected = 0
        decided_list = []

        for d in decisions or []:
            aid = d.get("advice_id")
            dec = d.get("decision", "approved")
            if aid:
                tools_called.append("decide_advice")
                res = execute_tool(ctx_user, "decide_advice", {"advice_id": aid, "decision": dec})
                if res.ok:
                    if dec == "approved":
                        approved += 1
                    else:
                        rejected += 1
                    decided_list.append({"advice_id": aid, "decision": dec, "status": dec})

        counts = {
            "decisions_applied": approved + rejected,
            "approved": approved,
            "rejected": rejected,
        }
        entry: TraceEntry = {
            "node": "review",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": list(set(tools_called)),
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"review": counts},
            "decided_advice": decided_list,
            "trace": [entry],
        }
    except GraphInterrupt:
        raise
    except Exception as exc:
        entry_err: TraceEntry = {
            "node": "review",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"decisions_applied": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "review", "message": str(exc)},
            "trace": [entry_err],
        }


# -------------------------------------------------------------------------------------------------
# 6. Finalize Node
# -------------------------------------------------------------------------------------------------


def finalize_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Capture the overall financial state overview snapshot and finalize run.
    Calls tool: get_financial_state
    """
    t0 = time.perf_counter()
    start_iso = now_utc()
    tools_called: list[str] = ["get_financial_state"]

    try:
        ctx, _ = _get_exec_ctx(state, config, actor="agent")

        result = execute_tool(ctx, "get_financial_state", {})
        fin_state = result.data.model_dump(mode="json") if (result.ok and result.data) else {}

        counts = {
            "accounts_count": len(fin_state.get("accounts", [])),
            "budgets_count": len(fin_state.get("budgets", [])),
            "review_queue_size": fin_state.get("review_queue_size", 0),
        }
        entry: TraceEntry = {
            "node": "finalize",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": counts,
            "status": "ok",
            "error": None,
        }
        return {
            "node_results": {"finalize": counts},
            "financial_state": fin_state,
            "status": "completed",
            "trace": [entry],
        }
    except Exception as exc:
        entry_err: TraceEntry = {
            "node": "finalize",
            "started_at": start_iso,
            "ended_at": now_utc(),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tools_called": tools_called,
            "counts": {"accounts_count": 0},
            "status": "error",
            "error": str(exc),
        }
        return {
            "status": "failed",
            "error": {"node": "finalize", "message": str(exc)},
            "trace": [entry_err],
        }


# -------------------------------------------------------------------------------------------------
# 7. Error Node
# -------------------------------------------------------------------------------------------------


def error_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Error node: audits run failure and exits cleanly.
    """
    t0 = time.perf_counter()
    start_iso = now_utc()

    error_info = state.get("error") or {"message": "Unknown workflow error"}
    err_msg = str(error_info.get("message", "Workflow failure"))
    failing_node = error_info.get("node", "unknown")

    try:
        ctx, conn = _get_exec_ctx(state, config, actor="agent")
        record_event(
            conn,
            user_id=state.get("user_id", "u_unknown"),
            actor="agent",
            event_type="run_failed",
            reason=f"Workflow failed at node '{failing_node}': {err_msg}",
            run_id=state.get("run_id", "run_unknown"),
            entity_type="run",
            entity_id=state.get("run_id", "run_unknown"),
            metadata=error_info,
            clock=ctx.clock,
        )
    except Exception:
        # Failure audit should never crash the error handler
        pass

    entry: TraceEntry = {
        "node": "error",
        "started_at": start_iso,
        "ended_at": now_utc(),
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "tools_called": [],
        "counts": {"errors": 1},
        "status": "error",
        "error": err_msg,
    }
    return {
        "status": "failed",
        "trace": [entry],
    }
