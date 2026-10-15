"""
Skill tool wrappers and registration (PLAN_PHASE3 Section 5.12).

Exposes each skill as a planner-selectable compute tool so that autonomous planners
can invoke an entire certified skill workflow as a single validated step.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import Field, StrictInt

from copilot.skills.runner import run_skill
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


class SkillToolOutput(ToolOutput):
    """Output from executing a skill workflow."""

    status: str
    skill_name: str
    skill_run_id: str
    outputs: dict[str, Any]
    reason: str | None = None
    duration_ms: float = 0.0


# 1. affordability_check
class AffordabilityCheckInput(ToolInput):
    amount_paise: StrictInt = Field(gt=0, description="Purchase amount in paise")
    category_id: str | None = None
    date: str | None = None
    recurring_months: int | None = None


def affordability_check_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = AffordabilityCheckInput.model_validate(kwargs)
    res = run_skill(ctx, "affordability_check", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 2. monthly_close
class MonthlyCloseInput(ToolInput):
    period: str | None = None


def monthly_close_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = MonthlyCloseInput.model_validate(kwargs)
    res = run_skill(ctx, "monthly_close", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 3. trip_planning
class TripPlanningInput(ToolInput):
    target_amount_paise: StrictInt = Field(gt=0, description="Target trip amount in paise")
    target_date: str = Field(description="Target date in YYYY-MM-DD")
    category_id: str | None = None


def trip_planning_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = TripPlanningInput.model_validate(kwargs)
    res = run_skill(ctx, "trip_planning", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 4. contribution_review
class ContributionReviewInput(ToolInput):
    horizon_months: int = Field(default=6, ge=1, le=24)


def contribution_review_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = ContributionReviewInput.model_validate(kwargs)
    res = run_skill(ctx, "contribution_review", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 5. explain_month_change
class ExplainMonthChangeInput(ToolInput):
    category_id: str | None = None
    period: str | None = None


def explain_month_change_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = ExplainMonthChangeInput.model_validate(kwargs)
    res = run_skill(ctx, "explain_month_change", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 6. run_skill generic
class RunSkillInput(ToolInput):
    skill_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)


def run_skill_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = RunSkillInput.model_validate(kwargs)
    res = run_skill(ctx, params.skill_name, params.inputs)
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 6. design_experiment_from_goal
class DesignExperimentFromGoalInput(ToolInput):
    goal_id: str


def design_experiment_from_goal_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = DesignExperimentFromGoalInput.model_validate(kwargs)
    res = run_skill(ctx, "design_experiment_from_goal", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 7. weekly_checkin
class WeeklyCheckinSkillInput(ToolInput):
    experiment_id: str


def weekly_checkin_skill_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = WeeklyCheckinSkillInput.model_validate(kwargs)
    res = run_skill(ctx, "weekly_checkin", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


# 8. review_experiment
class ReviewExperimentSkillInput(ToolInput):
    experiment_id: str


def review_experiment_skill_handler(ctx: "ExecutionContext", **kwargs) -> SkillToolOutput:
    params = ReviewExperimentSkillInput.model_validate(kwargs)
    res = run_skill(ctx, "review_experiment", params.model_dump())
    return SkillToolOutput(
        status=res.status,
        skill_name=res.skill_name,
        skill_run_id=res.skill_run_id,
        outputs=res.outputs,
        reason=res.reason,
        duration_ms=res.duration_ms,
    )


SKILL_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="affordability_check",
        description=(
            "Run affordability check skill: calendar projection, what-if spend, "
            "commitments, and goals."
        ),
        input_model=AffordabilityCheckInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=affordability_check_handler,
    ),
    ToolSpec(
        name="monthly_close",
        description=(
            "Run monthly close skill: rollover buckets, refresh memory confidence, "
            "scan alerts, and draft review."
        ),
        input_model=MonthlyCloseInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=monthly_close_handler,
    ),
    ToolSpec(
        name="trip_planning",
        description=(
            "Run trip planning skill: goal progress, bucket allocation, "
            "calendar buffer, and trade-offs."
        ),
        input_model=TripPlanningInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=trip_planning_handler,
    ),
    ToolSpec(
        name="contribution_review",
        description=(
            "Run contribution review skill: investment readiness, contribution plan, "
            "and goal status."
        ),
        input_model=ContributionReviewInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=contribution_review_handler,
    ),
    ToolSpec(
        name="explain_month_change",
        description=(
            "Run explain month change skill: causal investigation into spend changes "
            "and memory context."
        ),
        input_model=ExplainMonthChangeInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=explain_month_change_handler,
    ),
    ToolSpec(
        name="run_skill",
        description="Execute a registered certified skill workflow by name.",
        input_model=RunSkillInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=run_skill_handler,
    ),
    ToolSpec(
        name="design_experiment_from_goal",
        description="Run goal-to-experiment decomposition skill.",
        input_model=DesignExperimentFromGoalInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=design_experiment_from_goal_handler,
    ),
    ToolSpec(
        name="weekly_checkin",
        description="Run weekly experiment checkin skill.",
        input_model=WeeklyCheckinSkillInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=weekly_checkin_skill_handler,
    ),
    ToolSpec(
        name="review_experiment",
        description="Run completed experiment review skill.",
        input_model=ReviewExperimentSkillInput,
        output_model=SkillToolOutput,
        side_effect=SideEffect.READ,
        handler=review_experiment_skill_handler,
    ),
)


def register_skill_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register all skill tools into the tool registry."""
    for spec in SKILL_TOOLS:
        register_fn(spec)
