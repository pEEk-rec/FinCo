"""
Unit and property tests for Stage 4.2: Metric catalogue and baseline engine.
(PLAN_PHASE4 Stage 4.2, Section 5.1, Section 5.2)
"""

import random
from datetime import date, timedelta

import pytest

from copilot.core.baseline import (
    calculate_baseline,
    calculate_integrity_notes,
    calculate_pace,
    evaluate_outcome,
    generate_candidate_windows,
)
from copilot.core.metrics import (
    calculate_category_spend,
    calculate_checkin_rate,
    calculate_merchant_group_spend,
    calculate_no_spend_days,
    calculate_tagging_completeness,
    calculate_txn_count,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import Baseline


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u = User(id="user_alice", created_at="2026-01-01T00:00:00Z")
    insert_user(c, u)
    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=10000000,
        created_at="2026-01-01T00:00:00Z",
    )
    insert_account(c, acc)
    for cat_id, cat_name in [
        ("dining_out", "Dining Out"),
        ("dining", "Dining"),
        ("groceries", "Groceries"),
        ("shopping", "Shopping"),
    ]:
        insert_category(
            c,
            Category(
                id=cat_id,
                user_id="user_alice",
                name=cat_name,
                created_at="2026-01-01T00:00:00Z",
            ),
        )
    return c


def _insert_txn(
    conn,
    user_id: str,
    tx_id: str,
    occurred_at: str,
    amount_paise: int,
    direction: str = "debit",
    category_id: str | None = None,
    merchant_raw: str = "Merchant",
    merchant_normalized: str | None = None,
    excluded_from_spend: int = 0,
    is_duplicate_of: str | None = None,
    category_source: str = "rule",
    created_at: str | None = None,
):
    query = """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, merchant_normalized, category_id,
            excluded_from_spend, is_duplicate_of, category_source, created_at
        ) VALUES (?, ?, 'acc_main', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            tx_id,
            user_id,
            occurred_at,
            amount_paise,
            direction,
            merchant_raw,
            merchant_raw,
            merchant_normalized or merchant_raw,
            category_id,
            excluded_from_spend,
            is_duplicate_of,
            category_source,
            created_at or occurred_at,
        ),
    )


# ---------------------------------------------------------------------------------------------
# 1. Metric Tests on Hand-Built Data
# ---------------------------------------------------------------------------------------------
def test_category_spend_with_refunds_transfers_and_commitments(conn):
    """
    category_spend sums debits minus refunds; excludes transfers, duplicates,
    commitment-matched transactions, and weekend txns when weekdays_only is true.
    """
    # 2026-09-14 is Monday (weekday 0), 2026-09-20 is Sunday (weekday 6)
    # Debits in dining_out
    _insert_txn(conn, "user_alice", "t1", "2026-09-14T08:00:00Z", 25000, category_id="dining_out")
    _insert_txn(conn, "user_alice", "t2", "2026-09-15T08:00:00Z", 35000, category_id="dining_out")

    # Refund in dining_out (credit of 10000 => amount_paise -10000)
    _insert_txn(
        conn,
        "user_alice",
        "t3",
        "2026-09-16T08:00:00Z",
        -10000,
        direction="credit",
        category_id="dining_out",
    )

    # Transfer debit (excluded)
    _insert_txn(
        conn,
        "user_alice",
        "t4",
        "2026-09-16T09:00:00Z",
        50000,
        category_id="dining_out",
        excluded_from_spend=1,
    )

    # Duplicate debit (excluded)
    _insert_txn(
        conn,
        "user_alice",
        "t5",
        "2026-09-17T08:00:00Z",
        25000,
        category_id="dining_out",
        is_duplicate_of="t1",
    )

    # Weekend debit (Saturday 2026-09-19)
    _insert_txn(conn, "user_alice", "t6", "2026-09-19T14:00:00Z", 40000, category_id="dining_out")

    # Commitment-matched debit (t7 matched to commitment)
    _insert_txn(conn, "user_alice", "t7", "2026-09-18T08:00:00Z", 30000, category_id="dining_out")
    conn.execute(
        """
        INSERT INTO commitments (
            id, user_id, name, direction, kind, certainty, schedule_kind,
            schedule_json, start_date, source, status, created_at, updated_at
        ) VALUES ('c1', 'user_alice', 'Meal Plan', 'outflow', 'subscription', 'firm',
                  'weekly', '{}', '2026-09-01', 'user', 'active', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO commitment_matches (
            id, user_id, commitment_id, due_date, txn_id, match_method, confidence_bp, created_at
        ) VALUES ('cm1', 'user_alice', 'c1', '2026-09-18', 't7', 'manual', 10000, '2026-09-18T00:00:00Z')
        """
    )

    # Full week including weekend:
    # t1 (25000) + t2 (35000) - t3 (10000) + t6 (40000) = 90000 paise
    spend_all = calculate_category_spend(
        conn, "user_alice", "2026-09-14", "2026-09-20", ["dining_out"], weekdays_only=False
    )
    assert spend_all == 90000

    # Weekdays only: excludes t6 (40000 weekend) => 25000 + 35000 - 10000 = 50000 paise
    spend_weekdays = calculate_category_spend(
        conn, "user_alice", "2026-09-14", "2026-09-20", ["dining_out"], weekdays_only=True
    )
    assert spend_weekdays == 50000


def test_merchant_group_spend_matching(conn):
    """merchant_group_spend matches token substrings in normalized or raw merchant names."""
    _insert_txn(
        conn, "user_alice", "t1", "2026-09-14T10:00:00Z", 45000, merchant_raw="Swiggy Bangalore"
    )
    _insert_txn(
        conn, "user_alice", "t2", "2026-09-15T10:00:00Z", 35000, merchant_raw="Zomato Orders"
    )
    _insert_txn(conn, "user_alice", "t3", "2026-09-16T10:00:00Z", 20000, merchant_raw="BookMyShow")
    # Refund from Swiggy
    _insert_txn(
        conn,
        "user_alice",
        "t4",
        "2026-09-17T10:00:00Z",
        -5000,
        direction="credit",
        merchant_raw="Swiggy Refund",
    )

    # Merchant group: ["swiggy", "zomato"]
    spend = calculate_merchant_group_spend(
        conn, "user_alice", "2026-09-14", "2026-09-20", merchants=["swiggy", "zomato"]
    )
    # Swiggy 45000 - 5000 + Zomato 35000 = 75000
    assert spend == 75000


def test_txn_count_and_no_spend_days(conn):
    """txn_count counts debits; no_spend_days counts days without debits in target categories."""
    # Day 1: 2 debits
    _insert_txn(conn, "user_alice", "t1", "2026-09-14T08:00:00Z", 10000, category_id="shopping")
    _insert_txn(conn, "user_alice", "t2", "2026-09-14T12:00:00Z", 15000, category_id="shopping")
    # Day 2: 0 debits
    # Day 3: 1 debit in different category
    _insert_txn(conn, "user_alice", "t3", "2026-09-16T08:00:00Z", 5000, category_id="groceries")
    # Day 4: 1 debit
    _insert_txn(conn, "user_alice", "t4", "2026-09-17T08:00:00Z", 20000, category_id="shopping")

    # 4-day window: 2026-09-14 to 2026-09-17 (4 days total)
    count = calculate_txn_count(
        conn, "user_alice", "2026-09-14", "2026-09-17", categories=["shopping"]
    )
    assert count == 3  # t1, t2, t4

    # Shopping debits occurred on Day 1 (14th) and Day 4 (17th). Days 2 and 3 had zero shopping debits.
    no_spend = calculate_no_spend_days(
        conn, "user_alice", "2026-09-14", "2026-09-17", categories=["shopping"]
    )
    assert no_spend == 2


def test_tagging_completeness_and_checkin_rate(conn):
    """tagging_completeness and checkin_rate return integer basis points [0, 10000]."""
    # 4 transactions: 3 with non-guess category source ('user', 'rule', 'override'), 1 with 'guess'
    _insert_txn(
        conn,
        "user_alice",
        "t1",
        "2026-09-14T08:00:00Z",
        1000,
        category_id="dining",
        category_source="user",
    )
    _insert_txn(
        conn,
        "user_alice",
        "t2",
        "2026-09-14T09:00:00Z",
        1000,
        category_id="dining",
        category_source="rule",
    )
    _insert_txn(
        conn,
        "user_alice",
        "t3",
        "2026-09-14T10:00:00Z",
        1000,
        category_id="dining",
        category_source="override",
    )
    _insert_txn(
        conn,
        "user_alice",
        "t4",
        "2026-09-14T11:00:00Z",
        1000,
        category_id="dining",
        category_source="none",
    )

    comp_bp = calculate_tagging_completeness(conn, "user_alice", "2026-09-14", "2026-09-14")
    assert comp_bp == 7500  # 3/4 = 75.00% = 7500 bp

    # Checkins: insert 4 checkins, 3 answered, 1 skipped
    conn.execute(
        """
        INSERT INTO experiments (
            id, user_id, title, template_code, hypothesis_json, metric_def_json,
            params_json, difficulty, window_start, window_end, baseline_json,
            target_value, status, origin, created_at
        ) VALUES ('exp_chk', 'user_alice', 'Chk', 'tag', '{}', '{}', '{}', 'easy',
                  '2026-09-01', '2026-09-30', '{}', 100, 'active', 'user', '2026-09-01T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO experiment_checkins (id, user_id, experiment_id, checkin_date, observed_value, pace_status, user_response, created_at)
        VALUES ('c1', 'user_alice', 'exp_chk', '2026-09-07', 10, 'on_pace', 'going_well', '2026-09-07T00:00:00Z'),
               ('c2', 'user_alice', 'exp_chk', '2026-09-14', 20, 'on_pace', 'hard', '2026-09-14T00:00:00Z'),
               ('c3', 'user_alice', 'exp_chk', '2026-09-21', 30, 'on_pace', 'want_to_pause', '2026-09-21T00:00:00Z'),
               ('c4', 'user_alice', 'exp_chk', '2026-09-28', 40, 'on_pace', 'skip', '2026-09-28T00:00:00Z')
        """
    )
    chk_rate = calculate_checkin_rate(conn, "user_alice", "2026-09-01", "2026-09-30")
    # 3 answered out of 4 = 7500 bp
    assert chk_rate == 7500


# ---------------------------------------------------------------------------------------------
# 2. Candidate Windows & Year Boundary Alignment
# ---------------------------------------------------------------------------------------------
def test_candidate_windows_generator_and_weekday_alignment():
    """Candidate windows are exactly non-overlapping, equal duration, and aligned to the start weekday."""
    # 2026-09-14 is Monday
    windows = generate_candidate_windows(start_date="2026-09-14", duration_days=14, k=6)
    assert len(windows) == 6

    # Verify chronological order and weekday alignment
    for w_start_str, w_end_str in windows:
        w_start = date.fromisoformat(w_start_str)
        w_end = date.fromisoformat(w_end_str)
        assert w_start.weekday() == 0  # Monday
        assert (w_end - w_start).days + 1 == 14

    # Verify adjacent windows are contiguous and non-overlapping
    for i in range(len(windows) - 1):
        end_prev = date.fromisoformat(windows[i][1])
        start_next = date.fromisoformat(windows[i + 1][0])
        assert start_next == end_prev + timedelta(days=1)

    # Window crossing year boundary: starting on 2026-01-12 (Monday), duration 14
    yr_windows = generate_candidate_windows(start_date="2026-01-12", duration_days=14, k=4)
    assert len(yr_windows) == 4
    # The window immediately prior ends on 2026-01-11, starts on 2025-12-29 (crosses year)
    w_last = yr_windows[-1]
    assert w_last[0] == "2025-12-29"
    assert w_last[1] == "2026-01-11"
    assert date.fromisoformat(w_last[0]).weekday() == 0


# ---------------------------------------------------------------------------------------------
# 3. Baseline Engine: Exclusions, Even-Count Median, and Minimum Windows
# ---------------------------------------------------------------------------------------------
def test_baseline_calculation_even_count_median_and_exclusions(conn):
    """
    Even-count median rule takes the lower middle integer.
    Windows overlapping contextual exceptions or existing experiments are excluded.
    """
    # Create 6 windows of 14 days before 2026-09-14
    # Windows:
    # W1: 2026-06-22..2026-07-05
    # W2: 2026-07-06..2026-07-19
    # W3: 2026-07-20..2026-08-02
    # W4: 2026-08-03..2026-08-16
    # W5: 2026-08-17..2026-08-30
    # W6: 2026-08-31..2026-09-13
    windows = generate_candidate_windows("2026-09-14", duration_days=14, k=6)

    # Insert spend in each window:
    # W1: 100000, W2: 200000, W3: 300000, W4: 400000, W5: 500000, W6: 600000
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(
            conn,
            "user_alice",
            f"tw_{idx}",
            f"{ws}T10:00:00Z",
            idx * 100000,
            category_id="dining_out",
        )

    base, exclusions = calculate_baseline(
        conn,
        "user_alice",
        metric_code="category_spend",
        start_date="2026-09-14",
        duration_days=14,
        params={"categories": ["dining_out"]},
        k=6,
    )
    assert base is not None
    assert base.k == 6
    assert exclusions == []
    assert base.low == 100000
    assert base.high == 600000
    # Even count (6 values: [100000, 200000, 300000, 400000, 500000, 600000])
    # Lower middle index (6//2 - 1 = index 2) -> 300000
    assert base.median == 300000

    # Inject an active contextual exception overlapping W3 (2026-07-25)
    conn.execute(
        """
        INSERT INTO memory_items (
            id, user_id, kind, subject_key, statement_json, source, status,
            prior_bp, created_at
        ) VALUES ('mem_ex1', 'user_alice', 'contextual_exception', 'dining_out',
                  '{"period": "2026-07-25", "category": "dining_out", "reason": "festival"}',
                  'user_stated', 'active', 9000, '2026-07-25T00:00:00Z')
        """
    )
    base_ex, exclusions_ex = calculate_baseline(
        conn,
        "user_alice",
        metric_code="category_spend",
        start_date="2026-09-14",
        duration_days=14,
        params={"categories": ["dining_out"]},
        k=6,
    )
    assert base_ex is not None
    assert base_ex.k == 5
    assert len(exclusions_ex) == 1
    assert "festival" in exclusions_ex[0]["reason"]
    # 5 values remain: [100000, 200000, 400000, 500000, 600000] -> median is index 2 = 400000
    assert base_ex.median == 400000


def test_baseline_min_windows_threshold(conn):
    """If valid windows < 3, calculate_baseline returns None ('no_baseline'). Exactly 3 succeeds."""
    # Only 2 candidate windows with accounts
    # Account created on 2026-08-20, so earlier windows are excluded
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u = User(id="user_late", created_at="2026-08-20T00:00:00Z")
    insert_user(c, u)
    acc = Account(
        id="acc_late",
        user_id="user_late",
        name="Checking",
        opening_balance_paise=100000,
        created_at="2026-08-20T00:00:00Z",
    )
    insert_account(c, acc)
    # Data coverage starts at the user's first payment, not at the account's creation
    c.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction,"
        " merchant_raw, description, category_id, category_source, created_at)"
        " VALUES ('first', 'user_late', 'acc_late', '2026-08-20T10:00:00Z', 100, 'debit', 'M', 'd',"
        " NULL, 'none', '2026-08-20T10:00:00Z')"
    )

    # 14-day experiment starting 2026-09-14
    # Candidate windows:
    # W1: 2026-08-31..2026-09-13 (valid, after 2026-08-20)
    # W2: 2026-08-17..2026-08-30 (start is 08-17 < 08-20 -> excluded)
    base_fail, excls = calculate_baseline(
        c, "user_late", "category_spend", "2026-09-14", duration_days=14, k=6, min_windows=3
    )
    assert base_fail is None
    assert len(excls) >= 1

    # Now the data reaches back to 2026-08-01 (allowing exactly 3 windows)
    c.execute("UPDATE transactions SET occurred_at = '2026-08-01T10:00:00Z' WHERE id = 'first'")
    c.execute("UPDATE accounts SET created_at = '2026-08-01T00:00:00Z' WHERE id = 'acc_late'")
    base_ok, _ = calculate_baseline(
        c, "user_late", "category_spend", "2026-09-14", duration_days=14, k=6, min_windows=3
    )
    assert base_ok is not None
    assert base_ok.k == 3


# ---------------------------------------------------------------------------------------------
# 4. Exact Rank-P and Outcome Boundaries
# ---------------------------------------------------------------------------------------------
def test_rank_p_exact_math_k3_and_k6():
    """
    rank_p exact formula: (1 + count(b <= v)) / (k + 1) in basis points.
    For K=3, denominator is 4. For K=6, denominator is 7.
    """
    # K=3: window values = [10000, 20000, 30000]
    base3 = Baseline(
        k=3,
        window_values=[10000, 20000, 30000],
        median=20000,
        low=10000,
        high=30000,
    )
    # v < all (0 elements <= v): (1 + 0) / 4 = 1/4 = 2500 bp
    _, p_low, _, _ = evaluate_outcome(5000, base3, target_value=15000, metric_code="category_spend")
    assert p_low == 2500

    # v between 1st and 2nd (1 element <= v): (1 + 1) / 4 = 2/4 = 5000 bp
    _, p_mid, _, _ = evaluate_outcome(
        15000, base3, target_value=15000, metric_code="category_spend"
    )
    assert p_mid == 5000

    # v > all (3 elements <= v): (1 + 3) / 4 = 4/4 = 10000 bp
    _, p_high, _, _ = evaluate_outcome(
        35000, base3, target_value=15000, metric_code="category_spend"
    )
    assert p_high == 10000

    # K=6: window values = [10000, 20000, 30000, 40000, 50000, 60000]
    base6 = Baseline(
        k=6,
        window_values=[10000, 20000, 30000, 40000, 50000, 60000],
        median=30000,
        low=10000,
        high=60000,
    )
    # 0 elements <= v: (1 + 0) / 7 = 10000 // 7 = 1428 bp
    _, p6_low, _, _ = evaluate_outcome(
        5000, base6, target_value=25000, metric_code="category_spend"
    )
    assert p6_low == 1428


def test_outcome_boundaries_lower_is_better():
    """
    Boundary tests:
    - v = low: within_usual_range (must be strictly < low)
    - v = low - 1 paisa: checked against min_effect.
    - effect exactly at min_effect: beyond_usual_range.
    - effect exactly 1 paisa below min_effect: within_usual_range.
    """
    # median = 100000, low = 50000, high = 150000
    # min_effect_share = 10% of 100000 = 10000 paise. min_effect_paise = 20000 paise (₹200).
    # max(10000, 20000) = 20000 paise.
    # Therefore, to be beyond_usual_range, v must be < 50000 AND median - v >= 20000.
    base = Baseline(
        k=6,
        window_values=[50000, 70000, 100000, 120000, 140000, 150000],
        median=100000,
        low=50000,
        high=150000,
    )

    # 1. v == low (50000): within_usual_range (not strictly less)
    out1, _, eff1, met1 = evaluate_outcome(
        50000, base, target_value=80000, metric_code="category_spend"
    )
    assert out1 == "within_usual_range"
    assert eff1 == 50000
    assert met1 is True

    # 2. v == 49999 (strictly < low, and median - v = 50001 >= 20000): beyond_usual_range
    out2, _, eff2, met2 = evaluate_outcome(
        49999, base, target_value=80000, metric_code="category_spend"
    )
    assert out2 == "beyond_usual_range"
    assert eff2 == 50001
    assert met2 is True

    # 3. Test min_effect boundary where low is very close to median
    # low = 90000, median = 100000. min_effect is 20000 paise.
    # v must be <= median - 20000 = 80000 to qualify as beyond_usual_range.
    base_tight = Baseline(
        k=3,
        window_values=[90000, 100000, 110000],
        median=100000,
        low=90000,
        high=110000,
    )
    # v = 80001 (effect = 19999, 1 paisa below min_effect 20000): within_usual_range
    out3, _, eff3, _ = evaluate_outcome(
        80001, base_tight, target_value=85000, metric_code="category_spend"
    )
    assert out3 == "within_usual_range"
    assert eff3 == 19999

    # v = 80000 (effect = 20000, exactly min_effect): beyond_usual_range
    out4, _, eff4, _ = evaluate_outcome(
        80000, base_tight, target_value=85000, metric_code="category_spend"
    )
    assert out4 == "beyond_usual_range"
    assert eff4 == 20000

    # 4. v > high (110001): above_usual_range
    out5, _, _, met5 = evaluate_outcome(
        110001, base_tight, target_value=85000, metric_code="category_spend"
    )
    assert out5 == "above_usual_range"
    assert met5 is False


def test_outcome_boundaries_higher_is_better():
    """Higher-is-better metrics (no_spend_days, goal_allocation) mirror boundary logic."""
    # median = 4 days, low = 2, high = 6
    # For no_spend_days: min_effect_paise = 0, min_effect_share = 10% (0.4 days -> 0)
    base = Baseline(
        k=3,
        window_values=[2, 4, 6],
        median=4,
        low=2,
        high=6,
    )
    # v = 6 (at high): within_usual_range
    out_at_high, _, _, _ = evaluate_outcome(
        6, base, target_value=5, metric_code="no_spend_days", min_effect_paise=0
    )
    assert out_at_high == "within_usual_range"

    # v = 7 (> high): beyond_usual_range
    out_above, _, eff, met = evaluate_outcome(
        7, base, target_value=5, metric_code="no_spend_days", min_effect_paise=0
    )
    assert out_above == "beyond_usual_range"
    assert eff == 3  # 7 - 4 = 3
    assert met is True

    # v = 1 (< low): above_usual_range (worse than usual)
    out_below, _, _, met_below = evaluate_outcome(
        1, base, target_value=5, metric_code="no_spend_days", min_effect_paise=0
    )
    assert out_below == "above_usual_range"
    assert met_below is False


# ---------------------------------------------------------------------------------------------
# 5. Pace Rounding and Boundaries
# ---------------------------------------------------------------------------------------------
def test_pace_rounding_and_tolerance():
    """Pace computes integer expected progress and classifies ahead, on_pace, and behind."""
    # 14-day experiment: target = 140000 paise (10000/day), tolerance 10% (1000 bp)
    # Day 7 (halfway): expected = (140000 * 7 + 7) // 14 = 70000. tolerance = 7000.
    # on_pace range: [63000, 77000]

    # Exactly on pace
    p_exact = calculate_pace(
        observed_value=70000,
        target_value=140000,
        start_date="2026-09-01",
        end_date="2026-09-14",
        as_of_date="2026-09-07",
        metric_code="category_spend",
        tolerance_bp=1000,
    )
    assert p_exact == "on_pace"

    # Ahead (spent less than 63000)
    p_ahead = calculate_pace(
        observed_value=60000,
        target_value=140000,
        start_date="2026-09-01",
        end_date="2026-09-14",
        as_of_date="2026-09-07",
        metric_code="category_spend",
        tolerance_bp=1000,
    )
    assert p_ahead == "ahead"

    # Behind (spent more than 77000)
    p_behind = calculate_pace(
        observed_value=85000,
        target_value=140000,
        start_date="2026-09-01",
        end_date="2026-09-14",
        as_of_date="2026-09-07",
        metric_code="category_spend",
        tolerance_bp=1000,
    )
    assert p_behind == "behind"


# ---------------------------------------------------------------------------------------------
# 6. Integrity Threshold Boundary
# ---------------------------------------------------------------------------------------------
def test_integrity_notes_margin_threshold_boundary(conn):
    """
    If recategorized amount is >= 50% of winning margin, confirmation_required is True.
    1 paisa below 50% leaves confirmation_required False.
    """
    # Target = 100000 paise, Observed = 60000 paise -> Winning Margin = 40000 paise.
    # 50% threshold = 20000 paise.
    # 1. Recategorization of 19999 paise (1 paisa below): confirmation NOT required
    conn.execute(
        """
        INSERT INTO audit_events (
            id, user_id, actor, event_type, occurred_at, reason, metadata_json
        ) VALUES ('aud_1', 'user_alice', 'user', 'category_override_created', '2026-09-05T10:00:00Z',
                  're-categorized',
                  '{"previous_category_id": "dining_out", "new_category_id": "groceries", "amount_paise": 19999}')
        """
    )
    note_below = calculate_integrity_notes(
        conn,
        "user_alice",
        start_date="2026-09-01",
        end_date="2026-09-14",
        target_value=100000,
        observed_value=60000,
        categories=["dining_out"],
        metric_code="category_spend",
        share_of_margin_bp=5000,
    )
    assert note_below.recategorized_amount_paise == 19999
    assert note_below.confirmation_required is False

    # 2. Add 1 more paisa to reach exactly 20000 paise: confirmation REQUIRED
    conn.execute(
        """
        INSERT INTO audit_events (
            id, user_id, actor, event_type, occurred_at, reason, metadata_json
        ) VALUES ('aud_2', 'user_alice', 'user', 'category_override_created', '2026-09-06T10:00:00Z',
                  're-categorized',
                  '{"previous_category_id": "dining_out", "new_category_id": "groceries", "amount_paise": 1}')
        """
    )
    note_at = calculate_integrity_notes(
        conn,
        "user_alice",
        start_date="2026-09-01",
        end_date="2026-09-14",
        target_value=100000,
        observed_value=60000,
        categories=["dining_out"],
        metric_code="category_spend",
        share_of_margin_bp=5000,
    )
    assert note_at.recategorized_amount_paise == 20000
    assert note_at.confirmation_required is True


# ---------------------------------------------------------------------------------------------
# 7. Property-based Invariant Tests
# ---------------------------------------------------------------------------------------------
def test_baseline_and_rank_p_properties():
    """
    Property tests:
    1. low <= median <= high holds across all non-empty integer lists.
    2. rank_p_bp is always strictly in (0, 10000].
    """
    rng = random.Random(1337)

    for _ in range(50):
        k = rng.randint(3, 12)
        vals = [rng.randint(1000, 500000) for _ in range(k)]
        s_vals = sorted(vals)
        n = len(s_vals)
        med = s_vals[n // 2] if n % 2 == 1 else s_vals[(n // 2) - 1]
        low = min(vals)
        high = max(vals)

        # Property 1: Ordering invariant
        assert low <= med <= high

        base = Baseline(k=k, window_values=vals, median=med, low=low, high=high)

        # Test rank-p on random observations
        obs = rng.randint(0, 600000)
        _, p_bp, _, _ = evaluate_outcome(obs, base, target_value=med, metric_code="category_spend")

        # Property 2: Valid basis point range
        assert 1 <= p_bp <= 10000
