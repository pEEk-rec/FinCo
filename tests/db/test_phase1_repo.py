import sqlite3

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_budget, insert_transaction
from copilot.models.domain import Budget, Transaction

T = "2024-01-15T10:00:00Z"


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    with c:
        for u in ("u1", "u2"):
            c.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (u, T))
            c.execute(
                "INSERT INTO accounts (id, user_id, name, created_at) VALUES (?, ?, 'Acc', ?)",
                (f"a_{u}", u, T),
            )
            c.execute(
                "INSERT INTO categories (id, user_id, name, created_at) VALUES (?, ?, 'Food', ?)",
                (f"c_{u}", u, T),
            )
    return c


def insert_tx(conn, **overrides) -> Transaction:
    row = {
        "id": "t1",
        "user_id": "u1",
        "account_id": "a_u1",
        "occurred_at": T,
        "amount_paise": 1000,
        "direction": "debit",
        "merchant_raw": "m",
        "description": "d",
        "category_id": None,
        "category_confidence": None,
        "category_source": "none",
        "created_at": T,
        "fingerprint": "f1",
        "batch_id": None,
        "merchant_normalized": "m",
        "mode": "upi",
        "is_duplicate_of": None,
        "needs_review": False,
        "excluded_from_spend": False,
    }
    row.update(overrides)
    tx = Transaction(**row)
    insert_transaction(conn, tx)
    return tx


def test_transaction_fingerprint_unique(conn):
    insert_tx(conn, id="t1", fingerprint="f1")
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, id="t2", fingerprint="f1")


def test_transaction_fingerprint_nulls_allowed(conn):
    insert_tx(conn, id="t1", fingerprint=None)
    insert_tx(conn, id="t2", fingerprint=None)
    # No error


def test_v_category_totals_month(conn):
    # u1 spends 1000 on Food in Jan
    insert_tx(
        conn,
        id="t1",
        fingerprint="f1",
        category_id="c_u1",
        occurred_at="2024-01-05T10:00:00Z",
        amount_paise=1000,
    )
    # u1 spends 2000 on Food in Jan
    insert_tx(
        conn,
        id="t2",
        fingerprint="f2",
        category_id="c_u1",
        occurred_at="2024-01-20T10:00:00Z",
        amount_paise=2000,
    )
    # u1 excluded from spend
    insert_tx(
        conn,
        id="t3",
        fingerprint="f3",
        category_id="c_u1",
        occurred_at="2024-01-25T10:00:00Z",
        amount_paise=5000,
        excluded_from_spend=True,
    )
    # duplicate
    insert_tx(
        conn,
        id="t4",
        fingerprint="f4",
        category_id="c_u1",
        occurred_at="2024-01-26T10:00:00Z",
        amount_paise=5000,
        is_duplicate_of="t1",
    )
    # credit
    insert_tx(
        conn,
        id="t5",
        fingerprint="f5",
        category_id="c_u1",
        occurred_at="2024-01-27T10:00:00Z",
        direction="credit",
        amount_paise=-500,
    )

    rows = conn.execute("SELECT * FROM v_category_totals_month").fetchall()
    assert len(rows) == 1
    assert dict(rows[0]) == {
        "user_id": "u1",
        "category_id": "c_u1",
        "month_utc": "2024-01",
        "total_spend_paise": 3000,  # 1000 + 2000 (excludes t3, t4, t5)
    }


def test_v_budget_status_month(conn):
    insert_tx(
        conn,
        id="t1",
        fingerprint="f1",
        category_id="c_u1",
        occurred_at="2024-01-05T10:00:00Z",
        amount_paise=900,
    )

    b = Budget(
        id="b1",
        user_id="u1",
        category_id="c_u1",
        limit_paise=1000,
        warn_threshold_pct=80,
        forecast_warn=True,
    )
    insert_budget(conn, b)

    rows = conn.execute("SELECT * FROM v_budget_status_month").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["spent_paise"] == 900
    assert row["status"] == "warning"
    assert row["forecast_warn"] == 1


def test_v_balance(conn):
    insert_tx(conn, id="t1", fingerprint="f1", amount_paise=1000)
    insert_tx(conn, id="t2", fingerprint="f2", direction="credit", amount_paise=-200)
    insert_tx(
        conn, id="t3", fingerprint="f3", amount_paise=500, is_duplicate_of="t1"
    )  # duplicate, should be ignored

    rows = conn.execute("SELECT balance_paise FROM v_balance WHERE user_id='u1'").fetchall()
    assert dict(rows[0])["balance_paise"] == -800  # 0 - 1000 - (-200) = -800
