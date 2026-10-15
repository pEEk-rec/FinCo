"""
Financial Calendar Tools and Handlers (PLAN_PHASE3 Section 5.4 & Stage 3.5).

Provides read tools for:
- Projecting daily cash flow, running balances, and commitment coverage (get_calendar)
- Evaluating commitment coverage and liquidity risk in a horizon (check_commitment_coverage)
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from copilot.core.calendar import build_calendar, load_calendar_config
from copilot.core.timeutil import IST, now_utc
from copilot.models.phase3 import Calendar, Coverage
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. get_calendar (READ)
# -------------------------------------------------------------------------------------------------
class GetCalendarInput(ToolInput):
    """Input parameters for generating a financial calendar projection."""

    horizon_days: int = Field(default=60, ge=1, le=180)
    min_buffer_paise: int | None = Field(default=None, ge=0)
    today: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    scenario: dict[str, Any] | None = None


class GetCalendarOutput(ToolOutput):
    """Financial calendar projection with daily running balances and coverage."""

    calendar: Calendar


def get_calendar_handler(ctx: "ExecutionContext", **kwargs) -> GetCalendarOutput:
    params = GetCalendarInput.model_validate(kwargs)
    config = load_calendar_config()

    if params.horizon_days > config.max_horizon_days:
        params.horizon_days = config.max_horizon_days

    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    today_str = params.today or now_dt.astimezone(IST).strftime("%Y-%m-%d")

    cal = build_calendar(
        conn=ctx.conn,
        user_id=ctx.user_id,
        today=today_str,
        horizon_days=params.horizon_days,
        min_buffer_paise=params.min_buffer_paise,
        scenario=params.scenario,
    )
    return GetCalendarOutput(calendar=cal)


# -------------------------------------------------------------------------------------------------
# 2. check_commitment_coverage (READ)
# -------------------------------------------------------------------------------------------------
class CheckCommitmentCoverageInput(ToolInput):
    """Input parameters for checking commitment coverage."""

    commitment_id: str | None = None
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    horizon_days: int = Field(default=60, ge=1, le=180)
    window: int | None = None
    today: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CheckCommitmentCoverageOutput(ToolOutput):
    """Coverage evaluations for commitment occurrences in the window."""

    coverage: list[Coverage]


def check_commitment_coverage_handler(
    ctx: "ExecutionContext", **kwargs
) -> CheckCommitmentCoverageOutput:
    params = CheckCommitmentCoverageInput.model_validate(kwargs)
    config = load_calendar_config()

    horizon = params.window if params.window is not None else params.horizon_days
    if horizon > config.max_horizon_days:
        horizon = config.max_horizon_days

    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    today_str = params.today or now_dt.astimezone(IST).strftime("%Y-%m-%d")

    cal = build_calendar(
        conn=ctx.conn,
        user_id=ctx.user_id,
        today=today_str,
        horizon_days=horizon,
    )

    covs = cal.coverage
    if params.commitment_id is not None:
        covs = [c for c in covs if c.occurrence.commitment_id == params.commitment_id]
    if params.due_date is not None:
        covs = [c for c in covs if c.occurrence.due_date == params.due_date]

    return CheckCommitmentCoverageOutput(coverage=covs)


# -------------------------------------------------------------------------------------------------
# Tool Specifications & Registry
# -------------------------------------------------------------------------------------------------
CALENDAR_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_calendar",
        description="Project daily cash flow, running balances, and commitment coverage.",
        input_model=GetCalendarInput,
        output_model=GetCalendarOutput,
        side_effect=SideEffect.READ,
        handler=get_calendar_handler,
    ),
    ToolSpec(
        name="check_commitment_coverage",
        description="Check whether commitments due in a window are covered by projected reserves.",
        input_model=CheckCommitmentCoverageInput,
        output_model=CheckCommitmentCoverageOutput,
        side_effect=SideEffect.READ,
        handler=check_commitment_coverage_handler,
    ),
)


def register_calendar_tools(register_fn=register) -> None:
    """Register financial calendar tools into the tool registry."""
    for spec in CALENDAR_TOOLS:
        register_fn(spec)
