"""
Pure deterministic functions and calculations for goal-aware reasoning (PLAN_PHASE2 Section 5.5).

Financial rules:
- All money math is integer paise.
- Deadlines and dates are evaluated in Asia/Kolkata (IST) calendar months.
- The LLM never computes or invents numbers; all formulas here are pure and deterministic.
"""

import calendar
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
from copilot.models.phase3 import GoalProgress
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


# ---------------------------------------------------------------------------------------------
# Phase 3: Goals Full (Progress Sources, History, Projections, and Feasibility)
# ---------------------------------------------------------------------------------------------


def goal_current_paise(conn: sqlite3.Connection, user_id: str, goal: Goal) -> int:
    """
    Derive the current balance in paise of a goal from its single progress_source:
    - manual: goal.current_paise + sum(goal_contributions.amount_paise)
    - bucket: derived balance of linked bucket (allocations - spent)
    - account: derived balance of linked_account_id
    """
    source = getattr(goal, "progress_source", "manual") or "manual"
    if source not in ("manual", "bucket", "account"):
        raise ValueError(f"Invalid progress_source: {source!r}")

    if source == "manual":
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM goal_contributions
            WHERE user_id = ? AND goal_id = ?
            """,
            (user_id, goal.id),
        ).fetchone()
        contrib_sum = row[0] if row else 0
        return goal.current_paise + contrib_sum

    if source == "bucket":
        # Find bucket linked to this goal
        b_row = conn.execute(
            """
            SELECT id FROM buckets
            WHERE user_id = ? AND goal_id = ? AND status = 'active'
            LIMIT 1
            """,
            (user_id, goal.id),
        ).fetchone()
        if not b_row:
            return 0
        b_id = b_row["id"] if isinstance(b_row, dict) or hasattr(b_row, "__getitem__") else b_row[0]

        # Allocations
        alloc_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM bucket_allocations
            WHERE user_id = ? AND bucket_id = ?
            """,
            (user_id, b_id),
        ).fetchone()
        allocated = alloc_row[0] if alloc_row else 0

        # Spend for categories mapped to this bucket
        spent_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM transactions
            WHERE user_id = ?
              AND category_id IN (SELECT category_id FROM bucket_categories WHERE bucket_id = ?)
              AND direction = 'debit'
              AND excluded_from_spend = 0
            """,
            (user_id, b_id),
        ).fetchone()
        spent = spent_row[0] if spent_row else 0
        return allocated - spent

    if source == "account":
        acc_id = getattr(goal, "linked_account_id", None)
        if not acc_id:
            return 0
        acc_row = conn.execute(
            "SELECT opening_balance_paise FROM accounts WHERE user_id = ? AND id = ?",
            (user_id, acc_id),
        ).fetchone()
        if not acc_row:
            return 0
        opening = (
            acc_row["opening_balance_paise"]
            if isinstance(acc_row, dict) or hasattr(acc_row, "__getitem__")
            else acc_row[0]
        )
        tx_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM transactions
            WHERE user_id = ? AND account_id = ?
            """,
            (user_id, acc_id),
        ).fetchone()
        tx_sum = tx_row[0] if tx_row else 0
        return opening - tx_sum

    return goal.current_paise


def monthly_contribution_history(
    conn: sqlite3.Connection,
    user_id: str,
    goal: Goal,
    months: int = 3,
    today: datetime | date | str | None = None,
) -> list[int]:
    """
    Per complete IST month in the lookback window, compute net contribution in integer paise:
    - manual: sum of goal_contributions in that month
    - bucket: net allocations to the bucket in that month's period
    - account: month-end balance delta of linked_account_id
    """
    today_d = _to_ist_date(today or datetime.now(UTC))
    curr_y, curr_m = today_d.year, today_d.month

    complete_months: list[tuple[int, int]] = []
    y, m = curr_y, curr_m
    for _ in range(months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        complete_months.append((y, m))

    complete_months.reverse()  # Chronological order
    source = getattr(goal, "progress_source", "manual") or "manual"
    history: list[int] = []

    for yr, mo in complete_months:
        if source == "manual":
            start_str = f"{yr:04d}-{mo:02d}-01"
            last_day = calendar.monthrange(yr, mo)[1]
            end_str = f"{yr:04d}-{mo:02d}-{last_day:02d}"
            r = conn.execute(
                """
                SELECT COALESCE(SUM(amount_paise), 0)
                FROM goal_contributions
                WHERE user_id = ? AND goal_id = ? AND occurred_on >= ? AND occurred_on <= ?
                """,
                (user_id, goal.id, start_str, end_str),
            ).fetchone()
            history.append(r[0] if r else 0)

        elif source == "bucket":
            b_row = conn.execute(
                """
                SELECT id FROM buckets
                WHERE user_id = ? AND goal_id = ? AND status = 'active'
                LIMIT 1
                """,
                (user_id, goal.id),
            ).fetchone()
            if not b_row:
                history.append(0)
            else:
                if isinstance(b_row, dict) or hasattr(b_row, "__getitem__"):
                    b_id = b_row["id"]
                else:
                    b_id = b_row[0]
                period_str = f"{yr:04d}-{mo:02d}"
                r = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount_paise), 0)
                    FROM bucket_allocations
                    WHERE user_id = ? AND bucket_id = ? AND period = ?
                    """,
                    (user_id, b_id, period_str),
                ).fetchone()
                history.append(r[0] if r else 0)

        elif source == "account":
            acc_id = getattr(goal, "linked_account_id", None)
            if not acc_id:
                history.append(0)
            else:
                start_utc, end_utc = month_bounds(yr, mo)
                r = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount_paise), 0)
                    FROM transactions
                    WHERE user_id = ? AND account_id = ? AND occurred_at >= ? AND occurred_at <= ?
                    """,
                    (user_id, acc_id, start_utc, end_utc),
                ).fetchone()
                tx_sum = r[0] if r else 0
                history.append(-tx_sum)

    return history


def projected_completion(
    remaining_paise: int,
    monthly_history: list[int],
    today: datetime | date | str,
) -> tuple[str | None, dict[str, str | None]]:
    """
    Compute low/median/high projected completion dates:
    - If remaining is 0 -> completed
    - If fewer than 2 complete months -> insufficient_data
    - For each pace c:
        c > 0 -> add ceil(remaining / c) months to current month end
        c <= 0 -> never_at_current_pace
    """
    today_d = _to_ist_date(today)
    if remaining_paise <= 0:
        d_str = today_d.isoformat()
        return d_str, {"low": "completed", "median": "completed", "high": "completed"}

    if len(monthly_history) < 2:
        return None, {"status": "insufficient_data"}

    sorted_h = sorted(monthly_history)
    low = sorted_h[0]
    high = sorted_h[-1]
    n = len(sorted_h)
    median = sorted_h[n // 2] if n % 2 == 1 else (sorted_h[n // 2 - 1] + sorted_h[n // 2]) // 2

    def _add_months_to_month_end(pace: int) -> str:
        if pace <= 0:
            return "never_at_current_pace"
        months_needed = (remaining_paise + pace - 1) // pace
        tot_m = today_d.month + months_needed
        res_y = today_d.year + (tot_m - 1) // 12
        res_m = (tot_m - 1) % 12 + 1
        res_day = calendar.monthrange(res_y, res_m)[1]
        return f"{res_y:04d}-{res_m:02d}-{res_day:02d}"

    low_res = _add_months_to_month_end(low)
    med_res = _add_months_to_month_end(median)
    high_res = _add_months_to_month_end(high)

    proj_date = med_res if median > 0 else None
    return proj_date, {"low": low_res, "median": med_res, "high": high_res}


def goal_progress(
    conn: sqlite3.Connection,
    user_id: str,
    goal: Goal,
    today: datetime | date | str | None = None,
) -> GoalProgress:
    """
    Deterministic evaluation of goal progress, remaining balance, pace, and completion range.
    """
    today_val = today or datetime.now(UTC)
    today_d = _to_ist_date(today_val)

    curr = goal_current_paise(conn, user_id, goal)
    target = goal.target_paise
    remaining = max(0, target - curr)
    percent_bp = min(10000, max(0, (curr * 10000) // target))

    eval_goal = goal.model_copy(update={"current_paise": curr})
    req = required_monthly_paise(eval_goal, today_d) or 0
    rem_m = months_remaining(eval_goal, today_d) or 0

    history = monthly_contribution_history(conn, user_id, goal, months=3, today=today_d)
    proj_date, proj_range = projected_completion(remaining, history, today_d)

    if remaining == 0:
        track_status: Literal["on_track", "at_risk", "off_track", "completed", "unknown"] = (
            "completed"
        )
    else:
        surplus = monthly_surplus_estimate(conn, user_id, today_d)
        p2_status, _, _ = goal_status(eval_goal, today_d, surplus)
        track_status = p2_status

    source = getattr(goal, "progress_source", "manual") or "manual"
    return GoalProgress(
        goal_id=goal.id,
        user_id=user_id,
        name=goal.name,
        target_paise=target,
        current_paise=curr,
        remaining_paise=remaining,
        percent_bp=percent_bp,
        progress_source=source,
        linked_account_id=getattr(goal, "linked_account_id", None),
        required_monthly_paise=req,
        months_remaining=rem_m,
        projected_completion_date=proj_date,
        projection_range=proj_range,
        status=track_status,
    )
