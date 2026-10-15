"""
Tool execution tests for Contribution Planning and Trade-off Analysis (PLAN_PHASE3 Stage 3.7).

Verifies:
- All tools execute through execute_tool choke point
- Policy rules respected for all actors
- Explanation snapshots persisted in contribution_plans and tradeoff_analyses tables
- Strict multi-tenant isolation
"""

from datetime import UTC, datetime

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.db.repo_phase3 import (
    get_latest_contribution_plan,
    get_latest_tradeoff_analysis,
)
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.contributions import register_contributions_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry

T0 = "2026-10-01T10:00:00Z"


@pytest.fixture
def conn():
    """In-memory SQLite connection with migrations applied."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def policy():
    """Default policy configuration."""
    return PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "needs_approval"},
            },
            "tools": {
                "plan_contributions": {"decision": "allow"},
                "compare_tradeoffs": {"decision": "allow"},
            },
        }
    )


@pytest.fixture(autouse=True)
def setup_tools():
    """Register tools in clean registry before each test."""
    clear_registry()
    from copilot.tools.calendar import register_calendar_tools
    from copilot.tools.readiness import register_readiness_tools

    register_calendar_tools()
    register_readiness_tools()
    register_contributions_tools()
    yield
    clear_registry()


def _setup_test_environment(conn, user_id="u_tool_plan"):
    insert_user(conn, User(id=user_id, created_at=T0))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=10000000,
            created_at=T0,
        ),
    )
    for cat in ["income", "rent", "groceries", "utilities", "investments"]:
        try:
            insert_category(
                conn,
                Category(
                    id=f"cat_{cat}_{user_id}",
                    user_id=user_id,
                    name=cat.title(),
                    created_at=T0,
                ),
            )
        except Exception:
            pass

    # Record transactions
    for m in [7, 8, 9]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_inc_{m}_{user_id}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                amount_paise=-8000000,
                direction="credit",
                category_id=f"cat_income_{user_id}",
                description="Salary",
                merchant_raw="Employer Inc",
                occurred_at=f"2026-{m:02d}-01T10:00:00Z",
                created_at=f"2026-{m:02d}-01T10:00:00Z",
            ),
        )
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_exp_{m}_{user_id}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                amount_paise=2500000,
                direction="debit",
                category_id=f"cat_groceries_{user_id}",
                description="Groceries",
                merchant_raw="Supermarket",
                occurred_at=f"2026-{m:02d}-05T10:00:00Z",
                created_at=f"2026-{m:02d}-05T10:00:00Z",
            ),
        )


def test_plan_contributions_through_executor_and_persisted(conn, policy):
    """Verify plan_contributions executes through execute_tool and writes snapshot."""
    u = "u_plan_exec"
    _setup_test_environment(conn, u)

    ctx = ExecutionContext(
        conn=conn,
        user_id=u,
        actor="user",
        policy=policy,
        clock=datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC),
        run_id="run_plan_test",
    )

    res = execute_tool(
        ctx,
        "plan_contributions",
        {"horizon_months": 6, "start_date": "2026-10-15"},
    )
    assert res.ok, f"Tool execution failed: {res.error}"
    assert res.data is not None
    plan = res.data.plan
    assert plan.horizon_months == 6
    assert len(plan.steps) >= 4

    # Verify snapshot persisted in database
    latest_plan = get_latest_contribution_plan(conn, u)
    assert latest_plan is not None
    assert latest_plan.horizon_months == 6


def test_compare_tradeoffs_through_executor_and_persisted(conn, policy):
    """Verify compare_tradeoffs executes through execute_tool and writes snapshot."""
    u = "u_tradeoff_exec"
    _setup_test_environment(conn, u)

    ctx = ExecutionContext(
        conn=conn,
        user_id=u,
        actor="agent",  # Test agent actor execution
        policy=policy,
        clock=datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC),
        run_id="run_tradeoff_test",
    )

    alts = [
        {
            "name": "Alternative A",
            "description": "Baseline plan",
            "scenarios": [],
        },
        {
            "name": "Alternative B",
            "description": "Alternative with pause",
            "scenarios": [],
        },
    ]

    res = execute_tool(
        ctx,
        "compare_tradeoffs",
        {"alternatives": alts, "horizon_months": 12, "start_date": "2026-10-15"},
    )
    assert res.ok, f"Tool execution failed: {res.error}"
    assert res.data is not None
    result = res.data.result
    assert len(result.alternatives) == 2

    # Verify snapshot persisted
    latest_tradeoff = get_latest_tradeoff_analysis(conn, u)
    assert latest_tradeoff is not None
    assert len(latest_tradeoff.alternatives) == 2


def test_contributions_tools_multi_tenant_isolation(conn, policy):
    """Verify user isolation: User A cannot see User B's plan snapshots."""
    u_a = "u_alice_contrib_tool"
    u_b = "u_bob_contrib_tool"
    _setup_test_environment(conn, u_a)
    _setup_test_environment(conn, u_b)

    ctx_a = ExecutionContext(
        conn=conn,
        user_id=u_a,
        actor="user",
        policy=policy,
        clock=datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC),
        run_id="run_alice_test",
    )
    ctx_b = ExecutionContext(
        conn=conn,
        user_id=u_b,
        actor="user",
        policy=policy,
        clock=datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC),
        run_id="run_bob_test",
    )

    # Alice runs plan
    res_a = execute_tool(ctx_a, "plan_contributions", {"horizon_months": 6})
    assert res_a.ok, f"Alice plan failed: {res_a.error}"

    # Bob has not run a plan yet
    plan_b = get_latest_contribution_plan(conn, u_b)
    assert plan_b is None

    # Bob runs plan
    res_b = execute_tool(ctx_b, "plan_contributions", {"horizon_months": 12})
    assert res_b.ok, f"Bob plan failed: {res_b.error}"

    plan_a_latest = get_latest_contribution_plan(conn, u_a)
    plan_b_latest = get_latest_contribution_plan(conn, u_b)
    assert plan_a_latest.horizon_months == 6
    assert plan_b_latest.horizon_months == 12
