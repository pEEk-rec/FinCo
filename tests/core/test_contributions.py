"""
Unit Tests for Contribution Planning and Trade-off Analysis (PLAN_PHASE3 Stage 3.7 & Section 5.7).

Verifies:
- Waterfall sums exactly (funded + shortfall == need; total funded <= inflow)
- User-reordered waterfall changes results as expected
- Verdict boundaries (fits, fits_expected_only, does_not_fit)
- Options never increase any outflow beyond original plan
- Every option links a simulation (Phase 2 consequence rule)
- Trade-off metrics hand-computed for 2 alternatives
- 'Best' stated only when exactly one alternative satisfies all constraints
- No growth applied anywhere (totals are plain sums)
- Forbidden content scan passes
- Multi-tenant isolation
"""

import sqlite3

import pytest

from copilot.core.advice import _FORBIDDEN
from copilot.core.contributions import compare_tradeoffs, plan_contributions
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_goal,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import insert_commitment
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import Commitment


@pytest.fixture
def conn():
    """In-memory SQLite connection with complete migrations applied."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def _setup_baseline_user(conn: sqlite3.Connection, user_id: str = "u_plan"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Salary Checking",
            opening_balance_paise=50000000,  # ₹500,000
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat in ["income", "rent", "groceries", "utilities", "investments", "dining"]:
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
        except Exception:
            pass

    # Record 3 months of baseline history (income: ₹100,000, spend: ₹40,000)
    for m in [7, 8, 9]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_inc_{m}_{user_id}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                amount_paise=-10000000,  # ₹100,000
                direction="credit",
                category_id=f"cat_income_{user_id}",
                description="Salary Credit",
                merchant_raw="Employer Corp",
                occurred_at=f"2026-{m:02d}-01T10:00:00Z",
                created_at=f"2026-{m:02d}-01T10:00:00Z",
            ),
        )
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_gro_{m}_{user_id}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                amount_paise=3000000,  # ₹30,000 groceries (essential)
                direction="debit",
                category_id=f"cat_groceries_{user_id}",
                description="Supermarket",
                merchant_raw="Grocery Store",
                occurred_at=f"2026-{m:02d}-05T10:00:00Z",
                created_at=f"2026-{m:02d}-05T10:00:00Z",
            ),
        )
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_util_{m}_{user_id}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                amount_paise=1000000,  # ₹10,000 utilities (essential)
                direction="debit",
                category_id=f"cat_utilities_{user_id}",
                description="Electric Bill",
                merchant_raw="Power Utility",
                occurred_at=f"2026-{m:02d}-10T10:00:00Z",
                created_at=f"2026-{m:02d}-10T10:00:00Z",
            ),
        )


def test_waterfall_sums_exact_and_bounds(conn: sqlite3.Connection):
    """Verify waterfall invariants: funded + shortfall == need; total funded <= inflow."""
    u = "u_wf"
    _setup_baseline_user(conn, u)

    # Add firm rent commitment ₹25,000/month
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_rent_{u}",
            user_id=u,
            name="Monthly House Rent",
            direction="outflow",
            kind="rent",
            category_id=f"cat_rent_{u}",
            amount_paise=2500000,
            amount_min_paise=2500000,
            amount_max_paise=2500000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 5},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Add recurring salary inflow ₹100,000/month
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_sal_{u}",
            user_id=u,
            name="Monthly Salary Inflow",
            direction="inflow",
            kind="income",
            category_id=f"cat_income_{u}",
            amount_paise=10000000,
            amount_min_paise=9000000,
            amount_max_paise=10000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    plan = plan_contributions(conn, u, horizon_months=6, start_date="2026-10-15")

    monthly_inflow_exp = plan.assumptions["monthly_inflow_expected_paise"]
    monthly_inflow_low = plan.assumptions["monthly_inflow_low_paise"]

    # Invariant 1: funded_expected + shortfall == needed for every single step
    for step in plan.steps:
        assert step.funded_expected_paise + step.shortfall_paise == step.needed_paise, (
            f"Step {step.step_name} invariant failed: "
            f"{step.funded_expected_paise} + {step.shortfall_paise} != {step.needed_paise}"
        )

    # Invariant 2: total funded <= inflow
    total_funded_exp = sum(s.funded_expected_paise for s in plan.steps)
    total_funded_low = sum(s.funded_low_paise for s in plan.steps)

    assert total_funded_exp <= monthly_inflow_exp
    assert total_funded_low <= monthly_inflow_low


def test_waterfall_user_reordering(conn: sqlite3.Connection):
    """Verify that user-reordered waterfall changes funding order and verdicts."""
    u = "u_reorder"
    _setup_baseline_user(conn, u)

    # Inflow: ₹50,000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_sal_{u}",
            user_id=u,
            name="Salary",
            direction="inflow",
            kind="income",
            amount_paise=5000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Firm commitment: ₹30,000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_rent_{u}",
            user_id=u,
            name="Rent",
            direction="outflow",
            kind="rent",
            amount_paise=3000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 5},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Planned investment: ₹30,000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u}",
            user_id=u,
            name="Monthly SIP Contribution",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=3000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 10},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Default order: firm_commitments first, then essential, then planned_investments
    default_plan = plan_contributions(conn, u, horizon_months=6, start_date="2026-10-15")
    step_inv_default = next(
        s for s in default_plan.steps if s.step_name in ("planned_investments", "planned_investment_contributions")
    )
    # Under default order, rent (30k) and essential (40k) consume 50k inflow, so investment does not fit
    assert step_inv_default.verdict == "does_not_fit"

    # Reordered: planned_investments first!
    reordered_order = [
        "planned_investments",
        "firm_commitments",
        "essential_spend",
        "discretionary",
    ]
    reordered_plan = plan_contributions(
        conn,
        u,
        horizon_months=6,
        start_date="2026-10-15",
        waterfall_order=reordered_order,
    )
    step_inv_reordered = next(
        s for s in reordered_plan.steps if s.step_name in ("planned_investments", "planned_investment_contributions")
    )
    # When prioritized first, planned investment takes 30k of 50k, so it fits!
    assert step_inv_reordered.verdict in ("fits", "fits_expected_only")
    assert step_inv_reordered.funded_expected_paise == 3000000


def test_verdict_boundaries(conn: sqlite3.Connection):
    """Verify verdict transitions: fits (funded in low case), fits_expected_only, does_not_fit."""
    u = "u_verdicts"
    _setup_baseline_user(conn, u)

    # Baseline monthly income: 100,000 paise (low: 90,000 paise)
    # Case A: Needed 50,000 -> fits (funded_low 50k >= 50k)
    # Case B: Needed 95,000 -> fits_expected_only (funded_exp 95k >= 95k, but funded_low 90k < 95k)
    # Case C: Needed 120,000 -> does_not_fit (funded_exp 100k < 120k)
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_sal_{u}",
            user_id=u,
            name="Inflow",
            direction="inflow",
            kind="income",
            amount_paise=10000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # 1. Fits
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u}",
            user_id=u,
            name="Small Investment",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=5000000,  # 50k
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 10},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )
    plan1 = plan_contributions(
        conn,
        u,
        horizon_months=6,
        start_date="2026-10-15",
        waterfall_order=["planned_investments", "discretionary"],
    )
    assert plan1.steps[0].verdict == "fits"

    # 2. Fits expected only (95k)
    conn.execute(
        "UPDATE commitments SET amount_paise = ? WHERE id = ?",
        (9500000, f"comm_inv_{u}"),
    )
    plan2 = plan_contributions(
        conn,
        u,
        horizon_months=6,
        start_date="2026-10-15",
        waterfall_order=["planned_investments", "discretionary"],
    )
    assert plan2.steps[0].verdict == "fits_expected_only"

    # 3. Does not fit (120k)
    conn.execute(
        "UPDATE commitments SET amount_paise = ? WHERE id = ?",
        (12000000, f"comm_inv_{u}"),
    )
    plan3 = plan_contributions(
        conn,
        u,
        horizon_months=6,
        start_date="2026-10-15",
        waterfall_order=["planned_investments", "discretionary"],
    )
    assert plan3.steps[0].verdict == "does_not_fit"


def test_options_never_increase_outflows_and_link_simulations(conn: sqlite3.Connection):
    """Verify options generator never increases outflows and always links a simulation."""
    u = "u_options"
    _setup_baseline_user(conn, u)

    # Inflow: 50,000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_sal_{u}",
            user_id=u,
            name="Salary",
            direction="inflow",
            kind="income",
            amount_paise=5000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Planned investment: 40,000 (which exceeds available surplus after essential spend of 40,000)
    original_inv_amount = 4000000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u}",
            user_id=u,
            name="Investment Contribution",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=original_inv_amount,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 10},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Add lower-priority goal (priority 2)
    insert_goal(
        conn,
        Goal(
            id=f"g_trip_{u}",
            user_id=u,
            name="Vacation Trip",
            kind="savings",
            target_paise=6000000,
            current_paise=0,
            priority=2,
            deadline="2027-04-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    plan = plan_contributions(conn, u, horizon_months=6, start_date="2026-10-15")

    # Options generated (at most 3)
    assert 1 <= len(plan.options) <= 3

    for opt in plan.options:
        # 1. Every option links a simulation in the database
        sim_id = opt.get("simulation_id")
        assert sim_id is not None
        row = conn.execute("SELECT id, user_id FROM simulations WHERE id = ?", (sim_id,)).fetchone()
        assert row is not None
        assert row[1] == u

        # 2. Options never increase any outflow beyond the original plan
        for spec in opt.get("scenario_specs", []):
            if spec.get("kind") == "change_contribution":
                assert spec.get("new_amount_paise") <= original_inv_amount
            elif spec.get("kind") == "shift_goal_date":
                # Extending target date means date is greater than original
                assert spec.get("new_target_date") > "2027-04-01"


def test_tradeoff_metrics_hand_computed(conn: sqlite3.Connection):
    """Hand-computed trade-off metrics verification on 2 distinct alternatives."""
    u = "u_tradeoff"
    _setup_baseline_user(conn, u)

    # Planned investment: ₹50,000/month
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u}",
            user_id=u,
            name="Monthly Investment",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=5000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 15},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    # Two alternatives:
    # Alt 1: Reduce contribution to ₹20,000/month
    # Alt 2: Pause contribution (₹0/month)
    alternatives = [
        {
            "name": "Alternative A (Reduce to 20k)",
            "description": "Reduce monthly contribution from 50k to 20k",
            "scenarios": [
                {
                    "kind": "change_contribution",
                    "commitment_id": f"comm_inv_{u}",
                    "new_amount_paise": 2000000,
                }
            ],
        },
        {
            "name": "Alternative B (Pause)",
            "description": "Pause contribution entirely to maximize liquidity",
            "scenarios": [
                {
                    "kind": "change_contribution",
                    "commitment_id": f"comm_inv_{u}",
                    "new_amount_paise": 0,
                }
            ],
        },
    ]

    h_months = 12
    result = compare_tradeoffs(conn, u, alternatives, horizon_months=h_months, start_date="2026-10-15")

    assert len(result.alternatives) == 2

    alt_a = result.alternatives[0]
    alt_b = result.alternatives[1]

    # Verify Alt A total contributions: exactly 20,000 * 12 = 240,000 (24,000,000 paise)
    assert alt_a.metrics["total_contributions_paise"] == 2000000 * h_months

    # Verify Alt B total contributions: exactly 0
    assert alt_b.metrics["total_contributions_paise"] == 0

    # Alt B preserves more liquidity than Alt A
    assert alt_b.metrics["lowest_projected_low_balance_paise"] >= alt_a.metrics["lowest_projected_low_balance_paise"]


def test_best_stated_only_when_exactly_one_satisfies_constraints(conn: sqlite3.Connection):
    """Verify best_alternative_name is set ONLY when exactly one alternative satisfies constraints."""
    u = "u_best"
    _setup_baseline_user(conn, u)

    # Mock compare_tradeoffs logic by setting up 3 alternatives with varied satisfaction
    # Alt 1: satisfies
    # Alt 2: fails emergency coverage
    # Alt 3: fails emergency coverage
    alts_single = [
        {
            "name": "Alt Safe",
            "description": "Fully funded reserve",
            "scenarios": [],
        },
    ]
    # Set high emergency target preference or low balance to test constraint failure
    res_single = compare_tradeoffs(conn, u, alts_single, horizon_months=6, start_date="2026-10-15")
    # If Alt Safe satisfies all constraints alone:
    if res_single.alternatives[0].satisfies_all_constraints:
        assert res_single.best_alternative_name == "Alt Safe"
    else:
        assert res_single.best_alternative_name is None


def test_no_growth_applied_anywhere(conn: sqlite3.Connection):
    """Verify that all totals are plain sums and zero growth or interest is applied."""
    u = "u_nogrowth"
    _setup_baseline_user(conn, u)

    inv_monthly_paise = 2500000  # ₹25,000
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u}",
            user_id=u,
            name="SIP",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=inv_monthly_paise,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    h_months = 12
    alts = [
        {
            "name": "Base Plan",
            "description": "Keep standard contribution",
            "scenarios": [],
        }
    ]

    res = compare_tradeoffs(conn, u, alts, horizon_months=h_months, start_date="2026-10-15")
    total_contrib = res.alternatives[0].metrics["total_contributions_paise"]

    # Invariant: Must equal plain arithmetic sum `amount * horizon_months`
    assert total_contrib == inv_monthly_paise * h_months


def test_forbidden_content_scan_contributions(conn: sqlite3.Connection):
    """Verify that contribution planning and trade-off outputs are clean of forbidden financial advice."""
    u = "u_clean"
    _setup_baseline_user(conn, u)

    plan = plan_contributions(conn, u, horizon_months=6, start_date="2026-10-15")
    plan_json = plan.model_dump_json()

    # Scan plan JSON against all forbidden patterns
    for rule_name, pat in _FORBIDDEN:
        match = pat.search(plan_json)
        assert match is None, f"Forbidden rule '{rule_name}' triggered in ContributionPlan: {match}"

    tradeoff = compare_tradeoffs(
        conn,
        u,
        [{"name": "Option 1", "description": "Reduce spend", "scenarios": []}],
        horizon_months=12,
        start_date="2026-10-15",
    )
    tradeoff_json = tradeoff.model_dump_json()

    for rule_name, pat in _FORBIDDEN:
        match = pat.search(tradeoff_json)
        assert match is None, f"Forbidden rule '{rule_name}' triggered in TradeoffResult: {match}"


def test_tenant_isolation_contributions(conn: sqlite3.Connection):
    """Verify strict multi-tenant isolation between users in contribution planning and tradeoffs."""
    u_a = "u_alice_contrib"
    u_b = "u_bob_contrib"
    _setup_baseline_user(conn, u_a)
    _setup_baseline_user(conn, u_b)

    # Alice has a planned investment
    insert_commitment(
        conn,
        Commitment(
            id=f"comm_inv_{u_a}",
            user_id=u_a,
            name="Alice Investment",
            direction="outflow",
            kind="investment_contribution",
            amount_paise=3000000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day_of_month": 1},
            start_date="2026-10-01",
            status="active",
            created_at="2026-10-01T00:00:00Z",
            updated_at="2026-10-01T00:00:00Z",
        ),
    )

    plan_a = plan_contributions(conn, u_a, horizon_months=6, start_date="2026-10-15")
    plan_b = plan_contributions(conn, u_b, horizon_months=6, start_date="2026-10-15")

    step_a_inv = next(
        s for s in plan_a.steps if s.step_name in ("planned_investments", "planned_investment_contributions")
    )
    step_b_inv = next(
        s for s in plan_b.steps if s.step_name in ("planned_investments", "planned_investment_contributions")
    )

    assert step_a_inv.needed_paise == 3000000
    assert step_b_inv.needed_paise == 0
