"""
Contribution Planning and Trade-off Analysis Tools (PLAN_PHASE3 Section 5.7 & Stage 3.7).

Provides compute/read tools for:
- plan_contributions: evaluates monthly waterfall allocation and generates alternatives
- compare_tradeoffs: evaluates and compares metrics across scenario alternatives
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from copilot.core.contributions import compare_tradeoffs, plan_contributions
from copilot.core.timeutil import IST, now_utc
from copilot.models.phase3 import ContributionPlan, TradeoffResult
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. Tool Input / Output Models
# -------------------------------------------------------------------------------------------------
class PlanContributionsInput(ToolInput):
    """Input for waterfall contribution planning."""

    horizon_months: int | None = Field(
        default=None,
        ge=1,
        le=24,
        description="Horizon in months (1-24). Defaults to 6.",
    )
    start_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Start date in YYYY-MM-DD format. Defaults to current date.",
    )
    waterfall_order: list[str] | None = Field(
        default=None,
        description="Optional custom waterfall priority order.",
    )


class PlanContributionsOutput(ToolOutput):
    """Output containing waterfall contribution plan and alternatives."""

    plan: ContributionPlan


class CompareTradeoffsInput(ToolInput):
    """Input for trade-off analysis across alternatives."""

    alternatives: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=3,
        description="List of up to 3 scenario alternatives to compare.",
    )
    horizon_months: int = Field(
        default=12,
        ge=1,
        le=24,
        description="Horizon in months for projection comparison (1-24). Defaults to 12.",
    )
    start_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Start date in YYYY-MM-DD format. Defaults to current date.",
    )


class CompareTradeoffsOutput(ToolOutput):
    """Output containing comparative trade-off results and constraint satisfaction."""

    result: TradeoffResult


# -------------------------------------------------------------------------------------------------
# 2. Tool Handlers
# -------------------------------------------------------------------------------------------------
def plan_contributions_handler(ctx: "ExecutionContext", **kwargs) -> PlanContributionsOutput:
    params = PlanContributionsInput.model_validate(kwargs)

    if isinstance(ctx.clock, datetime):
        now_dt = ctx.clock
    elif hasattr(ctx.clock, "now"):
        now_dt = ctx.clock.now()
    else:
        now_dt = now_utc()

    today_str = params.start_date or now_dt.astimezone(IST).strftime("%Y-%m-%d")

    plan = plan_contributions(
        conn=ctx.conn,
        user_id=ctx.user_id,
        horizon_months=params.horizon_months,
        start_date=today_str,
        waterfall_order=params.waterfall_order,
    )

    return PlanContributionsOutput(plan=plan)


def compare_tradeoffs_handler(ctx: "ExecutionContext", **kwargs) -> CompareTradeoffsOutput:
    params = CompareTradeoffsInput.model_validate(kwargs)

    if isinstance(ctx.clock, datetime):
        now_dt = ctx.clock
    elif hasattr(ctx.clock, "now"):
        now_dt = ctx.clock.now()
    else:
        now_dt = now_utc()

    today_str = params.start_date or now_dt.astimezone(IST).strftime("%Y-%m-%d")
    alts = (
        params.alternatives
        if params.alternatives
        else [
            {
                "name": "Current Plan",
                "description": "Baseline plan without modifications",
                "scenarios": [],
            }
        ]
    )

    result = compare_tradeoffs(
        conn=ctx.conn,
        user_id=ctx.user_id,
        alternatives=alts,
        horizon_months=params.horizon_months,
        start_date=today_str,
    )

    return CompareTradeoffsOutput(result=result)


# -------------------------------------------------------------------------------------------------
# 3. Tool Specifications & Registration
# -------------------------------------------------------------------------------------------------
def register_contributions_tools(
    register_fn: Callable[[ToolSpec], None] = register,
) -> None:
    """Register contribution planning and trade-off analysis tools."""
    register_fn(
        ToolSpec(
            name="plan_contributions",
            description=(
                "Compute monthly waterfall contribution plan and generate "
                "options when contributions do not fit"
            ),
            input_model=PlanContributionsInput,
            output_model=PlanContributionsOutput,
            side_effect=SideEffect.READ,
            handler=plan_contributions_handler,
        )
    )
    register_fn(
        ToolSpec(
            name="compare_tradeoffs",
            description=(
                "Compare up to 3 scenario alternatives assessing cash flow, "
                "goal completions, and constraint satisfaction"
            ),
            input_model=CompareTradeoffsInput,
            output_model=CompareTradeoffsOutput,
            side_effect=SideEffect.READ,
            handler=compare_tradeoffs_handler,
        )
    )
