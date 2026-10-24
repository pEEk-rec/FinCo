"""
Financial Calendar Projection Engine (PLAN_PHASE3 Section 5.4 & Stage 3.5).

Projects daily running balances, known commitment flows, variable spend run-rates,
commitment coverage, and shortfall ranges across a configurable horizon.

Financial invariants:
1. Strict integer paise throughout; no floating-point arithmetic.
2. Property ordering invariant: for every day, running_balance_low <= expected <= high.
3. Category exclusion: categories covered by active commitments are excluded from
   variable spend to prevent double counting rent, fees, subscriptions, etc.
4. Reconciliation invariant: for the current month, expected variable spend summed over
   the remaining days matches the forecast v2 variable figure within one rupee of rounding.
5. Scenario invariants: zero-change scenario equals baseline exactly; scenarios never
   write to financial tables.
"""

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from copilot.config.phase3 import CalendarConfig
from copilot.core.buckets import get_liquid_balance
from copilot.core.commitments import expand_occurrences
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import month_bounds
from copilot.db.repo import list_transactions
from copilot.db.repo_phase3 import list_commitments
from copilot.models.phase3 import Calendar, CalendarDay, Commitment, Coverage, Occurrence

_DEFAULT_CALENDAR_CONFIG_PATH = PROJECT_ROOT / "config" / "calendar.yaml"


def load_calendar_config(path: Path | None = None) -> CalendarConfig:
    """Load and validate calendar configuration from YAML."""
    p = path or _DEFAULT_CALENDAR_CONFIG_PATH
    if not p.is_file():
        return CalendarConfig(
            default_horizon_days=60,
            max_horizon_days=180,
            min_buffer_paise=100000,
        )
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CalendarConfig.model_validate(data)


class CalendarScenario(BaseModel):
    """Scenario extension for what-if simulations on the financial calendar."""

    model_config = ConfigDict(extra="forbid")

    change_contributions: list[dict[str, Any]] = Field(default_factory=list)
    add_commitments: list[Commitment] = Field(default_factory=list)
    remove_commitment_ids: list[str] = Field(default_factory=list)
    shift_goal_dates: list[dict[str, Any]] = Field(default_factory=list)
    bucket_allocations: list[dict[str, Any]] = Field(default_factory=list)


def build_calendar(
    conn: Any,
    user_id: str,
    today: str,
    horizon_days: int = 60,
    min_buffer_paise: int | None = None,
    scenario: CalendarScenario | dict[str, Any] | None = None,
) -> Calendar:
    """
    Build a daily financial calendar projection starting from `today` (IST YYYY-MM-DD).

    Steps:
    1. Start: liquid_balance today across deposit accounts.
    2. Known flows: active commitment occurrences in [today, today + horizon_days - 1].
    3. Variable spend: daily variable run-rate from forecast v2, excluding commitment categories.
    4. Daily projection: running balances for expected, low, and high.
    5. Coverage per outflow occurrence: covered, at_risk, not_covered, or unknown.
    6. Shortfall days: contiguous periods where low balance < min_buffer_paise.
    """
    config = load_calendar_config()
    if horizon_days < 1 or horizon_days > config.max_horizon_days:
        raise ValueError(
            f"horizon_days ({horizon_days}) must be between 1 and {config.max_horizon_days}"
        )

    buffer_paise = min_buffer_paise if min_buffer_paise is not None else config.min_buffer_paise
    if buffer_paise < 0:
        raise ValueError("min_buffer_paise cannot be negative")

    today_d = date.fromisoformat(today)
    end_d = today_d + timedelta(days=horizon_days - 1)
    end_str = end_d.isoformat()

    # Parse scenario if provided
    scen: CalendarScenario | None = None
    if scenario is not None:
        if isinstance(scenario, dict):
            scen = CalendarScenario.model_validate(scenario)
        else:
            scen = scenario

    # 1. Start balance: liquid balance today
    start_balance = get_liquid_balance(conn, user_id)

    # 2. Known flows: active commitments
    active_comms = list_commitments(conn, user_id, status="active")

    # Apply scenario adjustments to commitments
    if scen:
        if scen.remove_commitment_ids:
            active_comms = [c for c in active_comms if c.id not in scen.remove_commitment_ids]
        if scen.change_contributions:
            changes = {
                item["commitment_id"]: item["new_amount_paise"]
                for item in scen.change_contributions
            }
            updated_comms = []
            for c in active_comms:
                if c.id in changes:
                    new_amt = changes[c.id]
                    if new_amt == 0:
                        continue  # Paused / zeroed out
                    c = c.model_copy(
                        update={
                            "amount_paise": new_amt,
                            "amount_min_paise": new_amt,
                            "amount_max_paise": new_amt,
                        }
                    )
                updated_comms.append(c)
            active_comms = updated_comms
        if scen.add_commitments:
            active_comms.extend(scen.add_commitments)

    # Expand occurrences for all active commitments
    occurrences_by_date: dict[str, list[Occurrence]] = {}
    commitment_categories = {c.category_id for c in active_comms if c.category_id}

    for comm in active_comms:
        occs = expand_occurrences(comm, today, end_str)
        for occ in occs:
            occurrences_by_date.setdefault(occ.due_date, []).append(occ)

    # 3. Variable spend run-rate
    # Current month metrics
    cur_year, cur_month = today_d.year, today_d.month
    days_in_cur_month = calendar.monthrange(cur_year, cur_month)[1]
    days_elapsed = today_d.day  # IST day of month

    start_utc, _ = month_bounds(cur_year, cur_month)
    txs = list_transactions(conn, user_id, start_utc, f"{today}T23:59:59Z")

    spent_var = 0
    for tx in txs:
        if tx.is_duplicate_of or tx.excluded_from_spend:
            continue
        if tx.category_id in commitment_categories:
            continue
        if tx.category_id is None and tx.direction == "credit":
            continue
        spent_var += tx.amount_paise
    spent_var = max(0, spent_var)

    insufficient_data = days_elapsed < 3
    remaining_days_in_month = max(1, days_in_cur_month - days_elapsed)

    if insufficient_data:
        var_status: Literal["forecast", "unknown"] = "unknown"
        daily_var_expected_cur = 0
        daily_var_low_cur = 0
        daily_var_high_cur = 0
        future_daily_expected = 0
        future_daily_low = 0
        future_daily_high = 0
    else:
        var_status = "forecast"
        rem_var_total = (spent_var * (days_in_cur_month - days_elapsed)) // days_elapsed
        daily_var_expected_cur = rem_var_total // remaining_days_in_month
        daily_var_low_cur = (daily_var_expected_cur * 80) // 100
        daily_var_high_cur = (daily_var_expected_cur * 120) // 100

        # Future months use monthly run-rate normalized to daily
        monthly_var_total = (spent_var * days_in_cur_month) // days_elapsed
        future_daily_expected = monthly_var_total // 30
        future_daily_low = (future_daily_expected * 80) // 100
        future_daily_high = (future_daily_expected * 120) // 100

    # 4. Daily projection
    calendar_days: list[CalendarDay] = []
    coverage_list: list[Coverage] = []

    running_expected = start_balance
    running_low = start_balance
    running_high = start_balance

    for offset in range(horizon_days):
        day_date = today_d + timedelta(days=offset)
        day_str = day_date.isoformat()
        day_occs = occurrences_by_date.get(day_str, [])

        inflow_exp = sum(o.amount_expected_paise for o in day_occs if o.direction == "inflow")
        inflow_low = sum(o.amount_low_paise for o in day_occs if o.direction == "inflow")
        inflow_high = sum(o.amount_high_paise for o in day_occs if o.direction == "inflow")

        outflow_exp = sum(o.amount_expected_paise for o in day_occs if o.direction == "outflow")
        outflow_low = sum(o.amount_low_paise for o in day_occs if o.direction == "outflow")
        outflow_high = sum(o.amount_high_paise for o in day_occs if o.direction == "outflow")

        # Variable spend for this day
        if var_status == "unknown":
            var_exp = var_low = var_high = 0
        elif (day_date.year, day_date.month) == (cur_year, cur_month):
            var_exp = daily_var_expected_cur
            var_low = daily_var_low_cur
            var_high = daily_var_high_cur
        else:
            var_exp = future_daily_expected
            var_low = future_daily_low
            var_high = future_daily_high

        # Running balances:
        # expected: expected flows - var_expected
        # low: low inflows - high outflows - var_high (most conservative)
        # high: high inflows - low outflows - var_low (most optimistic)
        running_expected = running_expected + inflow_exp - outflow_exp - var_exp
        running_low = running_low + inflow_low - outflow_high - var_high
        running_high = running_high + inflow_high - outflow_low - var_low

        below_buf = running_low < buffer_paise

        cal_day = CalendarDay(
            date=day_str,
            running_balance_expected_paise=running_expected,
            running_balance_low_paise=running_low,
            running_balance_high_paise=running_high,
            known_inflows_paise=inflow_exp,
            known_outflows_paise=outflow_exp,
            variable_spend_paise=var_exp,
            variable_spend_status=var_status,
            occurrences=day_occs,
            below_buffer=below_buf,
        )
        calendar_days.append(cal_day)

        # 5. Coverage per outflow occurrence
        for occ in day_occs:
            if occ.direction == "outflow":
                if var_status == "unknown" and running_expected < buffer_paise:
                    cov_status: Literal["covered", "at_risk", "not_covered", "unknown"] = "unknown"
                elif running_low >= buffer_paise:
                    cov_status = "covered"
                elif running_expected >= buffer_paise:
                    cov_status = "at_risk"
                else:
                    cov_status = "not_covered"

                coverage_list.append(
                    Coverage(
                        occurrence=occ,
                        coverage_status=cov_status,
                        balance_after_low_paise=running_low,
                        balance_after_expected_paise=running_expected,
                        buffer_paise=buffer_paise,
                    )
                )

    # 6. Shortfall days: grouped into contiguous ranges
    shortfall_ranges: list[dict[str, Any]] = []
    current_range: dict[str, Any] | None = None

    for c_day in calendar_days:
        if c_day.below_buffer:
            if current_range is None:
                current_range = {
                    "start_date": c_day.date,
                    "end_date": c_day.date,
                    "lowest_balance_paise": c_day.running_balance_low_paise,
                    "lowest_date": c_day.date,
                    "shortfall_paise": max(0, buffer_paise - c_day.running_balance_low_paise),
                    "commitments_due": [
                        occ.commitment_id for occ in c_day.occurrences if occ.direction == "outflow"
                    ],
                }
            else:
                current_range["end_date"] = c_day.date
                if c_day.running_balance_low_paise < current_range["lowest_balance_paise"]:
                    current_range["lowest_balance_paise"] = c_day.running_balance_low_paise
                    current_range["lowest_date"] = c_day.date
                    current_range["shortfall_paise"] = max(
                        0, buffer_paise - c_day.running_balance_low_paise
                    )
                for occ in c_day.occurrences:
                    if (
                        occ.direction == "outflow"
                        and occ.commitment_id not in current_range["commitments_due"]
                    ):
                        current_range["commitments_due"].append(occ.commitment_id)
        else:
            if current_range is not None:
                shortfall_ranges.append(current_range)
                current_range = None

    if current_range is not None:
        shortfall_ranges.append(current_range)

    return Calendar(
        today=today,
        horizon_days=horizon_days,
        start_balance_paise=start_balance,
        min_buffer_paise=buffer_paise,
        days=calendar_days,
        coverage=coverage_list,
        shortfall_ranges=shortfall_ranges,
    )


# Alias for backward/forward compatibility
get_calendar_projection = build_calendar
