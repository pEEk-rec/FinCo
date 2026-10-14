"""
Deterministic Planner (PLAN_PHASE2 Section 5.3 & Stage 2.8).

Uses config/plan_templates.yaml to map each IntentType to the minimal ordered
tool list and argument bindings from the intent.
Always available; baseline for LLM-off mode and fallback when LLM plans fail validation.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from copilot.config.phase2 import PlanTemplatesConfig, load_plan_templates
from copilot.core.timeutil import IST, month_bounds, previous_months
from copilot.models.agentic import Intent, Plan, PlanStep


class DeterministicPlanner:
    """Produces minimal canonical execution plans using configuration templates."""

    def __init__(self, config: PlanTemplatesConfig | None = None) -> None:
        self.config = config or load_plan_templates()

    def propose(
        self,
        task_id: str,
        user_id: str,
        intent: Intent,
        state_projection: dict[str, Any] | None = None,
        tool_catalogue: list[dict[str, Any]] | None = None,
    ) -> Plan:
        """Generate a deterministic plan for the given intent."""
        projection = state_projection or {}
        clock_str = projection.get("clock")
        now_dt = datetime.fromisoformat(clock_str) if clock_str else datetime.now(UTC)

        # Resolve year & month
        year = intent.year
        month = intent.month
        if (year is None or month is None) and intent.period:
            try:
                parts = intent.period.split("-")
                if len(parts) == 2:
                    year = int(parts[0])
                    month = int(parts[1])
            except (ValueError, IndexError):
                pass

        if year is None or month is None:
            # Default to clock/current IST month
            ist_now = now_dt.astimezone(IST)
            year = year or ist_now.year
            month = month or ist_now.month

        # A relative span ("last 3 months", "this week") is not one month. Tools that take a
        # single period get the current month; a span of months is planned month by month.
        one_month = bool(intent.period and re.fullmatch(r"\d{4}-\d{2}", intent.period))
        period_str = intent.period if one_month else f"{year:04d}-{month:02d}"
        span = (
            re.fullmatch(r"last_(\d+)_months", intent.period or "")
            if intent.type == "summarize_period"
            else None
        )
        span_months = previous_months(year, month, min(int(span.group(1)), 6)) if span else []

        # Fetch plan template for intent type
        template = self.config.templates.get(intent.type)
        if template is None:
            # Fallback to summarize_period if unknown
            template = self.config.templates.get("summarize_period")

        steps: list[PlanStep] = []
        if template:
            for step_tpl in template.default_steps:
                tool_name = step_tpl.tool_name
                args: dict[str, Any] = {}
                variants: list[dict[str, Any]] | None = None

                if tool_name in (
                    "aggregate_spend_by_category",
                    "check_budgets",
                    "forecast_month",
                    "get_financial_state",
                ):
                    args = {"year": year, "month": month}
                    if tool_name == "aggregate_spend_by_category" and span_months:
                        variants = [{"year": int(p[:4]), "month": int(p[5:])} for p in span_months]

                elif tool_name == "get_transactions":
                    start_utc, end_utc = month_bounds(year, month)
                    args = {
                        "start_utc": start_utc,
                        "end_utc": end_utc,
                    }
                    if intent.category_id:
                        args["category_id"] = intent.category_id

                elif tool_name == "forecast_category_spend":
                    args = {
                        "year": year,
                        "month": month,
                        "category_id": intent.category_id or "uncategorized",
                    }

                elif tool_name == "get_balance":
                    args = {}

                elif tool_name == "detect_anomalies":
                    args = {}

                elif tool_name == "list_goals":
                    args = {}

                elif tool_name == "list_alerts":
                    args = {"period": period_str}

                elif tool_name == "evaluate_goal_impact":
                    args = {
                        "decision_paise": intent.amount_paise or 0,
                    }
                    if intent.category_id:
                        args["category_id"] = intent.category_id

                elif tool_name in ("run_whatif", "compare_options"):
                    if not intent.amount_paise or not intent.category_id:
                        # A scenario needs both an amount and a category; never invent either.
                        continue
                    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
                    scenario = {
                        "kind": "reduce_spend"
                        if intent.type == "whatif_reduce_spend"
                        else "add_spend",
                        "category_id": intent.category_id,
                        "amount_paise": intent.amount_paise or 0,
                        "start_month": f"{next_year:04d}-{next_month:02d}",
                        "recurring": True,
                        "months": min(intent.horizon_months or 3, 6),
                        "goal_id": intent.goal_id,
                    }
                    if tool_name == "compare_options":
                        args = {"scenarios": [scenario], "horizon_months": scenario["months"]}
                    else:
                        args = {"scenario": scenario, "horizon_months": scenario["months"]}

                elif tool_name == "investigate_anomaly":
                    anom_id = projection.get("anomaly_id") or "anom_001"
                    args = {"anomaly_id": anom_id}

                elif tool_name == "explain_change":
                    args = {"period": period_str}
                    if intent.category_id:
                        args["category_id"] = intent.category_id

                for step_args in variants or [args]:
                    steps.append(
                        PlanStep(
                            id=f"step_{uuid.uuid4().hex[:8]}",
                            task_id=task_id,
                            user_id=user_id,
                            seq=len(steps),
                            tool_name=tool_name,
                            args=step_args,
                            rationale=step_tpl.rationale or f"Deterministic step for {intent.type}",
                            proposed_by="deterministic",
                            status="proposed",
                        )
                    )

        return Plan(task_id=task_id, steps=steps)
