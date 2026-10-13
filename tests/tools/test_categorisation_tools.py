from pathlib import Path

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import get_transaction
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, User
from copilot.tools.categorisation import CategorizeUpdate
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry

T0 = "2024-01-01T00:00:00Z"
POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")


@pytest.fixture
def ctx():
    clear_registry()
    register_financial_tools()
    conn = get_connection(":memory:")
    init_db(conn)
    from copilot.db.repo import insert_account, insert_category, insert_user
    from copilot.models.domain import Category

    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="Savings", created_at=T0))
    insert_category(conn, Category(id="food", user_id="u1", name="Food", created_at=T0))
    insert_category(conn, Category(id="travel", user_id="u1", name="Travel", created_at=T0))
    insert_category(conn, Category(id="rent", user_id="u1", name="Rent", created_at=T0))

    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t1", "u1", "a1", T0, 1000, "debit", "swiggy", "desc", T0, "none"),
    )

    return ExecutionContext(conn=conn, user_id="u1", run_id="r1", policy=POLICY, actor="agent")


def test_categorize_batch_updates_transactions_and_queues_low_confidence(ctx):
    # ctx has transaction t1
    updates = [
        CategorizeUpdate(
            transaction_id="t1",
            category_id="food",
            confidence=0.9,
            source="llm",
            model="test-1",
            prompt_version="v1",
        ),
        CategorizeUpdate(transaction_id="t2", category_id="travel", confidence=0.7, source="llm"),
    ]

    # insert t2
    ctx.conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t2", "u1", "a1", T0, 1000, "debit", "uber", "desc2", T0, "none"),
    )

    out = execute_tool(
        ctx, "categorize_batch", {"updates": [u.model_dump() for u in updates]}, approved=True
    )
    assert out.ok
    assert out.data.updated_count == 1
    assert out.data.review_queue_count == 1

    t1 = get_transaction(ctx.conn, "u1", "t1")
    assert t1.category_id == "food"
    assert t1.needs_review is False
    assert t1.category_source == "llm"

    t2 = get_transaction(ctx.conn, "u1", "t2")
    assert t2.category_id == "travel"
    assert t2.needs_review is True
    assert t2.category_source == "llm"


def test_categorize_batch_skips_user_and_override(ctx):
    # set t1 as user-set
    ctx.conn.execute(
        "UPDATE transactions SET category_source = 'user', category_id = 'rent' WHERE id = 't1'"
    )
    updates = [
        CategorizeUpdate(transaction_id="t1", category_id="food", confidence=0.9, source="llm"),
    ]

    out = execute_tool(
        ctx, "categorize_batch", {"updates": [u.model_dump() for u in updates]}, approved=True
    )
    assert out.ok
    assert out.data.updated_count == 0
    assert out.data.review_queue_count == 0

    t1 = get_transaction(ctx.conn, "u1", "t1")
    assert t1.category_id == "rent"


def test_undo_categorize_batch(ctx):
    updates = [
        CategorizeUpdate(
            transaction_id="t1",
            category_id="food",
            confidence=0.9,
            source="llm",
            model="test-1",
            prompt_version="v1",
        ),
    ]

    # Before
    t1_before = get_transaction(ctx.conn, "u1", "t1")

    out = execute_tool(
        ctx, "categorize_batch", {"updates": [u.model_dump() for u in updates]}, approved=True
    )
    assert out.ok

    # Undo
    undo_out = execute_tool(
        ctx, "undo_categorize_batch", {"target_run_id": ctx.run_id}, approved=True
    )
    assert undo_out.ok
    assert undo_out.data.restored_count == 1

    t1_after = get_transaction(ctx.conn, "u1", "t1")
    assert t1_after.category_id == t1_before.category_id
    assert t1_after.category_source == t1_before.category_source
