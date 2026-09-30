from datetime import datetime

import pytest

from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_budget, insert_transaction
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Budget, Transaction
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import (
    aggregate_spend_by_category_handler,
    check_budgets_handler,
    forecast_category_spend_handler,
    get_balance_handler,
    recategorize_transaction_handler,
    register_financial_tools,
)
from copilot.tools.registry import clear_registry, get, register


@pytest.fixture
def ctx():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")
    conn.execute(
        "INSERT INTO accounts (id, user_id, name, created_at) "
        "VALUES ('a1', 'u1', 'C', '2023-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO categories (id, user_id, name, created_at) "
        "VALUES ('c1', 'u1', 'F', '2023-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO categories (id, user_id, name, created_at) "
        "VALUES ('c2', 'u1', 'E', '2023-01-01T00:00:00Z')"
    )

    tx1 = Transaction(
        id="t1",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-10T10:00:00Z",
        amount_paise=1000,
        direction="debit",
        merchant_raw="M1",
        description="D1",
        created_at="2023-01-01T00:00:00Z",
        category_id="c1",
    )
    tx2 = Transaction(
        id="t2",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-20T10:00:00Z",
        amount_paise=500,
        direction="debit",
        merchant_raw="M2",
        description="D2",
        created_at="2023-01-01T00:00:00Z",
        category_id="c1",
    )
    tx3_uncat = Transaction(
        id="t3",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-25T10:00:00Z",
        amount_paise=2000,
        direction="debit",
        merchant_raw="M3",
        description="D3",
        created_at="2023-01-01T00:00:00Z",
        category_id=None,
    )
    tx4_credit = Transaction(
        id="t4",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-26T10:00:00Z",
        amount_paise=-5000,
        direction="credit",
        merchant_raw="M4",
        description="D4",
        created_at="2023-01-01T00:00:00Z",
        category_id=None,
    )

    insert_transaction(conn, tx1)
    insert_transaction(conn, tx2)
    insert_transaction(conn, tx3_uncat)
    insert_transaction(conn, tx4_credit)

    b1 = Budget(
        id="b1",
        user_id="u1",
        category_id="c1",
        period="monthly",
        limit_paise=1500,
        warn_threshold_pct=80,
    )
    b2 = Budget(
        id="b2",
        user_id="u1",
        category_id="c2",
        period="monthly",
        limit_paise=1000,
        warn_threshold_pct=80,
    )
    insert_budget(conn, b1)
    insert_budget(conn, b2)

    policy = PolicySettings()
    clock = datetime(2023, 1, 15, 12, 0, tzinfo=IST)
    return ExecutionContext(conn, "u1", "run1", policy, clock)


def test_aggregate_spend(ctx):
    out = aggregate_spend_by_category_handler(ctx, 2023, 1)
    totals = {t["category_id"]: t["total_spend_paise"] for t in out["totals"]}

    assert totals["c1"] == 1500
    assert totals[None] == 2000
    assert out["grand_total_spend_paise"] == 3500


def test_check_budgets(ctx):
    out = check_budgets_handler(ctx, 2023, 1)
    statuses = {s["category_id"]: s for s in out["statuses"]}

    assert statuses["c1"]["spent_paise"] == 1500
    assert statuses["c1"]["pct_used"] == 100
    assert statuses["c1"]["status"] == "warning"

    assert statuses["c2"]["spent_paise"] == 0
    assert statuses["c2"]["pct_used"] == 0
    assert statuses["c2"]["status"] == "ok"

    tx_exceed = Transaction(
        id="t_ex",
        user_id="u1",
        account_id="a1",
        occurred_at="2023-01-28T10:00:00Z",
        amount_paise=1001,
        direction="debit",
        merchant_raw="M5",
        description="D5",
        created_at="2023-01-01T00:00:00Z",
        category_id="c2",
    )
    insert_transaction(ctx.conn, tx_exceed)

    out2 = check_budgets_handler(ctx, 2023, 1)
    statuses2 = {s["category_id"]: s for s in out2["statuses"]}
    assert statuses2["c2"]["status"] == "exceeded"


def test_forecast_category_spend(ctx):
    out = forecast_category_spend_handler(ctx, 2023, 1, "c1")
    assert out["spent_so_far_paise"] == 1500
    assert out["days_elapsed"] == 15
    assert out["projected_spend_paise"] == 3100


def test_recategorize_transaction(ctx):
    out = recategorize_transaction_handler(ctx, "t3", "c2")
    assert out["success"] is True

    tx = ctx.conn.execute("SELECT * FROM transactions WHERE id = 't3'").fetchone()
    assert tx["category_id"] == "c2"
    assert tx["category_source"] == "user"

    events = ctx.conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'recategorize_transaction'"
    ).fetchall()
    assert len(events) == 1
    assert '"category_id": null' in events[0]["before_json"]
    assert '"category_id": "c2"' in events[0]["after_json"]


def test_get_balance(ctx):
    out = get_balance_handler(ctx)
    # Debits: 1000 + 500 + 2000 = 3500
    # Credits: -5000
    assert out["balance_paise"] == -8500


def test_registration():
    clear_registry()
    register_financial_tools(register)
    assert get("get_transactions") is not None
    assert get("recategorize_transaction") is not None
