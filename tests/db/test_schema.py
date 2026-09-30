import sqlite3

import pytest

from copilot.db.connection import SCHEMA_VERSION, get_connection, init_db

T = "2024-01-15T10:00:00Z"
TX_COLS = (
    "id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, "
    "description, category_id, category_confidence, category_source, created_at"
)


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


def insert_tx(conn, **overrides):
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
    }
    row.update(overrides)
    with conn:
        conn.execute(
            f"INSERT INTO transactions ({TX_COLS}) VALUES ({', '.join('?' * 12)})",
            tuple(row.values()),
        )


def test_init_db_is_idempotent_and_versioned(conn):
    init_db(conn)  # second call is a no-op, not a crash
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_db_rejects_unknown_version():
    c = get_connection(":memory:")
    c.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="Unknown schema version 99"):
        init_db(c)


def test_init_db_on_file_db_twice(tmp_path):
    path = str(tmp_path / "copilot.db")
    c1 = get_connection(path)
    init_db(c1)
    c1.close()
    c2 = get_connection(path)
    init_db(c2)
    tables = {r[0] for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "transactions", "audit_events", "goals", "buckets"} <= tables
    c2.close()


def test_every_table_has_user_id(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        if table == "users":
            continue
        cols = {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "user_id" in cols, table
        assert cols["user_id"]["notnull"] == 1, table


def test_real_amount_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, amount_paise=499.5)


def test_text_amount_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, amount_paise="abc")


@pytest.mark.parametrize(
    "direction, amount",
    [("debit", -1000), ("credit", 1000), ("debit", 0), ("credit", 0)],
)
def test_sign_must_match_direction(conn, direction, amount):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, direction=direction, amount_paise=amount)


def test_credit_with_negative_amount_accepted(conn):
    insert_tx(conn, direction="credit", amount_paise=-500)


@pytest.mark.parametrize(
    "ts", ["2024-01-31T23:30:00+05:30", "2024-01-31T18:00:00", "yesterday", "2024-01-31"]
)
def test_non_canonical_timestamp_rejected(conn, ts):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, occurred_at=ts)


def test_transaction_cannot_use_other_users_account(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, user_id="u2", account_id="a_u1")


def test_transaction_cannot_use_other_users_category(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, category_id="c_u2")


def test_transaction_category_must_exist(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_tx(conn, category_id="missing")


def test_budget_cannot_use_other_users_category(conn):
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(
            "INSERT INTO budgets (id, user_id, category_id, period, limit_paise, "
            "warn_threshold_pct) VALUES ('b1', 'u2', 'c_u1', 'monthly', 100, 80)"
        )


def test_one_budget_per_category(conn):
    sql = (
        "INSERT INTO budgets (id, user_id, category_id, period, limit_paise, "
        "warn_threshold_pct) VALUES (?, 'u1', 'c_u1', 'monthly', ?, 80)"
    )
    with conn:
        conn.execute(sql, ("b1", 100))
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(sql, ("b2", 200))


def test_category_name_unique_per_user(conn):
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(
            "INSERT INTO categories (id, user_id, name, created_at) VALUES ('c2', 'u1', 'Food', ?)",
            (T,),
        )


def test_account_opening_balance_defaults_to_zero(conn):
    row = conn.execute("SELECT opening_balance_paise FROM accounts WHERE id='a_u1'").fetchone()
    assert row[0] == 0
