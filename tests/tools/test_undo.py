from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_transaction,
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.financial import recategorize_transaction_handler, register_financial_tools
from copilot.tools.undo import undo_handler
from copilot.workflow.nodes import ensure_tools_registered

T0 = "2024-01-01T00:00:00Z"
POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(c, Account(id="a1", user_id="u1", name="A", created_at=T0))
    insert_category(c, Category(id="food", user_id="u1", name="Food", created_at=T0))
    insert_category(c, Category(id="dining", user_id="u1", name="Dining", created_at=T0))
    insert_category(
        c, Category(id="entertainment", user_id="u1", name="Entertainment", created_at=T0)
    )
    insert_category(c, Category(id="travel", user_id="u1", name="Travel", created_at=T0))
    return c


@pytest.fixture
def exec_ctx(conn):
    return ExecutionContext(
        conn=conn,
        user_id="u1",
        actor="user",
        run_id="r1",
        clock=datetime(2024, 1, 15, tzinfo=UTC),
        policy=POLICY,
    )


def test_recategorize_and_undo(conn, exec_ctx):
    # Insert a tx
    tx = Transaction(
        id="tx1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    insert_transaction(conn, tx)

    # Recategorize
    out = recategorize_transaction_handler(exec_ctx, "tx1", "dining")

    # Undo
    undo_handler(exec_ctx, out.audit_event_id)

    tx_restored = get_transaction(conn, "u1", "tx1")
    assert tx_restored.category_id == "food"


def test_recategorize_with_remember(conn, exec_ctx):
    # Insert two txs for same merchant
    tx1 = Transaction(
        id="tx1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        merchant_normalized="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    tx2 = Transaction(
        id="tx2",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=2000,
        direction="debit",
        merchant_raw="M1",
        merchant_normalized="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    insert_transaction(conn, tx1)
    insert_transaction(conn, tx2)

    recategorize_transaction_handler(exec_ctx, "tx1", "dining", remember=True)

    t2 = get_transaction(conn, "u1", "tx2")
    assert t2.category_id == "dining"
    assert t2.category_source == "override"


def test_undo_refused_on_divergence_preserves_newer_edit(conn, exec_ctx):
    tx = Transaction(
        id="tx1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    insert_transaction(conn, tx)

    # First edit: change to dining
    out1 = recategorize_transaction_handler(exec_ctx, "tx1", "dining")
    assert get_transaction(conn, "u1", "tx1").category_id == "dining"

    # Interleaved edit: user changes to entertainment
    recategorize_transaction_handler(exec_ctx, "tx1", "entertainment")
    assert get_transaction(conn, "u1", "tx1").category_id == "entertainment"

    # Attempt to undo out1 (the earlier edit)
    with pytest.raises(ToolFailure) as exc_info:
        undo_handler(exec_ctx, out1.audit_event_id)

    assert "diverged" in str(exc_info.value).lower()

    # Newer state is preserved
    tx_current = get_transaction(conn, "u1", "tx1")
    assert tx_current.category_id == "entertainment"

    # Refusal is audited in audit_events
    refusal_events = conn.execute(
        "SELECT * FROM audit_events WHERE user_id = 'u1' AND event_type = 'undo_refused'"
    ).fetchall()
    assert len(refusal_events) == 1
    assert "state_diverged" in refusal_events[0]["metadata_json"]


def test_undo_batch_all_or_nothing(conn, exec_ctx):
    tx1 = Transaction(
        id="tx1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        merchant_normalized="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    tx2 = Transaction(
        id="tx2",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=2000,
        direction="debit",
        merchant_raw="M1",
        merchant_normalized="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    tx3 = Transaction(
        id="tx3",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=3000,
        direction="debit",
        merchant_raw="M1",
        merchant_normalized="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    insert_transaction(conn, tx1)
    insert_transaction(conn, tx2)
    insert_transaction(conn, tx3)

    # Recategorize tx1 with remember=True -> triggers override_applied batch event for tx2 and tx3
    recategorize_transaction_handler(exec_ctx, "tx1", "dining", remember=True)

    batch_event = conn.execute(
        "SELECT id FROM audit_events WHERE user_id = 'u1' AND event_type = 'override_applied'"
    ).fetchone()
    assert batch_event is not None
    batch_event_id = batch_event["id"]

    assert get_transaction(conn, "u1", "tx2").category_id == "dining"
    assert get_transaction(conn, "u1", "tx3").category_id == "dining"

    # Interleaved edit: user manually changes tx2 to travel
    recategorize_transaction_handler(exec_ctx, "tx2", "travel")
    assert get_transaction(conn, "u1", "tx2").category_id == "travel"

    # Attempt to undo the batch event (which covers tx2 and tx3)
    with pytest.raises(ToolFailure) as exc_info:
        undo_handler(exec_ctx, batch_event_id)

    assert "diverged" in str(exc_info.value).lower()

    # All-or-nothing: NEITHER transaction in the batch is reverted
    assert get_transaction(conn, "u1", "tx2").category_id == "travel"
    assert get_transaction(conn, "u1", "tx3").category_id == "dining"

    # Refusal is audited
    refusal_events = conn.execute(
        "SELECT * FROM audit_events WHERE user_id = 'u1' AND event_type = 'undo_refused'"
    ).fetchall()
    assert len(refusal_events) == 1
    assert "batch_item_diverged" in refusal_events[0]["metadata_json"]


def test_undo_through_execute_tool_after_interleaved_edit(conn, exec_ctx):
    register_financial_tools()

    tx = Transaction(
        id="tx1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        description="d",
        category_id="food",
        category_source="llm",
        created_at=T0,
    )
    insert_transaction(conn, tx)

    out1 = recategorize_transaction_handler(exec_ctx, "tx1", "dining")
    assert get_transaction(conn, "u1", "tx1").category_id == "dining"

    recategorize_transaction_handler(exec_ctx, "tx1", "entertainment")
    assert get_transaction(conn, "u1", "tx1").category_id == "entertainment"

    prior_audit_count = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE user_id = 'u1'"
    ).fetchone()[0]

    res = execute_tool(exec_ctx, "undo", {"audit_event_id": out1.audit_event_id})

    # Assert tool result indicates failure with STALE_DATA
    assert not res.ok
    assert res.error.code == ErrorCode.STALE_DATA
    assert "diverged" in res.error.message.lower()

    # Assert entity remains unchanged (newer edit preserved)
    assert get_transaction(conn, "u1", "tx1").category_id == "entertainment"

    # Assert exactly one failure audit row exists from the failed tool call
    current_audit_count = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE user_id = 'u1'"
    ).fetchone()[0]
    assert current_audit_count == prior_audit_count + 1

    last_event = conn.execute(
        "SELECT * FROM audit_events WHERE user_id = 'u1' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert last_event["event_type"] == "undo_refused"
    assert "STALE_DATA" in last_event["metadata_json"]
    assert "state_diverged" in last_event["metadata_json"]


def test_undo_called_as_in_ui(conn, exec_ctx):
    """Verify that calling undo through execute_tool exactly as UI does works cleanly."""
    ensure_tools_registered()  # this test must not depend on what an earlier test registered
    T0 = "2026-09-01T10:00:00Z"
    tx = Transaction(
        id="tx_ui_1",
        user_id="u1",
        account_id="a1",
        occurred_at=T0,
        amount_paise=1500,
        direction="debit",
        merchant_raw="Swiggy",
        description="food delivery",
        category_id="food",
        category_source="rule",
        created_at=T0,
    )
    insert_transaction(conn, tx)

    # Recategorize through execute_tool
    re_res = execute_tool(
        exec_ctx,
        "recategorize_transaction",
        {"transaction_id": "tx_ui_1", "new_category_id": "dining"},
    )
    assert re_res.ok
    audit_evt_id = re_res.data.audit_event_id

    # Call undo exactly as UI calls it: execute_tool(ctx, "undo", {"audit_event_id": eid})
    undo_res = execute_tool(exec_ctx, "undo", {"audit_event_id": audit_evt_id})
    assert undo_res.ok
    assert undo_res.data.undone_event_id == audit_evt_id

    # Verified transaction reverted to original food category
    tx_after = get_transaction(conn, "u1", "tx_ui_1")
    assert tx_after.category_id == "food"
    assert tx_after.category_source == "rule"
