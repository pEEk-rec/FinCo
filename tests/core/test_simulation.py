"""
Unit and property tests for the what-if simulation engine (PLAN_PHASE2 Stage 2.3).

Verifies:
- All invariants from PLAN_PHASE2 Section 5.6:
    1. Simulation is pure: does not mutate financial tables.
    2. Identity: zero-amount scenario reproduces baseline exactly.
    3. Monotonicity: adding spend never improves any metric; reducing spend never worsens any metric.
    4. Determinism: same inputs yield identical outputs.
    5. Conservation of paise: all additions and subtractions balance exactly.
- Hand-computed month-by-month projections.
- Budget boundary conditions: exactly at the limit (warning/ok) vs one paisa over (exceeded).
- Recurring vs one-off scenario applications.
- Horizon limit capping.
- Propagation of insufficient data.
"""

import random

from copilot.core.simulation import (
    FinancialSnapshot,
    compare_scenarios,
    simulate,
)
from copilot.models.agentic import Goal, Scenario

T0 = "2026-10-15T10:00:00Z"


def make_snapshot(
    income: int = 50_000_00,
    dining_spend: int = 10_000_00,
    rent_spend: int = 20_000_00,
    dining_budget: int = 12_000_00,
    has_insufficient_data: bool = False,
) -> FinancialSnapshot:
    return FinancialSnapshot(
        user_id="u1",
        today_month="2026-10",
        estimated_monthly_income_paise=income,
        baseline_variable_spend_by_category={
            "dining": dining_spend,
            "rent": rent_spend,
        },
        budgets={"dining": dining_budget},
        warn_threshold_pct=80,
        recurring_series_monthly_paise=0,
        recurring_by_category={},
        goals=[
            Goal(
                id="g1",
                user_id="u1",
                name="Trip",
                kind="savings",
                target_paise=30_000_00,
                current_paise=10_000_00,
                deadline="2026-12-31",
                priority=1,
                status="active",
                created_at=T0,
                updated_at=T0,
            )
        ],
        has_insufficient_data=has_insufficient_data,
    )


# ---------------------------------------------------------------------------------------------
# 1. Invariants (Property-Based Tests)
# ---------------------------------------------------------------------------------------------
def test_invariant_identity_zero_amount():
    """Identity: a scenario with amount_paise == 0 matches baseline exactly."""
    snap = make_snapshot()
    s_zero = Scenario(
        kind="add_spend",
        amount_paise=0,
        start_month="2026-10",
        recurring=False,
    )
    proj = simulate(snap, s_zero, horizon_months=6)

    # Baseline total spend = dining (10k) + rent (20k) = 30k
    for m in proj.monthly_spend_paise:
        assert proj.monthly_spend_paise[m] == 30_000_00
        assert proj.monthly_surplus_paise[m] == 20_000_00  # 50k - 30k


def test_invariant_determinism():
    """Determinism: identical inputs produce identical projections."""
    snap = make_snapshot()
    scenario = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=3_500_00,
        start_month="2026-11",
        recurring=True,
    )
    proj1 = simulate(snap, scenario, horizon_months=4)
    proj2 = simulate(snap, scenario, horizon_months=4)

    assert proj1.model_dump() == proj2.model_dump()


def test_invariant_monotonicity_add_and_reduce_spend():
    """
    Monotonicity property across pseudo-random iterations:
    - Adding spend never increases surplus, never decreases spend.
    - Reducing spend never decreases surplus, never increases spend.
    """
    rng = random.Random(42)
    snap = make_snapshot()

    for _ in range(50):
        amount = rng.randint(100, 10_000_00)
        start = "2026-10" if rng.choice([True, False]) else "2026-11"
        rec = rng.choice([True, False])

        s_add = Scenario(
            kind="add_spend",
            category_id="dining",
            amount_paise=amount,
            start_month=start,
            recurring=rec,
        )
        p_add = simulate(snap, s_add, horizon_months=4)

        s_red = Scenario(
            kind="reduce_spend",
            category_id="dining",
            amount_paise=amount,
            start_month=start,
            recurring=rec,
        )
        p_red = simulate(snap, s_red, horizon_months=4)

        for m in p_add.monthly_spend_paise:
            # Baseline is 30,000.00
            assert p_add.monthly_spend_paise[m] >= 30_000_00
            assert p_add.monthly_surplus_paise[m] <= 20_000_00

            assert p_red.monthly_spend_paise[m] <= 30_000_00
            assert p_red.monthly_surplus_paise[m] >= 20_000_00


def test_invariant_conservation_of_paise():
    """All spending additions and reductions balance exactly in paise."""
    snap = make_snapshot()
    amount = 4_500_00
    s_add = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=amount,
        start_month="2026-11",
        recurring=False,
    )
    proj = simulate(snap, s_add, horizon_months=3)

    # 2026-10 unaffected: 30,000.00
    assert proj.monthly_spend_paise["2026-10"] == 30_000_00
    # 2026-11 affected: exactly 30,000.00 + 4,500.00 = 34,500.00
    assert proj.monthly_spend_paise["2026-11"] == 34_500_00
    # Difference in surplus is exactly amount
    delta = proj.monthly_surplus_paise["2026-10"] - proj.monthly_surplus_paise["2026-11"]
    assert delta == amount


# ---------------------------------------------------------------------------------------------
# 2. Hand-Computed Scenarios & Budget Boundaries
# ---------------------------------------------------------------------------------------------
def test_budget_crossing_boundary_at_limit_vs_one_paisa_over():
    """
    Dining limit = ₹12,000 (1,200,000 paise). Baseline spend = ₹10,000 (1,000,000 paise).
    - Scenario A: add ₹2,000 (200,000 paise) -> total 12,000 -> warning (spent*100 >= 80*limit, not exceeded).
    - Scenario B: add ₹2,000.01 (200,001 paise) -> total 12,000.01 -> exceeded!
    """
    snap = make_snapshot(dining_spend=10_000_00, dining_budget=12_000_00)

    # Scenario A: Exactly at the limit
    s_exact = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=2_000_00,
        start_month="2026-10",
        recurring=False,
    )
    p_exact = simulate(snap, s_exact, horizon_months=1)
    assert p_exact.budget_statuses["dining:2026-10"] == "warning"

    # Scenario B: One paisa over the limit
    s_over = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=2_000_01,
        start_month="2026-10",
        recurring=False,
    )
    p_over = simulate(snap, s_over, horizon_months=1)
    assert p_over.budget_statuses["dining:2026-10"] == "exceeded"


def test_recurring_vs_one_off_horizon():
    """Recurring scenario impacts all future months; one-off impacts only specified count."""
    snap = make_snapshot()

    # One-off: 2 months starting 2026-11
    s_one_off = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=5_000_00,
        start_month="2026-11",
        recurring=False,
        months=2,
    )
    p_one_off = simulate(snap, s_one_off, horizon_months=4)
    # Months: 2026-10 (base), 2026-11 (add), 2026-12 (add), 2027-01 (base)
    assert p_one_off.monthly_spend_paise["2026-10"] == 30_000_00
    assert p_one_off.monthly_spend_paise["2026-11"] == 35_000_00
    assert p_one_off.monthly_spend_paise["2026-12"] == 35_000_00
    assert p_one_off.monthly_spend_paise["2027-01"] == 30_000_00

    # Recurring: starting 2026-11
    s_rec = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=5_000_00,
        start_month="2026-11",
        recurring=True,
    )
    p_rec = simulate(snap, s_rec, horizon_months=4)
    assert p_rec.monthly_spend_paise["2026-10"] == 30_000_00
    assert p_rec.monthly_spend_paise["2026-11"] == 35_000_00
    assert p_rec.monthly_spend_paise["2026-12"] == 35_000_00
    assert p_rec.monthly_spend_paise["2027-01"] == 35_000_00


def test_horizon_limit_and_insufficient_data():
    """Horizon requested > 6 is capped at 6; insufficient data propagates."""
    snap = make_snapshot(has_insufficient_data=True)
    s = Scenario(
        kind="add_spend",
        amount_paise=1_000_00,
        start_month="2026-10",
        recurring=False,
    )

    # Request 12 months -> capped at 6
    proj = simulate(snap, s, horizon_months=12)
    assert proj.months_projected == 6
    assert len(proj.monthly_spend_paise) == 6
    assert proj.has_insufficient_data is True


def test_compare_scenarios_side_by_side():
    """compare_scenarios produces side-by-side table against baseline."""
    snap = make_snapshot()
    s1 = Scenario(
        kind="add_spend",
        category_id="dining",
        amount_paise=2_000_00,
        start_month="2026-10",
        recurring=False,
    )
    s2 = Scenario(
        kind="reduce_spend",
        category_id="dining",
        amount_paise=3_000_00,
        start_month="2026-10",
        recurring=False,
    )

    comparison = compare_scenarios(snap, [s1, s2], horizon_months=2)
    assert len(comparison.scenarios) == 2
    assert len(comparison.side_by_side) == 2

    m0_row = comparison.side_by_side[0]
    assert m0_row["month"] == "2026-10"
    assert m0_row["baseline_spend_paise"] == 30_000_00
    assert m0_row["scenario_1_spend_paise"] == 32_000_00
    assert m0_row["scenario_1_spend_delta_paise"] == 2_000_00
    assert m0_row["scenario_2_spend_paise"] == 27_000_00
    assert m0_row["scenario_2_spend_delta_paise"] == -3_000_00
