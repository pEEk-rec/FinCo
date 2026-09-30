from datetime import datetime

import pytest

from copilot.agent.loop import run_turn
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_transaction
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Transaction
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry, register


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
    
    tx = Transaction(
        id="tx123", user_id="u1", account_id="a1", occurred_at="2023-01-15T10:00:00Z",
        amount_paise=1000, direction="debit", merchant_raw="M1", description="D1",
        created_at="2023-01-01T00:00:00Z", category_id=None
    )
    insert_transaction(conn, tx)
    
    policy = PolicySettings(
        default="deny",
        side_effects={
            "read": {"decision": "allow"},
            "write_logical": {"decision": "needs_approval"}
        },
        tools={}
    )
    clock = datetime(2023, 1, 15, 12, 0, tzinfo=IST)
    return ExecutionContext(conn, "u1", "run1", policy, clock)

@pytest.fixture(autouse=True)
def setup_tools():
    clear_registry()
    register_financial_tools(register)
    yield
    clear_registry()

def test_run_turn_balance(ctx):
    resp = run_turn(ctx, "what is my balance")
    assert "Your balance is -10.00" in resp

def test_run_turn_transactions(ctx):
    resp = run_turn(ctx, "show my transactions")
    assert "You have 1 transactions" in resp

def test_run_turn_recategorize_requires_approval(ctx):
    resp = run_turn(ctx, "recategorize tx123 to c1")
    assert "Action requires approval" in resp
    
    resp2 = run_turn(ctx, "recategorize tx123 to c1", approved=True)
    assert "Transaction successfully recategorized" in resp2
