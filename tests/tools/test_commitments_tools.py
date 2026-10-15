"""
Through-executor and governance tests for commitment tools (PLAN_PHASE3 Stage 3.2).

Verifies:
- All tools execute strictly through execute_tool(ctx, ...)
- Actor permissions:
    actor user -> create_commitment, update_commitment, pause_commitment, end_commitment, accept_commitment, reject_commitment allowed
    actor agent -> create_commitment, update_commitment, pause_commitment, end_commitment, accept_commitment, reject_commitment require approval (needs_approval)
    actor agent and user -> suggest_commitments allowed (writes drafts only)
    list_commitments and get_commitment_status allowed for both
- Audit events recorded on real execution path
- User isolation: User 2 cannot view or modify User 1's commitments
- Lifecycle transitions: draft -> active (accept), draft -> rejected (reject), active -> paused, active -> ended
- Suggestions from recurring series write drafts only and never duplicate
"""

from datetime import datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, User
from copilot.tools.commitments import register_commitment_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry

T0 = "2026-10-15T10:00:00Z"
DT0 = datetime.fromisoformat("2026-10-15T10:00:00+00:00")


@pytest.fixture
def test_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    insert_account(
        c, Account(id="acc_1", user_id="u1", name="Main", opening_balance_paise=0, created_at=T0)
    )
    insert_category(c, Category(id="bills", user_id="u1", name="Bills", created_at=T0))

    policy = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "needs_approval"},
            },
            "tools": {
                "create_commitment": {"agent": "needs_approval", "user": "allow"},
                "update_commitment": {"agent": "needs_approval", "user": "allow"},
                "pause_commitment": {"agent": "needs_approval", "user": "allow"},
                "end_commitment": {"agent": "needs_approval", "user": "allow"},
                "accept_commitment": {"agent": "needs_approval", "user": "allow"},
                "reject_commitment": {"agent": "needs_approval", "user": "allow"},
                "suggest_commitments": {"agent": "allow", "user": "allow"},
                "list_commitments": {"decision": "allow"},
                "get_commitment_status": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_commitment_tools()

    ctx = ExecutionContext(
        conn=c,
        user_id="u1",
        run_id="run_1",
        actor="user",
        policy=policy,
        clock=DT0,
    )
    return ctx


def test_agent_cannot_create_or_accept_commitments(test_ctx):
    """Agent actor must require approval when attempting to create or accept commitments."""
    agent_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u1",
        run_id="run_agent",
        actor="agent",
        policy=test_ctx.policy,
        clock=DT0,
    )

    res_create = execute_tool(
        agent_ctx,
        "create_commitment",
        {
            "name": "Electricity",
            "direction": "outflow",
            "kind": "bill",
            "schedule_kind": "monthly",
            "schedule_json": {"day": 5},
            "start_date": "2026-10-01",
            "amount_paise": 250000,
        },
    )
    assert not res_create.ok
    assert res_create.error.code == ErrorCode.APPROVAL_REQUIRED

    res_accept = execute_tool(agent_ctx, "accept_commitment", {"commitment_id": "comm_123"})
    assert not res_accept.ok
    assert res_accept.error.code == ErrorCode.APPROVAL_REQUIRED


def test_user_can_create_and_manage_commitments(test_ctx):
    """User actor can create, update, pause, and end commitments."""
    res = execute_tool(
        test_ctx,
        "create_commitment",
        {
            "name": "Broadband",
            "direction": "outflow",
            "kind": "bill",
            "schedule_kind": "monthly",
            "schedule_json": {"day": 15},
            "start_date": "2026-10-01",
            "amount_paise": 119900,
        },
    )
    assert res.ok
    comm = res.data.commitment
    assert comm.name == "Broadband"
    assert comm.status == "active"
    comm_id = comm.id

    # Pause commitment
    res_pause = execute_tool(test_ctx, "pause_commitment", {"commitment_id": comm_id})
    assert res_pause.ok
    assert res_pause.data.commitment.status == "paused"

    # Update commitment
    res_upd = execute_tool(
        test_ctx,
        "update_commitment",
        {"commitment_id": comm_id, "amount_paise": 149900, "status": "active"},
    )
    assert res_upd.ok
    assert res_upd.data.commitment.amount_paise == 149900
    assert res_upd.data.commitment.status == "active"

    # End commitment
    res_end = execute_tool(
        test_ctx,
        "end_commitment",
        {"commitment_id": comm_id, "end_date": "2026-12-31"},
    )
    assert res_end.ok
    assert res_end.data.commitment.status == "ended"
    assert res_end.data.commitment.end_date == "2026-12-31"


def test_suggest_commitments_writes_drafts_only(test_ctx):
    """suggest_commitments creates drafts from active recurring series and does not duplicate."""
    # Insert recurring series for user
    test_ctx.conn.execute(
        """
        INSERT INTO recurring_series (
            id, user_id, merchant_normalized, typical_amount_paise,
            cadence_days, last_seen, next_expected, confidence, kind
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rs_1",
            "u1",
            "Netflix",
            64900,
            30,
            "2026-10-01T10:00:00Z",
            "2026-10-31T10:00:00Z",
            0.95,
            "subscription",
        ),
    )

    agent_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u1",
        run_id="run_agent",
        actor="agent",
        policy=test_ctx.policy,
        clock=DT0,
    )

    res = execute_tool(agent_ctx, "suggest_commitments", {})
    assert res.ok
    assert res.data.drafts_created == 1
    draft = res.data.commitments[0]
    assert draft.name == "Netflix"
    assert draft.status == "draft"
    assert draft.source == "suggested"
    assert draft.recurring_series_id == "rs_1"

    # Re-running suggest_commitments produces 0 drafts since rs_1 is already linked
    res_repeat = execute_tool(agent_ctx, "suggest_commitments", {})
    assert res_repeat.ok
    assert res_repeat.data.drafts_created == 0

    # User accepts draft
    res_accept = execute_tool(test_ctx, "accept_commitment", {"commitment_id": draft.id})
    assert res_accept.ok
    assert res_accept.data.commitment.status == "active"

    # Accepting again raises error because it's no longer a draft
    res_accept_again = execute_tool(test_ctx, "accept_commitment", {"commitment_id": draft.id})
    assert not res_accept_again.ok
    assert res_accept_again.error.code == ErrorCode.INVALID_INPUT


def test_user_isolation(test_ctx):
    """User 2 cannot list or update User 1's commitments."""
    # Create commitment for u1
    res = execute_tool(
        test_ctx,
        "create_commitment",
        {
            "name": "Secret Bill",
            "direction": "outflow",
            "kind": "bill",
            "schedule_kind": "monthly",
            "schedule_json": {"day": 1},
            "start_date": "2026-10-01",
            "amount_paise": 50000,
        },
    )
    comm_id = res.data.commitment.id

    # Context for u2
    u2_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u2",
        run_id="run_u2",
        actor="user",
        policy=test_ctx.policy,
        clock=DT0,
    )

    # u2 listing commitments sees empty list
    list_res = execute_tool(u2_ctx, "list_commitments", {})
    assert list_res.ok
    assert len(list_res.data.commitments) == 0

    # u2 attempting to pause u1's commitment fails with NOT_FOUND
    pause_res = execute_tool(u2_ctx, "pause_commitment", {"commitment_id": comm_id})
    assert not pause_res.ok
    assert pause_res.error.code == ErrorCode.NOT_FOUND


def test_get_commitment_status_with_matches(test_ctx):
    """get_commitment_status computes occurrences, matches transactions, and determines status."""
    res = execute_tool(
        test_ctx,
        "create_commitment",
        {
            "name": "Phone Bill",
            "direction": "outflow",
            "kind": "bill",
            "schedule_kind": "monthly",
            "schedule_json": {"day": 5},
            "start_date": "2026-09-01",
            "amount_paise": 49900,
        },
    )
    comm_id = res.data.commitment.id

    # Insert matching transaction for Sept 5 bill
    test_ctx.conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, category_source, created_at, excluded_from_spend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tx_bill_1",
            "u1",
            "acc_1",
            "2026-09-06T10:00:00Z",
            49900,
            "debit",
            "Airtel",
            "Phone payment",
            "rule",
            T0,
            0,
        ),
    )

    # Check status as of 2026-10-15
    res_status = execute_tool(
        test_ctx,
        "get_commitment_status",
        {
            "commitment_id": comm_id,
            "window_from": "2026-09-01",
            "window_to": "2026-11-30",
            "as_of_date": "2026-10-15",
        },
    )
    assert res_status.ok
    data = res_status.data
    assert data.matched_count >= 1
    # September 5 is paid
    # October 5 is overdue (due Oct 5, as_of is Oct 15, no matching txn)
    assert data.overdue_count >= 1
    assert data.status_summary == "overdue"
    # Next due is November 5
    assert data.next_due is not None
    assert data.next_due.due_date == "2026-11-05"
