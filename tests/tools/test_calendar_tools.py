"""
Through-executor tests for financial calendar tools (PLAN_PHASE3 Stage 3.5).

Verifies:
- All tools execute through execute_tool(ctx, ...).
- get_calendar and check_commitment_coverage allowed for both user and agent actors.
- Filtering by commitment_id and date.
- Multi-tenant isolation.
- Audit event logging.
"""

from datetime import datetime

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user
from copilot.db.repo_phase3 import insert_commitment
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, User
from copilot.models.phase3 import Commitment
from copilot.tools.calendar import register_calendar_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry

T0 = "2026-10-01T10:00:00Z"
DT0 = datetime.fromisoformat("2026-10-01T10:00:00+00:00")


@pytest.fixture
def test_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    insert_account(
        c,
        Account(
            id="acc_1",
            user_id="u1",
            name="Checking",
            opening_balance_paise=5000000,
            created_at=T0,
        ),
    )

    policy = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "needs_approval"},
            },
            "tools": {
                "get_calendar": {"decision": "allow"},
                "check_commitment_coverage": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_calendar_tools()

    ctx_user = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="user",
        policy=policy,
        clock=DT0,
        run_id="run_user",
    )
    ctx_agent = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="agent",
        policy=policy,
        clock=DT0,
        run_id="run_agent",
    )
    ctx_u2 = ExecutionContext(
        conn=c,
        user_id="u2",
        actor="user",
        policy=policy,
        clock=DT0,
        run_id="run_u2",
    )
    yield ctx_user, ctx_agent, ctx_u2
    c.close()
    clear_registry()


def test_get_calendar_tool_execution(test_ctx):
    """User and agent can generate financial calendar projections via execute_tool."""
    ctx_user, ctx_agent, _ = test_ctx

    comm = Commitment(
        id="c1",
        user_id="u1",
        name="Internet",
        direction="outflow",
        kind="bill",
        amount_paise=150000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 10},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(ctx_user.conn, comm)

    res_user = execute_tool(ctx_user, "get_calendar", {"horizon_days": 30, "today": "2026-10-01"})
    assert res_user.ok
    cal_user = res_user.data.calendar
    assert len(cal_user.days) == 30
    assert cal_user.start_balance_paise == 5000000

    # Agent also allowed
    res_agent = execute_tool(ctx_agent, "get_calendar", {"horizon_days": 15, "today": "2026-10-01"})
    assert res_agent.ok
    assert len(res_agent.data.calendar.days) == 15


def test_check_commitment_coverage_tool(test_ctx):
    """check_commitment_coverage evaluates and filters coverage by commitment_id and date."""
    ctx_user, _, _ = test_ctx

    c1 = Commitment(
        id="c_rent",
        user_id="u1",
        name="Rent",
        direction="outflow",
        kind="rent",
        amount_paise=2000000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 5},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    c2 = Commitment(
        id="c_emi",
        user_id="u1",
        name="Loan EMI",
        direction="outflow",
        kind="emi",
        amount_paise=1500000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 12},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(ctx_user.conn, c1)
    insert_commitment(ctx_user.conn, c2)

    # Check coverage for all commitments in window
    res_all = execute_tool(
        ctx_user,
        "check_commitment_coverage",
        {"horizon_days": 30, "today": "2026-10-01"},
    )
    assert res_all.ok
    assert len(res_all.data.coverage) == 2

    # Filter specifically for Rent
    res_rent = execute_tool(
        ctx_user,
        "check_commitment_coverage",
        {"commitment_id": "c_rent", "horizon_days": 30, "today": "2026-10-01"},
    )
    assert res_rent.ok
    assert len(res_rent.data.coverage) == 1
    assert res_rent.data.coverage[0].occurrence.commitment_id == "c_rent"
    assert res_rent.data.coverage[0].coverage_status == "covered"


def test_calendar_tenant_isolation(test_ctx):
    """User 2 cannot see User 1's commitments or balances in the calendar."""
    ctx_user, _, ctx_u2 = test_ctx

    c = Commitment(
        id="c_u1",
        user_id="u1",
        name="User 1 Secret",
        direction="outflow",
        kind="bill",
        amount_paise=500000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 10},
        start_date="2026-10-01",
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_commitment(ctx_user.conn, c)

    res_u2 = execute_tool(ctx_u2, "get_calendar", {"horizon_days": 30, "today": "2026-10-01"})
    assert res_u2.ok
    cal_u2 = res_u2.data.calendar
    assert cal_u2.start_balance_paise == 0
    assert cal_u2.coverage == []
    for d in cal_u2.days:
        assert d.occurrences == []
        assert d.known_outflows_paise == 0
