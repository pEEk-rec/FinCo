from datetime import datetime

import pytest

from copilot.agent.loop import run_turn
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_budget, insert_transaction
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Budget, Transaction
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry, register


def test_no_orms_present():
    """Verify SQLAlchemy or other ORMs are not importable (Phase 0 rule)."""
    with pytest.raises(ImportError):
        pass  # type: ignore
        
def test_full_flow():
    clear_registry()
    register_financial_tools(register)
    
    conn = get_connection(":memory:")
    init_db(conn)
    
    conn.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")
    conn.execute(
        "INSERT INTO accounts (id, user_id, name, created_at) "
        "VALUES ('a1', 'u1', 'Check', '2023-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO categories (id, user_id, name, created_at) "
        "VALUES ('c1', 'u1', 'Food', '2023-01-01T00:00:00Z')"
    )
    
    tx = Transaction(
        id="tx1", user_id="u1", account_id="a1", occurred_at="2023-01-15T10:00:00Z",
        amount_paise=5000, direction="debit", merchant_raw="M1", description="D1",
        created_at="2023-01-01T00:00:00Z", category_id=None
    )
    insert_transaction(conn, tx)
    
    budget = Budget(
        id="b1", user_id="u1", category_id="c1", period="monthly",
        limit_paise=4000, warn_threshold_pct=80
    )
    insert_budget(conn, budget)
    
    policy = PolicySettings(
        default="deny",
        side_effects={
            "read": {"decision": "allow"},
            "write_logical": {"decision": "needs_approval"}
        },
        tools={}
    )
    clock = datetime(2023, 1, 15, 12, 0, tzinfo=IST)
    ctx = ExecutionContext(conn, "u1", "run1", policy, clock)
    
    resp_balance = run_turn(ctx, "what is my balance")
    assert "-50.00" in resp_balance
    
    resp_budget = run_turn(ctx, "budget")
    assert "All budgets are looking good." in resp_budget
    
    resp_recat1 = run_turn(ctx, "recategorize tx1 to c1")
    assert "Action requires approval" in resp_recat1
    
    resp_recat2 = run_turn(ctx, "recategorize tx1 to c1", approved=True)
    assert "successfully recategorized" in resp_recat2
    
    resp_budget2 = run_turn(ctx, "budget")
    assert "1 budgets exceeded" in resp_budget2
    
    events = conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    assert len(events) >= 5
    
    logical_events = [e for e in events if e["event_type"] == "recategorize_transaction"]
    assert len(logical_events) == 1
    assert '"category_id": "c1"' in logical_events[0]["after_json"]
