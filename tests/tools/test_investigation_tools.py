"""
Through-executor tests for investigation tools (PLAN_PHASE2 Stage 2.4).

Verifies:
- investigate_anomaly and explain_change execute strictly through execute_tool(ctx, ...)
- Both tools write immutable rows to `investigations`, `hypotheses`, and `evidence_items`
- Both tools record audited events (investigation_executed, change_explained)
- dismiss_anomaly allows actor user, requires approval / blocks actor agent
- Strict user isolation across investigation data
- Failure paths survive cleanly with proper ToolFailure
"""

from datetime import datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_investigation,
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.investigation import register_investigation_tools
from copilot.tools.registry import clear_registry

T0 = "2026-10-15T10:00:00Z"
DT0 = datetime.fromisoformat("2026-10-15T10:00:00+00:00")


@pytest.fixture
def inv_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(
        c, Account(id="acc_1", user_id="u1", name="Main", opening_balance_paise=0, created_at=T0)
    )
    insert_category(c, Category(id="food", user_id="u1", name="Food", created_at=T0))
    insert_category(c, Category(id="shopping", user_id="u1", name="Shopping", created_at=T0))

    # Baseline: September 2026 transactions
    for i in range(5):
        insert_transaction(
            c,
            Transaction(
                id=f"tx_base_{i}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-09-0{i+1}T12:00:00Z",
                amount_paise=250_00,
                direction="debit",
                merchant_raw="SWIGGY",
                merchant_normalized="SWIGGY",
                category_id="food",
                description="Dinner",
                created_at=T0,
            ),
        )

    # Target: October 2026 transactions with a large purchase at CROMA
    insert_transaction(
        c,
        Transaction(
            id="tx_target_croma",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-10-10T14:00:00Z",
            amount_paise=25_000_00,
            direction="debit",
            merchant_raw="CROMA-ELECTRONICS",
            merchant_normalized="CROMA",
            category_id="shopping",
            description="Laptop purchase",
            created_at=T0,
        ),
    )

    clear_registry()
    register_investigation_tools()

    policy = PolicySettings(
        default="deny",
        side_effects={
            "read": {"decision": "allow"},
            "write_logical": {"decision": "needs_approval"},
            "external": {"decision": "deny"},
        },
        tools={
            "investigate_anomaly": {"decision": "allow"},
            "explain_change": {"decision": "allow"},
            "dismiss_anomaly": {"agent": "needs_approval", "user": "allow"},
        },
    )

    ctx_agent = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="agent",
        policy=policy,
        clock=DT0,
        run_id="run_1",
    )

    ctx_user = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="user",
        policy=policy,
        clock=DT0,
        run_id="run_1",
    )

    return {"conn": c, "agent": ctx_agent, "user": ctx_user}


def test_investigate_anomaly_through_executor(inv_ctx):
    """investigate_anomaly executes via execute_tool, writes to DB, emits audit event."""
    ctx = inv_ctx["agent"]

    res = execute_tool(ctx, "investigate_anomaly", {"anomaly_id": "tx_target_croma"})
    assert res.ok, f"Expected ok, got: {res.error}"

    output = res.data
    assert output.investigation.subject_kind == "anomaly"
    assert output.investigation.outcome == "explained"
    assert output.investigation.user_id == "u1"

    # Verify persisted in DB
    db_inv = get_investigation(ctx.conn, "u1", output.investigation.id)
    assert db_inv is not None
    assert db_inv.id == output.investigation.id
    assert len(db_inv.hypotheses) > 0
    assert len(db_inv.evidence) > 0

    # Verify audit event
    audit_row = ctx.conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'investigation_executed'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["user_id"] == "u1"


def test_explain_change_through_executor(inv_ctx):
    """explain_change executes via execute_tool, explains period change, writes to DB."""
    ctx = inv_ctx["agent"]

    res = execute_tool(
        ctx,
        "explain_change",
        {
            "period": "2026-10",
            "category_id": "shopping",
            "baseline_period": "2026-09",
        },
    )
    assert res.ok, f"Expected ok, got: {res.error}"

    output = res.data
    assert output.investigation.subject_kind == "category_change"
    assert output.investigation.explained_share_bp > 0
    assert "volume_effect_paise" in output.decomposition

    # Verify audit event
    audit_row = ctx.conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'change_explained'"
    ).fetchone()
    assert audit_row is not None


def test_dismiss_anomaly_governance_and_audit(inv_ctx):
    """
    dismiss_anomaly is user-only:
    - Actor agent is blocked with APPROVAL_REQUIRED
    - Actor user succeeds and records anomaly_dismissed audit event
    """
    agent_ctx = inv_ctx["agent"]
    user_ctx = inv_ctx["user"]

    # 1. Agent actor blocked
    res_agent = execute_tool(
        agent_ctx, "dismiss_anomaly", {"anomaly_id": "tx_target_croma", "reason": "Expected"}
    )
    assert not res_agent.ok
    assert res_agent.error.code == ErrorCode.APPROVAL_REQUIRED

    # 2. User actor allowed
    res_user = execute_tool(
        user_ctx, "dismiss_anomaly", {"anomaly_id": "tx_target_croma", "reason": "Planned spend"}
    )
    assert res_user.ok
    assert res_user.data.status == "dismissed"

    # Verify audit event
    row = user_ctx.conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'anomaly_dismissed'"
    ).fetchone()
    assert row is not None
    assert row["actor"] == "user"


def test_investigation_user_isolation(inv_ctx):
    """Investigations cannot be viewed or triggered across user boundaries."""
    c = inv_ctx["conn"]
    insert_user(c, User(id="u2", created_at=T0))

    policy = inv_ctx["agent"].policy
    ctx_u2 = ExecutionContext(
        conn=c,
        user_id="u2",
        actor="agent",
        policy=policy,
        clock=DT0,
        run_id="run_2",
    )

    # u2 attempting to investigate u1's anomaly fails with INVALID_INPUT
    res = execute_tool(ctx_u2, "investigate_anomaly", {"anomaly_id": "tx_target_croma"})
    assert not res.ok
    assert res.error.code == ErrorCode.INVALID_INPUT

    # First run investigation as u1
    res_u1 = execute_tool(inv_ctx["agent"], "investigate_anomaly", {"anomaly_id": "tx_target_croma"})
    assert res_u1.ok
    inv_id = res_u1.data.investigation.id

    # u2 querying u1's investigation returns None
    assert get_investigation(c, "u2", inv_id) is None


def test_explain_change_failure_path_invalid_period(inv_ctx):
    """Invalid period format cleanly fails with INVALID_INPUT."""
    ctx = inv_ctx["agent"]
    res = execute_tool(ctx, "explain_change", {"period": "invalid_date_format"})
    assert not res.ok
    assert res.error.code == ErrorCode.INVALID_INPUT
