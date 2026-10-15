"""
Unit and property tests for Stage 4.6: Self-competition, personal bests, and forgiving streaks.
(PLAN_PHASE4 Section 5.6 & Stage 4.6)

Tests:
1. Best detection and ties (earliest wins) for both lower-is-better and higher-is-better metrics.
2. Grace day exactly at 7-day boundaries (1 grace day per 7 days).
3. Streak freezes during declared contextual exceptions (preserves streak without consuming grace).
4. Broken streak wording (shown as 'longest streak: N days', never as a loss or shame).
5. No comparison with any other user anywhere (scan test over outputs).
6. End-to-end integration tests for tagging_streak and checkin_streak against real SQLite DB.
"""

from datetime import date, datetime, timedelta

import pytest

from copilot.core.self_competition import (
    FORBIDDEN_SHAME_TERMS,
    FORBIDDEN_SOCIAL_COMPARISON_TERMS,
    assert_no_social_comparison,
    calculate_checkin_streak,
    calculate_streak_from_daily_series,
    calculate_tagging_streak,
    compute_personal_bests,
    evaluate_new_personal_best,
    format_self_comparison,
    get_streak_freeze_dates,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import (
    insert_experiment,
    insert_experiment_checkin,
    insert_experiment_review,
    insert_streak_freeze,
)
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import (
    Experiment,
    ExperimentCheckin,
    ExperimentReview,
    PersonalBest,
    StreakFreeze,
)

T0 = "2026-01-01T00:00:00Z"
DT0 = datetime(2026, 9, 1, 10, 0, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u_alice", created_at=T0))
    insert_account(c, Account(id="acc_main", user_id="u_alice", name="Checking", created_at=T0))
    insert_category(c, Category(id="dining", user_id="u_alice", name="Dining", created_at=T0))
    return c


# ---------------------------------------------------------------------------------------------
# 1. Personal Best Detection & Ties (Earliest Wins)
# ---------------------------------------------------------------------------------------------
def test_personal_bests_lower_is_better(conn):
    """Lower is better: smaller value is a new best; tie keeps earlier."""
    # Experiment 1: 300000 paise on 2026-06-01
    exp1 = Experiment(
        id="exp_1",
        user_id="u_alice",
        title="Dining Cap 1",
        template_code="dining_cap",
        hypothesis_json={},
        metric_def_json={"metric": "category_spend"},
        params_json={},
        difficulty="medium",
        window_start="2026-06-01",
        window_end="2026-06-14",
        baseline_json={},
        target_value=350000,
        status="reviewed",
        origin="user",
        created_at="2026-06-01T00:00:00Z",
    )
    insert_experiment(conn, exp1)
    insert_experiment_review(
        conn,
        ExperimentReview(
            id="rev_1",
            user_id="u_alice",
            experiment_id="exp_1",
            observed_value=300000,
            outcome="beyond_usual_range",
            rank_p_bp=1428,
            effect_value=50000,
            target_met=True,
            integrity_json={},
            data_quality_json={},
            created_at="2026-06-15T10:00:00Z",
        ),
    )

    bests = compute_personal_bests(conn, "u_alice")
    assert len(bests) == 1
    assert bests[0].best_value == 300000
    assert bests[0].achieved_at == "2026-06-15T10:00:00Z"

    # Experiment 2: Better spend (250000 paise) on 2026-07-01 -> New Best!
    exp2 = Experiment(
        id="exp_2",
        user_id="u_alice",
        title="Dining Cap 2",
        template_code="dining_cap",
        hypothesis_json={},
        metric_def_json={"metric": "category_spend"},
        params_json={},
        difficulty="medium",
        window_start="2026-07-01",
        window_end="2026-07-14",
        baseline_json={},
        target_value=300000,
        status="reviewed",
        origin="user",
        created_at="2026-07-01T00:00:00Z",
    )
    insert_experiment(conn, exp2)
    insert_experiment_review(
        conn,
        ExperimentReview(
            id="rev_2",
            user_id="u_alice",
            experiment_id="exp_2",
            observed_value=250000,
            outcome="beyond_usual_range",
            rank_p_bp=1428,
            effect_value=50000,
            target_met=True,
            integrity_json={},
            data_quality_json={},
            created_at="2026-07-15T10:00:00Z",
        ),
    )

    bests = compute_personal_bests(conn, "u_alice")
    assert len(bests) == 1
    assert bests[0].best_value == 250000
    assert bests[0].achieved_at == "2026-07-15T10:00:00Z"
    assert bests[0].experiment_id == "exp_2"

    # Experiment 3: Worse spend (280000 paise) on 2026-08-01 -> NOT a new best
    exp3 = Experiment(
        id="exp_3",
        user_id="u_alice",
        title="Dining Cap 3",
        template_code="dining_cap",
        hypothesis_json={},
        metric_def_json={"metric": "category_spend"},
        params_json={},
        difficulty="medium",
        window_start="2026-08-01",
        window_end="2026-08-14",
        baseline_json={},
        target_value=300000,
        status="reviewed",
        origin="user",
        created_at="2026-08-01T00:00:00Z",
    )
    insert_experiment(conn, exp3)
    insert_experiment_review(
        conn,
        ExperimentReview(
            id="rev_3",
            user_id="u_alice",
            experiment_id="exp_3",
            observed_value=280000,
            outcome="within_usual_range",
            rank_p_bp=2857,
            effect_value=20000,
            target_met=True,
            integrity_json={},
            data_quality_json={},
            created_at="2026-08-15T10:00:00Z",
        ),
    )

    bests = compute_personal_bests(conn, "u_alice")
    assert len(bests) == 1
    assert bests[0].best_value == 250000
    assert bests[0].experiment_id == "exp_2"


def test_personal_bests_ties_earliest_wins():
    """Ties break in favor of the earliest achievement (is_new_best = False)."""
    initial_pb = PersonalBest(
        metric_code="category_spend",
        window_length_days=14,
        best_value=200000,
        achieved_at="2026-05-01T00:00:00Z",
        experiment_id="exp_early",
    )
    existing_bests = [initial_pb]

    # Exactly matching value at a later date
    is_new, prev, res = evaluate_new_personal_best(
        existing_bests,
        metric_code="category_spend",
        window_length_days=14,
        observed_value=200000,
        achieved_at="2026-08-01T00:00:00Z",
        experiment_id="exp_later",
    )
    assert not is_new
    assert prev is not None
    assert res.achieved_at == "2026-05-01T00:00:00Z"
    assert res.experiment_id == "exp_early"


def test_personal_bests_higher_is_better():
    """Higher is better metrics (e.g. no_spend_days): larger value is new best."""
    initial_pb = PersonalBest(
        metric_code="no_spend_days",
        window_length_days=14,
        best_value=5,
        achieved_at="2026-05-01T00:00:00Z",
    )
    existing_bests = [initial_pb]

    # Value 7 -> New Best!
    is_new, prev, res = evaluate_new_personal_best(
        existing_bests,
        metric_code="no_spend_days",
        window_length_days=14,
        observed_value=7,
        achieved_at="2026-06-01T00:00:00Z",
    )
    assert is_new
    assert prev.best_value == 5
    assert res.best_value == 7

    # Value 7 again (tie) -> Not new best, 2026-06-01 wins
    is_new_tie, _, res_tie = evaluate_new_personal_best(
        [res],
        metric_code="no_spend_days",
        window_length_days=14,
        observed_value=7,
        achieved_at="2026-07-01T00:00:00Z",
    )
    assert not is_new_tie
    assert res_tie.achieved_at == "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------------------------
# 2. Grace Days at Exactly 7-Day Boundaries
# ---------------------------------------------------------------------------------------------
def test_grace_day_exactly_at_7_day_boundaries():
    """
    Forgiving streaks allow 1 grace day per 7-day boundary.
    - 6 compliant + 1 missed (Day 7) = 7-day streak (forgiven).
    - 6 compliant + 1 missed (Day 7) + 1 missed (Day 8) -> breaks at Day 8!
    - 6 compliant + 1 missed (Day 7) + 6 compliant + 1 missed (Day 14) -> forgiven (14-day streak)!
    """
    start = date(2026, 9, 1)

    # Scenario A: 6 compliant days + 1 miss on Day 7
    daily_a: dict[date, bool] = {}
    for i in range(6):
        daily_a[start + timedelta(days=i)] = True
    daily_a[start + timedelta(days=6)] = False  # Miss on Day 7

    as_of_a = start + timedelta(days=6)
    info_a = calculate_streak_from_daily_series(daily_a, set(), as_of_a)
    assert info_a.current_streak == 7
    assert info_a.longest_streak == 7
    assert info_a.is_active is True

    # Scenario B: Miss on Day 7 followed immediately by miss on Day 8
    daily_b = dict(daily_a)
    daily_b[start + timedelta(days=7)] = False  # Miss on Day 8 (not at 7-day boundary from Day 7)
    as_of_b = start + timedelta(days=7)
    info_b = calculate_streak_from_daily_series(daily_b, set(), as_of_b)
    # Day 8 cannot use grace because only 1 day has passed since Day 7 grace day
    assert info_b.current_streak == 0
    assert info_b.longest_streak == 7
    assert info_b.is_active is False
    assert "Longest streak: 7 days" in info_b.display_text

    # Scenario C: Miss on Day 7, then 6 compliant days (Days 8-13), then miss on Day 14 (Day index 13)
    daily_c = dict(daily_a)
    for i in range(7, 13):
        daily_c[start + timedelta(days=i)] = True  # Days 8 to 13 compliant (6 days)
    daily_c[start + timedelta(days=13)] = False  # Miss on Day 14 (exactly 7 days after Day 7 miss)

    as_of_c = start + timedelta(days=13)
    info_c = calculate_streak_from_daily_series(daily_c, set(), as_of_c)
    assert info_c.current_streak == 14
    assert info_c.longest_streak == 14
    assert info_c.is_active is True

    # Scenario D: Miss on Day 7, only 4 compliant days, then second miss on Day 12
    daily_d = dict(daily_a)
    for i in range(7, 11):
        daily_d[start + timedelta(days=i)] = True
    daily_d[start + timedelta(days=11)] = False  # Day 12 miss (< 7 days since Day 7)
    as_of_d = start + timedelta(days=11)
    info_d = calculate_streak_from_daily_series(daily_d, set(), as_of_d)
    assert info_d.current_streak == 0
    assert info_d.longest_streak == 11
    assert info_d.is_active is False


# ---------------------------------------------------------------------------------------------
# 3. Streak Freezes During Declared Exceptions
# ---------------------------------------------------------------------------------------------
def test_streak_freezes_during_declared_exceptions(conn):
    """
    When an exception is declared (contextual_exception memory or streak_freezes table),
    those days freeze the streak without consuming a grace day.
    """
    start = date(2026, 9, 1)

    # Insert a 3-day freeze from 2026-09-06 to 2026-09-08
    insert_streak_freeze(
        conn,
        StreakFreeze(
            id="frz_1",
            user_id="u_alice",
            streak_code="tagging_streak",
            from_date="2026-09-06",
            to_date="2026-09-08",
            reason="exception",
            created_at=T0,
        ),
    )

    freezes = get_streak_freeze_dates(conn, "u_alice", "tagging_streak")
    assert date(2026, 9, 6) in freezes
    assert date(2026, 9, 7) in freezes
    assert date(2026, 9, 8) in freezes

    # Days 1-5 compliant (Sep 1 to 5)
    # Days 6-8 frozen (Sep 6 to 8)
    # Day 9 compliant (Sep 9)
    # Day 10 missed (Sep 10) -> can still use grace because grace was not used during freeze!
    daily: dict[date, bool] = {}
    for i in range(5):
        daily[start + timedelta(days=i)] = True
    # Days 6-8 are missed or unrecorded, but covered by freeze
    daily[start + timedelta(days=5)] = False
    daily[start + timedelta(days=6)] = False
    daily[start + timedelta(days=7)] = False
    # Day 9 compliant
    daily[start + timedelta(days=8)] = True

    as_of = start + timedelta(days=8)
    info = calculate_streak_from_daily_series(daily, freezes, as_of)
    # 5 compliant + 1 compliant = 6 compliant days, preserved across 3 freeze days
    assert info.current_streak == 6
    assert info.is_active is True


# ---------------------------------------------------------------------------------------------
# 4. Broken Streak Wording (Never as Loss or Shame)
# ---------------------------------------------------------------------------------------------
def test_broken_streak_wording_no_shame():
    """A broken streak is shown as 'longest streak: N days', never as a loss or failure."""
    start = date(2026, 9, 1)
    daily = {
        start: True,
        start + timedelta(days=1): True,
        start + timedelta(days=2): True,
        start + timedelta(days=3): False,  # Missed (no grace yet)
    }
    as_of = start + timedelta(days=3)
    info = calculate_streak_from_daily_series(daily, set(), as_of)

    assert not info.is_active
    assert info.current_streak == 0
    assert info.longest_streak == 3
    assert info.display_text == "Longest streak: 3 days"

    # Scan for forbidden words
    lower = info.display_text.lower()
    for term in FORBIDDEN_SHAME_TERMS:
        assert term not in lower, f"Shame term '{term}' found in display_text: '{info.display_text}'"


# ---------------------------------------------------------------------------------------------
# 5. Output Scan Test: No Social Comparison Anywhere
# ---------------------------------------------------------------------------------------------
def test_no_social_comparison_scan_test():
    """Scan over formatting outputs ensuring zero social comparison or peer metrics."""
    pb = PersonalBest(
        metric_code="category_spend",
        window_length_days=14,
        best_value=185000,
        achieved_at="2026-07-15T10:00:00Z",
    )

    statement = format_self_comparison(
        current_value_formatted="Rs 2,100",
        median_formatted="Rs 2,800",
        k=6,
        range_formatted="Rs 2,400 to Rs 3,400",
        personal_best=pb,
        pb_formatted="Rs 1,850",
        window_name="comparable fortnights",
    )

    assert "Rs 2,100" in statement
    assert "your median of Rs 2,800" in statement
    assert "your personal best of Rs 1,850" in statement
    assert "2026-07-15" in statement

    # Scan for forbidden comparison terms
    lower = statement.lower()
    for term in FORBIDDEN_SOCIAL_COMPARISON_TERMS:
        assert term not in lower, f"Social comparison term '{term}' found in '{statement}'"

    # Verify validator raises if a forbidden term is injected
    with pytest.raises(AssertionError, match="Forbidden social comparison"):
        assert_no_social_comparison("You spent less than 85% of other users!")

    with pytest.raises(AssertionError, match="Forbidden shame term"):
        assert_no_social_comparison("You lost your streak today.")


# ---------------------------------------------------------------------------------------------
# 6. Database Integration: Tagging Streak & Checkin Streak
# ---------------------------------------------------------------------------------------------
def test_tagging_streak_integration(conn):
    """Verify calculate_tagging_streak against real SQLite transactions."""
    # Day 1 (Sep 1): tagged txn
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            category_id, category_source, merchant_raw, description, created_at
        ) VALUES ('tx_1', 'u_alice', 'acc_main', '2026-09-01T10:00:00Z', 10000, 'debit',
                  'dining', 'user', 'Swiggy', 'Order', '2026-09-01T10:00:00Z')
        """
    )
    # Day 2 (Sep 2): tagged txn
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            category_id, category_source, merchant_raw, description, created_at
        ) VALUES ('tx_2', 'u_alice', 'acc_main', '2026-09-02T10:00:00Z', 15000, 'debit',
                  'dining', 'rule', 'Zomato', 'Order', '2026-09-02T10:00:00Z')
        """
    )
    # Day 3 (Sep 3): untagged txn (category_source = 'none') -> breaks tagging streak
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            category_id, category_source, merchant_raw, description, created_at
        ) VALUES ('tx_3', 'u_alice', 'acc_main', '2026-09-03T10:00:00Z', 20000, 'debit',
                  NULL, 'none', 'Cafe Coffee', 'Order', '2026-09-03T10:00:00Z')
        """
    )

    as_of = date(2026, 9, 3)
    info = calculate_tagging_streak(conn, "u_alice", as_of)
    assert not info.is_active
    assert info.current_streak == 0
    assert info.longest_streak == 2
    assert "Longest streak: 2 days" in info.display_text


def test_checkin_streak_integration(conn):
    """Verify calculate_checkin_streak against real SQLite experiment checkins."""
    # First insert experiment exp_x for foreign key
    insert_experiment(
        conn,
        Experiment(
            id="exp_x",
            user_id="u_alice",
            title="Active Experiment",
            template_code="dining_cap",
            hypothesis_json={},
            metric_def_json={"metric": "category_spend"},
            params_json={},
            difficulty="medium",
            window_start="2026-09-01",
            window_end="2026-09-14",
            baseline_json={},
            target_value=300000,
            status="active",
            origin="user",
            created_at=T0,
        ),
    )

    # Week 1 checkin answered
    insert_experiment_checkin(
        conn,
        ExperimentCheckin(
            id="chk_1",
            user_id="u_alice",
            experiment_id="exp_x",
            checkin_date="2026-09-01",
            observed_value=100000,
            pace_status="on_pace",
            user_response="going_well",
            created_at=T0,
        ),
    )
    # Week 2 checkin answered
    insert_experiment_checkin(
        conn,
        ExperimentCheckin(
            id="chk_2",
            user_id="u_alice",
            experiment_id="exp_x",
            checkin_date="2026-09-08",
            observed_value=200000,
            pace_status="on_pace",
            user_response="going_well",
            created_at=T0,
        ),
    )

    as_of = date(2026, 9, 8)
    info = calculate_checkin_streak(conn, "u_alice", as_of)
    assert info.is_active
    assert info.current_streak == 8  # 8 continuous days (Sep 1 to Sep 8) with answered checkins

