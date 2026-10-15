"""
Pure Contribution Planning and Trade-off Analysis Engine (PLAN_PHASE3 Section 5.7 & Stage 3.7).

Provides:
- Waterfall allocation engine across user-ordered priority steps
- Option generator when contributions or goals do not fit (at most 3 alternatives)
- Trade-off evaluation engine assessing metrics across alternatives
- Strict safety invariants: plain sums only, zero growth, no product advice
"""

import sqlite3
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from copilot.config.phase3 import ContributionsConfig
from copilot.core.calendar import CalendarScenario, build_calendar
from copilot.core.goals import goal_progress
from copilot.core.readiness import assess_readiness
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo import (
    insert_simulation,
    list_goals,
)
from copilot.db.repo_phase3 import (
    get_user_preference,
    insert_contribution_plan,
    insert_tradeoff_analysis,
    list_commitments,
)
from copilot.models.phase3 import (
    ContributionPlan,
    ContributionPlanStep,
    TradeoffAlternative,
    TradeoffResult,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONTRIBUTIONS_CONFIG_PATH = PROJECT_ROOT / "config" / "contributions.yaml"


def load_contributions_config(path: Path | None = None) -> ContributionsConfig:
    """Load and validate contribution planning configuration from YAML."""
    p = path or _DEFAULT_CONTRIBUTIONS_CONFIG_PATH
    if not p.is_file():
        return ContributionsConfig(
            default_horizon_months=6,
            max_horizon_months=24,
            max_tradeoff_alternatives=3,
            waterfall_order=[
                "firm_commitments",
                "essential_spend",
                "emergency_fund",
                "goals",
                "planned_investments",
                "discretionary",
            ],
        )
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ContributionsConfig.model_validate(data)


def _get_waterfall_order(
    conn: sqlite3.Connection,
    user_id: str,
    override_order: list[str] | None,
    config: ContributionsConfig,
) -> list[str]:
    """Retrieve waterfall order from override, user preferences, or config."""
    if override_order:
        return list(override_order)
    pref = get_user_preference(conn, user_id, "waterfall_order")
    if pref:
        val = pref.value_json
        if isinstance(val, list):
            return [str(v) for v in val]
    return list(config.waterfall_order)


def plan_contributions(
    conn: sqlite3.Connection,
    user_id: str,
    horizon_months: int | None = None,
    start_date: str | None = None,
    waterfall_order: list[str] | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
) -> ContributionPlan:
    """
    Compute a monthly waterfall contribution plan across the horizon.

    Enforces invariants:
    - funded_expected + shortfall == needed for every step
    - total funded_expected <= inflow_expected
    - total funded_low <= inflow_low
    - plain sums only, zero growth
    """
    config = load_contributions_config(config_path)
    h_months = horizon_months or config.default_horizon_months
    h_months = max(1, min(config.max_horizon_months, h_months))

    rid = run_id or f"run_{uuid.uuid4().hex[:12]}"
    now_dt = now_utc()
    if start_date:
        today_d = date.fromisoformat(start_date)
    else:
        today_d = from_utc_iso(to_utc_iso(now_dt)).date()

    period_from = f"{today_d.year:04d}-{today_d.month:02d}"
    order = _get_waterfall_order(conn, user_id, waterfall_order, config)

    # 1. Estimate monthly inflows (calendar + active commitments)
    cal_horizon_days = min(180, h_months * 30)
    cal = build_calendar(conn, user_id, today_d.isoformat(), horizon_days=cal_horizon_days)

    total_cal_inflows = sum(d.known_inflows_paise for d in cal.days)
    cal_months = max(1, cal_horizon_days // 30)
    monthly_inflow_expected = total_cal_inflows // cal_months

    if monthly_inflow_expected == 0:
        # Fallback to credit transactions over last 90 days
        tx_rows = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM transactions
            WHERE user_id = ?
              AND direction = 'credit'
              AND category_id != 'transfer'
              AND is_duplicate_of IS NULL
              AND excluded_from_spend = 0
            """,
            (user_id,),
        ).fetchone()
        credit_sum = tx_rows[0] if tx_rows else 0
        monthly_inflow_expected = credit_sum // 3

    # Inflow low case: conservative 90% or calendar low run-rate
    monthly_inflow_low = int(monthly_inflow_expected * 9 // 10)

    # 2. Evaluate component needs
    active_comms = list_commitments(conn, user_id, status="active")
    firm_outflows = [
        c
        for c in active_comms
        if c.direction == "outflow"
        and c.certainty == "firm"
        and c.kind != "investment_contribution"
    ]
    # Monthly firm commitment need
    firm_monthly_paise = sum(c.amount_paise for c in firm_outflows if c.schedule_kind == "monthly")
    # For non-monthly, add amortised monthly share
    for c in firm_outflows:
        if c.schedule_kind == "yearly":
            firm_monthly_paise += c.amount_paise // 12
        elif c.schedule_kind == "quarterly":
            firm_monthly_paise += c.amount_paise // 3

    # Essential spend from readiness assessment
    readiness = assess_readiness(conn, user_id, today_d.isoformat())
    essential_monthly_spend_paise = readiness.numbers.get("essential_monthly_spend_paise", 0)
    emergency_target_paise = readiness.numbers.get("emergency_target_paise", 0)
    emergency_fund_paise = readiness.numbers.get("emergency_fund_paise", 0)

    emergency_deficit = max(0, emergency_target_paise - emergency_fund_paise)
    emergency_monthly_topup = (
        (emergency_deficit + h_months - 1) // h_months if emergency_deficit > 0 else 0
    )

    # Goals by priority
    all_goals = list_goals(conn, user_id)
    active_goals = [
        g
        for g in all_goals
        if g.status != "done" and not bool(getattr(g, "essential", 0))
    ]
    active_goals.sort(
        key=lambda g: (g.priority, getattr(g, "deadline", None) or "9999-12-31")
    )

    goals_monthly_paise = 0
    for g in active_goals:
        prog = goal_progress(conn, user_id, g, today_d)
        goals_monthly_paise += prog.required_monthly_paise

    # Planned investment contributions
    inv_comms = [
        c
        for c in active_comms
        if c.direction == "outflow" and c.kind == "investment_contribution"
    ]
    inv_monthly_paise = sum(c.amount_paise for c in inv_comms if c.schedule_kind == "monthly")
    for c in inv_comms:
        if c.schedule_kind == "yearly":
            inv_monthly_paise += c.amount_paise // 12
        elif c.schedule_kind == "quarterly":
            inv_monthly_paise += c.amount_paise // 3

    # Map category to need amount
    need_by_name: dict[str, int] = {
        "firm_commitments": firm_monthly_paise,
        "essential_spend": essential_monthly_spend_paise,
        "emergency_fund": emergency_monthly_topup,
        "emergency_top_up": emergency_monthly_topup,
        "goals": goals_monthly_paise,
        "goals_by_priority": goals_monthly_paise,
        "planned_investments": inv_monthly_paise,
        "planned_investment_contributions": inv_monthly_paise,
    }

    # 3. Waterfall allocation
    rem_exp = monthly_inflow_expected
    rem_low = monthly_inflow_low
    steps: list[ContributionPlanStep] = []

    for step_name in order:
        if step_name in ("discretionary", "discretionary_spend"):
            # Takes whatever is left
            need = max(0, rem_exp)
            funded_exp = min(rem_exp, need)
            rem_exp -= funded_exp
            funded_low = min(rem_low, funded_exp)
            rem_low -= funded_low
            shortfall = need - funded_exp
            verdict = "fits"
        else:
            need = need_by_name.get(step_name, 0)
            funded_exp = min(rem_exp, need)
            rem_exp -= funded_exp
            funded_low = min(rem_low, need)
            rem_low -= funded_low
            shortfall = need - funded_exp

            if need == 0:
                verdict = "fits"
            elif funded_low >= need:
                verdict = "fits"
            elif funded_exp >= need:
                verdict = "fits_expected_only"
            else:
                verdict = "does_not_fit"

        steps.append(
            ContributionPlanStep(
                step_name=step_name,
                needed_paise=need,
                funded_expected_paise=funded_exp,
                funded_low_paise=funded_low,
                shortfall_paise=shortfall,
                verdict=verdict,
            )
        )

    # 4. Generate options when planned contributions or goals do not fit
    options: list[dict[str, Any]] = []
    unfunded_steps = [s for s in steps if s.verdict in ("does_not_fit", "fits_expected_only")]

    if unfunded_steps and inv_comms:
        primary_comm = inv_comms[0]
        step_inv = next(
            (
                s
                for s in steps
                if s.step_name in ("planned_investments", "planned_investment_contributions")
            ),
            None,
        )

        # Option 1: Reduce contribution to fundable amount
        if step_inv and step_inv.needed_paise > 0:
            fundable_paise = max(0, step_inv.funded_expected_paise)
            sim_id1 = f"sim_{uuid.uuid4().hex[:8]}"
            scenario1 = {
                "kind": "change_contribution",
                "commitment_id": primary_comm.id,
                "new_amount_paise": fundable_paise,
            }
            # Record simulation
            insert_simulation(
                conn=conn,
                sim_id=sim_id1,
                user_id=user_id,
                scenario=scenario1,
                baseline={"planned_contribution_paise": primary_comm.amount_paise},
                result={"adjusted_contribution_paise": fundable_paise, "shortfall_paise": 0},
                assumptions=["Contribution reduced to available monthly cash flow"],
                created_at=to_utc_iso(now_dt),
            )
            options.append(
                {
                    "id": f"opt_{uuid.uuid4().hex[:6]}",
                    "title": f"Reduce contribution to ₹{fundable_paise / 100:,.0f}/month",
                    "scenario_specs": [scenario1],
                    "simulation_id": sim_id1,
                    "metrics": {
                        "monthly_contribution_paise": fundable_paise,
                        "cash_flow_shortfall_paise": 0,
                    },
                }
            )

        # Option 2: Pause contribution for N months until emergency reserve is funded
        if emergency_deficit > 0:
            denom = max(1, monthly_inflow_expected)
            pause_months = min(12, max(1, (emergency_deficit + denom - 1) // denom))
            sim_id2 = f"sim_{uuid.uuid4().hex[:8]}"
            scenario2 = {
                "kind": "change_contribution",
                "commitment_id": primary_comm.id,
                "new_amount_paise": 0,
                "duration_months": pause_months,
            }
            insert_simulation(
                conn=conn,
                sim_id=sim_id2,
                user_id=user_id,
                scenario=scenario2,
                baseline={"emergency_reserve_deficit_paise": emergency_deficit},
                result={"emergency_funded_months": pause_months},
                assumptions=["Temporarily pausing contribution to build emergency cushion"],
                created_at=to_utc_iso(now_dt),
            )
            options.append(
                {
                    "id": f"opt_{uuid.uuid4().hex[:6]}",
                    "title": (
                        f"Pause contribution for {pause_months} months to complete emergency fund"
                    ),
                    "scenario_specs": [scenario2],
                    "simulation_id": sim_id2,
                    "metrics": {
                        "emergency_months_reached": readiness.numbers.get(
                            "emergency_months_target", 3
                        ),
                        "pause_duration_months": pause_months,
                    },
                }
            )

        # Option 3: Move lower priority goal date
        lower_priority_goals = [g for g in active_goals if g.priority >= 2]
        if lower_priority_goals:
            target_goal = lower_priority_goals[0]
            g_deadline = getattr(target_goal, "deadline", None)
            g_name = getattr(target_goal, "name", "Goal")
            cur_target_d = (
                date.fromisoformat(g_deadline) if g_deadline else today_d
            )
            new_target_d = date(
                cur_target_d.year + (cur_target_d.month + 6) // 12,
                ((cur_target_d.month + 6) % 12) or 12,
                min(28, cur_target_d.day),
            )
            sim_id3 = f"sim_{uuid.uuid4().hex[:8]}"
            scenario3 = {
                "kind": "shift_goal_date",
                "goal_id": target_goal.id,
                "new_target_date": new_target_d.isoformat(),
            }
            insert_simulation(
                conn=conn,
                sim_id=sim_id3,
                user_id=user_id,
                scenario=scenario3,
                baseline={"deadline": g_deadline},
                result={"new_target_date": new_target_d.isoformat()},
                assumptions=["Extending goal target date to free up monthly savings"],
                created_at=to_utc_iso(now_dt),
            )
            options.append(
                {
                    "id": f"opt_{uuid.uuid4().hex[:6]}",
                    "title": f"Shift '{g_name}' target date to {new_target_d.isoformat()}",
                    "scenario_specs": [scenario3],
                    "simulation_id": sim_id3,
                    "metrics": {
                        "goal_id": target_goal.id,
                        "new_target_date": new_target_d.isoformat(),
                    },
                }
            )

    # Limit to at most 3 options
    options = options[:3]

    plan = ContributionPlan(
        run_id=rid,
        period_from=period_from,
        horizon_months=h_months,
        waterfall_order=order,
        steps=steps,
        options=options,
        assumptions={
            "monthly_inflow_expected_paise": monthly_inflow_expected,
            "monthly_inflow_low_paise": monthly_inflow_low,
            "emergency_target_paise": emergency_target_paise,
            "emergency_fund_paise": emergency_fund_paise,
        },
    )

    insert_contribution_plan(conn, user_id, plan)
    return plan


def compare_tradeoffs(
    conn: sqlite3.Connection,
    user_id: str,
    alternatives: list[dict[str, Any]],
    horizon_months: int = 12,
    start_date: str | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
) -> TradeoffResult:
    """
    Compare up to 3 alternatives and evaluate metrics across the projection engine.

    Hard constraints:
    - Zero 'not_covered' firm commitments
    - Emergency reserve >= emergency_months_target at horizon end

    Strict safety invariant:
    - total_contributions_paise is a plain sum; strictly NO growth is applied.
    """
    config = load_contributions_config(config_path)
    clamped_alts = alternatives[: config.max_tradeoff_alternatives]
    h_months = max(1, min(config.max_horizon_months, horizon_months))
    rid = run_id or f"ta_{uuid.uuid4().hex[:12]}"

    now_dt = now_utc()
    if start_date:
        today_d = date.fromisoformat(start_date)
    else:
        today_d = from_utc_iso(to_utc_iso(now_dt)).date()

    readiness = assess_readiness(conn, user_id, today_d.isoformat())
    essential_monthly = readiness.numbers.get("essential_monthly_spend_paise", 0)
    emergency_target_months = readiness.numbers.get("emergency_months_target", 3)
    baseline_emergency = readiness.numbers.get("emergency_fund_paise", 0)

    evaluated_alts: list[TradeoffAlternative] = []

    for alt_dict in clamped_alts:
        name = alt_dict.get("name", "Alternative")
        description = alt_dict.get("description", "")
        scenarios = alt_dict.get("scenarios", [])

        # Build scenario object
        change_conts: list[dict[str, Any]] = []
        shifted_goals: list[dict[str, Any]] = []
        for s in scenarios:
            k = s.get("kind")
            if k == "change_contribution":
                change_conts.append(s)
            elif k == "shift_goal_date":
                shifted_goals.append(s)

        scen_obj = CalendarScenario(
            change_contributions=change_conts,
            shift_goal_dates=shifted_goals,
        )

        cal = build_calendar(
            conn,
            user_id,
            today_d.isoformat(),
            horizon_days=min(180, h_months * 30),
            scenario=scen_obj,
        )

        # Count not_covered firm commitments
        active_comms = {c.id: c for c in list_commitments(conn, user_id, status="active")}
        not_covered_count = 0
        for cov in cal.coverage:
            comm = active_comms.get(cov.occurrence.commitment_id)
            if comm and comm.certainty == "firm" and cov.coverage_status == "not_covered":
                not_covered_count += 1

        # Lowest projected low balance
        if cal.days:
            lowest_day = min(cal.days, key=lambda d: d.running_balance_low_paise)
            lowest_balance = lowest_day.running_balance_low_paise
            lowest_date = lowest_day.date
        else:
            lowest_balance = 0
            lowest_date = today_d.isoformat()

        shortfall_days_count = sum(1 for d in cal.days if d.below_buffer)

        # Goal completion projections under this alternative
        all_goals = list_goals(conn, user_id)
        shifted_map = {s.get("goal_id"): s.get("new_target_date") for s in shifted_goals}
        goal_completions: dict[str, str] = {}
        for g in all_goals:
            if g.status == "done":
                continue
            g_name = getattr(g, "name", "Goal")
            g_deadline = getattr(g, "deadline", None)
            effective_target_d = shifted_map.get(g.id) or g_deadline
            prog = goal_progress(conn, user_id, g, today_d)
            if prog.status == "completed" or g.status == "done":
                goal_completions[g_name] = today_d.isoformat()
            elif effective_target_d:
                goal_completions[g_name] = effective_target_d
            else:
                goal_completions[g_name] = "never_at_current_pace"

        # Calculate total planned contributions made:
        # Plain sum across horizon; zero growth!
        # Search active investment commitments
        inv_comms = [
            c
            for c in active_comms.values()
            if c.direction == "outflow" and c.kind == "investment_contribution"
        ]
        change_map = {s.get("commitment_id"): s.get("new_amount_paise") for s in change_conts}
        total_contributions = 0
        for c in inv_comms:
            amt = change_map.get(c.id, c.amount_paise)
            # plain sum across horizon months
            total_contributions += amt * h_months

        # Emergency coverage at horizon end
        # Baseline reserve + net cumulative savings over horizon
        # (approximated conservatively from end balance vs baseline)
        if cal.days and essential_monthly > 0:
            final_low_bal = max(0, cal.days[-1].running_balance_low_paise)
            emg_months = float(
                (Decimal(final_low_bal) / Decimal(essential_monthly)).quantize(Decimal("0.1"))
            )
        else:
            emg_months = float(
                (Decimal(baseline_emergency) / Decimal(max(1, essential_monthly))).quantize(
                    Decimal("0.1")
                )
            )

        # Check hard constraints
        satisfies_constraints = (not_covered_count == 0) and (emg_months >= emergency_target_months)

        metrics = {
            "goal_completions": goal_completions,
            "emergency_coverage_months": emg_months,
            "not_covered_commitments_count": not_covered_count,
            "lowest_projected_low_balance_paise": lowest_balance,
            "lowest_projected_low_balance_date": lowest_date,
            "shortfall_days": shortfall_days_count,
            "total_contributions_paise": total_contributions,
        }

        evaluated_alts.append(
            TradeoffAlternative(
                name=name,
                description=description,
                scenarios=scenarios,
                metrics=metrics,
                satisfies_all_constraints=satisfies_constraints,
            )
        )

    # Check how many satisfy all hard constraints
    satisfying = [a for a in evaluated_alts if a.satisfies_all_constraints]
    if len(satisfying) == 1:
        best_name: str | None = satisfying[0].name
    else:
        best_name = None

    result = TradeoffResult(
        run_id=rid,
        alternatives=evaluated_alts,
        best_alternative_name=best_name,
        assumptions={
            "horizon_months": h_months,
            "emergency_target_months": emergency_target_months,
            "essential_monthly_spend_paise": essential_monthly,
        },
    )

    insert_tradeoff_analysis(conn, user_id, result)
    return result
