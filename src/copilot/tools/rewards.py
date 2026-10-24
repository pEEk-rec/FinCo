"""
Tool specifications and handlers for user rewards, personal bests, and progress tracking.
(PLAN_PHASE4 Section 5.6, Section 5.7 & Section 5.11)

Governance rules:
- get_user_progress, get_personal_bests:
    SideEffect.READ. Allowed for all actors, planner-selectable.
- award_xp_and_badges:
    SideEffect.WRITE_LOGICAL. Allowed for agent and user (runtime maintenance job).
    Never planner-selectable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from copilot.core.goals import goal_progress
from copilot.core.metrics import _date_to_utc_bounds, calculate_tagging_completeness
from copilot.core.rewards import (
    award_experiment_outcome_xp,
)
from copilot.core.rewards import (
    award_xp as core_award_xp,
)
from copilot.core.rewards import (
    check_and_award_badges as core_check_and_award_badges,
)
from copilot.core.rewards import (
    get_user_progress as core_get_user_progress,
)
from copilot.core.self_competition import compute_personal_bests as core_compute_personal_bests
from copilot.core.timeutil import IST, from_utc_iso, now_utc
from copilot.db.repo import list_goals
from copilot.db.repo_phase4 import list_experiment_checkins, list_experiments
from copilot.models.phase4 import PersonalBest, Progress
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

#: A week only counts for the tagging reward with enough payments to say something, and when
#: at least 95% were tagged by the user or a rule (config/rewards.yaml: tagging_completeness_week).
TAGGING_MIN_PAYMENTS = 5
TAGGING_WEEK_MIN_BP = 9500


# -------------------------------------------------------------------------------------------------
# 1. get_user_progress
# -------------------------------------------------------------------------------------------------
class GetUserProgressInput(ToolInput):
    """Input for retrieving unified user gamification progress snapshot."""

    as_of: str | None = None


class GetUserProgressOutput(ToolOutput):
    progress: Progress


def get_user_progress_handler(ctx: ExecutionContext, **kwargs) -> GetUserProgressOutput:
    params = GetUserProgressInput.model_validate(kwargs)
    clock_dt = (
        from_utc_iso(params.as_of)
        if params.as_of
        else (ctx.clock if isinstance(ctx.clock, datetime) else now_utc())
    )
    prog = core_get_user_progress(ctx.conn, ctx.user_id, clock=clock_dt)
    return GetUserProgressOutput(progress=prog)


# -------------------------------------------------------------------------------------------------
# 2. get_personal_bests
# -------------------------------------------------------------------------------------------------
class GetPersonalBestsInput(ToolInput):
    """Input for querying derived personal bests."""

    metric_code: str | None = None


class GetPersonalBestsOutput(ToolOutput):
    personal_bests: list[PersonalBest]


def get_personal_bests_handler(ctx: ExecutionContext, **kwargs) -> GetPersonalBestsOutput:
    params = GetPersonalBestsInput.model_validate(kwargs)
    bests = core_compute_personal_bests(ctx.conn, ctx.user_id)
    if params.metric_code:
        bests = [b for b in bests if b.metric_code == params.metric_code]
    return GetPersonalBestsOutput(personal_bests=bests)


# -------------------------------------------------------------------------------------------------
# 3. award_xp_and_badges (Runtime Job)
# -------------------------------------------------------------------------------------------------
class AwardXpAndBadgesInput(ToolInput):
    """Input for idempotent progress evaluation and maintenance job."""

    dry_run: bool = False


class AwardXpAndBadgesOutput(ToolOutput):
    xp_events_count: int
    badges_awarded_count: int


def award_xp_and_badges_handler(ctx: ExecutionContext, **kwargs) -> AwardXpAndBadgesOutput:
    params = AwardXpAndBadgesInput.model_validate(kwargs)
    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()

    if params.dry_run:
        return AwardXpAndBadgesOutput(xp_events_count=0, badges_awarded_count=0)

    xp_count = 0
    today = clock_dt.astimezone(IST).date()

    # 1. Check-ins the user answered. Each one is rewarded once (idempotency key).
    for chk in list_experiment_checkins(ctx.conn, ctx.user_id):
        if chk.user_response is not None and core_award_xp(
            ctx.conn,
            ctx.user_id,
            "checkin_answered",
            "checkin",
            chk.id,
            period_day=today.isoformat(),
            clock=clock_dt,
        ):
            xp_count += 1

    # 2. Experiment outcomes, through the one function that applies the rules: completion,
    # learning XP for an abandoned-and-reviewed experiment, and `target_met` only when the
    # integrity check does not need the user's confirmation (or it was given).
    for exp in list_experiments(ctx.conn, ctx.user_id):
        if exp.status in ("completed", "reviewed", "abandoned"):
            xp_count += len(
                award_experiment_outcome_xp(ctx.conn, ctx.user_id, exp.id, clock=clock_dt)
            )

    # 3. Goal milestones, from the goal's own progress (never from amounts contributed).
    for goal in list_goals(ctx.conn, ctx.user_id, status="active"):
        percent = goal_progress(ctx.conn, ctx.user_id, goal, today).percent_bp // 100
        for mark in (25, 50, 75, 100):
            if percent >= mark and core_award_xp(
                ctx.conn,
                ctx.user_id,
                f"goal_milestone_{mark}",
                "goal",
                goal.id,
                period_day=today.isoformat(),
                clock=clock_dt,
            ):
                xp_count += 1

    # 4. A week whose payments were almost all tagged by the user or a rule
    week_start = today - timedelta(days=today.weekday() + 7)  # the last full Monday to Sunday
    week_end = week_start + timedelta(days=6)
    start_utc, end_utc = _date_to_utc_bounds(week_start.isoformat(), week_end.isoformat())
    in_week = ctx.conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND occurred_at >= ? "
        "AND occurred_at < ?",
        (ctx.user_id, start_utc, end_utc),
    ).fetchone()[0]
    if in_week >= TAGGING_MIN_PAYMENTS and (
        calculate_tagging_completeness(
            ctx.conn, ctx.user_id, week_start.isoformat(), week_end.isoformat()
        )
        >= TAGGING_WEEK_MIN_BP
    ):
        if core_award_xp(
            ctx.conn,
            ctx.user_id,
            "tagging_completeness_week",
            "week",
            week_start.isoformat(),
            period_day=today.isoformat(),
            clock=clock_dt,
        ):
            xp_count += 1

    # 5. Behavioural memories the user confirmed ("Still true?")
    for row in ctx.conn.execute(
        "SELECT id FROM memory_items WHERE user_id = ? AND user_confirmed = 1 "
        "AND last_confirmed_at IS NOT NULL",
        (ctx.user_id,),
    ).fetchall():
        if core_award_xp(
            ctx.conn,
            ctx.user_id,
            "memory_confirmation",
            "memory",
            row["id"],
            period_day=today.isoformat(),
            clock=clock_dt,
        ):
            xp_count += 1

    # 3. Award badges (idempotent one-time badge awards)
    new_badges = core_check_and_award_badges(ctx.conn, ctx.user_id, clock=clock_dt)

    return AwardXpAndBadgesOutput(
        xp_events_count=xp_count,
        badges_awarded_count=len(new_badges),
    )


# -------------------------------------------------------------------------------------------------
# Specifications and Registration
# -------------------------------------------------------------------------------------------------
REWARDS_TOOLS = (
    ToolSpec(
        name="get_user_progress",
        description="Get unified user gamification progress snapshot (XP, level, badges, bests).",
        input_model=GetUserProgressInput,
        output_model=GetUserProgressOutput,
        side_effect=SideEffect.READ,
        handler=get_user_progress_handler,
    ),
    ToolSpec(
        name="get_personal_bests",
        description="Query user personal best achievements across metrics and windows.",
        input_model=GetPersonalBestsInput,
        output_model=GetPersonalBestsOutput,
        side_effect=SideEffect.READ,
        handler=get_personal_bests_handler,
    ),
    ToolSpec(
        name="award_xp_and_badges",
        description="Runtime maintenance job: evaluate and award due XP and badges idempotently.",
        input_model=AwardXpAndBadgesInput,
        output_model=AwardXpAndBadgesOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=award_xp_and_badges_handler,
    ),
)


def register_rewards_tools(register_fn=register) -> None:
    """Register all reward and progress tools into the global registry."""
    for spec in REWARDS_TOOLS:
        register_fn(spec)
