from pathlib import Path

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import get_transaction, insert_account, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, User
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

    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="Checking", created_at=T0))
    insert_account(conn, Account(id="a2", user_id="u1", name="Savings", created_at=T0))

    # A transfer pair
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t_deb",
            "u1",
            "a1",
            "2024-01-10T10:00:00Z",
            500000,
            "debit",
            "IMPS-OUT",
            "Transfer",
            T0,
            "none",
        ),
    )
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t_cred",
            "u1",
            "a2",
            "2024-01-10T10:01:00Z",
            -500000,
            "credit",
            "IMPS-IN",
            "Received",
            T0,
            "none",
        ),
    )

    # Recurring bills (same merchant)
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, merchant_normalized, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t_rec1",
            "u1",
            "a1",
            "2024-01-01T10:00:00Z",
            19900,
            "debit",
            "NETFLIX",
            "Netflix",
            "Sub",
            T0,
            "none",
        ),
    )
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, merchant_normalized, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t_rec2",
            "u1",
            "a1",
            "2024-02-01T10:00:00Z",
            19900,
            "debit",
            "NETFLIX",
            "Netflix",
            "Sub",
            T0,
            "none",
        ),
    )
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, merchant_raw, merchant_normalized, description, created_at, category_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t_rec3",
            "u1",
            "a1",
            "2024-03-01T10:00:00Z",
            19900,
            "debit",
            "NETFLIX",
            "Netflix",
            "Sub",
            T0,
            "none",
        ),
    )

    return ExecutionContext(conn=conn, user_id="u1", run_id="r1", policy=POLICY, actor="agent")


def test_detect_transfers_tool(ctx):
    out = execute_tool(ctx, "detect_transfers", {})
    assert out.ok, out.error
    assert out.data.links_created == 1

    # Check that they are excluded from spend
    d = get_transaction(ctx.conn, ctx.user_id, "t_deb")
    c = get_transaction(ctx.conn, ctx.user_id, "t_cred")

    assert d.excluded_from_spend is True
    assert c.excluded_from_spend is True

    # Check transfer_links table
    links = ctx.conn.execute("SELECT debit_txn_id, credit_txn_id FROM transfer_links").fetchall()
    assert len(links) == 1
    assert links[0][0] == "t_deb"
    assert links[0][1] == "t_cred"

    # Check audit log
    events = ctx.conn.execute(
        "SELECT event_type, metadata_json FROM audit_events WHERE event_type='transfer_detected'"
    ).fetchall()
    assert len(events) == 1


def test_detect_recurring_tool(ctx):
    out = execute_tool(ctx, "detect_recurring", {})
    assert out.ok, out.error
    assert out.data.series_detected == 1

    series = ctx.conn.execute(
        "SELECT merchant_normalized, cadence_days FROM recurring_series"
    ).fetchall()
    assert len(series) == 1
    assert series[0][0] == "Netflix"
    assert series[0][1] == 30
