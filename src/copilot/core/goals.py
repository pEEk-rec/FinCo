"""
Pure deterministic functions and calculations for goal-aware reasoning (PLAN_PHASE2 Section 5.5).

Financial rules:
- All money math is integer paise.
- Deadlines and dates are evaluated in Asia/Kolkata (IST) calendar months.
- The LLM never computes or invents numbers; all formulas here are pure and deterministic.
"""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot.config.phase2 import GoalsConfig, load_goals_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import IST, from_utc_iso, month_bounds
from copilot.db.repo import list_transactions
from copilot.models.agentic import Goal
from copilot.models.domain import Transaction
from copilot.tools.financial import net_spend_by_category

_DEFAULT_GOALS_CONFIG_PATH = PROJECT_ROOT / "config" / "goals.yaml"

GoalTrackStatus = Literal["on_track", "at_risk", "off_track", "unknown"]


class SurplusEstimate(BaseModel):
    """
    Result of estimating monthly surplus over complete history months.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "insufficient_data"]
    low_paise: int | None = None
    expected_paise: int | None = None
    high_paise: int | None = None
    months_evaluated: int = 0
    monthly_surpluses_paise: list[int] = Field(default_factory=list)


class GoalEvaluation(BaseModel):
    """
    Evaluation of a single goal's pace against available monthly surplus.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str
    name: str
    target_paise: int
    current_paise: int
    months_remaining: int | None
    required_monthly_paise: int | None
    status: GoalTrackStatus
    shortfall_paise: int = 0


class GoalImpactResult(BaseModel):
    """
    Result of evaluating the impact of a spending decision on active goals.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_paise: int
    surplus_before: SurplusEstimate
    surplus_after: SurplusEstimate
    goals_before: list[GoalEvaluation]
    goals_after: list[GoalEvaluation]


def _to_ist_date(val: datetime | date | str) -> date:
    """Parse or convert any timestamp or date into an IST calendar date."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        if val.tzinfo is None:
            # Assume UTC if naive, per project conventions
            val = val.replace(tzinfo=UTC)
        return val.astimezone(IST).date()
    if isinstance(val, str):
        # Could be "YYYY-MM-DD" or full ISO timestamp
        if len(val) == 10 and val.count("-") == 2:
            return date.fromisoformat(val)
        return from_utc_iso(val).astimezone(IST).date()
    raise TypeError(f"Cannot convert {type(val)} to IST date: {val!r}")


def months_remaining(goal: Goal, today: datetime | date | str) -> int | None:
    """
    Calculate calendar months remaining to reach a goal deadline, evaluated in IST.

    Returns:
    - None: if goal has no deadline.
    - 0: if the deadline has already passed (before today's date).
    - 1: if the deadline falls in the current IST calendar month ('deadline this month').
    - N: (deadline_year - today_year)*12 + (deadline_month - today_month) + 1 for future months.
    """
    if goal.deadline is None or not goal.deadline.strip():
        return None

    today_date = _to_ist_date(today)
    deadline_date = _to_ist_date(goal.deadline)

    if deadline_date < today_date:
        return 0

    year_diff = deadline_date.year - today_date.year
    month_diff = deadline_date.month - today_date.month
    calendar_diff = year_diff * 12 + month_diff

    # If calendar_diff is 0, deadline is in current month (>= today) => 1 month remaining
    return calendar_diff + 1


def required_monthly_paise(goal: Goal, today: datetime | date | str) -> int | None:
    """
    Calculate required monthly savings in integer paise using ceiling rounding.

    Formula: ceil((target - current) / months_remaining), never negative.
    - None if goal has no deadline.
    - 0 if current_paise >= target_paise (target already met).
    - If deadline passed and target not met: full remaining deficit.
    """
    if goal.deadline is None or not goal.deadline.strip():
        return None

    if goal.current_paise >= goal.target_paise:
        return 0

    rem = months_remaining(goal, today)
    deficit = goal.target_paise - goal.current_paise

    if rem == 0:
        return deficit

    # Ceiling integer division for positive numbers: (a + b - 1) // b
    return (deficit + rem - 1) // rem


def _calculate_month_surplus(txs: Iterable[Transaction]) -> int:
    """
    Calculate net surplus (income - spend, transfers excluded) for transactions in a month.
    """
    valid_txs = [tx for tx in txs if not tx.excluded_from_spend and tx.category_id != "transfer"]
    # Income: non-transfer credits (amount_paise is negative for credit)
    income_paise = sum(-tx.amount_paise for tx in valid_txs if tx.direction == "credit")
    # Spend: net spend by category
    spend_dict = net_spend_by_category(valid_txs)
    spend_paise = sum(spend_dict.values())
    return income_paise - spend_paise


def monthly_surplus_estimate(
    conn: sqlite3.Connection,
    user_id: str,
    today: datetime | date | str,
    config: GoalsConfig | None = None,
) -> SurplusEstimate:
    """
    Estimate monthly surplus over the last N complete calendar months.

    Transfers are excluded.
    Returns:
    - status="insufficient_data" if fewer than min complete months have data.
    - status="ok" with low (min), expected (median), and high (max) integer paise.
    """
    if config is None:
        if _DEFAULT_GOALS_CONFIG_PATH.exists():
            config = load_goals_config(_DEFAULT_GOALS_CONFIG_PATH)
        else:
            config = GoalsConfig()

    today_date = _to_ist_date(today)
    curr_year, curr_month = today_date.year, today_date.month

    # Generate the last N complete calendar months before the current month
    complete_months: list[tuple[int, int]] = []
    y, m = curr_year, curr_month
    for _ in range(config.surplus_lookback_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        complete_months.append((y, m))

    surpluses: list[int] = []
    for y, m in complete_months:
        start_utc, end_utc = month_bounds(y, m)
        txs = list_transactions(conn, user_id, start_utc, end_utc)
        if len(txs) > 0:
            month_surplus = _calculate_month_surplus(txs)
            surpluses.append(month_surplus)

    if len(surpluses) < config.min_history_months_for_surplus:
        return SurplusEstimate(
            status="insufficient_data",
            months_evaluated=len(surpluses),
            monthly_surpluses_paise=surpluses,
        )

    low = min(surpluses)
    high = max(surpluses)
    sorted_s = sorted(surpluses)
    n = len(sorted_s)
    if n % 2 == 1:
        expected = sorted_s[n // 2]
    else:
        expected = (sorted_s[n // 2 - 1] + sorted_s[n // 2]) // 2

    return SurplusEstimate(
        status="ok",
        low_paise=low,
        expected_paise=expected,
        high_paise=high,
        months_evaluated=n,
        monthly_surpluses_paise=surpluses,
    )


def goal_status(
    goal: Goal,
    today: datetime | date | str,
    surplus: SurplusEstimate | None,
) -> tuple[GoalTrackStatus, int | None, int]:
    """
    Evaluate goal track status against surplus range:
    - on_track: low >= required (or target already met)
    - at_risk: expected >= required but low < required
    - off_track: expected < required
    - unknown: insufficient data or no deadline

    Returns: (status, required_monthly_paise, shortfall_paise)
    """
    required = required_monthly_paise(goal, today)
    if required is None:
        return "unknown", None, 0

    if required == 0:
        # Target already met
        return "on_track", 0, 0

    if surplus is None or surplus.status == "insufficient_data" or surplus.expected_paise is None:
        return "unknown", required, 0

    low = surplus.low_paise or 0
    expected = surplus.expected_paise
    shortfall = max(0, required - expected)

    if low >= required:
        return "on_track", required, 0
    if expected >= required:
        return "at_risk", required, 0
    return "off_track", required, shortfall


def goal_impact(
    decision_paise: int,
    goals: list[Goal],
    today: datetime | date | str,
    surplus: SurplusEstimate,
) -> GoalImpactResult:
    """
    Evaluate the impact of a spending decision on active goals in priority order.
    Subtracts the decision from this period's surplus.
    """
    # Filter active goals and sort by priority (1 is highest), then deadline
    active_goals = [g for g in goals if g.status == "active"]
    sorted_goals = sorted(
        active_goals,
        key=lambda g: (g.priority, g.deadline or "9999-12-31", g.created_at),
    )

    # Status before
    eval_before: list[GoalEvaluation] = []
    for g in sorted_goals:
        status, req, shortfall = goal_status(g, today, surplus)
        eval_before.append(
            GoalEvaluation(
                goal_id=g.id,
                name=g.name,
                target_paise=g.target_paise,
                current_paise=g.current_paise,
                months_remaining=months_remaining(g, today),
                required_monthly_paise=req,
                status=status,
                shortfall_paise=shortfall,
            )
        )

    # Surplus after subtracting decision
    if surplus.status == "ok":
        surplus_after = SurplusEstimate(
            status="ok",
            low_paise=(surplus.low_paise or 0) - decision_paise,
            expected_paise=(surplus.expected_paise or 0) - decision_paise,
            high_paise=(surplus.high_paise or 0) - decision_paise,
            months_evaluated=surplus.months_evaluated,
            monthly_surpluses_paise=[s - decision_paise for s in surplus.monthly_surpluses_paise],
        )
    else:
        surplus_after = surplus

    # Status after
    eval_after: list[GoalEvaluation] = []
    for g in sorted_goals:
        status, req, shortfall = goal_status(g, today, surplus_after)
        eval_after.append(
            GoalEvaluation(
                goal_id=g.id,
                name=g.name,
                target_paise=g.target_paise,
                current_paise=g.current_paise,
                months_remaining=months_remaining(g, today),
                required_monthly_paise=req,
                status=status,
                shortfall_paise=shortfall,
            )
        )

    return GoalImpactResult(
        decision_paise=decision_paise,
        surplus_before=surplus,
        surplus_after=surplus_after,
        goals_before=eval_before,
        goals_after=eval_after,
    )
