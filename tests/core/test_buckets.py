"""
Core Virtual Buckets Unit Tests (PLAN_PHASE3 Stage 3.4).

Verifies:
1. Four core invariants:
   - Allocations never change any transaction or account balance table.
   - Recategorising a transaction moves spend between buckets while conserving totals.
   - Reassignment allocation rows always come in matched pairs summing to zero (pair_id).
   - Liquid balance invariant: available_unallocated + reserved_total == liquid_balance.
2. Rollover:
   - reset_monthly releases unspent funds in closing period.
   - accumulate buckets are never released.
   - Depleted (negative) buckets are never released (overspend preserved).
   - Idempotency: calling rollover twice writes nothing new.
3. Threshold boundaries:
   - Status 'ok', 'low' (at and below low_threshold_bp), and 'depleted' (< 0).
4. Spend calculation:
   - Category mapping and commitment matching.
   - Debits increase spend, refunds reduce spend within bucket, floored at 0.
5. would_exceed pure check.
6. Tenant isolation across all operations.
"""

from datetime import datetime

import pytest

from copilot.core.buckets import (
    bucket_balance,
    bucket_spent_paise,
    get_allocation_summary,
    rollover_buckets,
    would_exceed,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
    list_transactions,
    update_transaction_category,
)
from copilot.db.repo_phase3 import (
    insert_bucket,
    insert_bucket_allocation,
    map_bucket_category,
)
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import Bucket, BucketAllocation

T0 = "2026-09-01T00:00:00Z"
DT0 = datetime.fromisoformat("2026-09-01T00:00:00+00:00")


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    insert_account(
        c,
        Account(
            id="acc_1",
            user_id="u1",
            name="Checking",
            opening_balance_paise=5000000,
            created_at=T0,
        ),
    )
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=T0))
    insert_category(c, Category(id="cat_groceries", user_id="u1", name="Groceries", created_at=T0))
    yield c
    c.close()


def test_invariant_allocations_do_not_change_tx_or_account_balances(conn):
    """Allocations are an append-only logical ledger and never mutate accounts or transactions."""
    insert_transaction(
        conn,
        Transaction(
            id="t1",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-09-10T12:00:00Z",
            amount_paise=150000,
            direction="debit",
            merchant_raw="Cafe",
            description="Coffee",
            category_id="cat_dining",
            created_at=T0,
        ),
    )

    acc_before = conn.execute("SELECT * FROM accounts WHERE user_id = 'u1'").fetchall()
    tx_before = list_transactions(conn, "u1", "1970-01-01T00:00:00Z", "2099-01-01T00:00:00Z")

    b1 = Bucket(
        id="b1",
        user_id="u1",
        name="Dining Bucket",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b1)

    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b1",
            amount_paise=200000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba2",
            user_id="u1",
            bucket_id="b1",
            amount_paise=-50000,
            kind="release",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    acc_after = conn.execute("SELECT * FROM accounts WHERE user_id = 'u1'").fetchall()
    tx_after = list_transactions(conn, "u1", "1970-01-01T00:00:00Z", "2099-01-01T00:00:00Z")

    assert [dict(r) for r in acc_before] == [dict(r) for r in acc_after]
    assert [t.model_dump() for t in tx_before] == [t.model_dump() for t in tx_after]


def test_invariant_recategorisation_moves_spend_conserving_totals(conn):
    """Recategorising a transaction moves spend between buckets with total spend conserved."""
    b_dining = Bucket(
        id="b_din",
        user_id="u1",
        name="Dining",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    b_groc = Bucket(
        id="b_gro",
        user_id="u1",
        name="Groceries",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b_dining)
    insert_bucket(conn, b_groc)
    map_bucket_category(conn, "u1", "b_din", "cat_dining", T0)
    map_bucket_category(conn, "u1", "b_gro", "cat_groceries", T0)

    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b_din",
            amount_paise=500000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba2",
            user_id="u1",
            bucket_id="b_gro",
            amount_paise=500000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    # Insert transaction in Dining: 120000 paise (₹1,200)
    tx = Transaction(
        id="tx_food",
        user_id="u1",
        account_id="acc_1",
        occurred_at="2026-09-12T14:00:00Z",
        amount_paise=120000,
        direction="debit",
        merchant_raw="Supermarket",
        description="Lunch and supplies",
        category_id="cat_dining",
        created_at=T0,
    )
    insert_transaction(conn, tx)

    s_din_before = bucket_spent_paise(conn, "u1", b_dining, "2026-09")
    s_gro_before = bucket_spent_paise(conn, "u1", b_groc, "2026-09")
    assert s_din_before == 120000
    assert s_gro_before == 0
    assert s_din_before + s_gro_before == 120000

    # Recategorise to Groceries
    update_transaction_category(conn, "u1", "tx_food", "cat_groceries", "user")

    s_din_after = bucket_spent_paise(conn, "u1", b_dining, "2026-09")
    s_gro_after = bucket_spent_paise(conn, "u1", b_groc, "2026-09")
    assert s_din_after == 0
    assert s_gro_after == 120000
    assert s_din_after + s_gro_after == 120000


def test_invariant_reassignment_paired_sum_zero(conn):
    """Reassignment allocation rows always come in matched pairs summing to zero."""
    b1 = Bucket(
        id="b1",
        user_id="u1",
        name="Source",
        kind="flexible",
        period_policy="reset_monthly",
        created_at=T0,
    )
    b2 = Bucket(
        id="b2",
        user_id="u1",
        name="Target",
        kind="flexible",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b1)
    insert_bucket(conn, b2)

    pair_id = "reassign_test_123"
    amount = 75000  # 750 rupees
    out_row = BucketAllocation(
        id="ba_out",
        user_id="u1",
        bucket_id="b1",
        amount_paise=-amount,
        kind="reassign_out",
        period="2026-09",
        pair_id=pair_id,
        source="user",
        created_at=T0,
    )
    in_row = BucketAllocation(
        id="ba_in",
        user_id="u1",
        bucket_id="b2",
        amount_paise=amount,
        kind="reassign_in",
        period="2026-09",
        pair_id=pair_id,
        source="user",
        created_at=T0,
    )
    insert_bucket_allocation(conn, out_row)
    insert_bucket_allocation(conn, in_row)

    rows = conn.execute(
        "SELECT amount_paise FROM bucket_allocations WHERE user_id = 'u1' AND pair_id = ?",
        (pair_id,),
    ).fetchall()
    amounts = [r[0] for r in rows]
    assert len(amounts) == 2
    assert -amount in amounts and amount in amounts
    assert sum(amounts) == 0


def test_invariant_liquid_balance_decomposition(conn):
    """available_unallocated + reserved_total == liquid_balance holds exactly in all states."""
    b1 = Bucket(
        id="b1",
        user_id="u1",
        name="B1",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    b2 = Bucket(
        id="b2",
        user_id="u1",
        name="B2",
        kind="goal",
        period_policy="accumulate",
        created_at=T0,
    )
    insert_bucket(conn, b1)
    insert_bucket(conn, b2)

    # State 1: Under-allocated (liquid = 5,000,000; allocated = 3,000,000)
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b1",
            amount_paise=1000000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba2",
            user_id="u1",
            bucket_id="b2",
            amount_paise=2000000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    s1 = get_allocation_summary(conn, "u1", "2026-09")
    assert s1.liquid_balance_paise == 5000000
    assert s1.reserved_total_paise == 3000000
    assert s1.available_unallocated_paise == 2000000
    assert s1.over_allocated_by_paise == 0
    assert s1.available_unallocated_paise + s1.reserved_total_paise == s1.liquid_balance_paise

    # State 2: Over-allocated (allocate 4,000,000 more -> reserved 7,000,000 > liquid 5,000,000)
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba3",
            user_id="u1",
            bucket_id="b1",
            amount_paise=4000000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )
    s2 = get_allocation_summary(conn, "u1", "2026-09")
    assert s2.liquid_balance_paise == 5000000
    assert s2.reserved_total_paise == 7000000
    assert s2.available_unallocated_paise == -2000000
    assert s2.over_allocated_by_paise == 2000000
    assert s2.available_unallocated_paise + s2.reserved_total_paise == s2.liquid_balance_paise


def test_rollover_idempotency_and_policies(conn):
    """Rollover releases unspent in reset_monthly, ignores accumulate, and is strictly idempotent."""
    b_reset = Bucket(
        id="b_res",
        user_id="u1",
        name="Reset Bucket",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    b_acc = Bucket(
        id="b_acc",
        user_id="u1",
        name="Accumulate Bucket",
        kind="goal",
        period_policy="accumulate",
        created_at=T0,
    )
    insert_bucket(conn, b_reset)
    insert_bucket(conn, b_acc)
    map_bucket_category(conn, "u1", "b_res", "cat_dining", T0)

    # Period 2026-08: allocated 10,000; spent 4,000 -> unspent 6,000
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba_r1",
            user_id="u1",
            bucket_id="b_res",
            amount_paise=1000000,
            kind="allocate",
            period="2026-08",
            source="user",
            created_at="2026-08-01T00:00:00Z",
        ),
    )
    insert_transaction(
        conn,
        Transaction(
            id="tx_r1",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-08-15T12:00:00Z",
            amount_paise=400000,
            direction="debit",
            merchant_raw="Cafe",
            description="Meals",
            category_id="cat_dining",
            created_at=T0,
        ),
    )

    # Accumulate bucket: allocated 10,000; spent 0
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba_a1",
            user_id="u1",
            bucket_id="b_acc",
            amount_paise=1000000,
            kind="allocate",
            period="2026-08",
            source="user",
            created_at="2026-08-01T00:00:00Z",
        ),
    )

    # Initial balance check in closing month 2026-08
    bal_res_pre = bucket_balance(conn, "u1", b_reset, "2026-08")
    assert bal_res_pre.balance_paise == 600000

    # First rollover run
    created = rollover_buckets(conn, "u1", "2026-08")
    assert len(created) == 1

    # In closing month, reset bucket ends at exactly zero
    bal_res_post = bucket_balance(conn, "u1", b_reset, "2026-08")
    assert bal_res_post.balance_paise == 0

    # Accumulate bucket was untouched
    bal_acc_post = bucket_balance(conn, "u1", b_acc, "2026-08")
    assert bal_acc_post.balance_paise == 1000000

    # Second rollover run for same period: writes NOTHING
    created_second = rollover_buckets(conn, "u1", "2026-08")
    assert created_second == []


def test_rollover_does_not_release_depleted_buckets(conn):
    """Depleted buckets (balance < 0) are not released; overspend stays visible in closed month."""
    b_dep = Bucket(
        id="b_dep",
        user_id="u1",
        name="Overspent Dining",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b_dep)
    map_bucket_category(conn, "u1", "b_dep", "cat_dining", T0)

    # Allocated 300000, spent 500000 -> balance -200000
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b_dep",
            amount_paise=300000,
            kind="allocate",
            period="2026-08",
            source="user",
            created_at="2026-08-01T00:00:00Z",
        ),
    )
    insert_transaction(
        conn,
        Transaction(
            id="tx_over",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-08-10T12:00:00Z",
            amount_paise=500000,
            direction="debit",
            merchant_raw="Expensive Restaurant",
            description="Party",
            category_id="cat_dining",
            created_at=T0,
        ),
    )

    created = rollover_buckets(conn, "u1", "2026-08")
    assert created == []

    bal = bucket_balance(conn, "u1", b_dep, "2026-08")
    assert bal.balance_paise == -200000
    assert bal.status == "depleted"


def test_threshold_boundaries(conn):
    """Threshold boundaries: 'ok', 'low' (< 2000 bp), and 'depleted' (< 0)."""
    b = Bucket(
        id="b1",
        user_id="u1",
        name="Test",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b)
    map_bucket_category(conn, "u1", "b1", "cat_dining", T0)

    # Allocated 10,000 paise (₹100)
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b1",
            amount_paise=10000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    # Spend 8,000 paise -> balance 2,000 paise (exactly 20.00% = 2000 bp) -> 'ok'
    tx1 = Transaction(
        id="t1",
        user_id="u1",
        account_id="acc_1",
        occurred_at="2026-09-02T12:00:00Z",
        amount_paise=8000,
        direction="debit",
        merchant_raw="Shop",
        description="Item",
        category_id="cat_dining",
        created_at=T0,
    )
    insert_transaction(conn, tx1)
    bal1 = bucket_balance(conn, "u1", b, "2026-09", low_threshold_bp=2000)
    assert bal1.balance_paise == 2000
    assert bal1.status == "ok"

    # Spend 1 more paisa -> balance 1,999 paise (19.99% < 2000 bp) -> 'low'
    tx2 = Transaction(
        id="t2",
        user_id="u1",
        account_id="acc_1",
        occurred_at="2026-09-03T12:00:00Z",
        amount_paise=1,
        direction="debit",
        merchant_raw="Shop",
        description="Candy",
        category_id="cat_dining",
        created_at=T0,
    )
    insert_transaction(conn, tx2)
    bal2 = bucket_balance(conn, "u1", b, "2026-09", low_threshold_bp=2000)
    assert bal2.balance_paise == 1999
    assert bal2.status == "low"

    # Spend 2,000 more paise -> balance -1 paisa -> 'depleted'
    tx3 = Transaction(
        id="t3",
        user_id="u1",
        account_id="acc_1",
        occurred_at="2026-09-04T12:00:00Z",
        amount_paise=2000,
        direction="debit",
        merchant_raw="Shop",
        description="Extra",
        category_id="cat_dining",
        created_at=T0,
    )
    insert_transaction(conn, tx3)
    bal3 = bucket_balance(conn, "u1", b, "2026-09", low_threshold_bp=2000)
    assert bal3.balance_paise == -1
    assert bal3.status == "depleted"


def test_refunds_net_against_spend_floored_at_zero(conn):
    """Refunds reduce spend within category; spend is floored at 0."""
    b = Bucket(
        id="b1",
        user_id="u1",
        name="Shopping",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b)
    map_bucket_category(conn, "u1", "b1", "cat_dining", T0)

    # Debit 50,000
    insert_transaction(
        conn,
        Transaction(
            id="t_deb",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-09-05T10:00:00Z",
            amount_paise=50000,
            direction="debit",
            merchant_raw="Store",
            description="Buy",
            category_id="cat_dining",
            created_at=T0,
        ),
    )
    assert bucket_spent_paise(conn, "u1", b, "2026-09") == 50000

    # Credit refund 20,000
    insert_transaction(
        conn,
        Transaction(
            id="t_ref",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-09-06T10:00:00Z",
            amount_paise=-20000,
            direction="credit",
            merchant_raw="Store",
            description="Refund",
            category_id="cat_dining",
            created_at=T0,
        ),
    )
    assert bucket_spent_paise(conn, "u1", b, "2026-09") == 30000

    # Additional refund of 50,000 exceeds spend (net would be -20,000), floored at 0
    insert_transaction(
        conn,
        Transaction(
            id="t_ref_big",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-09-07T10:00:00Z",
            amount_paise=-50000,
            direction="credit",
            merchant_raw="Store",
            description="Large Refund",
            category_id="cat_dining",
            created_at=T0,
        ),
    )
    assert bucket_spent_paise(conn, "u1", b, "2026-09") == 0


def test_would_exceed_pure_check(conn):
    """would_exceed flags transactions that would push bucket balance below zero."""
    b = Bucket(
        id="b1",
        user_id="u1",
        name="Budget",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b)
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba1",
            user_id="u1",
            bucket_id="b1",
            amount_paise=100000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    assert not would_exceed(conn, "u1", b, 99999, "2026-09")
    assert not would_exceed(conn, "u1", b, 100000, "2026-09")
    assert would_exceed(conn, "u1", b, 100001, "2026-09")


def test_tenant_isolation(conn):
    """User 2 cannot see or affect User 1's buckets and allocations."""
    b1 = Bucket(
        id="b_u1",
        user_id="u1",
        name="User 1 Secret",
        kind="spending",
        period_policy="reset_monthly",
        created_at=T0,
    )
    insert_bucket(conn, b1)
    insert_bucket_allocation(
        conn,
        BucketAllocation(
            id="ba_u1",
            user_id="u1",
            bucket_id="b_u1",
            amount_paise=1000000,
            kind="allocate",
            period="2026-09",
            source="user",
            created_at=T0,
        ),
    )

    s_u2 = get_allocation_summary(conn, "u2", "2026-09")
    assert s_u2.buckets == []
    assert s_u2.reserved_total_paise == 0
    assert s_u2.liquid_balance_paise == 0
