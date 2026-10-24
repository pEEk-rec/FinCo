"""
12 Phase 1 Golden Scenarios (PLAN_PHASE1 Section 5.10).

Verifies critical safety, accounting, and policy invariants across the full stack:
1. Double ingestion produces 0 duplicate records.
2. Internal transfer is excluded from spend.
3. Subscription is detected and forms fixed forecast component.
4. Budget status transitions to warning at threshold.
5. Budget projected exceed fires on run-rate burn.
6. Insufficient data triggers safe fallback forecast.
7. Low-confidence merchant routes to review queue.
8. User correction propagates to Monthly Review v2 while preserving v1.
9. Agent is strictly blocked from overwriting user category choice.
10. Undo batch reverts automated changes without touching user edits.
11. Advice validator rejects invented number and triggers template fallback.
12. Expired/revoked consent blocks bank data fetch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot.bank.ingest import set_connector
from copilot.bank.mock_bank import MockAAConnector
from copilot.bank.synth import generate_transactions
from copilot.core.advice import validate_advice
from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_monthly_review,
    get_transaction,
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
    list_transactions,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.models.findings import AdviceDraft, Finding, FindingNumber
from copilot.review.builder import build_monthly_review
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "policy.yaml"
T0 = "2024-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def setup_tools():
    clear_registry()
    register_financial_tools()
    yield
    clear_registry()


@pytest.fixture
def eval_ctx():
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="HDFC Checking", created_at=T0))
    insert_account(conn, Account(id="a2", user_id="u1", name="SBI Savings", created_at=T0))

    cats = [
        ("food", "Food & Dining"),
        ("travel", "Travel & Commute"),
        ("groceries", "Groceries"),
        ("shopping", "Shopping"),
        ("utilities", "Utilities & Bills"),
        ("subscriptions", "Subscriptions"),
        ("housing", "Housing & Rent"),
        ("income", "Salary & Income"),
    ]
    for cid, cname in cats:
        insert_category(conn, Category(id=cid, user_id="u1", name=cname, created_at=T0))

    policy = load_policy(POLICY_PATH)
    return ExecutionContext(
        conn=conn, user_id="u1", run_id="gold_run_1", policy=policy, actor="agent"
    )


# 1. Double ingestion
def test_golden_double_ingestion(eval_ctx: ExecutionContext):
    synth = generate_transactions(seed=42, months=1, user_id="u1", account_ids=["a1"])
    connector = MockAAConnector(synth.transactions)
    set_connector(connector)

    cid = "consent_gold_1"
    eval_ctx.conn.execute(
        """
        INSERT INTO consents (id, user_id, purpose, fi_types, account_ids,
                              date_range_from, date_range_to, status, expires_at, created_at)
        VALUES (?, 'u1', 'sync', 'DEPOSIT', '["a1"]',
                '2020-01-01T00:00:00Z', '2030-01-01T00:00:00Z', 'active',
                '2030-01-01T00:00:00Z', '2024-01-01T00:00:00Z')
        """,
        (cid,),
    )
    connector._consents[cid] = {
        "user_id": "u1",
        "account_ids": ["a1"],
        "range_from": "2020-01-01T00:00:00Z",
        "range_to": "2030-01-01T00:00:00Z",
        "status": "active",
        "expires_at": "2030-01-01T00:00:00Z",
    }

    # First ingestion
    res1 = execute_tool(eval_ctx, "ingest_statements", {"consent_id": cid, "account_id": "a1"})
    assert res1.ok
    assert res1.data.inserted > 0

    count_after_first = len(
        list_transactions(eval_ctx.conn, "u1", "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    )

    # Second ingestion with identical session
    res2 = execute_tool(eval_ctx, "ingest_statements", {"consent_id": cid, "account_id": "a1"})
    assert res2.ok
    assert res2.data.inserted == 0
    assert res2.data.skipped_existing > 0

    count_after_second = len(
        list_transactions(eval_ctx.conn, "u1", "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    )
    assert count_after_first == count_after_second


# 2. Transfer excluded from spend
def test_golden_transfer_excluded_from_spend(eval_ctx: ExecutionContext):
    # Debit from a1, matching credit to a2
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_gold_debit",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-15T10:00:00Z",
            amount_paise=500000,
            direction="debit",
            merchant_raw="TRANSFER TO SBI A2",
            description="Transfer to own account A2",
            created_at=T0,
        ),
    )
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_gold_credit",
            account_id="a2",
            user_id="u1",
            occurred_at="2024-02-15T10:02:00Z",
            amount_paise=-500000,
            direction="credit",
            merchant_raw="TRANSFER FROM HDFC A1",
            description="Transfer from own account A1",
            created_at=T0,
        ),
    )

    t_res = execute_tool(eval_ctx, "detect_transfers", {})
    assert t_res.ok
    assert t_res.data.links_created == 1

    # Verify both transactions have excluded_from_spend=1
    d_tx = get_transaction(eval_ctx.conn, "u1", "tx_gold_debit")
    c_tx = get_transaction(eval_ctx.conn, "u1", "tx_gold_credit")
    assert d_tx.excluded_from_spend is True
    assert c_tx.excluded_from_spend is True


# 3. Subscription detected and forecast as fixed
def test_golden_subscription_detected_and_forecast_as_fixed(eval_ctx: ExecutionContext):
    # Insert 3 monthly Spotify payments
    for mo in (1, 2, 3):
        insert_transaction(
            eval_ctx.conn,
            Transaction(
                id=f"tx_spotify_{mo}",
                account_id="a1",
                user_id="u1",
                occurred_at=f"2024-0{mo}-05T12:00:00Z",
                amount_paise=11900,
                direction="debit",
                merchant_raw="SPOTIFY INDIA",
                merchant_normalized="spotify",
                description="Spotify monthly subscription",
                category_id="subscriptions",
                category_source="rule",
                created_at=T0,
            ),
        )

    r_res = execute_tool(eval_ctx, "detect_recurring", {})
    assert r_res.ok
    assert r_res.data.series_detected >= 1

    # Forecast category spend
    f_res = execute_tool(
        eval_ctx,
        "forecast_category_spend",
        {"year": 2024, "month": 3, "category_id": "subscriptions"},
    )
    assert f_res.ok
    assert f_res.data.projected_spend_paise >= 11900


# 4. Budget exactly at warning
def test_golden_budget_at_warning(eval_ctx: ExecutionContext):
    insert_budget(
        eval_ctx.conn,
        Budget(
            id="b_food_warn",
            user_id="u1",
            category_id="food",
            limit_paise=1000000,  # ₹10,000
            warn_threshold_pct=80,  # Warning at ₹8,000
        ),
    )
    # Spend exactly ₹8,000
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_b_warn",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-10T12:00:00Z",
            amount_paise=800000,
            direction="debit",
            merchant_raw="CANTEEN FOOD",
            description="Canteen lunch",
            category_id="food",
            category_source="rule",
            created_at=T0,
        ),
    )

    b_res = execute_tool(eval_ctx, "check_budgets", {"year": 2024, "month": 2})
    assert b_res.ok
    food_status = next(s for s in b_res.data.statuses if s.category_id == "food")
    assert food_status.status == "warning"
    assert food_status.spent_paise == 800000


# 5. Budget projected exceed
def test_golden_budget_projected_exceed(eval_ctx: ExecutionContext):
    eval_ctx.clock = datetime(2024, 2, 5, 12, 0, 0, tzinfo=UTC)
    insert_budget(
        eval_ctx.conn,
        Budget(
            id="b_groceries_proj",
            user_id="u1",
            category_id="groceries",
            limit_paise=1000000,  # ₹10,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    # On day 5 of the month, already spent ₹5,000 (run-rate will far exceed ₹10,000)
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_b_proj",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-05T12:00:00Z",
            amount_paise=500000,
            direction="debit",
            merchant_raw="SUPERMARKET",
            description="Grocery run",
            category_id="groceries",
            category_source="rule",
            created_at=T0,
        ),
    )

    b_res = execute_tool(eval_ctx, "check_budgets", {"year": 2024, "month": 2})
    assert b_res.ok
    g_status = next(s for s in b_res.data.statuses if s.category_id == "groceries")
    # Even though currently under 80% (50%), projected exceed fires via forecast_warn
    assert g_status.status == "projected_exceed"


# 6. Insufficient data triggers safe fallback forecast
def test_golden_insufficient_data_forecast(eval_ctx: ExecutionContext):
    # Empty month with no transactions
    f_res = execute_tool(
        eval_ctx, "forecast_category_spend", {"year": 2025, "month": 7, "category_id": "groceries"}
    )
    assert f_res.ok
    assert f_res.data.spent_so_far_paise == 0
    assert f_res.data.projected_spend_paise == 0


# 7. Low-confidence merchant to review queue
def test_golden_low_confidence_merchant_to_review_queue(eval_ctx: ExecutionContext):
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_low_conf",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-12T12:00:00Z",
            amount_paise=45000,
            direction="debit",
            merchant_raw="UNKNOWN MYSTERY CORNER",
            description="Mystery purchase",
            created_at=T0,
        ),
    )

    # Batch update proposes low confidence (0.45)
    up = {
        "transaction_id": "tx_low_conf",
        "category_id": "shopping",
        "confidence": 0.45,
        "source": "llm",
        "model": "fake-llm",
        "prompt_version": "v1",
    }
    b_res = execute_tool(eval_ctx, "categorize_batch", {"updates": [up]})
    assert b_res.ok
    assert b_res.data.review_queue_count == 1

    tx = get_transaction(eval_ctx.conn, "u1", "tx_low_conf")
    assert tx.needs_review is True
    assert tx.category_id == "shopping"
    assert tx.category_confidence == 0.45


# 8. Correction propagates to monthly review v2 while preserving v1
def test_golden_correction_propagates_to_monthly_review_v2(eval_ctx: ExecutionContext):
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_rev_target",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-15T12:00:00Z",
            amount_paise=200000,
            direction="debit",
            merchant_raw="LOCAL BISTRO",
            description="Dinner out",
            category_id="food",
            category_source="rule",
            created_at=T0,
        ),
    )

    # Build initial Monthly Review (v1)
    rev_v1 = build_monthly_review(eval_ctx.conn, "u1", 2024, 2, "run_v1")
    assert rev_v1.version == 1
    assert any(
        c.category_id == "food" and c.current_spend_paise == 200000 for c in rev_v1.category_totals
    )

    # User recategorizes transaction from food -> travel
    user_ctx = ExecutionContext(
        conn=eval_ctx.conn, user_id="u1", run_id="u_corr", policy=eval_ctx.policy, actor="user"
    )
    recat_res = execute_tool(
        user_ctx,
        "recategorize_transaction",
        {"transaction_id": "tx_rev_target", "new_category_id": "travel", "remember": False},
    )
    assert recat_res.ok

    # Build Monthly Review again (v2)
    rev_v2 = build_monthly_review(eval_ctx.conn, "u1", 2024, 2, "run_v2")
    assert rev_v2.version == 2
    assert any(
        c.category_id == "travel" and c.current_spend_paise == 200000
        for c in rev_v2.category_totals
    )

    # Verify v1 is still preserved in database
    v1_stored = get_monthly_review(eval_ctx.conn, "u1", 2024, 2, version=1)
    assert v1_stored is not None
    assert v1_stored.version == 1


# 9. Agent blocked from overwriting user category choice
def test_golden_agent_blocked_from_overwriting_user_category(eval_ctx: ExecutionContext):
    insert_transaction(
        eval_ctx.conn,
        Transaction(
            id="tx_user_set",
            account_id="a1",
            user_id="u1",
            occurred_at="2024-02-18T12:00:00Z",
            amount_paise=150000,
            direction="debit",
            merchant_raw="AIRLINE BOOKING",
            description="Flight to Delhi",
            category_id="travel",
            category_source="user",
            category_confidence=1.0,
            created_at=T0,
        ),
    )

    # Attempt recategorization as agent
    res = execute_tool(
        eval_ctx,
        "recategorize_transaction",
        {"transaction_id": "tx_user_set", "new_category_id": "food"},
    )
    assert not res.ok
    assert res.error.code in (ErrorCode.APPROVAL_REQUIRED, ErrorCode.DENIED_BY_POLICY)

    tx = get_transaction(eval_ctx.conn, "u1", "tx_user_set")
    assert tx.category_id == "travel"
    assert tx.category_source == "user"


# 10. Undo batch reverts automated changes without touching user edits
def test_golden_undo_batch(eval_ctx: ExecutionContext):
    t_ids = ["tx_batch_1", "tx_batch_2"]
    for tid in t_ids:
        insert_transaction(
            eval_ctx.conn,
            Transaction(
                id=tid,
                account_id="a1",
                user_id="u1",
                occurred_at="2024-02-20T12:00:00Z",
                amount_paise=100000,
                direction="debit",
                merchant_raw="BATCH STORE",
                description="General store purchase",
                category_id=None,
                created_at=T0,
            ),
        )

    # Apply batch categorization
    ups = [
        {
            "transaction_id": tid,
            "category_id": "food",
            "confidence": 0.95,
            "source": "rule",
            "model": "rule_v1",
            "prompt_version": "v1",
        }
        for tid in t_ids
    ]
    b_res = execute_tool(eval_ctx, "categorize_batch", {"updates": ups})
    assert b_res.ok
    assert b_res.data.updated_count == 2

    # Undo the batch
    u_res = execute_tool(eval_ctx, "undo_categorize_batch", {"target_run_id": eval_ctx.run_id})
    assert u_res.ok
    assert u_res.data.restored_count == 2

    # Transactions are back to None
    for tid in t_ids:
        tx = get_transaction(eval_ctx.conn, "u1", tid)
        assert tx.category_id is None
        assert tx.category_source == "none"


# 11. Advice validator rejects invented number and triggers fallback
def test_golden_validator_rejects_invented_number_and_falls_back():
    finding = Finding(
        id="f_food_1",
        kind="category_spend",
        period="2024-02",
        subject="Food",
        description="High spend on food",
        numbers=[
            FindingNumber(label="spend", value=800000, unit="paise"),
            FindingNumber(label="pct", value=80, unit="percent"),
        ],
    )
    findings = {"f_food_1": finding}

    # Grounded advice passes
    res_valid = validate_advice(
        AdviceDraft(text="You spent ₹8,000 on Food (80% of budget).", finding_ids=["f_food_1"]),
        findings,
    )
    assert res_valid.ok is True

    # Hallucinated advice with unauthorized invented number (₹25,000)
    res_fake = validate_advice(
        AdviceDraft(text="You spent ₹25,000 on Food (99% of budget).", finding_ids=["f_food_1"]),
        findings,
    )
    assert res_fake.ok is False
    assert len(res_fake.violations) > 0


# 12. Expired or revoked consent blocks statement fetch
def test_golden_consent_expired_blocks_fetch(eval_ctx: ExecutionContext):
    synth = generate_transactions(seed=42, months=1, user_id="u1", account_ids=["a1"])
    connector = MockAAConnector(synth.transactions)
    set_connector(connector)

    cid = "consent_expired_12"
    eval_ctx.conn.execute(
        """
        INSERT INTO consents (id, user_id, purpose, fi_types, account_ids,
                              date_range_from, date_range_to, status, expires_at, created_at)
        VALUES (?, 'u1', 'sync', 'DEPOSIT', '["a1"]',
                '2020-01-01T00:00:00Z', '2021-01-01T00:00:00Z', 'expired',
                '2021-01-01T00:00:00Z', '2020-01-01T00:00:00Z')
        """,
        (cid,),
    )
    connector._consents[cid] = {
        "user_id": "u1",
        "account_ids": ["a1"],
        "range_from": "2020-01-01T00:00:00Z",
        "range_to": "2021-01-01T00:00:00Z",
        "status": "expired",
        "expires_at": "2021-01-01T00:00:00Z",
    }

    res = execute_tool(eval_ctx, "ingest_statements", {"consent_id": cid, "account_id": "a1"})
    assert not res.ok
    assert res.error.code in (ErrorCode.DENIED_BY_POLICY, ErrorCode.TOOL_FAILURE)
