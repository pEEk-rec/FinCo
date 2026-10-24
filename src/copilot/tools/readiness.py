"""
Investment Readiness Tools and Handlers (PLAN_PHASE3 Section 5.6 & Stage 3.6).

Provides read/compute tools for:
- assess_investment_readiness: evaluates savings capacity, emergency cushion, and obligations
- get_readiness_assessment: alias for retrieving structured readiness evaluations
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field

from copilot.core.readiness import assess_readiness
from copilot.core.timeutil import IST, now_utc
from copilot.db.repo_phase3 import insert_readiness_assessment
from copilot.models.phase3 import Readiness
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. Tool Input / Output Models
# -------------------------------------------------------------------------------------------------
class AssessReadinessInput(ToolInput):
    """Input for evaluating financial readiness."""

    today: str | None = Field(
        default=None,
        description="Assessment date in YYYY-MM-DD format. Defaults to current date.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class AssessReadinessOutput(ToolOutput):
    """Output containing structured financial readiness assessment and snapshot record ID."""

    readiness: Readiness
    assessment_id: str


# -------------------------------------------------------------------------------------------------
# 2. Tool Handlers
# -------------------------------------------------------------------------------------------------
def assess_readiness_handler(ctx: "ExecutionContext", **kwargs) -> AssessReadinessOutput:
    params = AssessReadinessInput.model_validate(kwargs)

    if isinstance(ctx.clock, datetime):
        now_dt = ctx.clock
    elif hasattr(ctx.clock, "now"):
        now_dt = ctx.clock.now()
    else:
        now_dt = now_utc()

    today_str = params.today or now_dt.astimezone(IST).strftime("%Y-%m-%d")

    # Pure deterministic assessment
    readiness = assess_readiness(ctx.conn, ctx.user_id, today_str)

    # Persist explanation snapshot record
    aid = insert_readiness_assessment(ctx.conn, ctx.user_id, readiness)

    return AssessReadinessOutput(readiness=readiness, assessment_id=aid)


# -------------------------------------------------------------------------------------------------
# 3. Tool Specifications & Registration
# -------------------------------------------------------------------------------------------------
def register_readiness_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register investment readiness tools with the provided registration function."""
    register_fn(
        ToolSpec(
            name="assess_investment_readiness",
            description=(
                "Assess financial capacity, emergency cushion, and obligation "
                "coverage against readiness criteria"
            ),
            input_model=AssessReadinessInput,
            output_model=AssessReadinessOutput,
            side_effect=SideEffect.READ,
            handler=assess_readiness_handler,
        )
    )
    register_fn(
        ToolSpec(
            name="get_readiness_assessment",
            description=(
                "Retrieve structured readiness evaluation of financial cushion and savings capacity"
            ),
            input_model=AssessReadinessInput,
            output_model=AssessReadinessOutput,
            side_effect=SideEffect.READ,
            handler=assess_readiness_handler,
        )
    )
