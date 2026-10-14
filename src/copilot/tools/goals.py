"""
Tool specifications and handlers for goal-aware reasoning (PLAN_PHASE2 Section 5.5).

Governance rules:
- create_goal, update_goal: SideEffect.WRITE_LOGICAL. Allowed for user, requires approval for agent.
- list_goals: SideEffect.READ. Planner-selectable.
- evaluate_goal_impact: SideEffect.READ. Planner-selectable.
- All modifications are strictly audited and isolated by user_id.
"""

import uuid
from typing import TYPE_CHECKING

from pydantic import Field, StrictInt

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.goals import (
    GoalImpactResult,
    goal_impact,
    monthly_surplus_estimate,
)
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo import (
    get_goal,
    insert_goal,
)
from copilot.db.repo import (
    list_goals as repo_list_goals,
)
from copilot.db.repo import (
    update_goal as repo_update_goal,
)
from copilot.models.agentic import Goal, GoalKind, GoalStatus
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# ---------------------------------------------------------------------------------------------
# 1. create_goal
# ---------------------------------------------------------------------------------------------
class CreateGoalInput(ToolInput):
    """Input parameters for creating a new financial goal."""

    name: str = Field(min_length=1)
    kind: GoalKind = "savings"
    target_paise: StrictInt = Field(gt=0)
    current_paise: StrictInt = Field(default=0, ge=0)
    deadline: str | None = None  # YYYY-MM-DD
    priority: int = Field(default=1, ge=1, le=3)


class CreateGoalOutput(ToolOutput):
    """Result of creating a financial goal."""

    goal: Goal


def create_goal_handler(ctx: "ExecutionContext", **kwargs) -> CreateGoalOutput:
    params = CreateGoalInput.model_validate(kwargs)
    ts = to_utc_iso(now_utc(ctx.clock))
    goal_id = f"goal_{uuid.uuid4().hex[:8]}"

    goal = Goal(
        id=goal_id,
        user_id=ctx.user_id,
        name=params.name,
        kind=params.kind,
        target_paise=params.target_paise,
        current_paise=params.current_paise,
        deadline=params.deadline,
        priority=params.priority,
        status="active",
        created_at=ts,
        updated_at=ts,
    )

    insert_goal(ctx.conn, goal)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="goal_created",
        reason=f"Goal '{goal.name}' created by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="goal",
        entity_id=goal.id,
        after_data=goal.model_dump(mode="json"),
        metadata={
            "goal_id": goal.id,
            "name": goal.name,
            "target_paise": goal.target_paise,
            "priority": goal.priority,
        },
        clock=ctx.clock,
    )

    return CreateGoalOutput(goal=goal)


# ---------------------------------------------------------------------------------------------
# 2. update_goal
# ---------------------------------------------------------------------------------------------
class UpdateGoalInput(ToolInput):
    """Input parameters for updating a goal."""

    goal_id: str
    name: str | None = None
    kind: GoalKind | None = None
    target_paise: StrictInt | None = Field(default=None, gt=0)
    current_paise: StrictInt | None = Field(default=None, ge=0)
    deadline: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: GoalStatus | None = None


class UpdateGoalOutput(ToolOutput):
    """Result of updating a financial goal."""

    goal: Goal


def update_goal_handler(ctx: "ExecutionContext", **kwargs) -> UpdateGoalOutput:
    params = UpdateGoalInput.model_validate(kwargs)
    existing = get_goal(ctx.conn, ctx.user_id, params.goal_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Goal '{params.goal_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    update_data = {}
    if params.name is not None:
        update_data["name"] = params.name
    if params.kind is not None:
        update_data["kind"] = params.kind
    if params.target_paise is not None:
        update_data["target_paise"] = params.target_paise
    if params.current_paise is not None:
        update_data["current_paise"] = params.current_paise
    if params.deadline is not None:
        update_data["deadline"] = params.deadline
    if params.priority is not None:
        update_data["priority"] = params.priority
    if params.status is not None:
        update_data["status"] = params.status
    update_data["updated_at"] = ts

    updated = existing.model_copy(update=update_data)
    repo_update_goal(
        ctx.conn,
        ctx.user_id,
        params.goal_id,
        name=params.name,
        target_paise=params.target_paise,
        current_paise=params.current_paise,
        deadline=params.deadline,
        priority=params.priority,
        status=params.status,
        updated_at=ts,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="goal_updated",
        reason=f"Goal '{updated.name}' updated by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="goal",
        entity_id=updated.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        metadata={
            "goal_id": updated.id,
            "updated_fields": list(update_data.keys()),
        },
        clock=ctx.clock,
    )

    return UpdateGoalOutput(goal=updated)


# ---------------------------------------------------------------------------------------------
# 3. list_goals
# ---------------------------------------------------------------------------------------------
class ListGoalsInput(ToolInput):
    """Input parameters for listing goals."""

    status: GoalStatus | None = None


class ListGoalsOutput(ToolOutput):
    """List of financial goals."""

    goals: list[Goal]


def list_goals_handler(ctx: "ExecutionContext", **kwargs) -> ListGoalsOutput:
    params = ListGoalsInput.model_validate(kwargs)
    goals = repo_list_goals(ctx.conn, ctx.user_id, status=params.status)
    return ListGoalsOutput(goals=goals)


# ---------------------------------------------------------------------------------------------
# 4. evaluate_goal_impact
# ---------------------------------------------------------------------------------------------
class EvaluateGoalImpactInput(ToolInput):
    """Input parameters for evaluating spending impact on goals."""

    decision_paise: StrictInt = Field(default=0, ge=0)
    today: str | None = None  # UTC ISO timestamp or YYYY-MM-DD


class EvaluateGoalImpactOutput(ToolOutput):
    """Deterministic evaluation of goal pace and impact."""

    impact: GoalImpactResult


def evaluate_goal_impact_handler(ctx: "ExecutionContext", **kwargs) -> EvaluateGoalImpactOutput:
    params = EvaluateGoalImpactInput.model_validate(kwargs)
    today_val = params.today or to_utc_iso(now_utc(ctx.clock))

    active_goals = repo_list_goals(ctx.conn, ctx.user_id, status="active")
    surplus = monthly_surplus_estimate(ctx.conn, ctx.user_id, today_val)
    impact = goal_impact(params.decision_paise, active_goals, today_val, surplus)

    return EvaluateGoalImpactOutput(impact=impact)


# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------
GOAL_TOOLS = (
    ToolSpec(
        name="create_goal",
        description="Create a new financial savings or purchase goal.",
        input_model=CreateGoalInput,
        output_model=CreateGoalOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_goal_handler,
    ),
    ToolSpec(
        name="update_goal",
        description="Update an existing financial goal's target, progress, or deadline.",
        input_model=UpdateGoalInput,
        output_model=UpdateGoalOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=update_goal_handler,
    ),
    ToolSpec(
        name="list_goals",
        description="List the user's active or paused financial goals.",
        input_model=ListGoalsInput,
        output_model=ListGoalsOutput,
        side_effect=SideEffect.READ,
        handler=list_goals_handler,
    ),
    ToolSpec(
        name="evaluate_goal_impact",
        description="Evaluate the impact of a spending decision on active goals.",
        input_model=EvaluateGoalImpactInput,
        output_model=EvaluateGoalImpactOutput,
        side_effect=SideEffect.READ,
        handler=evaluate_goal_impact_handler,
    ),
)


def register_goals_tools(register_fn=register) -> None:
    """Register all goal-related tools into the global registry."""
    for spec in GOAL_TOOLS:
        register_fn(spec)
