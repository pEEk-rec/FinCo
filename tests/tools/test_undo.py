from datetime import datetime
from pathlib import Path

import pytest

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
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import recategorize_transaction_handler
from copilot.tools.undo import undo_handler

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
    return c


from datetime import UTC, datetime


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
