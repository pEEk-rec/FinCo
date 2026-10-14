"""
Unit tests for deterministic goal reasoning and calculations (PLAN_PHASE2 Stage 2.2).

Verifies hand-computed boundary conditions on both sides of every threshold:
- exactly on-track
- one paisa short (at_risk and off_track)
- deadline this month
- deadline passed
- no deadline
- target already met
- zero history
- fewer than minimum history months
- ceil rounding
- IST month boundaries
- goal impact evaluation
"""


import pytest

from copilot.config.phase2 import GoalsConfig
from copilot.core.goals import (
    SurplusEstimate,
    goal_impact,
    goal_status,
    monthly_surplus_estimate,
    months_remaining,
    required_monthly_paise,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, Transaction, User

T0 = "2026-10-15T10:00:00Z"


def make_goal(
    goal_id: str = "g1",
    target_paise: int = 60_000_00,  # ₹60,000
    current_paise: int = 18_000_00,  # ₹18,000
    deadline: str | None = "2027-03-31",
    priority: int = 1,
    status: str = "active",
) -> Goal:
    return Goal(
        id=goal_id,
        user_id="u1",
        name="Test Goal",
        kind="savings",
        target_paise=target_paise,
        current_paise=current_paise,
        deadline=deadline,
        priority=priority,
        status=status,
        created_at=T0,
        updated_at=T0,
    )


# ---------------------------------------------------------------------------------------------
# 1. Months Remaining and Ceil Rounding
# ---------------------------------------------------------------------------------------------
def test_months_remaining_and_ceil_rounding():
    """Formula: ceil((target - current) / months_remaining)."""
    # October 2026 to March 2027: Oct, Nov, Dec, Jan, Feb, Mar = 6 months
    today = "2026-10-15T10:00:00Z"
    g = make_goal(target_paise=60_000_00, current_paise=18_000_00, deadline="2027-03-31")

    assert months_remaining(g, today) == 6
    # (60000 - 18000) / 6 = 42000 / 6 = 7000
    assert required_monthly_paise(g, today) == 7_000_00

    # Test Ceil rounding: 100 paise over 3 months -> ceil(100/3) = 34
    g_ceil = make_goal(target_paise=100, current_paise=0, deadline="2026-12-31")
    # Oct, Nov, Dec = 3 months
    assert months_remaining(g_ceil, today) == 3
    assert required_monthly_paise(g_ceil, today) == 34

    # 99 paise over 3 months -> 33 paise exactly
    g_exact = make_goal(target_paise=99, current_paise=0, deadline="2026-12-31")
    assert required_monthly_paise(g_exact, today) == 33

    # 101 paise over 3 months -> 34 paise
    g_ceil2 = make_goal(target_paise=101, current_paise=0, deadline="2026-12-31")
    assert required_monthly_paise(g_ceil2, today) == 34


def test_deadline_this_month():
    """Deadline in current calendar month means 1 month remaining."""
    today = "2026-10-15T10:00:00Z"
    g = make_goal(target_paise=10_000_00, current_paise=4_000_00, deadline="2026-10-31")

    assert months_remaining(g, today) == 1
    # Full remaining deficit needed this month
    assert required_monthly_paise(g, today) == 6_000_00


def test_deadline_passed():
    """Deadline in past returns 0 months remaining and full remaining deficit."""
    today = "2026-10-15T10:00:00Z"
    # Past month
    g_past_month = make_goal(target_paise=10_000_00, current_paise=4_000_00, deadline="2026-09-30")
    assert months_remaining(g_past_month, today) == 0
    assert required_monthly_paise(g_past_month, today) == 6_000_00

    # Earlier in the same month
    g_past_day = make_goal(target_paise=10_000_00, current_paise=4_000_00, deadline="2026-10-10")
    assert months_remaining(g_past_day, today) == 0
    assert required_monthly_paise(g_past_day, today) == 6_000_00


def test_no_deadline_and_target_already_met():
    """No deadline returns None; target already met returns 0."""
    today = "2026-10-15T10:00:00Z"

    # No deadline
    g_none = make_goal(deadline=None)
    assert months_remaining(g_none, today) is None
    assert required_monthly_paise(g_none, today) is None

    # Target already met
    g_met = make_goal(target_paise=10_000_00, current_paise=10_000_00, deadline="2027-01-31")
    assert required_monthly_paise(g_met, today) == 0

    # Target exceeded
    g_over = make_goal(target_paise=10_000_00, current_paise=12_000_00, deadline="2027-01-31")
    assert required_monthly_paise(g_over, today) == 0


def test_ist_month_boundary_handling():
    """
    UTC timestamp near midnight IST boundary must resolve to the correct IST date.
    2026-10-31T18:00:00Z is 2026-10-31 23:30:00 IST (October).
    2026-10-31T19:00:00Z is 2026-11-01 00:30:00 IST (November).
    """
    g = make_goal(deadline="2026-10-31")

    # Before IST midnight: still October in IST -> deadline is this month (1 month remaining)
    assert months_remaining(g, "2026-10-31T18:00:00Z") == 1

    # After IST midnight: November in IST -> deadline was in October, so it passed (0 months)
    assert months_remaining(g, "2026-10-31T19:00:00Z") == 0


# ---------------------------------------------------------------------------------------------
# 2. Goal Status Boundaries
# ---------------------------------------------------------------------------------------------
def test_goal_status_on_track_at_risk_off_track_boundaries():
    """
    Test exact boundaries between on_track, at_risk, and off_track.
    Required monthly paise = 5,000.
    """
    today = "2026-10-15T10:00:00Z"
    # Target 5,000, current 0, deadline this month -> required = 5,000
    g = make_goal(target_paise=5_000_00, current_paise=0, deadline="2026-10-31")

    # Boundary 1: exactly on_track (low == required)
    surplus_on_track = SurplusEstimate(
        status="ok",
        low_paise=5_000_00,
        expected_paise=7_000_00,
        high_paise=9_000_00,
        months_evaluated=3,
    )
    status, req, shortfall = goal_status(g, today, surplus_on_track)
    assert status == "on_track"
    assert req == 5_000_00
    assert shortfall == 0

    # Boundary 2: one paisa short on low -> at_risk (low = required - 1, expected >= required)
    surplus_at_risk = SurplusEstimate(
        status="ok",
        low_paise=4_999_99,
        expected_paise=5_000_00,
        high_paise=8_000_00,
        months_evaluated=3,
    )
    status, req, shortfall = goal_status(g, today, surplus_at_risk)
    assert status == "at_risk"
    assert req == 5_000_00
    assert shortfall == 0

    # Boundary 3: one paisa short on expected -> off_track (expected = required - 1)
    surplus_off_track = SurplusEstimate(
        status="ok",
        low_paise=3_000_00,
        expected_paise=4_999_99,
        high_paise=8_000_00,
        months_evaluated=3,
    )
    status, req, shortfall = goal_status(g, today, surplus_off_track)
    assert status == "off_track"
    assert req == 5_000_00
    assert shortfall == 1  # 5,000.00 - 4,999.99 = 1 paisa


def test_goal_status_unknown_when_insufficient_data_or_no_deadline():
    """Status is unknown when surplus is insufficient or deadline is missing."""
    today = "2026-10-15T10:00:00Z"
    g = make_goal(deadline="2026-12-31")
    surplus_insufficient = SurplusEstimate(status="insufficient_data", months_evaluated=1)

    status, req, shortfall = goal_status(g, today, surplus_insufficient)
    assert status == "unknown"
    assert req is not None
    assert shortfall == 0

    # No deadline
    g_no_deadline = make_goal(deadline=None)
    surplus_ok = SurplusEstimate(
        status="ok", low_paise=10_000_00, expected_paise=12_000_00, high_paise=15_000_00
    )
    status, req, shortfall = goal_status(g_no_deadline, today, surplus_ok)
    assert status == "unknown"
    assert req is None
    assert shortfall == 0


# ---------------------------------------------------------------------------------------------
# 3. Monthly Surplus Estimate
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def db():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(
        c, Account(id="acc_1", user_id="u1", name="Main", opening_balance_paise=0, created_at=T0)
    )
    insert_category(c, Category(id="food", user_id="u1", name="Food", created_at=T0))
    return c


def test_surplus_estimate_zero_history_and_fewer_than_min_months(db):
    """Zero history or fewer than minimum complete months returns insufficient_data."""
    today = "2026-10-15T10:00:00Z"
    cfg = GoalsConfig(surplus_lookback_months=3, min_history_months_for_surplus=2)

    # 1. Zero history
    est_zero = monthly_surplus_estimate(db, "u1", today, config=cfg)
    assert est_zero.status == "insufficient_data"
    assert est_zero.months_evaluated == 0

    # 2. Add 1 complete month (September 2026: 2026-09)
    # Income credit ₹50,000 (-5,000,000 paise), Spend debit ₹30,000 (3,000,000 paise)
    insert_transaction(
        db,
        Transaction(
            id="tx_sep_in",
            account_id="acc_1",
            user_id="u1",
            amount_paise=-5_000_000,
            direction="credit",
            merchant_raw="Salary",
            description="Salary",
            occurred_at="2026-09-05T10:00:00Z",
            created_at="2026-09-05T10:00:00Z",
        ),
    )
    insert_transaction(
        db,
        Transaction(
            id="tx_sep_out",
            account_id="acc_1",
            user_id="u1",
            amount_paise=3_000_000,
            direction="debit",
            category_id="food",
            merchant_raw="Swiggy",
            description="Food",
            occurred_at="2026-09-10T10:00:00Z",
            created_at="2026-09-10T10:00:00Z",
        ),
    )
    db.commit()

    # 1 month evaluated < min 2 months -> still insufficient_data
    est_one = monthly_surplus_estimate(db, "u1", today, config=cfg)
    assert est_one.status == "insufficient_data"
    assert est_one.months_evaluated == 1

    # 3. Add second complete month (August 2026: 2026-08)
    # Income ₹60,000, Spend ₹20,000 -> Surplus = ₹40,000
    insert_transaction(
        db,
        Transaction(
            id="tx_aug_in",
            account_id="acc_1",
            user_id="u1",
            amount_paise=-6_000_000,
            direction="credit",
            merchant_raw="Salary",
            description="Salary",
            occurred_at="2026-08-05T10:00:00Z",
            created_at="2026-08-05T10:00:00Z",
        ),
    )
    insert_transaction(
        db,
        Transaction(
            id="tx_aug_out",
            account_id="acc_1",
            user_id="u1",
            amount_paise=2_000_000,
            direction="debit",
            category_id="food",
            merchant_raw="Grocery",
            description="Food",
            occurred_at="2026-08-10T10:00:00Z",
            created_at="2026-08-10T10:00:00Z",
        ),
    )
    db.commit()

    # Now 2 months evaluated >= min 2 -> status ok!
    # Sep surplus: 50,000 - 30,000 = 20,000 (2,000,000 paise)
    # Aug surplus: 60,000 - 20,000 = 40,000 (4,000,000 paise)
    # Low = 20,000; High = 40,000; Expected = (20,000 + 40,000) / 2 = 30,000 (3,000,000 paise)
    est_two = monthly_surplus_estimate(db, "u1", today, config=cfg)
    assert est_two.status == "ok"
    assert est_two.months_evaluated == 2
    assert est_two.low_paise == 2_000_000
    assert est_two.high_paise == 4_000_000
    assert est_two.expected_paise == 3_000_000


# ---------------------------------------------------------------------------------------------
# 4. Goal Impact Evaluation
# ---------------------------------------------------------------------------------------------
def test_goal_impact_spending_decision():
    """
    Evaluate goal impact of a spending decision on active goals by priority.
    """
    today = "2026-10-15T10:00:00Z"
    surplus = SurplusEstimate(
        status="ok",
        low_paise=10_000_00,  # ₹10,000
        expected_paise=15_000_00,  # ₹15,000
        high_paise=20_000_00,  # ₹20,000
        months_evaluated=3,
        monthly_surpluses_paise=[10_000_00, 15_000_00, 20_000_00],
    )

    # Goal 1: Priority 1, required ₹8,000/mo (low 10,000 >= 8,000 -> on_track)
    g1 = make_goal(
        goal_id="g1",
        target_paise=8_000_00,
        current_paise=0,
        deadline="2026-10-31",
        priority=1,
    )
    # Goal 2: Priority 2, required ₹12,000/mo (exp 15,000 >= 12,000, low 10,000 < 12,000 -> at_risk)
    g2 = make_goal(
        goal_id="g2",
        target_paise=12_000_00,
        current_paise=0,
        deadline="2026-10-31",
        priority=2,
    )

    # Spending decision: ₹5,000 (500,000 paise)
    decision = 5_000_00
    impact = goal_impact(decision, [g1, g2], today, surplus)

    # Surplus after: low = 5,000, expected = 10,000, high = 15,000
    assert impact.surplus_after.low_paise == 5_000_00
    assert impact.surplus_after.expected_paise == 10_000_00

    # Before: g1 on_track, g2 at_risk
    assert impact.goals_before[0].status == "on_track"
    assert impact.goals_before[1].status == "at_risk"

    # After:
    # g1: required 8,000. Low (5,000) < 8,000, but Expected (10,000) >= 8,000 -> moved to AT_RISK!
    assert impact.goals_after[0].status == "at_risk"
    assert impact.goals_after[0].shortfall_paise == 0

    # g2: required 12,000. Expected (10,000) < 12,000 -> moved to OFF_TRACK! Shortfall = 2,000
    assert impact.goals_after[1].status == "off_track"
    assert impact.goals_after[1].shortfall_paise == 2_000_00
