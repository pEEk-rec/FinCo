"""
Tool specifications and handlers for what-if simulation (PLAN_PHASE2 Section 5.6).

Governance:
- run_whatif and compare_options: SideEffect.READ, planner-selectable (compute class).
- Simulation execution writes immutable explanation records to `simulations` and
  records audit events.
- Never mutates financial state (accounts, budgets, transactions).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field, StrictInt

from copilot.audit.events import record_event
from copilot.core.simulation import (
    ScenarioComparison,
    build_snapshot,
    compare_scenarios,
    simulate,
)
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.repo import insert_simulation
from copilot.models.agentic import Projection, Scenario, ScenarioKind
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# ---------------------------------------------------------------------------------------------
# 1. run_whatif
# ---------------------------------------------------------------------------------------------
class RunWhatIfInput(ToolInput):
    """Input parameters for simulating a financial scenario."""

    scenario: Scenario | None = None
    kind: ScenarioKind | None = None
    amount_paise: StrictInt | None = None
    category_id: str | None = None
    start_month: str | None = None
    recurring: bool = False
    months: int = 1
    goal_id: str | None = None
    horizon_months: int | None = Field(default=None, ge=1, le=6)


class RunWhatIfOutput(ToolOutput):
    """Result of what-if scenario simulation."""

    projection: Projection
    simulation_id: str


def run_whatif_handler(ctx: "ExecutionContext", **kwargs) -> RunWhatIfOutput:
    params = RunWhatIfInput.model_validate(kwargs)
    ts = to_utc_iso(now_utc(ctx.clock))
    sim_id = f"sim_{uuid.uuid4().hex[:8]}"

    scenario = params.scenario
    if scenario is None:
        now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
        ist_now = now_dt.astimezone(IST)
        start_m = params.start_month or f"{ist_now.year:04d}-{ist_now.month:02d}"
        scenario = Scenario(
            kind=params.kind or "add_spend",
            amount_paise=params.amount_paise or 0,
            category_id=params.category_id,
            start_month=start_m,
            recurring=params.recurring,
            months=params.months,
            goal_id=params.goal_id,
        )

    snapshot = build_snapshot(ctx.conn, ctx.user_id, ctx.clock or ts)
    projection = simulate(snapshot, scenario, params.horizon_months)

    # Persist immutable explanation record
    insert_simulation(
        conn=ctx.conn,
        sim_id=sim_id,
        user_id=ctx.user_id,
        scenario=scenario.model_dump(mode="json"),
        baseline={
            "income_paise": snapshot.estimated_monthly_income_paise,
            "category_spend": snapshot.baseline_variable_spend_by_category,
        },
        result=projection.model_dump(mode="json"),
        assumptions=projection.assumptions,
        created_at=ts,
        task_id=None,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="whatif_simulated",
        reason=f"What-if scenario '{scenario.kind}' simulated by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="simulation",
        entity_id=sim_id,
        metadata={
            "simulation_id": sim_id,
            "kind": scenario.kind,
            "amount_paise": scenario.amount_paise,
        },
        clock=ctx.clock,
    )

    return RunWhatIfOutput(projection=projection, simulation_id=sim_id)


# ---------------------------------------------------------------------------------------------
# 2. compare_options
# ---------------------------------------------------------------------------------------------
class CompareOptionsInput(ToolInput):
    """Input parameters for comparing up to 3 scenarios side-by-side."""

    scenarios: list[Scenario] = Field(min_length=1, max_length=3)
    horizon_months: int | None = Field(default=None, ge=1, le=6)


class CompareOptionsOutput(ToolOutput):
    """Side-by-side comparison of scenarios against baseline."""

    comparison: ScenarioComparison
    simulation_id: str


def compare_options_handler(ctx: "ExecutionContext", **kwargs) -> CompareOptionsOutput:
    params = CompareOptionsInput.model_validate(kwargs)
    ts = to_utc_iso(now_utc(ctx.clock))
    sim_id = f"sim_{uuid.uuid4().hex[:8]}"

    snapshot = build_snapshot(ctx.conn, ctx.user_id, ctx.clock or ts)
    comparison = compare_scenarios(snapshot, params.scenarios, params.horizon_months)

    # Persist explanation record
    insert_simulation(
        conn=ctx.conn,
        sim_id=sim_id,
        user_id=ctx.user_id,
        scenario={"count": len(params.scenarios), "kinds": [s.kind for s in params.scenarios]},
        baseline={
            "income_paise": snapshot.estimated_monthly_income_paise,
            "category_spend": snapshot.baseline_variable_spend_by_category,
        },
        result=comparison.model_dump(mode="json"),
        assumptions=comparison.baseline.assumptions,
        created_at=ts,
        task_id=None,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="scenarios_compared",
        reason=f"Comparison of {len(params.scenarios)} scenarios by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="simulation",
        entity_id=sim_id,
        metadata={
            "simulation_id": sim_id,
            "scenario_count": len(params.scenarios),
        },
        clock=ctx.clock,
    )

    return CompareOptionsOutput(comparison=comparison, simulation_id=sim_id)


# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------
WHATIF_TOOLS = (
    ToolSpec(
        name="run_whatif",
        description="Simulate financial outcomes of a spending or contribution scenario.",
        input_model=RunWhatIfInput,
        output_model=RunWhatIfOutput,
        side_effect=SideEffect.READ,
        handler=run_whatif_handler,
    ),
    ToolSpec(
        name="compare_options",
        description="Compare up to 3 what-if scenarios side-by-side with the baseline.",
        input_model=CompareOptionsInput,
        output_model=CompareOptionsOutput,
        side_effect=SideEffect.READ,
        handler=compare_options_handler,
    ),
)


def register_whatif_tools(register_fn=register) -> None:
    """Register what-if simulation tools into the global registry."""
    for spec in WHATIF_TOOLS:
        register_fn(spec)
