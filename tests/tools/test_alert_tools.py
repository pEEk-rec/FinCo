"""
Tests for Adaptive Alerts Tools (PLAN_PHASE2 Section 5.7 & Stage 2.5).

Verifies:
- Execution through execute_tool(ctx, ...)
- evaluate_alerts creates open alerts on budget breach
- Dedup and in-place escalation (higher severity updates existing alert without duplicating)
- User alert preference silencing (muted kind suppresses alert and audits alert_suppressed)
- Alert lifecycle: acknowledge, dismiss, snooze
- Dismissal triggers cooldown suppression on subsequent evaluation
- Snooze triggers snooze suppression on subsequent evaluation
- User isolation: user A cannot access or mutate user B's alerts
"""

import sqlite3
from datetime import datetime

import pytest

from copilot.core.config import PROJECT_ROOT
from copilot.core.errors import ErrorCode
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db import repo
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import load_policy
from copilot.models.domain import Budget, Category, Transaction
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

DT0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=IST)
POLICY = load_policy(PROJECT_ROOT / "config" / "policy.yaml")


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    init_db(conn)
    ensure_tools_registered()
    return conn


@pytest.fixture
def exec_ctx(db_conn):
    return ExecutionContext(
        conn=db_conn,
        user_id="u_alice",
        clock=DT0,
        actor="agent",
        policy=POLICY,
        run_id="run_agent",
    )


@pytest.fixture
def user_ctx(db_conn):
    return ExecutionContext(
        conn=db_conn,
        user_id="u_alice",
        clock=DT0,
        actor="user",
        policy=POLICY,
        run_id="run_user",
    )


from copilot.models.domain import Account, Budget, Category, Transaction, User


def _setup_user_and_budget(conn: sqlite3.Connection, user_id: str = "u_alice"):
    cat_id = "dining" if user_id == "u_alice" else f"cat_{user_id}_dining"
    repo.insert_user(conn, User(id=user_id, created_at=to_utc_iso(DT0)))
    repo.insert_category(
        conn, Category(id=cat_id, user_id=user_id, name="Dining", created_at=to_utc_iso(DT0))
    )
    repo.insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=100000_00,
            created_at=to_utc_iso(DT0),
        ),
    )
    # Set a budget of ₹5,000 for dining
    repo.insert_budget(
        conn,
        Budget(
            id=f"b_{user_id}_dining",
            user_id=user_id,
            category_id=cat_id,
            period="monthly",
            limit_paise=5000_00,
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    # Baseline history for July, August, September (days <= 15) so confidence damping is 1.0
    hist_spends = [3800_00, 3900_00, 4000_00]
    for idx, (month_str, spend_paise) in enumerate(
        zip(["2026-07", "2026-08", "2026-09"], hist_spends, strict=True)
    ):
        repo.insert_transaction(
            conn,
            Transaction(
                id=f"tx_hist_{user_id}_{idx}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"{month_str}-10T12:00:00Z",
                amount_paise=spend_paise,
                direction="debit",
                merchant_raw="Swiggy",
                description="Past dining",
                category_id=cat_id,
                created_at=f"{month_str}-10T12:00:00Z",
            ),
        )


def test_evaluate_alerts_creates_open_alert_on_exceeded_budget(exec_ctx):
    """When spend exceeds budget, evaluate_alerts generates an open warning/critical alert."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")

    # Add transactions totalling ₹6,000 (120% of ₹5,000 limit)
    tx = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-10T12:00:00Z",
        amount_paise=6000_00,
        direction="debit",
        merchant_raw="Zomato",
        description="Dinner delivery",
        category_id="dining",
        created_at="2026-10-10T12:00:00Z",
    )
    repo.insert_transaction(conn, tx)

    res = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res.ok
    data = res.data
    assert data.created_count == 1
    assert len(data.alerts) == 1

    alert = data.alerts[0]
    assert alert.kind == "budget_risk"
    assert alert.subject_key == "dining"
    assert alert.status == "open"
    assert alert.severity in ("notice", "warning", "critical")
    assert "Dining" in alert.why_text


def test_alert_in_place_escalation(exec_ctx):
    """Subsequent evaluation with worsened status escalates alert in place rather than duplicating."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")

    # 1. Mild warning spend: ₹4,100 (82% of limit)
    tx1 = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-05T12:00:00Z",
        amount_paise=4100_00,
        direction="debit",
        merchant_raw="Swiggy",
        description="Lunch",
        category_id="dining",
        created_at="2026-10-05T12:00:00Z",
    )
    repo.insert_transaction(conn, tx1)

    res1 = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res1.ok
    assert res1.data.created_count == 1
    alert_id1 = res1.data.alerts[0].id
    old_score = res1.data.alerts[0].score_bp

    # 2. Add further spend: ₹2,000 more, pushing spend to ₹6,100 (exceeded)
    tx2 = Transaction(
        id="tx2",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-12T12:00:00Z",
        amount_paise=2000_00,
        direction="debit",
        merchant_raw="Restaurant",
        description="Family dinner",
        category_id="dining",
        created_at="2026-10-12T12:00:00Z",
    )
    repo.insert_transaction(conn, tx2)

    res2 = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res2.ok
    # Created count is 0; escalated count is 1
    assert res2.data.created_count == 0
    assert res2.data.escalated_count == 1
    # Alert ID remains the same
    assert len(res2.data.alerts) == 1
    assert res2.data.alerts[0].id == alert_id1
    assert res2.data.alerts[0].score_bp > old_score


def test_user_preference_silencing(exec_ctx, user_ctx):
    """Muted alert preference suppresses alert and records alert_suppressed audit event."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")

    # Mute dining category alerts via user tool
    pref_res = execute_tool(
        user_ctx,
        "set_alert_preference",
        {"category_id": "dining", "muted": True},
    )
    assert pref_res.ok

    # Exceed budget
    tx = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-10T12:00:00Z",
        amount_paise=8000_00,
        direction="debit",
        merchant_raw="Dining Out",
        description="Weekend party",
        category_id="dining",
        created_at="2026-10-10T12:00:00Z",
    )
    repo.insert_transaction(conn, tx)

    # Evaluate alerts
    res = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res.ok
    assert res.data.created_count == 0
    assert res.data.suppressed_count == 1
    assert len(res.data.alerts) == 0

    # Verify audit log recorded alert_suppressed
    events = conn.execute(
        "SELECT event_type, metadata_json FROM audit_events WHERE user_id = 'u_alice' AND event_type = 'alert_suppressed'"
    ).fetchall()
    assert len(events) >= 1
    assert "muted" in events[0][1]


def test_alert_lifecycle_dismiss_and_cooldown(exec_ctx, user_ctx):
    """Dismissing an alert triggers cooldown suppression on subsequent evaluation."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")

    tx = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-10T12:00:00Z",
        amount_paise=6000_00,
        direction="debit",
        merchant_raw="Food",
        description="Dinner",
        category_id="dining",
        created_at="2026-10-10T12:00:00Z",
    )
    repo.insert_transaction(conn, tx)

    res = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    alert_id = res.data.alerts[0].id

    # User dismisses alert
    decide_res = execute_tool(
        user_ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "dismiss", "reason": "Expected family dinner"},
    )
    assert decide_res.ok
    assert decide_res.data.status == "dismissed"

    # Next evaluation during cooldown suppresses alert
    res2 = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res2.ok
    assert res2.data.created_count == 0
    assert res2.data.suppressed_count == 1


def test_alert_lifecycle_snooze(exec_ctx, user_ctx):
    """Snoozing an alert suppresses it until snoozed_until expires."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")

    tx = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-10T12:00:00Z",
        amount_paise=6000_00,
        direction="debit",
        merchant_raw="Food",
        description="Takeout",
        category_id="dining",
        created_at="2026-10-10T12:00:00Z",
    )
    repo.insert_transaction(conn, tx)

    res = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    alert_id = res.data.alerts[0].id

    # User snoozes alert for 5 days
    decide_res = execute_tool(
        user_ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "snooze", "snooze_days": 5},
    )
    assert decide_res.ok
    assert decide_res.data.status == "snoozed"

    # Evaluation during snooze window suppresses alert
    res2 = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    assert res2.ok
    assert res2.data.created_count == 0
    assert res2.data.suppressed_count == 1


def test_user_isolation_alerts(exec_ctx, user_ctx):
    """User Bob cannot see or mutate Alice's alerts."""
    conn = exec_ctx.conn
    _setup_user_and_budget(conn, "u_alice")
    _setup_user_and_budget(conn, "u_bob")

    # Alice creates an alert
    tx = Transaction(
        id="tx1",
        user_id="u_alice",
        account_id="acc_u_alice",
        occurred_at="2026-10-10T12:00:00Z",
        amount_paise=6000_00,
        direction="debit",
        merchant_raw="Food",
        description="Dinner",
        category_id="dining",
        created_at="2026-10-10T12:00:00Z",
    )
    repo.insert_transaction(conn, tx)
    res_a = execute_tool(exec_ctx, "evaluate_alerts", {"period": "2026-10"})
    alert_id_a = res_a.data.alerts[0].id

    # Bob lists alerts -> sees 0
    bob_ctx = ExecutionContext(
        conn=conn,
        user_id="u_bob",
        clock=DT0,
        actor="user",
        policy=POLICY,
        run_id="run_bob",
    )
    list_bob = execute_tool(bob_ctx, "list_alerts", {})
    assert list_bob.ok
    assert len(list_bob.data.alerts) == 0

    # Bob tries to dismiss Alice's alert -> fails
    bob_decide = execute_tool(
        bob_ctx,
        "decide_alert",
        {"alert_id": alert_id_a, "action": "dismiss"},
    )
    assert not bob_decide.ok
    assert bob_decide.error.code == ErrorCode.NOT_FOUND
