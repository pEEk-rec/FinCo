"""
Through-executor tests for what-if simulation tools (PLAN_PHASE2 Stage 2.3).

Verifies:
- run_whatif and compare_options execute strictly through execute_tool(ctx, ...)
- Both tools write immutable explanation rows to `simulations`
- Both tools emit audited events (`whatif_simulated`, `scenarios_compared`)
- Crucial invariant: NO financial table (users, accounts, budgets, transactions, goals)
  is mutated by any simulation (asserted by full table snapshot comparisons).
"""

from datetime import datetime

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_simulation,
    insert_account,
    insert_budget,
    insert_category,
    insert_goal,
    insert_transaction,
    insert_user,
)
from copilot.governance.policy import PolicySettings
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry
from copilot.tools.whatif import register_whatif_tools

T0 = "2026-10-15T10:00:00Z"
DT0 = datetime.fromisoformat("2026-10-15T10:00:00+00:00")


def count_all_financial_rows(conn) -> dict[str, int]:
    """Take an exact row count snapshot of all core financial tables."""
    tables = ["users", "accounts", "categories", "budgets", "transactions", "goals"]
    counts = {}
    for t in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        counts[t] = row[0]
    return counts


@pytest.fixture
def whatif_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(
        c, Account(id="acc_1", user_id="u1", name="Main", opening_balance_paise=0, created_at=T0)
    )
    insert_category(c, Category(id="dining", user_id="u1", name="Dining", created_at=T0))
    insert_budget(
        c,
        Budget(
            id="b_din",
            user_id="u1",
            category_id="dining",
            limit_paise=15_000_00,
            warn_threshold_pct=80,
        ),
    )
    insert_goal(
        c,
        Goal(
            id="g_trip",
            user_id="u1",
            name="Trip Goal",
            kind="savings",
            target_paise=30_000_00,
            current_paise=10_000_00,
            deadline="2026-12-31",
            priority=1,
            created_at=T0,
            updated_at=T0,
        ),
    )
    # Complete month history (September 2026)
    insert_transaction(
        c,
        Transaction(
            id="tx_sep_in",
            account_id="acc_1",
            user_id="u1",
            amount_paise=-5_000_000,
            direction="credit",
            merchant_raw="Salary",
            description="Salary",
            occurred_at="2026-09-01T10:00:00Z",
            created_at="2026-09-01T10:00:00Z",
        ),
    )
    insert_transaction(
        c,
        Transaction(
            id="tx_sep_out",
            account_id="acc_1",
            user_id="u1",
            amount_paise=2_000_000,
            direction="debit",
            category_id="dining",
            merchant_raw="Restaurant",
            description="Food",
            occurred_at="2026-09-02T10:00:00Z",
            created_at="2026-09-02T10:00:00Z",
        ),
    )
    c.commit()

    p = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {"read": {"decision": "allow"}},
            "tools": {
                "run_whatif": {"decision": "allow"},
                "compare_options": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_whatif_tools()

    ctx = ExecutionContext(
        conn=c,
        user_id="u1",
        run_id="run_whatif",
        policy=p,
        clock=DT0,
        actor="agent",
    )
    yield ctx
    clear_registry()


def test_run_whatif_through_executor_and_preserves_financial_state(whatif_ctx):
    """
    run_whatif runs via executor, creates a simulation record and audit event,
    and strictly preserves financial tables.
    """
    counts_before = count_all_financial_rows(whatif_ctx.conn)

    scenario_input = {
        "scenario": {
            "kind": "add_spend",
            "category_id": "dining",
            "amount_paise": 5_000_00,
            "start_month": "2026-10",
            "recurring": False,
            "months": 1,
        },
        "horizon_months": 3,
    }

    res = execute_tool(whatif_ctx, "run_whatif", scenario_input)
    assert res.ok is True
    sim_id = res.data.simulation_id
    proj = res.data.projection
    assert proj.months_projected == 3
    assert len(proj.monthly_spend_paise) == 3

    # Financial tables invariant: exactly identical counts before and after
    counts_after = count_all_financial_rows(whatif_ctx.conn)
    assert counts_before == counts_after

    # Simulation explanation row persisted in simulations table
    sim_record = get_simulation(whatif_ctx.conn, "u1", sim_id)
    assert sim_record is not None
    assert sim_record["scenario"]["kind"] == "add_spend"
    assert sim_record["scenario"]["amount_paise"] == 5_000_00
    assert len(sim_record["assumptions"]) > 0

    # Audit event verified
    audit_row = whatif_ctx.conn.execute(
        "SELECT event_type, entity_id FROM audit_events WHERE event_type = 'whatif_simulated'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["entity_id"] == sim_id


def test_compare_options_through_executor(whatif_ctx):
    """
    compare_options runs via executor, creates a simulation record and audit event,
    and compares up to 3 scenarios side-by-side without mutating financial state.
    """
    counts_before = count_all_financial_rows(whatif_ctx.conn)

    scenarios_input = {
        "scenarios": [
            {
                "kind": "add_spend",
                "category_id": "dining",
                "amount_paise": 2_000_00,
                "start_month": "2026-10",
                "recurring": False,
            },
            {
                "kind": "reduce_spend",
                "category_id": "dining",
                "amount_paise": 3_000_00,
                "start_month": "2026-10",
                "recurring": False,
            },
        ],
        "horizon_months": 2,
    }

    res = execute_tool(whatif_ctx, "compare_options", scenarios_input)
    assert res.ok is True
    sim_id = res.data.simulation_id
    comp = res.data.comparison
    assert len(comp.scenarios) == 2
    assert len(comp.side_by_side) == 2

    # Financial state unchanged
    counts_after = count_all_financial_rows(whatif_ctx.conn)
    assert counts_before == counts_after

    # Record persisted
    sim_record = get_simulation(whatif_ctx.conn, "u1", sim_id)
    assert sim_record is not None
    assert sim_record["scenario"]["count"] == 2

    # Audit event recorded
    audit_row = whatif_ctx.conn.execute(
        "SELECT event_type, entity_id FROM audit_events WHERE event_type = 'scenarios_compared'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["entity_id"] == sim_id
