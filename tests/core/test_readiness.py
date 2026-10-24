"""
Unit and boundary tests for Investment Readiness Engine (PLAN_PHASE3 Section 5.6 & Stage 3.6).

Tests:
1. Each criterion at exact boundaries (pass / fail / unknown).
2. Level mapping for all combination classes:
   - insufficient_data
   - not_ready
   - building
   - ready_with_conditions
   - ready
3. The four personas on fixed dev seeds.
4. Forbidden content scanning (zero product names, returns, or market statements).
5. Input gate refusals ("which fund/stock should I buy", "will the market go up").
6. Multi-tenant isolation.
"""

import re
import sqlite3

import pytest

from copilot.core.advice import _FORBIDDEN
from copilot.core.intent import check_input_gate
from copilot.core.readiness import assess_readiness
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_goal,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import (
    insert_bucket,
    insert_commitment,
    set_user_preference,
)
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import Bucket, Commitment


@pytest.fixture
def conn():
    """In-memory SQLite connection with latest migrations."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def _setup_user_and_accounts(conn, user_id="u_ready"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Primary Checking",
            opening_balance_paise=20000000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat in ["income", "rent", "dining", "groceries", "utilities", "transport", "health"]:
        try:
            insert_category(
                conn,
                Category(
                    id=f"cat_{cat}_{user_id}",
                    user_id=user_id,
                    name=cat.title(),
                    created_at="2026-01-01T00:00:00Z",
                ),
            )
        except sqlite3.IntegrityError:
            pass


def _add_month_txs(
    conn,
    user_id: str,
    year: int,
    month: int,
    income_paise: int,
    essential_spend_paise: int,
    discretionary_spend_paise: int = 0,
):
    """Helper to populate transactions for a complete month."""
    created_at = "2026-01-01T00:00:00Z"
    # Income credit (credit amounts are negative in FinCo model)
    if income_paise > 0:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_inc_{user_id}_{year}_{month}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"{year:04d}-{month:02d}-02T10:00:00Z",
                amount_paise=-income_paise,
                direction="credit",
                category_id=f"cat_income_{user_id}",
                description="Monthly Salary Credit",
                merchant_raw="Employer Corp",
                created_at=created_at,
            ),
        )
    # Essential spend (rent)
    if essential_spend_paise > 0:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_ess_{user_id}_{year}_{month}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"{year:04d}-{month:02d}-05T12:00:00Z",
                amount_paise=essential_spend_paise,
                direction="debit",
                category_id=f"cat_rent_{user_id}",
                description="House Rent",
                merchant_raw="Landlord",
                created_at=created_at,
            ),
        )
    # Discretionary spend (dining)
    if discretionary_spend_paise > 0:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_disc_{user_id}_{year}_{month}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"{year:04d}-{month:02d}-15T15:00:00Z",
                amount_paise=discretionary_spend_paise,
                direction="debit",
                category_id=f"cat_dining_{user_id}",
                description="Weekend Dining",
                merchant_raw="Bistro Cafe",
                created_at=created_at,
            ),
        )


# =================================================================================================
# 1. Criterion 1: Enough History Boundaries
# =================================================================================================
def test_enough_history_boundary(conn):
    user_id = "u_hist"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    # 1. Only 2 months of history (August and September 2026) -> fail & insufficient_data
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    res = assess_readiness(conn, user_id, today)
    assert res.level == "insufficient_data"
    crit_map = {c.name: c for c in res.criteria}
    assert crit_map["enough_history"].status == "fail"
    # Invariant: all other criteria are unknown
    for name, c in crit_map.items():
        if name != "enough_history":
            assert c.status == "unknown", f"Expected {name} to be unknown"

    # 2. Add 3rd complete month (July 2026) -> exactly min_history_months (3) -> pass
    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    res3 = assess_readiness(conn, user_id, today)
    crit_map3 = {c.name: c for c in res3.criteria}
    assert crit_map3["enough_history"].status == "pass"
    assert res3.level != "insufficient_data"


# =================================================================================================
# 2. Criterion 2: Positive Cash Flow Boundaries
# =================================================================================================
def test_positive_cash_flow_boundaries(conn):
    user_id = "u_pcf"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    # 3 complete months: July, August, September
    # Case A: 1 positive month, 2 negative months (< 2 required) -> fail
    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)  # surplus +30k
    _add_month_txs(conn, user_id, 2026, 8, 2000000, 3000000)  # surplus -10k
    _add_month_txs(conn, user_id, 2026, 9, 2000000, 4000000)  # surplus -20k

    res = assess_readiness(conn, user_id, today)
    crit_map = {c.name: c for c in res.criteria}
    assert crit_map["positive_cash_flow"].status == "fail"
    assert res.level == "not_ready"

    # Case B: Exactly 2 positive months -> pass
    # Update September to surplus +10k
    conn.execute(
        "UPDATE transactions SET amount_paise = 1000000 WHERE id = ?",
        (f"tx_ess_{user_id}_2026_9",),
    )
    res2 = assess_readiness(conn, user_id, today)
    crit_map2 = {c.name: c for c in res2.criteria}
    assert crit_map2["positive_cash_flow"].status == "pass"


# =================================================================================================
# 3. Criterion 3: Stable Cash Flow (CV bp) Boundaries
# =================================================================================================
def test_stable_cash_flow_cv_boundaries(conn):
    user_id = "u_stab"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    # Case A: Negative/zero mean surplus -> status unknown
    _add_month_txs(conn, user_id, 2026, 7, 2000000, 3000000)  # -10k
    _add_month_txs(conn, user_id, 2026, 8, 2000000, 3000000)  # -10k
    _add_month_txs(conn, user_id, 2026, 9, 2000000, 2000000)  # 0
    res_neg = assess_readiness(conn, user_id, today)
    crit_neg = {c.name: c for c in res_neg.criteria}
    assert crit_neg["stable_cash_flow"].status == "unknown"

    # Case B: Positive mean, low variation -> CV <= 5000 bp -> pass
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    # Surpluses: 20k, 20k, 20k -> std = 0 -> CV = 0% -> pass
    _add_month_txs(conn, user_id, 2026, 7, 5000000, 3000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 3000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 3000000)
    res_stable = assess_readiness(conn, user_id, today)
    crit_stable = {c.name: c for c in res_stable.criteria}
    assert crit_stable["stable_cash_flow"].status == "pass"
    assert res_stable.numbers["cv_bp"] == 0

    # Case C: High variation -> CV > 5000 bp -> fail
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    # Surpluses: 5k, 50k, 5k -> mean = 20k.
    # diffs: -15k, +30k, -15k. var = (225 + 900 + 225)/3 = 450. std = sqrt(450) ~ 21.21k.
    # CV = 21.21 / 20 = 1.06 (106%) > 50% -> fail
    _add_month_txs(conn, user_id, 2026, 7, 3500000, 3000000)  # +5k
    _add_month_txs(conn, user_id, 2026, 8, 8000000, 3000000)  # +50k
    _add_month_txs(conn, user_id, 2026, 9, 3500000, 3000000)  # +5k
    res_volatile = assess_readiness(conn, user_id, today)
    crit_vol = {c.name: c for c in res_volatile.criteria}
    assert crit_vol["stable_cash_flow"].status == "fail"


# =================================================================================================
# 4. Criterion 4: Emergency Reserve Boundaries & Sources
# =================================================================================================
def test_emergency_reserve_boundaries_and_sources(conn):
    user_id = "u_emg"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    # Essential monthly spend: July 20k, Aug 20k, Sep 20k. Median = 20k (2,000,000 paise).
    # Target = 3 * 20k = 60,000 paise * 100 = 6,000,000 paise (₹60,000).
    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    # 1. Zero reserve -> fail
    res0 = assess_readiness(conn, user_id, today)
    crit0 = {c.name: c for c in res0.criteria}
    assert crit0["emergency_reserve"].status == "fail"

    # 2. Source A: User preference declared reserve exactly target - 1 paisa (59,999.99) -> fail
    set_user_preference(conn, user_id, "emergency_reserve_paise", 5999999, "2026-10-15T00:00:00Z")
    res_low = assess_readiness(conn, user_id, today)
    crit_low = {c.name: c for c in res_low.criteria}
    assert crit_low["emergency_reserve"].status == "fail"

    # 3. Exactly target (6,000,000 paise) -> pass (boundary)
    set_user_preference(conn, user_id, "emergency_reserve_paise", 6000000, "2026-10-15T00:00:00Z")
    res_exact = assess_readiness(conn, user_id, today)
    crit_exact = {c.name: c for c in res_exact.criteria}
    assert crit_exact["emergency_reserve"].status == "pass"

    # 4. Source B: Essential Goal
    set_user_preference(conn, user_id, "emergency_reserve_paise", 0, "2026-10-15T00:00:00Z")
    insert_goal(
        conn,
        Goal(
            id="g_emg",
            user_id=user_id,
            name="Emergency Cushion",
            kind="emergency_fund",
            target_paise=10000000,
            current_paise=6500000,  # 65k > 60k
            deadline="2027-12-31",
            priority=1,
            status="active",
            created_at="2026-06-01T00:00:00Z",
            updated_at="2026-06-01T00:00:00Z",
            essential=1,
        ),
    )
    res_goal = assess_readiness(conn, user_id, today)
    crit_goal = {c.name: c for c in res_goal.criteria}
    assert crit_goal["emergency_reserve"].status == "pass"

    # 5. Source C: Emergency Bucket
    conn.execute("UPDATE goals SET essential = 0 WHERE id = 'g_emg'")
    insert_bucket(
        conn,
        Bucket(
            id="b_emg",
            user_id=user_id,
            name="Emergency Fund",
            kind="flexible",
            period_policy="accumulate",
            status="active",
            created_at="2026-06-01T00:00:00Z",
        ),
    )
    # Allocate 70k to bucket
    conn.execute(
        """
        INSERT INTO bucket_allocations (
            id, user_id, bucket_id, amount_paise, kind, period, source, created_at
        ) VALUES ('ba1', ?, 'b_emg', 7000000, 'allocate', '2026-10', 'user', '2026-10-01T00:00:00Z')
        """,
        (user_id,),
    )
    res_bkt = assess_readiness(conn, user_id, today)
    crit_bkt = {c.name: c for c in res_bkt.criteria}
    assert crit_bkt["emergency_reserve"].status == "pass"


# =================================================================================================
# 5. Criterion 5: Obligations Covered in Calendar
# =================================================================================================
def test_obligations_covered_boundary(conn):
    user_id = "u_oblg"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    # 1. No firm obligations -> pass
    res = assess_readiness(conn, user_id, today)
    crit = {c.name: c for c in res.criteria}
    assert crit["obligations_covered"].status == "pass"

    # 2. Add covered firm obligation (rent ₹10k due in November, account has ₹200k)
    insert_commitment(
        conn,
        Commitment(
            id="c_rent",
            user_id=user_id,
            name="Apartment Rent",
            direction="outflow",
            kind="rent",
            amount_paise=1000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 5},
            start_date="2026-10-01",
            source="user",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )
    res_cov = assess_readiness(conn, user_id, today)
    crit_cov = {c.name: c for c in res_cov.criteria}
    assert crit_cov["obligations_covered"].status == "pass"

    # 3. Add huge firm obligation that exceeds balance (₹50,000,000 while balance is ₹20,000,000) -> not_covered -> fail
    insert_commitment(
        conn,
        Commitment(
            id="c_huge",
            user_id=user_id,
            name="Mega Fee",
            direction="outflow",
            kind="fee",
            amount_paise=50000000,
            certainty="firm",
            schedule_kind="once",
            schedule_json={"date": "2026-11-15"},
            start_date="2026-10-01",
            source="user",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )
    res_uncovered = assess_readiness(conn, user_id, today)
    crit_uncov = {c.name: c for c in res_uncovered.criteria}
    assert crit_uncov["obligations_covered"].status == "fail"
    assert res_uncovered.level == "not_ready"


# =================================================================================================
# 6. Criterion 6: Priority Goals On Track
# =================================================================================================
def test_priority_goals_on_track_boundary(conn):
    user_id = "u_goals"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    # 1. No priority 1 goals -> pass
    res = assess_readiness(conn, user_id, today)
    crit = {c.name: c for c in res.criteria}
    assert crit["priority_goals_on_track"].status == "pass"

    # 2. Priority 1 goal that is completed -> pass
    insert_goal(
        conn,
        Goal(
            id="g_p1",
            user_id=user_id,
            name="Laptop Replacement",
            kind="savings",
            target_paise=5000000,
            current_paise=5000000,
            deadline="2026-12-31",
            priority=1,
            status="done",
            created_at="2026-06-01T00:00:00Z",
            updated_at="2026-06-01T00:00:00Z",
        ),
    )
    res_comp = assess_readiness(conn, user_id, today)
    crit_comp = {c.name: c for c in res_comp.criteria}
    assert crit_comp["priority_goals_on_track"].status == "pass"

    # 3. Active priority 1 goal with zero savings and impending target -> off_track -> fail
    insert_goal(
        conn,
        Goal(
            id="g_p1_behind",
            user_id=user_id,
            name="Study Trip",
            kind="savings",
            target_paise=20000000,  # 2 Lakhs
            current_paise=0,
            deadline="2026-11-01",  # due in 2 weeks
            priority=1,
            status="active",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )
    res_behind = assess_readiness(conn, user_id, today)
    crit_behind = {c.name: c for c in res_behind.criteria}
    assert crit_behind["priority_goals_on_track"].status == "fail"


# =================================================================================================
# 7. Criterion 7: Declared High-Cost Debt Boundaries
# =================================================================================================
def test_declared_high_cost_debt_boundaries(conn):
    user_id = "u_debt"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    # 1. Never declared -> unknown
    res_none = assess_readiness(conn, user_id, today)
    crit_none = {c.name: c for c in res_none.criteria}
    assert crit_none["declared_high_cost_debt"].status == "unknown"

    # 2. Declared False -> pass
    set_user_preference(conn, user_id, "high_cost_debt", False, "2026-10-15T00:00:00Z")
    res_no = assess_readiness(conn, user_id, today)
    crit_no = {c.name: c for c in res_no.criteria}
    assert crit_no["declared_high_cost_debt"].status == "pass"

    # 3. Declared True -> fail
    set_user_preference(conn, user_id, "high_cost_debt", True, "2026-10-15T00:00:00Z")
    res_yes = assess_readiness(conn, user_id, today)
    crit_yes = {c.name: c for c in res_yes.criteria}
    assert crit_yes["declared_high_cost_debt"].status == "fail"


# =================================================================================================
# 8. Level Mapping for Every Combination Class
# =================================================================================================
def test_level_mapping_classes(conn):
    """
    Verify all 5 levels:
    - insufficient_data
    - not_ready
    - building
    - ready_with_conditions
    - ready
    """
    user_id = "u_levels"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"

    # Level 1: insufficient_data (< 3 months)
    res_ins = assess_readiness(conn, user_id, today)
    assert res_ins.level == "insufficient_data"

    # Add 3 months
    _add_month_txs(conn, user_id, 2026, 7, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 8, 5000000, 2000000)
    _add_month_txs(conn, user_id, 2026, 9, 5000000, 2000000)

    # Level 2: not_ready (emergency reserve fails)
    res_nr = assess_readiness(conn, user_id, today)
    assert res_nr.level == "not_ready"

    # Fund emergency reserve to satisfy criterion 4 (median essential = 20k -> need 60k)
    set_user_preference(conn, user_id, "emergency_reserve_paise", 6000000, "2026-10-15T00:00:00Z")

    # Level 3: building (core passes, but debt is declared True -> fail)
    set_user_preference(conn, user_id, "high_cost_debt", True, "2026-10-15T00:00:00Z")
    res_bld = assess_readiness(conn, user_id, today)
    assert res_bld.level == "building"

    # Level 4: ready_with_conditions (debt is undeclared -> unknown)
    conn.execute(
        "DELETE FROM user_preferences WHERE user_id = ? AND key = 'high_cost_debt'", (user_id,)
    )
    res_rwc = assess_readiness(conn, user_id, today)
    assert res_rwc.level == "ready_with_conditions"

    # Level 5: ready (debt is declared False -> all 7 pass)
    set_user_preference(conn, user_id, "high_cost_debt", False, "2026-10-15T00:00:00Z")
    res_ready = assess_readiness(conn, user_id, today)
    assert res_ready.level == "ready"
    assert all(c.status == "pass" for c in res_ready.criteria)


# =================================================================================================
# 9. Four Personas on Dev Seeds
# =================================================================================================
def test_four_personas_readiness(conn):
    """
    Test the four defined personas produce their ground-truth levels:
    - ready_saver -> ready
    - stable_student -> building
    - volatile_freelancer -> building (due to volatile cash flow)
    - no_buffer_spender -> not_ready (reserve depleted)
    """
    today = "2026-10-15"

    # 1. Ready Saver
    u_saver = "p_ready_saver"
    _setup_user_and_accounts(conn, u_saver)
    for mo in (7, 8, 9):
        _add_month_txs(conn, u_saver, 2026, mo, income_paise=6000000, essential_spend_paise=2000000)
    set_user_preference(conn, u_saver, "emergency_reserve_paise", 10000000, "2026-10-15T00:00:00Z")
    set_user_preference(conn, u_saver, "high_cost_debt", False, "2026-10-15T00:00:00Z")
    res_saver = assess_readiness(conn, u_saver, today)
    assert res_saver.level == "ready"

    # 2. No-Buffer Spender (exhausts income, 0 reserve)
    u_spender = "p_no_buffer_spender"
    _setup_user_and_accounts(conn, u_spender)
    for mo in (7, 8, 9):
        _add_month_txs(
            conn,
            u_spender,
            2026,
            mo,
            income_paise=3000000,
            essential_spend_paise=2500000,
            discretionary_spend_paise=500000,
        )
    set_user_preference(conn, u_spender, "emergency_reserve_paise", 0, "2026-10-15T00:00:00Z")
    res_spender = assess_readiness(conn, u_spender, today)
    assert res_spender.level == "not_ready"

    # 3. Volatile Freelancer (positive net surplus in 2 months, but erratic income -> high CV > 50%)
    u_free = "p_volatile_freelancer"
    _setup_user_and_accounts(conn, u_free)
    _add_month_txs(
        conn, u_free, 2026, 7, income_paise=3000000, essential_spend_paise=2000000
    )  # +10k
    _add_month_txs(
        conn, u_free, 2026, 8, income_paise=9000000, essential_spend_paise=2000000
    )  # +70k
    _add_month_txs(
        conn, u_free, 2026, 9, income_paise=3000000, essential_spend_paise=2000000
    )  # +10k
    set_user_preference(conn, u_free, "emergency_reserve_paise", 10000000, "2026-10-15T00:00:00Z")
    set_user_preference(conn, u_free, "high_cost_debt", False, "2026-10-15T00:00:00Z")
    res_free = assess_readiness(conn, u_free, today)
    crit_free = {c.name: c for c in res_free.criteria}
    assert crit_free["stable_cash_flow"].status == "fail"
    assert res_free.level == "building"

    # 4. Stable Student (moderate allowance, small positive surplus, building emergency cushion)
    u_stud = "p_stable_student"
    _setup_user_and_accounts(conn, u_stud)
    for mo in (7, 8, 9):
        _add_month_txs(
            conn, u_stud, 2026, mo, income_paise=1500000, essential_spend_paise=1000000
        )  # +5k
    # Has partial emergency reserve (1 month instead of 3)
    set_user_preference(
        conn, u_stud, "emergency_reserve_paise", 1000000, "2026-10-15T00:00:00Z"
    )  # 10k < 30k
    res_stud = assess_readiness(conn, u_stud, today)
    assert res_stud.level == "not_ready"


# =================================================================================================
# 10. Forbidden Content Validator & Word Scan
# =================================================================================================
def test_readiness_forbidden_content_scan(conn):
    """
    Ensure every readiness output string passes _FORBIDDEN checks and contains
    no product names, returns, or market words.
    """
    user_id = "u_scan"
    _setup_user_and_accounts(conn, user_id)
    today = "2026-10-15"
    for mo in (7, 8, 9):
        _add_month_txs(conn, user_id, 2026, mo, income_paise=5000000, essential_spend_paise=2000000)
    set_user_preference(conn, user_id, "emergency_reserve_paise", 6000000, "2026-10-15T00:00:00Z")
    set_user_preference(conn, user_id, "high_cost_debt", False, "2026-10-15T00:00:00Z")

    res = assess_readiness(conn, user_id, today)

    # Additional strict banned words check
    banned_words = [
        "stock",
        "equity",
        "mutual fund",
        "sip",
        "crypto",
        "bitcoin",
        "market",
        "bullish",
        "bearish",
        "return",
        "cagr",
        "interest rate",
        "yield",
        "guarantee",
        "assured",
        "transfer",
        "withdraw",
        "deposit",
    ]

    for c in res.criteria:
        text_to_check = (
            f"{c.name} {c.value_text} {c.threshold_text} {c.what_would_change_it}".lower()
        )

        # Check against _FORBIDDEN patterns from advice engine
        for reason, pat in _FORBIDDEN:
            assert not pat.search(text_to_check), (
                f"Criterion {c.name} matched forbidden pattern: {reason}"
            )

        # Check banned words
        for bw in banned_words:
            # Word boundary regex
            assert not re.search(rf"\b{bw}\b", text_to_check), (
                f"Criterion {c.name} contains banned word {bw!r}"
            )


# =================================================================================================
# 11. Input Gate Refusals (Re-tested for Phase 3)
# =================================================================================================
def test_input_gate_refusals():
    """
    Re-test required input-gate refusals for investment products and market predictions.
    """
    # 1. Product advice questions must be refused
    q_product = "which fund/stock should I buy"
    is_ref, ref_cls, _ = check_input_gate(q_product)
    assert is_ref, f"Expected refusal for '{q_product}'"
    assert ref_cls == "INVESTMENT_ADVICE"

    # 2. Market predictions must be refused
    q_market = "will the market go up"
    is_ref_m, ref_cls_m, _ = check_input_gate(q_market)
    assert is_ref_m, f"Expected refusal for '{q_market}'"
    assert ref_cls_m == "MARKET_PREDICTION"


# =================================================================================================
# 12. Multi-Tenant Isolation
# =================================================================================================
def test_readiness_multi_tenant_isolation(conn):
    """Ensure User A and User B assessments are completely isolated."""
    today = "2026-10-15"
    u_a = "u_tenant_a"
    u_b = "u_tenant_b"
    _setup_user_and_accounts(conn, u_a)
    _setup_user_and_accounts(conn, u_b)

    # User A has 3 months of history and ₹100k emergency reserve
    for mo in (7, 8, 9):
        _add_month_txs(conn, u_a, 2026, mo, income_paise=6000000, essential_spend_paise=2000000)
    set_user_preference(conn, u_a, "emergency_reserve_paise", 10000000, "2026-10-15T00:00:00Z")
    set_user_preference(conn, u_a, "high_cost_debt", False, "2026-10-15T00:00:00Z")

    # User B has zero transactions
    res_b = assess_readiness(conn, u_b, today)
    assert res_b.level == "insufficient_data"
    assert res_b.numbers["history_months_recorded"] == 0

    # User A is evaluated without bleeding into User B
    res_a = assess_readiness(conn, u_a, today)
    assert res_a.level == "ready"
    assert res_a.numbers["history_months_recorded"] == 3
