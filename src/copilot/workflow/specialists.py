"""
Specialist roles, tool isolation, and execution (PLAN_PHASE3 Section 5.13).

Architecture Invariants:
1. Each specialist can call ONLY its allowed tool subset.
2. Any attempt outside the allowed subset is rejected and audited as `specialist_tool_rejected`.
3. All tool calls MUST pass through `execute_tool(ctx, tool_name, arguments_dict)`.
4. Transient tool errors allow at most one retry.
5. Specialists return typed `SpecialistReport`.
"""

import logging
import time
import uuid
from typing import Any

from copilot.audit.events import record_event
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.phase3 import SpecialistReport, SubQuestion
from copilot.ops.tracing import span
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

logger = logging.getLogger(__name__)

# Allowed tool subsets per specialist (PLAN_PHASE3 Section 5.13)
SPECIALIST_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "CashflowAgent": {
        "get_calendar",
        "get_commitment_status",
        "check_commitment_coverage",
        "suggest_commitments",
        "forecast_month",
        "forecast_category_spend",
        "run_whatif",
        "compare_options",
    },
    "GoalsAgent": {
        "list_goals",
        "get_goal_progress",
        "evaluate_goal_impact",
        "list_buckets",
        "get_bucket_status",
        "get_allocation_summary",
        "compare_tradeoffs",
    },
    "ReadinessAgent": {
        "assess_investment_readiness",
        "plan_contributions",
    },
    "BehaviourAgent": {
        "list_memories",
        "explain_memory",
        "detect_anomalies",
        "investigate_anomaly",
        "explain_change",
        "investigate_month_change",
    },
}

DOMAIN_TO_ROLE: dict[str, str] = {
    "cashflow": "CashflowAgent",
    "goals": "GoalsAgent",
    "readiness": "ReadinessAgent",
    "behaviour": "BehaviourAgent",
}


def execute_specialist_tool(
    ctx: ExecutionContext,
    role: str,
    tool_name: str,
    args: dict[str, Any],
) -> Any:
    """
    Execute a tool call for a specialist, strictly enforcing tool allowlists.
    If the tool is outside the specialist's allowlist:
      - Audits `specialist_tool_rejected`
      - Raises PermissionError
    Retries once on transient errors.
    """
    ensure_tools_registered()
    allowed = SPECIALIST_TOOL_ALLOWLIST.get(role, set())
    if tool_name not in allowed:
        # Security rejection & audit logging (PLAN_PHASE3 Section 5.13 & Rule 13)
        record_event(
            conn=ctx.conn,
            user_id=ctx.user_id,
            actor="agent",
            event_type="specialist_tool_rejected",
            reason=f"Tool '{tool_name}' is outside allowed subset for role '{role}'",
            run_id=ctx.run_id,
            metadata={"role": role, "tool_name": tool_name, "allowed_tools": list(allowed)},
        )
        raise PermissionError(
            f"Specialist '{role}' attempted to call forbidden tool '{tool_name}'. "
            f"Allowed: {sorted(allowed)}"
        )


    # First attempt
    res = execute_tool(ctx, tool_name, args)
    if not res.ok:
        # Check if transient / retryable
        is_retryable = getattr(getattr(res, "error", None), "retryable", False)
        if is_retryable:
            logger.info("Transient error calling tool %s in %s; retrying once", tool_name, role)
            res = execute_tool(ctx, tool_name, args)

    return res


def _to_dict(val: Any) -> Any:
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, dict):
        return {k: _to_dict(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_dict(x) for x in val]
    return val


def _run_specialist_core(
    role: str,
    subquestion: SubQuestion,
    ctx: ExecutionContext,
    task_id: str,
    step_budget: int = 5,
) -> SpecialistReport:
    t0 = time.perf_counter()
    findings: list[dict[str, Any]] = []
    gaps: list[str] = []
    status: str = "ok"
    error_code: str | None = None

    params = dict(subquestion.parameters)
    kind = subquestion.question_kind

    try:
        if role == "CashflowAgent":
            if kind == "calendar_coverage":
                horizon = int(params.get("horizon_days", 60))
                cal_res = execute_specialist_tool(
                    ctx, role, "get_calendar", {"horizon_days": horizon}
                )
                cov_res = execute_specialist_tool(
                    ctx, role, "check_commitment_coverage", {"horizon_days": horizon}
                )
                if cal_res.ok and cal_res.data:
                    findings.append({
                        "metric": "calendar_coverage",
                        "value": _to_dict(cal_res.data),
                        "confidence": "high",
                        "evidence": f"get_calendar(horizon_days={horizon})",
                    })
                else:
                    gaps.append("Could not compute calendar cashflow projection")

                if cov_res.ok and cov_res.data:
                    findings.append({
                        "metric": "commitment_coverage",
                        "value": _to_dict(cov_res.data),
                        "confidence": "high",
                        "evidence": f"check_commitment_coverage(window={horizon})",
                    })
                else:
                    gaps.append("Could not evaluate commitment coverage")

            elif kind == "scenario_cashflow":
                whatif_params = {
                    "scenario": {
                        "kind": params.get("kind", "add_spend"),
                        "amount_paise": params.get("amount_paise", 0),
                        "category_id": params.get("category_id"),
                        "date": params.get("date"),
                    }
                }
                res = execute_specialist_tool(ctx, role, "run_whatif", whatif_params)
                if res.ok and res.data:
                    findings.append({
                        "metric": "scenario_cashflow",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": f"run_whatif({whatif_params['scenario']['kind']})",
                    })
                else:
                    gaps.append("Could not simulate cashflow scenario")

            elif kind == "contribution_fit":
                res = execute_specialist_tool(
                    ctx, role, "check_commitment_coverage", {"horizon_days": 60}
                )
                if res.ok and res.data:
                    findings.append({
                        "metric": "contribution_fit",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "check_commitment_coverage(horizon_days=60)",
                    })
                else:
                    gaps.append("Could not evaluate cashflow contribution fit")

            elif kind == "forecast":
                res = execute_specialist_tool(ctx, role, "forecast_month", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "forecast",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "forecast_month",
                    })
                else:
                    gaps.append("Could not forecast month spend")

            elif kind == "commitment_status":
                res = execute_specialist_tool(ctx, role, "get_commitment_status", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "commitments",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "get_commitment_status",
                    })
                else:
                    gaps.append("Could not retrieve commitment status")

            else:
                gaps.append(f"Unhandled cashflow question kind: {kind}")

        elif role == "GoalsAgent":
            if kind == "goal_impact":
                amount = int(params.get("amount_paise", 0))
                res = execute_specialist_tool(
                    ctx, role, "evaluate_goal_impact", {"amount_paise": amount}
                )
                if res.ok and res.data:
                    findings.append({
                        "metric": "goal_impact",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": f"evaluate_goal_impact(amount={amount})",
                    })
                else:
                    gaps.append("Could not evaluate goal impact")

            elif kind == "scenario_goals":
                amount = int(params.get("amount_paise", 0))
                res = execute_specialist_tool(
                    ctx, role, "evaluate_goal_impact", {"amount_paise": amount}
                )
                if res.ok and res.data:
                    findings.append({
                        "metric": "scenario_goals",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "evaluate_goal_impact",
                    })
                else:
                    gaps.append("Could not simulate goal scenario impact")


            elif kind == "bucket_allocation":
                res = execute_specialist_tool(ctx, role, "list_buckets", {})
                alloc_res = execute_specialist_tool(ctx, role, "get_allocation_summary", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "buckets",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "list_buckets",
                    })
                if alloc_res.ok and alloc_res.data:
                    findings.append({
                        "metric": "allocation_summary",
                        "value": _to_dict(alloc_res.data),
                        "confidence": "high",
                        "evidence": "get_allocation_summary",
                    })
                if not findings:
                    gaps.append("Could not retrieve bucket allocations")

            elif kind == "tradeoff_analysis":
                res = execute_specialist_tool(ctx, role, "compare_tradeoffs", params)
                if res.ok and res.data:
                    findings.append({
                        "metric": "tradeoff_analysis",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "compare_tradeoffs",
                    })
                else:
                    gaps.append("Could not compare tradeoffs")

            elif kind == "goal_progress":
                gid = params.get("goal_id")
                if gid:
                    res = execute_specialist_tool(ctx, role, "get_goal_progress", {"goal_id": gid})
                else:
                    res = execute_specialist_tool(ctx, role, "list_goals", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "goal_progress",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "get_goal_progress",
                    })
                else:
                    gaps.append("Could not retrieve goal progress")

            else:
                gaps.append(f"Unhandled goals question kind: {kind}")

        elif role == "ReadinessAgent":
            if kind == "readiness_assessment":
                res = execute_specialist_tool(ctx, role, "assess_investment_readiness", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "readiness_level",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "assess_investment_readiness",
                    })
                else:
                    gaps.append("Could not assess investment readiness")

            elif kind == "contribution_plan":
                target_paise = int(params.get("target_monthly_paise", 0))
                res = execute_specialist_tool(
                    ctx, role, "plan_contributions", {"target_monthly_paise": target_paise}
                )

                if res.ok and res.data:
                    findings.append({
                        "metric": "contribution_plan",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": f"plan_contributions(target_monthly_paise={target_paise})",
                    })
                else:
                    gaps.append("Could not generate contribution plan")

            else:
                gaps.append(f"Unhandled readiness question kind: {kind}")

        elif role == "BehaviourAgent":
            if kind in ("seasonal_patterns", "memory_retrieval"):
                res = execute_specialist_tool(ctx, role, "list_memories", {"status": "active"})
                if res.ok and res.data:
                    findings.append({
                        "metric": "active_memories",
                        "value": _to_dict(res.data),
                        "confidence": "medium",
                        "evidence": "list_memories(status=active)",
                    })
                else:
                    gaps.append("Could not retrieve active memories")

            elif kind == "anomaly_check":
                res = execute_specialist_tool(ctx, role, "detect_anomalies", {})
                if res.ok and res.data:
                    findings.append({
                        "metric": "anomalies",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "detect_anomalies",
                    })
                else:
                    gaps.append("Could not detect anomalies")

            elif kind == "habit_investigation":
                res = execute_specialist_tool(ctx, role, "explain_change", params)
                if res.ok and res.data:
                    findings.append({
                        "metric": "habit_investigation",
                        "value": _to_dict(res.data),
                        "confidence": "high",
                        "evidence": "explain_change",
                    })
                else:
                    gaps.append("Could not investigate habit change")

            else:
                gaps.append(f"Unhandled behaviour question kind: {kind}")


    except PermissionError as p_err:
        status = "failed"
        error_code = "permission_denied"
        gaps.append(f"Specialist rejected: {str(p_err)}")
    except Exception as exc:
        logger.exception("Error executing specialist %s: %s", role, exc)
        status = "failed"
        error_code = "specialist_execution_error"
        gaps.append(f"Specialist error: {str(exc)}")

    if gaps and findings:
        status = "partial"
    elif gaps and not findings:
        status = "failed" if not error_code else status

    duration_ms = int((time.perf_counter() - t0) * 1000)
    created_at = to_utc_iso(now_utc(ctx.clock))

    return SpecialistReport(
        id=f"sr_{uuid.uuid4().hex[:12]}",
        user_id=ctx.user_id,
        task_id=task_id,
        agent_role=role,
        sub_question_json=subquestion.model_dump(),
        status=status,  # type: ignore[arg-type]
        findings_json=findings,
        gaps_json=gaps,
        error_code=error_code,
        duration_ms=duration_ms,
        created_at=created_at,
    )


def run_specialist(
    role: str,
    subquestion: SubQuestion,
    ctx: ExecutionContext,
    task_id: str,
    step_budget: int = 5,
) -> SpecialistReport:
    """
    Execute a specialist's tasks for a sub-question within its isolated state slice.
    Traced with span kind='specialist'.
    """
    with span(
        kind="specialist",
        name=role,
        attrs={
            "role": role,
            "domain": subquestion.domain,
            "question_kind": subquestion.question_kind,
        },
        user_id=ctx.user_id,
        trace_id=task_id,
        conn=ctx.conn,
    ) as sp:
        report = _run_specialist_core(role, subquestion, ctx, task_id, step_budget)
        if report.status != "ok":
            sp.status = "error"
            sp.error_code = report.error_code or "specialist_failed"
        return report
