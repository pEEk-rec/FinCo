"""
Through-executor tests for Investment Readiness Tools (PLAN_PHASE3 Section 5.6 & Stage 3.6).

Verifies:
- All tools execute strictly through execute_tool(ctx, ...).
- Both user and agent actors can execute assess_investment_readiness and get_readiness_assessment.
- Snapshot explanation row is persisted and retrievable.
- Policy enforcement (allow by default, denied when unconfigured).
- Strict multi-tenant isolation.
- Input validation on malformed inputs.
"""

from datetime import datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.db.repo_phase3 import (
    get_latest_readiness_assessment,
    list_readiness_assessments,
    set_user_preference,
)
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.readiness import register_readiness_tools
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
            opening_balance_paise=20000000,
            created_at=T0,
        ),
    )
    insert_account(
        c,
        Account(
            id="acc_2",
            user_id="u2",
            name="Checking",
            opening_balance_paise=5000000,
            created_at=T0,
        ),
    )
    # Standard categories
    for cat in ["income", "rent", "dining", "groceries"]:
        insert_category(c, Category(id=f"cat_{cat}_u1", user_id="u1", name=cat.title(), created_at=T0))
        insert_category(c, Category(id=f"cat_{cat}_u2", user_id="u2", name=cat.title(), created_at=T0))

    # Add 3 complete months of history for u1 (July, August, September 2026)
    for mo in (7, 8, 9):
        # Income
        insert_transaction(
            c,
            Transaction(
                id=f"tx_inc_u1_{mo}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-{mo:02d}-02T10:00:00Z",
                amount_paise=-6000000,
                direction="credit",
                category_id="cat_income_u1",
                description="Salary",
                merchant_raw="Employer",
                created_at=T0,
            ),
        )
        # Rent
        insert_transaction(
            c,
            Transaction(
                id=f"tx_rent_u1_{mo}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-{mo:02d}-05T12:00:00Z",
                amount_paise=2000000,
                direction="debit",
                category_id="cat_rent_u1",
                description="Rent",
                merchant_raw="Landlord",
                created_at=T0,
            ),
        )

    set_user_preference(c, "u1", "emergency_reserve_paise", 8000000, T0)
    set_user_preference(c, "u1", "high_cost_debt", False, T0)

    policy = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "needs_approval"},
            },
            "tools": {
                "assess_investment_readiness": {"decision": "allow"},
                "get_readiness_assessment": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_readiness_tools()

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


def test_assess_investment_readiness_tool_execution(test_ctx):
    """assess_investment_readiness executes through execute_tool and writes snapshot."""
    ctx_user, ctx_agent, _ = test_ctx

    # 1. User execution
    res_user = execute_tool(
        ctx_user,
        "assess_investment_readiness",
        {"today": "2026-10-15"},
    )
    assert res_user.ok, f"Expected ok, got error: {res_user.error}"
    data = res_user.data
    assert data.readiness.level == "ready"
    assert data.assessment_id.startswith("ra_")

    # Verify snapshot row in SQLite
    latest = get_latest_readiness_assessment(ctx_user.conn, "u1")
    assert latest is not None
    assert latest.level == "ready"
    assert latest.assessed_on == "2026-10-15"

    # 2. Agent execution (analytical compute is allowed for agent)
    res_agent = execute_tool(
        ctx_agent,
        "assess_investment_readiness",
        {"today": "2026-10-15"},
    )
    assert res_agent.ok
    assert res_agent.data.readiness.level == "ready"


def test_get_readiness_assessment_alias(test_ctx):
    """get_readiness_assessment alias executes cleanly and returns readiness."""
    ctx_user, _, _ = test_ctx

    res = execute_tool(
        ctx_user,
        "get_readiness_assessment",
        {"today": "2026-10-15"},
    )
    assert res.ok
    assert res.data.readiness.level == "ready"
    assert len(res.data.readiness.criteria) == 7


def test_readiness_tool_policy_governance(test_ctx):
    """Denying readiness tool in policy rejects execution with DENIED_BY_POLICY."""
    ctx_user, _, _ = test_ctx

    deny_policy = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "deny"},
                "write_logical": {"decision": "deny"},
            },
            "tools": {
                "assess_investment_readiness": {"decision": "deny"},
            },
        }
    )
    denied_ctx = ExecutionContext(
        conn=ctx_user.conn,
        user_id="u1",
        actor="agent",
        policy=deny_policy,
        clock=DT0,
        run_id="run_denied",
    )
    res = execute_tool(denied_ctx, "assess_investment_readiness", {"today": "2026-10-15"})
    assert not res.ok
    assert res.error.code == ErrorCode.DENIED_BY_POLICY


def test_readiness_tool_multi_tenant_isolation(test_ctx):
    """User 2 only sees their own data through execute_tool."""
    _, _, ctx_u2 = test_ctx

    res = execute_tool(ctx_u2, "assess_investment_readiness", {"today": "2026-10-15"})
    assert res.ok
    # User 2 has zero transaction history
    assert res.data.readiness.level == "insufficient_data"
    assert res.data.readiness.numbers["history_months_recorded"] == 0

    # User 2's snapshot list does not contain User 1's
    u2_list = list_readiness_assessments(ctx_u2.conn, "u2")
    assert len(u2_list) == 1
    assert u2_list[0].level == "insufficient_data"


def test_readiness_tool_input_validation(test_ctx):
    """Extra fields or invalid date patterns fail validation."""
    ctx_user, _, _ = test_ctx

    # Extra inputs forbidden
    res_bad = execute_tool(
        ctx_user,
        "assess_investment_readiness",
        {"today": "2026-10-15", "unexpected_field": "injected"},
    )
    assert not res_bad.ok
    assert res_bad.error.code == ErrorCode.INVALID_INPUT

    # Bad date format
    res_date = execute_tool(
        ctx_user,
        "assess_investment_readiness",
        {"today": "invalid-date-format"},
    )
    assert not res_date.ok
    assert res_date.error.code == ErrorCode.INVALID_INPUT
