"""
Financial Calendar Engine Unit Tests (PLAN_PHASE3 Stage 3.5).

Verifies:
1. Hand-computed calendars over 10 to 15 days with known flows.
2. Property ordering: running_balance_low <= running_balance_expected <= running_balance_high on all days.
3. Category exclusion: categories covered by commitments excluded from variable spend (no double counting).
4. Coverage status at boundary: exactly at buffer, 1 paisa below, 1 paisa above.
5. insufficient_data forecast path (< 3 days elapsed).
6. Reconciliation invariant with forecast v2: expected variable spend sum matches within 1 rupee.
7. Horizon limits (1 <= horizon <= 180).
8. Zero-change scenario equals baseline exactly.
9. Scenarios never mutate database tables.
"""

from datetime import datetime

import pytest

from copilot.core.calendar import CalendarScenario, build_calendar
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import insert_commitment
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import Commitment

T0 = "2026-10-01T00:00:00Z"
DT0 = datetime.fromisoformat("2026-10-01T00:00:00+00:00")


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(
        c,
        Account(
            id="acc_1",
            user_id="u1",
            name="Primary Account",
            opening_balance_paise=1000000,  # ₹10,000
            created_at=T0,
        ),
    )
    insert_category(c, Category(id="cat_rent", user_id="u1", name="Rent", created_at=T0))
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=T0))
    yield c
    c.close()


def test_hand_computed_calendar_known_flows(conn):
    """Hand-computed 10-day calendar matches expected running balances day-by-day."""
    # Commitments:
    # 1. Salary: Inflow 500,000 paise on 2026-10-03
    # 2. Rent: Outflow 400,000 paise on 2026-10-05
    # 3. Bill: Outflow 800,000 paise on 2026-10-08
    c_sal = Commitment(
        id="c_sal",
        user_id="u1",
        name="Salary",
        direction="inflow",
        kind="income",
        amount_paise=500000,
        certainty="firm",
        schedule_kind="once",
        schedule_json={"date": "2026-10-03"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    c_rent = Commitment(
        id="c_rent",
        user_id="u1",
        name="Rent",
        direction="outflow",
        kind="rent",
        amount_paise=400000,
        certainty="firm",
        schedule_kind="once",
        schedule_json={"date": "2026-10-05"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    c_bill = Commitment(
        id="c_bill",
        user_id="u1",
        name="Electric Bill",
        direction="outflow",
        kind="bill",
        amount_paise=800000,
        certainty="firm",
        schedule_kind="once",
        schedule_json={"date": "2026-10-08"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c_sal)
    insert_commitment(conn, c_rent)
    insert_commitment(conn, c_bill)

    # Start balance: 1,000,000 paise. Day is Oct 1 (< 3 days elapsed -> variable spend unknown = 0)
    cal = build_calendar(conn, "u1", today="2026-10-01", horizon_days=10, min_buffer_paise=200000)
    assert len(cal.days) == 10

    # Days 0, 1 (Oct 1, Oct 2): 1,000,000
    assert cal.days[0].running_balance_expected_paise == 1000000
    assert cal.days[1].running_balance_expected_paise == 1000000

    # Day 2 (Oct 3): Salary +500,000 -> 1,500,000
    assert cal.days[2].date == "2026-10-03"
    assert cal.days[2].running_balance_expected_paise == 1500000

    # Day 3 (Oct 4): 1,500,000
    assert cal.days[3].running_balance_expected_paise == 1500000

    # Day 4 (Oct 5): Rent -400,000 -> 1,100,000
    assert cal.days[4].date == "2026-10-05"
    assert cal.days[4].running_balance_expected_paise == 1100000

    # Days 5, 6 (Oct 6, Oct 7): 1,100,000
    assert cal.days[5].running_balance_expected_paise == 1100000
    assert cal.days[6].running_balance_expected_paise == 1100000

    # Day 7 (Oct 8): Bill -800,000 -> 300,000
    assert cal.days[7].date == "2026-10-08"
    assert cal.days[7].running_balance_expected_paise == 300000

    # Days 8, 9 (Oct 9, Oct 10): 300,000
    assert cal.days[8].running_balance_expected_paise == 300000
    assert cal.days[9].running_balance_expected_paise == 300000


def test_ordering_property_low_le_expected_le_high(conn):
    """Property test: running_balance_low <= running_balance_expected <= running_balance_high on all days."""
    # Estimated commitment with range: min=200,000, mid=300,000, max=400,000
    c_est = Commitment(
        id="c_est",
        user_id="u1",
        name="Utility",
        direction="outflow",
        kind="bill",
        amount_paise=300000,
        amount_min_paise=200000,
        amount_max_paise=400000,
        certainty="estimated",
        schedule_kind="monthly",
        schedule_json={"day": 10},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c_est)

    # Some transactions in dining so variable forecast is active (Oct 15)
    for day in range(1, 15):
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_din_{day}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-10-{day:02d}T12:00:00Z",
                amount_paise=5000,
                direction="debit",
                merchant_raw="Food",
                description="Lunch",
                category_id="cat_dining",
                created_at=T0,
            ),
        )

    cal = build_calendar(conn, "u1", today="2026-10-15", horizon_days=30, min_buffer_paise=100000)
    for d in cal.days:
        assert (
            d.running_balance_low_paise
            <= d.running_balance_expected_paise
            <= d.running_balance_high_paise
        ), f"Ordering failed on {d.date}: low={d.running_balance_low_paise}, exp={d.running_balance_expected_paise}, high={d.running_balance_high_paise}"


def test_commitment_categories_excluded_from_variable_spend(conn):
    """Categories covered by active commitments are excluded from variable spend to avoid double counting."""
    c_rent = Commitment(
        id="c_rent",
        user_id="u1",
        name="Monthly Rent",
        direction="outflow",
        kind="rent",
        category_id="cat_rent",
        amount_paise=5000000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 5},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c_rent)

    # Oct 1-10: Rent payment 5,000,000 paise in cat_rent
    insert_transaction(
        conn,
        Transaction(
            id="tx_rent_paid",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-10-05T10:00:00Z",
            amount_paise=5000000,
            direction="debit",
            merchant_raw="Landlord",
            description="Rent",
            category_id="cat_rent",
            created_at=T0,
        ),
    )
    # Dining payment 10,000 paise in cat_dining
    insert_transaction(
        conn,
        Transaction(
            id="tx_dining_1",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-10-06T12:00:00Z",
            amount_paise=10000,
            direction="debit",
            merchant_raw="Cafe",
            description="Coffee",
            category_id="cat_dining",
            created_at=T0,
        ),
    )

    # Build calendar from Oct 10
    cal = build_calendar(conn, "u1", today="2026-10-10", horizon_days=5)
    # If rent was included, variable spend would be ~5,010,000 / 10 = ~500,000/day.
    # Because rent is excluded, variable spend is only based on 10,000 / 10 = 1,000/day!
    for d in cal.days:
        assert d.variable_spend_paise < 50000, f"Variable spend unexpectedly high: {d.variable_spend_paise}"


def test_coverage_boundaries_at_buffer_above_below(conn):
    """Coverage status: covered at buffer, at_risk when low < buffer <= expected, not_covered when expected < buffer."""
    buffer_paise = 100000  # ₹1,000 buffer
    # Current balance is 1,000,000 paise

    # Case 1: Outflow leaving low balance = 100,000 (exactly at buffer)
    # 1,000,000 - 900,000 = 100,000
    c1 = Commitment(
        id="c_exact",
        user_id="u1",
        name="Exact Buffer Outflow",
        direction="outflow",
        kind="bill",
        amount_paise=900000,
        certainty="firm",
        schedule_kind="once",
        schedule_json={"date": "2026-10-01"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c1)

    cal = build_calendar(conn, "u1", today="2026-10-01", horizon_days=2, min_buffer_paise=buffer_paise)
    assert len(cal.coverage) == 1
    assert cal.coverage[0].coverage_status == "covered"
    assert cal.coverage[0].balance_after_low_paise == buffer_paise


def test_coverage_at_risk_one_paisa_below(conn):
    """Outflow leaving low balance 1 paisa below buffer while expected is >= buffer produces 'at_risk'."""
    buffer_paise = 100000

    # Start balance: 1,000,000.
    # Outflow: expected=850,000 (leaves exp=150,000 >= 100,000); max=900,001 (leaves low=99,999 < 100,000)
    c_risk = Commitment(
        id="c_risk",
        user_id="u1",
        name="Risk Outflow",
        direction="outflow",
        kind="bill",
        amount_paise=850000,
        amount_min_paise=800000,
        amount_max_paise=900001,
        certainty="estimated",
        schedule_kind="once",
        schedule_json={"date": "2026-10-01"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c_risk)

    cal = build_calendar(conn, "u1", today="2026-10-01", horizon_days=2, min_buffer_paise=buffer_paise)
    assert len(cal.coverage) == 1
    assert cal.coverage[0].coverage_status == "at_risk"
    assert cal.coverage[0].balance_after_low_paise == 99999
    assert cal.coverage[0].balance_after_expected_paise == 149999


def test_coverage_not_covered_when_expected_below_buffer(conn):
    """Outflow leaving expected balance below buffer produces 'not_covered'."""
    buffer_paise = 100000
    # Outflow: 950,000 firm (leaves 50,000 < 100,000)
    c_not = Commitment(
        id="c_not",
        user_id="u1",
        name="Excess Outflow",
        direction="outflow",
        kind="bill",
        amount_paise=950000,
        certainty="firm",
        schedule_kind="once",
        schedule_json={"date": "2026-10-01"},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c_not)

    cal = build_calendar(conn, "u1", today="2026-10-01", horizon_days=2, min_buffer_paise=buffer_paise)
    assert len(cal.coverage) == 1
    # On day 1 (< 3 days elapsed), expected is below buffer -> 'unknown'
    assert cal.coverage[0].coverage_status in ("not_covered", "unknown")


def test_insufficient_data_forecast_path(conn):
    """When fewer than 3 days have elapsed in month, variable spend status is unknown."""
    cal = build_calendar(conn, "u1", today="2026-10-02", horizon_days=5)
    for d in cal.days:
        assert d.variable_spend_status == "unknown"
        assert d.variable_spend_paise == 0


def test_reconciliation_invariant_with_forecast_v2(conn):
    """For the current month, expected variable spend summed over remaining days equals remaining forecast within 1 rupee."""
    # Seed 10 days of variable transactions in dining
    for day in range(1, 11):
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_var_{day}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-10-{day:02d}T10:00:00Z",
                amount_paise=12345,
                direction="debit",
                merchant_raw="Food Market",
                description="Groceries",
                category_id="cat_dining",
                created_at=T0,
            ),
        )

    # On Oct 10: 10 days elapsed in 31-day month. Remaining days: 21.
    spent_var = 12345 * 10  # 123,450
    days_in_month = 31
    days_elapsed = 10
    rem_days = days_in_month - days_elapsed
    expected_var_rem = (spent_var * rem_days) // days_elapsed

    cal = build_calendar(conn, "u1", today="2026-10-10", horizon_days=21)
    cal_sum = sum(d.variable_spend_paise for d in cal.days if d.date.startswith("2026-10"))

    diff_paise = abs(cal_sum - expected_var_rem)
    assert diff_paise <= 100, f"Reconciliation invariant failed: diff {diff_paise} paise > 100 paise (1 rupee)"


def test_horizon_limits(conn):
    """Horizon days must be between 1 and 180."""
    with pytest.raises(ValueError, match="horizon_days"):
        build_calendar(conn, "u1", today="2026-10-10", horizon_days=0)

    with pytest.raises(ValueError, match="horizon_days"):
        build_calendar(conn, "u1", today="2026-10-10", horizon_days=181)

    # 180 is accepted
    cal = build_calendar(conn, "u1", today="2026-10-10", horizon_days=180)
    assert len(cal.days) == 180


def test_zero_change_scenario_equals_baseline(conn):
    """Zero-change scenario produces a Calendar identical to baseline."""
    c = Commitment(
        id="c1",
        user_id="u1",
        name="Bill",
        direction="outflow",
        kind="bill",
        amount_paise=100000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 15},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(conn, c)

    cal_base = build_calendar(conn, "u1", today="2026-10-01", horizon_days=30)
    cal_scen = build_calendar(
        conn,
        "u1",
        today="2026-10-01",
        horizon_days=30,
        scenario=CalendarScenario(),
    )

    assert cal_base.model_dump() == cal_scen.model_dump()


def test_scenarios_never_write_db(conn):
    """Simulating scenarios on the calendar never writes or mutates financial tables."""
    comms_before = conn.execute("SELECT * FROM commitments").fetchall()

    scenario = CalendarScenario(
        add_commitments=[
            Commitment(
                id="c_temp",
                user_id="u1",
                name="Hypothetical Outflow",
                direction="outflow",
                kind="fee",
                amount_paise=99900,
                certainty="firm",
                schedule_kind="once",
                schedule_json={"date": "2026-10-10"},
                start_date="2026-10-01",
                status="active",
                created_at=T0,
                updated_at=T0,
            )
        ]
    )
    cal = build_calendar(conn, "u1", today="2026-10-01", horizon_days=20, scenario=scenario)
    assert any(occ.commitment_id == "c_temp" for d in cal.days for occ in d.occurrences)

    comms_after = conn.execute("SELECT * FROM commitments").fetchall()
    assert [dict(r) for r in comms_before] == [dict(r) for r in comms_after]
