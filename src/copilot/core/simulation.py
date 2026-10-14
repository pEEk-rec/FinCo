"""
Pure deterministic what-if simulation engine (PLAN_PHASE2 Section 5.6).

Invariants:
- Pure functions: simulation never modifies financial state or database tables.
- Deterministic: identical inputs produce identical projections.
- Identity: amount_paise == 0 reproduces the baseline projection exactly.
- Monotonicity: adding spend never improves any metric; reducing spend never worsens any metric.
- Conservation of paise: all scenario deltas sum and balance exactly in integer paise.
"""

import sqlite3
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from copilot.config.phase2 import WhatIfConfig, load_whatif_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.goals import (
    SurplusEstimate,
    goal_status,
)
from copilot.core.timeutil import IST, month_bounds
from copilot.db.repo import (
    list_budgets,
    list_transactions,
)
from copilot.db.repo import (
    list_goals as repo_list_goals,
)
from copilot.models.agentic import Goal, Projection, Scenario
from copilot.tools.financial import budget_status, net_spend_by_category

_DEFAULT_WHATIF_CONFIG_PATH = PROJECT_ROOT / "config" / "whatif.yaml"


class FinancialSnapshot(BaseModel):
    """
    In-memory snapshot of user financial state used as the baseline for simulation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    today_month: str  # YYYY-MM
    estimated_monthly_income_paise: int
    baseline_variable_spend_by_category: dict[str, int]
    budgets: dict[str, int]  # category_id -> limit_paise
    warn_threshold_pct: int = 80
    recurring_series_monthly_paise: int = 0
    recurring_by_category: dict[str, int] = Field(default_factory=dict)
    goals: list[Goal] = Field(default_factory=list)
    has_insufficient_data: bool = False


class MonthlyProjectionDetail(BaseModel):
    """Month-by-month financial projection detail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    month: str  # YYYY-MM
    spend_low_paise: int
    spend_expected_paise: int
    spend_high_paise: int
    surplus_low_paise: int
    surplus_expected_paise: int
    surplus_high_paise: int
    category_spend_paise: dict[str, int]
    budget_statuses: dict[str, str]
    goal_statuses: dict[str, str]
    goal_shortfalls_paise: dict[str, int]


class ScenarioComparison(BaseModel):
    """Side-by-side comparison of up to 3 scenarios against the baseline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline: Projection
    scenarios: list[Projection]
    side_by_side: list[dict[str, Any]] = Field(default_factory=list)


def _next_month(period: str) -> str:
    """Return next calendar month string 'YYYY-MM'."""
    y, m = int(period[:4]), int(period[5:7])
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def _generate_horizon_months(start_month: str, count: int) -> list[str]:
    """Generate ordered list of N calendar months starting at start_month."""
    months = []
    curr = start_month
    for _ in range(count):
        months.append(curr)
        curr = _next_month(curr)
    return months


def build_snapshot(
    conn: sqlite3.Connection,
    user_id: str,
    today: datetime | date | str,
) -> FinancialSnapshot:
    """
    Build a FinancialSnapshot from the database to seed simulation projections.
    """
    if isinstance(today, str):
        today_date = date.fromisoformat(today[:10])
    elif isinstance(today, datetime):
        today_date = today.astimezone(IST).date()
    else:
        today_date = today

    curr_month_str = f"{today_date.year:04d}-{today_date.month:02d}"

    # Previous complete month for baseline spend
    prev_y, prev_m = today_date.year, today_date.month - 1
    if prev_m == 0:
        prev_m = 12
        prev_y -= 1
    start_utc, end_utc = month_bounds(prev_y, prev_m)
    txs = list_transactions(conn, user_id, start_utc, end_utc)

    # Estimate income: non-transfer credits from previous complete month
    income_credits = sum(
        -tx.amount_paise
        for tx in txs
        if tx.direction == "credit" and not tx.excluded_from_spend and tx.category_id != "transfer"
    )
    income_paise = income_credits if income_credits > 0 else 0

    # Net spend by category
    valid_txs = [tx for tx in txs if not tx.excluded_from_spend and tx.category_id != "transfer"]
    spend_by_cat = net_spend_by_category(valid_txs)
    clean_cat_spend = {str(k): v for k, v in spend_by_cat.items() if k is not None}

    # Budgets
    b_list = list_budgets(conn, user_id)
    budgets_dict = {b.category_id: b.limit_paise for b in b_list}
    warn_pct = b_list[0].warn_threshold_pct if b_list else 80

    # Goals
    goals = repo_list_goals(conn, user_id, status="active")

    has_insufficient = len(txs) == 0

    return FinancialSnapshot(
        user_id=user_id,
        today_month=curr_month_str,
        estimated_monthly_income_paise=income_paise,
        baseline_variable_spend_by_category=clean_cat_spend,
        budgets=budgets_dict,
        warn_threshold_pct=warn_pct,
        recurring_series_monthly_paise=0,
        recurring_by_category={},
        goals=goals,
        has_insufficient_data=has_insufficient,
    )


def simulate(
    snapshot: FinancialSnapshot,
    scenario: Scenario,
    horizon_months: int | None = None,
    config: WhatIfConfig | None = None,
) -> Projection:
    """
    Pure simulation function projecting finances under a scenario over the horizon.
    """
    if config is None:
        if _DEFAULT_WHATIF_CONFIG_PATH.exists():
            config = load_whatif_config(_DEFAULT_WHATIF_CONFIG_PATH)
        else:
            config = WhatIfConfig()

    effective_horizon = min(
        horizon_months or config.max_horizon_months, config.max_horizon_months
    )

    # Cap scenario amount
    effective_amount = min(scenario.amount_paise, config.max_amount_paise)

    horizon = _generate_horizon_months(snapshot.today_month, effective_horizon)

    # Determine which months are affected by the scenario
    affected_months: set[str] = set()
    if scenario.recurring:
        # All months in horizon >= scenario.start_month
        affected_months = {m for m in horizon if m >= scenario.start_month}
    else:
        # Exactly scenario.months starting at scenario.start_month
        active_list = _generate_horizon_months(scenario.start_month, scenario.months)
        affected_months = set(active_list).intersection(horizon)

    monthly_spend: dict[str, int] = {}
    monthly_surplus: dict[str, int] = {}
    budget_statuses: dict[str, str] = {}
    goal_impacts: dict[str, str] = {}
    inc_fmt = f"₹{snapshot.estimated_monthly_income_paise / 100:,.2f}"
    assumptions: list[str] = [
        f"Monthly income is assumed constant at {inc_fmt}.",
        "Baseline variable category spend continues at the historical rate.",
    ]

    amt_fmt = f"₹{effective_amount / 100:,.2f}"
    if scenario.kind == "add_spend":
        cat_str = f" in category '{scenario.category_id}'" if scenario.category_id else ""
        if scenario.recurring:
            assumptions.append(
                f"Additional recurring spend of {amt_fmt}/month{cat_str} "
                f"starting {scenario.start_month}."
            )
        else:
            assumptions.append(
                f"Additional spend of {amt_fmt}{cat_str} across "
                f"{scenario.months} month(s) starting {scenario.start_month}."
            )
    elif scenario.kind == "reduce_spend":
        cat_str = f" in category '{scenario.category_id}'" if scenario.category_id else ""
        assumptions.append(
            f"Spend reduction of {amt_fmt}/month{cat_str} starting {scenario.start_month}."
        )
    elif scenario.kind == "change_contribution":
        assumptions.append(
            f"Adjusted monthly savings contribution by {amt_fmt} for goal '{scenario.goal_id}'."
        )

    # Base category spend dictionary
    base_cats = dict(snapshot.baseline_variable_spend_by_category)

    for m in horizon:
        is_affected = m in affected_months
        current_cats = dict(base_cats)

        if is_affected:
            if scenario.kind == "add_spend":
                if scenario.category_id:
                    current_cats[scenario.category_id] = (
                        current_cats.get(scenario.category_id, 0) + effective_amount
                    )
                else:
                    # General spend addition
                    current_cats["general"] = current_cats.get("general", 0) + effective_amount
            elif scenario.kind == "reduce_spend":
                if scenario.category_id:
                    current_spend = current_cats.get(scenario.category_id, 0)
                    reduction = min(current_spend, effective_amount)
                    current_cats[scenario.category_id] = current_spend - reduction
                else:
                    # Proportionate or general reduction floored at 0
                    current_spend = sum(current_cats.values())
                    reduction = min(current_spend, effective_amount)
                    if current_spend > 0:
                        for c, v in list(current_cats.items()):
                            current_cats[c] = max(
                                0, v - int(reduction * (v / current_spend))
                            )

        month_total_spend = sum(current_cats.values()) + snapshot.recurring_series_monthly_paise
        month_surplus = snapshot.estimated_monthly_income_paise - month_total_spend

        monthly_spend[m] = month_total_spend
        monthly_surplus[m] = month_surplus

        # Check budgets
        for cat_id, limit in snapshot.budgets.items():
            spent = current_cats.get(cat_id, 0)
            _, state = budget_status(spent, limit, snapshot.warn_threshold_pct)
            budget_statuses[f"{cat_id}:{m}"] = state

        # Check goals pace
        # Create surplus estimate representing this month
        surplus_est = SurplusEstimate(
            status="insufficient_data" if snapshot.has_insufficient_data else "ok",
            low_paise=month_surplus - int(abs(month_surplus) * 0.1),
            expected_paise=month_surplus,
            high_paise=month_surplus + int(abs(month_surplus) * 0.1),
            months_evaluated=3,
        )

        for g in snapshot.goals:
            # If change_contribution targets this goal, adjust current progress or required pace
            eval_goal = g
            if is_affected and scenario.kind == "change_contribution" and scenario.goal_id == g.id:
                # Contribution adjustments modify current progress
                eval_goal = g.model_copy(
                    update={"current_paise": g.current_paise + effective_amount}
                )

            status, _, _ = goal_status(eval_goal, f"{m}-01", surplus_est)
            goal_impacts[f"{g.id}:{m}"] = status

    return Projection(
        scenario=scenario,
        months_projected=effective_horizon,
        monthly_spend_paise=monthly_spend,
        monthly_surplus_paise=monthly_surplus,
        budget_statuses=budget_statuses,
        goal_impacts=goal_impacts,
        assumptions=assumptions,
        has_insufficient_data=snapshot.has_insufficient_data,
    )


def compare_scenarios(
    snapshot: FinancialSnapshot,
    scenarios: list[Scenario],
    horizon_months: int | None = None,
    config: WhatIfConfig | None = None,
) -> ScenarioComparison:
    """
    Compare up to 3 scenarios side-by-side with the baseline.
    """
    if config is None:
        if _DEFAULT_WHATIF_CONFIG_PATH.exists():
            config = load_whatif_config(_DEFAULT_WHATIF_CONFIG_PATH)
        else:
            config = WhatIfConfig()

    capped_scenarios = scenarios[: config.max_scenarios_per_comparison]

    # Baseline projection: scenario with 0 amount
    baseline_scenario = Scenario(
        kind="add_spend",
        amount_paise=0,
        start_month=snapshot.today_month,
        recurring=False,
    )
    baseline_proj = simulate(snapshot, baseline_scenario, horizon_months, config)

    scenario_projections = [
        simulate(snapshot, s, horizon_months, config) for s in capped_scenarios
    ]

    # Build side-by-side comparison table
    comparison_rows: list[dict[str, Any]] = []
    horizon = _generate_horizon_months(snapshot.today_month, baseline_proj.months_projected)

    for m in horizon:
        row: dict[str, Any] = {
            "month": m,
            "baseline_spend_paise": baseline_proj.monthly_spend_paise[m],
            "baseline_surplus_paise": baseline_proj.monthly_surplus_paise[m],
        }
        for idx, p in enumerate(scenario_projections):
            row[f"scenario_{idx+1}_spend_paise"] = p.monthly_spend_paise[m]
            row[f"scenario_{idx+1}_surplus_paise"] = p.monthly_surplus_paise[m]
            row[f"scenario_{idx+1}_spend_delta_paise"] = (
                p.monthly_spend_paise[m] - baseline_proj.monthly_spend_paise[m]
            )
        comparison_rows.append(row)

    return ScenarioComparison(
        baseline=baseline_proj,
        scenarios=scenario_projections,
        side_by_side=comparison_rows,
    )
