"""
Investment Readiness assessment engine (PLAN_PHASE3 Section 5.6, Stage 3.6).

Pure deterministic financial readiness evaluation.
Determines savings capacity and reserve readiness against strict criteria:
1. Enough history: >= min_history_months complete calendar months.
2. Positive cash flow: net surplus > 0 in >= positive_months_required of recent complete months.
3. Stable cash flow: coefficient of variation (CV) <= max_cv_bp computed with Decimal.
4. Emergency reserve: emergency fund >= emergency_months_target * essential monthly spend.
5. Obligations covered: all firm outflow commitments in window are covered in calendar.
6. Priority goals on track: all priority 1 goals are on_track or completed.
7. Declared high-cost debt: user_preferences.high_cost_debt is not True.

All outputs use strictly templated language with ZERO product names, returns, or market statements.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from copilot.config.phase3 import ReadinessConfig, load_readiness_config
from copilot.core.buckets import bucket_balance
from copilot.core.calendar import build_calendar
from copilot.core.goals import _calculate_month_surplus, goal_current_paise, goal_progress
from copilot.core.timeutil import month_bounds
from copilot.db.repo import list_goals, list_transactions
from copilot.db.repo_phase3 import (
    get_user_preference,
    insert_readiness_assessment,
    list_buckets,
    list_commitments,
)
from copilot.models.phase3 import Readiness, ReadinessCriterion
from copilot.tools.financial import net_spend_by_category

_DEFAULT_READINESS_CONFIG_PATH = Path("config/readiness.yaml")


def _to_ist_date(val: datetime | date | str) -> date:
    """Coerce input into a naive date object representing the IST calendar day."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        iso = val.strip().replace("Z", "+00:00")
        if "T" in iso:
            return datetime.fromisoformat(iso).date()
        return date.fromisoformat(iso[:10])
    raise TypeError(f"Cannot convert {type(val)} to date")


def assess_readiness(
    conn: sqlite3.Connection,
    user_id: str,
    today: datetime | date | str,
    config: ReadinessConfig | None = None,
) -> Readiness:
    """
    Assess financial readiness and reserve cushion for a user as of today.

    Pure deterministic computation:
    - Zero floating point math on money.
    - Zero external side effects.
    - Strict multi-tenant isolation via user_id.
    """
    if config is None:
        if _DEFAULT_READINESS_CONFIG_PATH.exists():
            config = load_readiness_config(_DEFAULT_READINESS_CONFIG_PATH)
        else:
            config = ReadinessConfig(
                min_history_months=3,
                positive_months_required=2,
                max_cv_bp=5000,
                emergency_months_target=3,
                emergency_min_months=1,
                obligation_window_days=90,
                essential_categories=[
                    "rent",
                    "groceries",
                    "utilities",
                    "education",
                    "transport",
                    "health",
                    "insurance",
                    "emi",
                ],
            )

    today_d = _to_ist_date(today)
    curr_year, curr_month = today_d.year, today_d.month
    run_id = f"rd_{uuid.uuid4().hex[:12]}"
    config_version = "1.0.0"

    # 1. Determine last N complete calendar months before today's month
    complete_months: list[tuple[int, int]] = []
    y, m = curr_year, curr_month
    for _ in range(config.min_history_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        complete_months.append((y, m))

    # Reverse to chronological order (oldest to newest)
    complete_months_chronological = list(reversed(complete_months))

    # Check distinct complete calendar months with transactions
    first_day_curr_month = f"{curr_year:04d}-{curr_month:02d}-01"
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT strftime('%Y-%m', occurred_at))
        FROM transactions
        WHERE user_id = ? AND occurred_at < ?
        """,
        (user_id, first_day_curr_month),
    ).fetchone()
    history_months_count = row[0] if row else 0

    criteria: list[ReadinessCriterion] = []
    numbers: dict[str, Any] = {
        "history_months_recorded": history_months_count,
        "min_history_months_required": config.min_history_months,
    }

    # CRITERION 1: Enough history
    if history_months_count < config.min_history_months:
        crit_hist = ReadinessCriterion(
            name="enough_history",
            status="fail",
            value_text=(
                f"{history_months_count} of {config.min_history_months} "
                "complete months recorded"
            ),
            threshold_text=f"At least {config.min_history_months} complete calendar months",
            what_would_change_it=(
                f"Record financial activity across at least {config.min_history_months} "
                "complete calendar months."
            ),
        )
        criteria.append(crit_hist)

        # Invariant from Section 5.6: if not enough history, every other criterion is unknown
        other_names = [
            "positive_cash_flow",
            "stable_cash_flow",
            "emergency_reserve",
            "obligations_covered",
            "priority_goals_on_track",
            "declared_high_cost_debt",
        ]
        threshold_map = {
            "positive_cash_flow": (
                f"At least {config.positive_months_required} of "
                f"{config.min_history_months} complete months"
            ),
            "stable_cash_flow": f"<= {config.max_cv_bp / 100:.1f}% variation ratio",
            "emergency_reserve": f"{config.emergency_months_target} months essential spend",
            "obligations_covered": "All scheduled firm obligations covered",
            "priority_goals_on_track": "All priority 1 goals on track",
            "declared_high_cost_debt": "No high-cost debt declared",
        }
        for name in other_names:
            criteria.append(
                ReadinessCriterion(
                    name=name,
                    status="unknown",
                    value_text="Insufficient historical records",
                    threshold_text=threshold_map[name],
                    what_would_change_it=(
                        f"Record at least {config.min_history_months} complete "
                        "calendar months of activity first."
                    ),
                )
            )

        return Readiness(
            run_id=run_id,
            assessed_on=today_d.isoformat(),
            level="insufficient_data",
            criteria=criteria,
            numbers=numbers,
            config_version=config_version,
        )

    # History passes
    crit_hist = ReadinessCriterion(
        name="enough_history",
        status="pass",
        value_text=f"{history_months_count} complete months recorded",
        threshold_text=f"At least {config.min_history_months} complete calendar months",
        what_would_change_it="Sufficient historical records exist.",
    )
    criteria.append(crit_hist)

    # Calculate monthly surpluses and essential spending for the last complete months
    surpluses: list[int] = []
    essential_spends: list[int] = []
    essential_set = {cat.strip().lower() for cat in config.essential_categories}
    cat_rows = conn.execute(
        "SELECT id, name FROM categories WHERE user_id = ?", (user_id,)
    ).fetchall()
    id_to_name = {r[0]: r[1].lower() for r in cat_rows}

    for y_m in complete_months_chronological:
        yr, mo = y_m
        start_utc, end_utc = month_bounds(yr, mo)
        txs = list_transactions(conn, user_id, start_utc, end_utc)
        m_surplus = _calculate_month_surplus(txs)
        surpluses.append(m_surplus)

        # Essential category net spend
        valid_txs = [
            tx for tx in txs if not tx.excluded_from_spend and tx.category_id != "transfer"
        ]
        cat_spend = net_spend_by_category(valid_txs)
        m_essential = sum(
            amount
            for cat_id, amount in cat_spend.items()
            if cat_id
            and (cat_id.lower() in essential_set or id_to_name.get(cat_id, "") in essential_set)
        )
        essential_spends.append(max(0, m_essential))

    # CRITERION 2: Positive cash flow
    positive_count = sum(1 for s in surpluses if s > 0)
    pcf_passed = positive_count >= config.positive_months_required
    crit_pcf = ReadinessCriterion(
        name="positive_cash_flow",
        status="pass" if pcf_passed else "fail",
        value_text=f"{positive_count} of {len(surpluses)} recent months positive",
        threshold_text=(
            f"At least {config.positive_months_required} of {len(surpluses)} complete months"
        ),
        what_would_change_it=(
            "Maintain positive monthly net surplus in at least 2 of the last 3 months."
        ),
    )
    criteria.append(crit_pcf)

    # CRITERION 3: Stable cash flow (Decimal CV calculation)
    dec_surpluses = [Decimal(s) for s in surpluses]
    n_dec = Decimal(len(surpluses))
    mean_dec = sum(dec_surpluses) / n_dec

    cv_bp: int | None = None
    std_dec = Decimal(0)
    if mean_dec <= Decimal(0):
        crit_stab = ReadinessCriterion(
            name="stable_cash_flow",
            status="unknown",
            value_text="Average net surplus is non-positive",
            threshold_text=f"<= {config.max_cv_bp / 100:.1f}% variation ratio",
            what_would_change_it="Establish a positive average monthly net surplus.",
        )
    else:
        var_dec = sum((s - mean_dec) ** 2 for s in dec_surpluses) / n_dec
        std_dec = var_dec.sqrt()
        cv_ratio = std_dec / mean_dec
        cv_bp = int((cv_ratio * Decimal(10000)).to_integral_value(rounding=ROUND_HALF_UP))
        crit_stab = ReadinessCriterion(
            name="stable_cash_flow",
            status="pass" if cv_bp <= config.max_cv_bp else "fail",
            value_text=f"{cv_bp / 100:.1f}% variation ratio",
            threshold_text=f"<= {config.max_cv_bp / 100:.1f}% variation ratio",
            what_would_change_it=(
                "Keep month-to-month net surplus variability below 50% coefficient of variation."
            ),
        )
    criteria.append(crit_stab)

    # CRITERION 4: Emergency reserve
    sorted_essential = sorted(essential_spends)
    median_essential_spend_paise = (
        sorted_essential[len(sorted_essential) // 2] if sorted_essential else 0
    )
    emergency_target_paise = config.emergency_months_target * median_essential_spend_paise

    # Reserve sources:
    # 1. Essential goals
    all_goals = list_goals(conn, user_id)
    essential_goals = [
        g for g in all_goals if bool(getattr(g, "essential", 0)) and g.status != "archived"
    ]
    essential_goals_paise = sum(goal_current_paise(conn, user_id, g) for g in essential_goals)

    # 2. Emergency virtual bucket
    active_buckets = list_buckets(conn, user_id, status="active")
    emg_buckets = [
        b
        for b in active_buckets
        if b.name.strip().lower() in ("emergency", "emergency fund", "emergency_fund")
    ]
    emg_bucket_balance_paise = 0
    curr_period = f"{curr_year:04d}-{curr_month:02d}"
    for b in emg_buckets:
        bal = bucket_balance(conn, user_id, b, curr_period)
        if bal.balance_paise > 0:
            emg_bucket_balance_paise += bal.balance_paise

    # 3. User preference declared reserve
    pref_reserve = get_user_preference(conn, user_id, "emergency_reserve_paise")
    if pref_reserve is None:
        pref_reserve = get_user_preference(conn, user_id, "declared_emergency_reserve_paise")
    try:
        pref_reserve_paise = int(pref_reserve) if pref_reserve is not None else 0
    except (ValueError, TypeError):
        pref_reserve_paise = 0

    emergency_fund_paise = max(essential_goals_paise, emg_bucket_balance_paise, pref_reserve_paise)

    if median_essential_spend_paise == 0:
        emg_status = "pass"
        months_covered = Decimal(config.emergency_months_target)
    else:
        months_covered = Decimal(emergency_fund_paise) / Decimal(median_essential_spend_paise)
        emg_status = "pass" if emergency_fund_paise >= emergency_target_paise else "fail"

    crit_emg = ReadinessCriterion(
        name="emergency_reserve",
        status=emg_status,
        value_text=(
            f"₹{emergency_fund_paise / 100:,.0f} ({float(months_covered):.1f} months cushion)"
        ),
        threshold_text=(
            f"₹{emergency_target_paise / 100:,.0f} "
            f"({config.emergency_months_target} months essential spend)"
        ),
        what_would_change_it=(
            f"Accumulate at least {config.emergency_months_target} months of essential "
            "expenses in emergency reserve."
        ),
    )
    criteria.append(crit_emg)

    # CRITERION 5: Obligations covered (using calendar projection)
    cal = build_calendar(
        conn, user_id, today_d.isoformat(), horizon_days=config.obligation_window_days
    )
    active_comms = {c.id: c for c in list_commitments(conn, user_id, status="active")}
    firm_coverages = [
        c
        for c in cal.coverage
        if c.occurrence.direction == "outflow"
        and active_comms.get(c.occurrence.commitment_id)
        and active_comms[c.occurrence.commitment_id].certainty == "firm"
    ]

    if not firm_coverages:
        oblg_status = "pass"
        oblg_val_text = "0 scheduled firm obligations"
    else:
        uncovered = [c for c in firm_coverages if c.coverage_status in ("at_risk", "not_covered")]
        unknowns = [c for c in firm_coverages if c.coverage_status == "unknown"]
        if uncovered:
            oblg_status = "fail"
            oblg_val_text = (
                f"{len(uncovered)} of {len(firm_coverages)} scheduled obligations "
                "at risk or not covered"
            )
        elif unknowns:
            oblg_status = "unknown"
            oblg_val_text = (
                f"{len(unknowns)} of {len(firm_coverages)} scheduled obligations "
                "have unknown coverage"
            )
        else:
            oblg_status = "pass"
            oblg_val_text = f"All {len(firm_coverages)} scheduled firm obligations covered"

    crit_oblg = ReadinessCriterion(
        name="obligations_covered",
        status=oblg_status,
        value_text=oblg_val_text,
        threshold_text="All scheduled firm obligations covered",
        what_would_change_it=(
            "Ensure all scheduled firm obligations have projected coverage in the calendar."
        ),
    )
    criteria.append(crit_oblg)

    # CRITERION 6: Priority goals on track
    p1_goals = [g for g in all_goals if g.priority == 1 and g.status != "archived"]
    if not p1_goals:
        p1_status = "pass"
        p1_val_text = "No priority 1 savings goals active"
    else:
        behind = []
        for g in p1_goals:
            if g.status == "completed":
                continue
            prog = goal_progress(conn, user_id, g, today_d)
            if prog.status not in ("on_track", "completed"):
                behind.append(g)

        if not behind:
            p1_status = "pass"
            p1_val_text = f"All {len(p1_goals)} priority 1 goals on track"
        else:
            p1_status = "fail"
            p1_val_text = f"{len(behind)} of {len(p1_goals)} priority 1 goals behind schedule"

    crit_p1 = ReadinessCriterion(
        name="priority_goals_on_track",
        status=p1_status,
        value_text=p1_val_text,
        threshold_text="All priority 1 goals on track",
        what_would_change_it="Maintain on-track pace for priority 1 savings goals.",
    )
    criteria.append(crit_p1)

    # CRITERION 7: Declared high-cost debt
    debt_pref = get_user_preference(conn, user_id, "high_cost_debt")
    if debt_pref is None:
        debt_status = "unknown"
        debt_val_text = "Not declared"
    elif bool(debt_pref) is True:
        debt_status = "fail"
        debt_val_text = "High-cost debt declared"
    else:
        debt_status = "pass"
        debt_val_text = "No high-cost debt declared"

    crit_debt = ReadinessCriterion(
        name="declared_high_cost_debt",
        status=debt_status,
        value_text=debt_val_text,
        threshold_text="No high-cost debt declared",
        what_would_change_it="Record debt status in preferences as having no high-cost debt.",
    )
    criteria.append(crit_debt)

    # Overall level determination (PLAN Section 5.6)
    if (
        crit_pcf.status == "fail"
        or crit_emg.status == "fail"
        or crit_oblg.status == "fail"
    ):
        level = "not_ready"
    elif (
        crit_stab.status == "fail"
        or crit_p1.status == "fail"
        or crit_debt.status == "fail"
    ):
        level = "building"
    elif any(c.status == "unknown" for c in criteria):
        level = "ready_with_conditions"
    else:
        level = "ready"

    # Populate numbers dict
    numbers.update(
        {
            "positive_months_count": positive_count,
            "months_evaluated": len(surpluses),
            "monthly_surpluses_paise": surpluses,
            "mean_surplus_paise": int(mean_dec.to_integral_value(ROUND_HALF_UP)),
            "std_dev_surplus_paise": int(std_dec.to_integral_value(ROUND_HALF_UP)),
            "cv_bp": cv_bp,
            "emergency_fund_paise": emergency_fund_paise,
            "essential_monthly_spend_paise": median_essential_spend_paise,
            "emergency_target_paise": emergency_target_paise,
            "emergency_months_target": config.emergency_months_target,
            "emergency_months_covered": float(months_covered),
            "firm_obligations_count": len(firm_coverages),
            "firm_obligations_covered_count": len(
                [c for c in firm_coverages if c.coverage_status == "covered"]
            ),
            "priority_1_goals_count": len(p1_goals),
            "high_cost_debt_declared": debt_pref,
        }
    )

    return Readiness(
        run_id=run_id,
        assessed_on=today_d.isoformat(),
        level=level,
        criteria=criteria,
        numbers=numbers,
        config_version=config_version,
    )


def record_readiness_assessment(
    conn: sqlite3.Connection,
    user_id: str,
    readiness: Readiness,
) -> str:
    """Convenience helper to record a readiness assessment snapshot."""
    return insert_readiness_assessment(conn, user_id, readiness)
