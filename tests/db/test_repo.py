import sqlite3

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_transaction,
    insert_budget,
    insert_transaction,
    list_budgets,
    list_transactions,
    update_transaction_category,
)
from copilot.models.domain import Budget, Transaction


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    # Insert a dummy user and account to satisfy foreign keys
    c.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")
    c.execute("INSERT INTO users (id, created_at) VALUES ('u2', '2023-01-01T00:00:00Z')")
    c.execute(
        "INSERT INTO accounts (id, user_id, name, created_at) "
        "VALUES ('a1', 'u1', 'Checking', '2023-01-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO categories (id, user_id, name, created_at) "
        "VALUES ('c1', 'u1', 'Food', '2023-01-01T00:00:00Z')"
    )
    c.commit()
    return c

def test_insert_and_get_transaction(conn):
    tx = Transaction(
        id="t1",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-15T10:00:00Z",
        amount_paise=1000,
        direction="debit",
        merchant_raw="Coffee Shop",
        description="Coffee",
        category_id=None,
        category_confidence=None,
        category_source="none",
        created_at="2023-01-15T10:05:00Z"
    )
    insert_transaction(conn, tx)
    
    fetched = get_transaction(conn, "u1", "t1")
    assert fetched is not None
    assert fetched.amount_paise == 1000
    assert fetched.direction == "debit"
    
    # Query for another user should return None
    fetched_wrong_user = get_transaction(conn, "u2", "t1")
    assert fetched_wrong_user is None

def test_list_transactions(conn):
    tx1 = Transaction(
        id="t1", user_id="u1", account_id="a1", occurred_at="2023-01-10T10:00:00Z",
        amount_paise=1000, direction="debit", merchant_raw="A", description="A",
        created_at="2023-01-10T10:05:00Z", category_id="c1"
    )
    tx2 = Transaction(
        id="t2", user_id="u1", account_id="a1", occurred_at="2023-01-20T10:00:00Z",
        amount_paise=2000, direction="debit", merchant_raw="B", description="B",
        created_at="2023-01-20T10:05:00Z", category_id=None
    )
    tx_out_of_bounds = Transaction(
        id="t3", user_id="u1", account_id="a1", occurred_at="2023-02-05T10:00:00Z",
        amount_paise=3000, direction="debit", merchant_raw="C", description="C",
        created_at="2023-02-05T10:05:00Z", category_id=None
    )
    
    insert_transaction(conn, tx1)
    insert_transaction(conn, tx2)
    insert_transaction(conn, tx_out_of_bounds)
    
    # Test time filtering
    txs = list_transactions(conn, "u1", "2023-01-01T00:00:00Z", "2023-02-01T00:00:00Z")
    assert len(txs) == 2
    assert [t.id for t in txs] == ["t1", "t2"]
    
    # Test category filtering
    txs_cat = list_transactions(
        conn, "u1", "2023-01-01T00:00:00Z", "2023-02-01T00:00:00Z", category_id="c1"
    )
    assert len(txs_cat) == 1
    assert txs_cat[0].id == "t1"

def test_budget_constraints(conn):
    budget = Budget(
        id="b1",
        user_id="u1",
        category_id="c1",
        period="monthly",
        limit_paise=5000,
        warn_threshold_pct=80
    )
    insert_budget(conn, budget)
    
    budgets = list_budgets(conn, "u1")
    assert len(budgets) == 1
    assert budgets[0].limit_paise == 5000
    
    # DB Check constraints
    with pytest.raises(sqlite3.IntegrityError):
        # Using raw insert to test the DB constraint since Pydantic will block creation otherwise
        conn.execute(
            "INSERT INTO budgets "
            "(id, user_id, category_id, period, limit_paise, warn_threshold_pct) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("b2", "u1", "c1", "monthly", -100, 80)
        )

def test_foreign_key_enforcement(conn):
    tx = Transaction(
        id="t1",
        user_id="u1",
        account_id="invalid_acc",
        occurred_at="2023-01-15T10:00:00Z",
        amount_paise=1000,
        direction="debit",
        merchant_raw="Coffee Shop",
        description="Coffee",
        category_id=None,
        category_confidence=None,
        category_source="none",
        created_at="2023-01-15T10:05:00Z"
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert_transaction(conn, tx)

def test_update_transaction_category(conn):
    tx = Transaction(
        id="t1", user_id="u1", account_id="a1", occurred_at="2023-01-10T10:00:00Z",
        amount_paise=1000, direction="debit", merchant_raw="A", description="A",
        created_at="2023-01-10T10:05:00Z", category_id=None
    )
    insert_transaction(conn, tx)
    
    update_transaction_category(
        conn,
        user_id="u1",
        tx_id="t1",
        category_id="c1",
        category_source="user",
        category_confidence=1.0
    )
    
    updated = get_transaction(conn, "u1", "t1")
    assert updated.category_id == "c1"
    assert updated.category_source == "user"
    assert updated.category_confidence == 1.0
