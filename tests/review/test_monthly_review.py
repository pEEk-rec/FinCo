"""
Tests for MonthlyReview builder, versioning, and renderers (PLAN_PHASE1 Stage 1.10).

Verifies:
1. Review numbers match independent analysis tools' aggregations.
2. Re-run after user correction creates version 2 with updated numbers (version 1 preserved).
3. Partial month handled correctly (is_partial_month=True and missing days).
4. Safety invariant: Rendered Markdown and HTML contain no numbers absent from the review object.
5. Month-over-month comparison accurately reflects prior month totals and deltas.
"""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from copilot.core.anomalies import detect_anomalies
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_monthly_review,
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
    list_transactions,
)
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.review.builder import build_monthly_review
from copilot.review.renderers import (
    extract_all_review_numbers,
    extract_numbers_from_rendered_text,
    render_html,
    render_markdown,
)
from copilot.tools.financial import net_spend_by_category


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    t0 = "2026-01-01T00:00:00Z"
    insert_user(c, User(id="u1", created_at=t0))
    insert_account(c, Account(id="a1", user_id="u1", name="HDFC Checking", created_at=t0))
    insert_category(c, Category(id="cat_groceries", user_id="u1", name="Groceries", created_at=t0))
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=t0))
    insert_category(c, Category(id="cat_utilities", user_id="u1", name="Utilities", created_at=t0))
    insert_budget(
        c,
        Budget(
            id="b1",
            user_id="u1",
            category_id="cat_groceries",
            limit_paise=1500000,  # ₹15,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    insert_budget(
        c,
        Budget(
            id="b2",
            user_id="u1",
            category_id="cat_dining",
            limit_paise=500000,  # ₹5,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    return c


def _populate_september_data(c: sqlite3.Connection):
    # Income: Salary ₹1,00,000 credit
    insert_transaction(
        c,
        Transaction(
            id="tx_inc_1",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-09-01T10:00:00Z",
            amount_paise=-10000000,
            merchant_raw="ACME CORP SALARY",
            merchant_normalized="ACME CORP",
            description="Monthly salary deposit",
            direction="credit",
            category_id=None,
            category_source="none",
            category_confidence=1.0,
            excluded_from_spend=False,
            created_at="2026-09-01T10:00:00Z",
        ),
    )
    # Groceries: ₹5,000
    insert_transaction(
        c,
        Transaction(
            id="tx_sp_1",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-09-05T12:00:00Z",
            amount_paise=500000,
            merchant_raw="BIGBASKET",
            merchant_normalized="BIGBASKET",
            description="Grocery order BigBasket",
            direction="debit",
            category_id="cat_groceries",
            category_source="rule",
            category_confidence=0.95,
            created_at="2026-09-05T12:00:00Z",
        ),
    )
    # Dining: ₹3,000
    insert_transaction(
        c,
        Transaction(
            id="tx_sp_2",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-09-10T14:30:00Z",
            amount_paise=300000,
            merchant_raw="SWIGGY",
            merchant_normalized="SWIGGY",
            description="Food delivery Swiggy",
            direction="debit",
            category_id="cat_dining",
            category_source="rule",
            category_confidence=0.9,
            created_at="2026-09-10T14:30:00Z",
        ),
    )
    # Utilities (Recurring): ₹1,500
    insert_transaction(
        c,
        Transaction(
            id="tx_sp_3",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-09-15T09:00:00Z",
            amount_paise=150000,
            merchant_raw="BESCOM ELECTRICITY",
            merchant_normalized="BESCOM",
            description="Electricity bill payment",
            direction="debit",
            category_id="cat_utilities",
            category_source="rule",
            category_confidence=0.98,
            created_at="2026-09-15T09:00:00Z",
        ),
    )
    # Groceries: ₹6,000
    insert_transaction(
        c,
        Transaction(
            id="tx_sp_4",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-09-20T18:00:00Z",
            amount_paise=600000,
            merchant_raw="ZEPTO",
            merchant_normalized="ZEPTO",
            description="Quick grocery delivery",
            direction="debit",
            category_id="cat_groceries",
            category_source="rule",
            category_confidence=0.9,
            created_at="2026-09-20T18:00:00Z",
        ),
    )
    # Recurring series record
    c.execute(
        """
        INSERT INTO recurring_series (
            id, user_id, merchant_normalized, typical_amount_paise, cadence_days,
            last_seen, next_expected, confidence, kind
        ) VALUES (
            'rec_1', 'u1', 'BESCOM', 150000, 30,
            '2026-09-15T09:00:00Z', '2026-10-15T09:00:00Z', 0.95, 'bill'
        )
        """
    )


def test_review_numbers_match_analysis_tools(conn):
    """Review numbers equal the domain analysis tools' calculated numbers."""
    _populate_september_data(conn)

    clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    review = build_monthly_review(conn, "u1", 2026, 9, "run_test_01", clock=clock)

    # Independent computation via tools/core
    start_utc = "2026-08-31T18:30:00Z"
    end_utc = "2026-09-30T18:30:00Z"
    txs = list_transactions(conn, "u1", start_utc, end_utc)
    net_spends = net_spend_by_category(txs)

    # 1. Spend & Income
    expected_spend = sum(net_spends.values())
    expected_income = 10000000  # ₹1,00,000
    expected_net = expected_income - expected_spend

    assert review.income_paise == expected_income
    assert review.spend_paise == expected_spend
    assert review.net_paise == expected_net

    # 2. Category totals match net_spends
    review_cat_map = {c.category_id: c.current_spend_paise for c in review.category_totals}
    assert review_cat_map.get("cat_groceries") == 1100000  # 5k + 6k
    assert review_cat_map.get("cat_dining") == 300000
    assert review_cat_map.get("cat_utilities") == 150000

    # 3. Budget performance matches budget_status tool
    b_map = {b.category_id: b for b in review.budget_statuses}
    assert "cat_groceries" in b_map
    assert b_map["cat_groceries"].spent_paise == 1100000
    assert b_map["cat_groceries"].limit_paise == 1500000
    # Groceries: 11k / 15k = 73%
    assert b_map["cat_groceries"].pct_used == 73

    assert b_map["cat_dining"].spent_paise == 300000
    assert b_map["cat_dining"].limit_paise == 500000
    assert b_map["cat_dining"].pct_used == 60

    # 4. Recurring commitments
    assert len(review.recurring_payments) == 1
    assert review.recurring_payments[0].merchant == "BESCOM"
    assert review.recurring_payments[0].typical_amount_paise == 150000

    # 5. Anomalies & Forecast
    assert len(review.anomalies) == len(detect_anomalies(txs))
    assert review.forecast is not None
    assert review.forecast.spent_so_far_paise == expected_spend


def test_rerun_after_correction_creates_version_2(conn):
    """Re-running review after category correction creates version 2 with updated totals."""
    _populate_september_data(conn)
    clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)

    # Version 1
    v1 = build_monthly_review(conn, "u1", 2026, 9, "run_v1", clock=clock)
    assert v1.version == 1
    cat_spend_v1 = {c.category_id: c.current_spend_paise for c in v1.category_totals}
    assert cat_spend_v1["cat_dining"] == 300000
    assert cat_spend_v1["cat_groceries"] == 1100000

    # User re-categorizes SWIGGY (tx_sp_2) from Dining to Groceries
    conn.execute(
        """
        UPDATE transactions
        SET category_id = 'cat_groceries', category_source = 'user'
        WHERE id = 'tx_sp_2'
        """
    )
    conn.commit()

    # Re-run review
    v2 = build_monthly_review(conn, "u1", 2026, 9, "run_v2", clock=clock)
    assert v2.version == 2
    assert v2.id == "mr_u1_2026_09_v2"

    cat_spend_v2 = {c.category_id: c.current_spend_paise for c in v2.category_totals}
    # Dining reduced by ₹3,000 -> 0
    # Groceries increased by ₹3,000 -> 14,000
    assert cat_spend_v2.get("cat_dining", 0) == 0
    assert cat_spend_v2["cat_groceries"] == 1400000

    # Total spend remains invariant
    assert v2.spend_paise == v1.spend_paise

    # Check persistence: both versions stored in database
    db_v1 = get_monthly_review(conn, "u1", 2026, 9, version=1)
    db_v2 = get_monthly_review(conn, "u1", 2026, 9, version=2)
    latest = get_monthly_review(conn, "u1", 2026, 9)

    assert db_v1 is not None and db_v1.version == 1
    assert db_v2 is not None and db_v2.version == 2
    assert latest is not None and latest.version == 2


def test_partial_month_handled(conn):
    """A review generated mid-month flags is_partial_month and tracks recorded vs missing days."""
    _populate_september_data(conn)

    # Mid-month clock: September 16, 2026 IST (10:30 UTC)
    mid_clock = datetime(2026, 9, 16, 5, 0, 0, tzinfo=UTC)
    review_partial = build_monthly_review(conn, "u1", 2026, 9, "run_partial", clock=mid_clock)

    dq = review_partial.data_quality
    assert dq.is_partial_month is True
    assert dq.days_in_month == 30
    # Transactions occurred on Sept 1, 5, 10, 15 -> 4 distinct days recorded
    assert dq.days_recorded == 4
    # Up to day 16: 16 - 4 = 12 missing days
    assert dq.missing_days == 12

    # End-of-month clock: October 1, 2026
    eom_clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    review_full = build_monthly_review(conn, "u1", 2026, 9, "run_full", clock=eom_clock)

    dq_full = review_full.data_quality
    assert dq_full.is_partial_month is False
    assert dq_full.days_in_month == 30
    # Sept 1, 5, 10, 15, 20 -> 5 distinct days recorded
    assert dq_full.days_recorded == 5
    assert dq_full.missing_days == 25


def test_previous_month_comparison(conn):
    """Previous month comparison accurately reflects month-over-month differences."""
    # Seed August 2026 transactions:
    # Groceries: ₹8,000 (800000 paise)
    insert_transaction(
        conn,
        Transaction(
            id="tx_aug_1",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-08-10T10:00:00Z",
            amount_paise=800000,
            merchant_raw="SUPERMARKET",
            merchant_normalized="SUPERMARKET",
            description="August supermarket groceries",
            direction="debit",
            category_id="cat_groceries",
            category_source="rule",
            category_confidence=1.0,
            created_at="2026-08-10T10:00:00Z",
        ),
    )
    # August Income: ₹90,000
    insert_transaction(
        conn,
        Transaction(
            id="tx_aug_inc",
            account_id="a1",
            user_id="u1",
            occurred_at="2026-08-01T10:00:00Z",
            amount_paise=-9000000,
            merchant_raw="ACME CORP",
            merchant_normalized="ACME CORP",
            description="August salary deposit",
            direction="credit",
            category_id=None,
            category_source="none",
            category_confidence=1.0,
            created_at="2026-08-01T10:00:00Z",
        ),
    )

    _populate_september_data(conn)
    clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    review = build_monthly_review(conn, "u1", 2026, 9, "run_aug_sep", clock=clock)

    assert review.previous_period == "2026-08"
    assert review.previous_income_paise == 9000000
    assert review.previous_spend_paise == 800000
    assert review.previous_net_paise == 9000000 - 800000

    groceries_cat = next(c for c in review.category_totals if c.category_id == "cat_groceries")
    assert groceries_cat.current_spend_paise == 1100000
    assert groceries_cat.previous_spend_paise == 800000
    # Change: +300,000 paise (+₹3,000)
    assert groceries_cat.change_paise == 300000
    # Change %: 300000 / 800000 * 100 = 37.5%
    assert groceries_cat.change_pct == 37.5


def test_renderer_contains_no_unauthorized_numbers(conn):
    """
    CRITICAL SAFETY TEST:
    Rendered Markdown and HTML outputs must contain NO numbers absent from the MonthlyReviewData object.
    """
    _populate_september_data(conn)
    clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    review = build_monthly_review(conn, "u1", 2026, 9, "run_safety", clock=clock)

    valid_numbers = extract_all_review_numbers(review)

    # 1. Test Markdown rendering
    md_output = render_markdown(review)
    md_numbers = extract_numbers_from_rendered_text(md_output)

    diff_md = md_numbers - valid_numbers
    assert not diff_md, f"Rendered Markdown contains invented/unexpected numbers: {diff_md}"

    # 2. Test HTML rendering
    html_output = render_html(review)
    html_numbers = extract_numbers_from_rendered_text(html_output)

    diff_html = html_numbers - valid_numbers
    assert not diff_html, f"Rendered HTML contains invented/unexpected numbers: {diff_html}"

    # 3. Negative validation: ensure detector catches invented numbers
    tampered_md = md_output + "\n\nUnauthorized incentive bonus: ₹424242 awarded.\n"
    tampered_numbers = extract_numbers_from_rendered_text(tampered_md)
    assert Decimal("424242") in tampered_numbers
    assert not tampered_numbers.issubset(valid_numbers)
