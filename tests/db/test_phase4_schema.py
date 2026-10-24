"""
Tests for Stage 4.1: Phase 4 database schema, models, constraints, and migrations.
"""

import sqlite3

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_goal, insert_user
from copilot.db.repo_phase4 import (
    get_adjustment_proposal,
    get_experiment,
    get_experiment_review,
    get_offer,
    get_user_xp_for_day,
    get_user_xp_total,
    has_badge,
    insert_adjustment_proposal,
    insert_badge_award,
    insert_experiment,
    insert_experiment_checkin,
    insert_experiment_review,
    insert_offer,
    insert_streak_freeze,
    insert_xp_event,
    list_badge_awards,
    list_experiment_checkins,
    list_experiments,
    list_streak_freezes,
    update_adjustment_status,
    update_experiment_status,
    update_offer_status,
)
from copilot.models.agentic import Goal
from copilot.models.domain import Account, User
from copilot.models.phase4 import (
    AdjustmentProposal,
    BadgeAward,
    Baseline,
    Experiment,
    ExperimentCheckin,
    ExperimentReview,
    Hypothesis,
    IntegrityNote,
    MetricDef,
    Offer,
    StreakFreeze,
    XpEvent,
)


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u1 = User(id="user_alice", created_at="2026-09-01T00:00:00Z")
    u2 = User(id="user_bob", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u1)
    insert_user(c, u2)

    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=5000000,
        created_at="2026-09-01T00:00:00Z",
    )
    insert_account(c, acc)

    goal = Goal(
        id="goal_vacation",
        user_id="user_alice",
        name="Vacation Fund",
        kind="savings",
        target_paise=10000000,
        current_paise=4000000,
        priority=1,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    insert_goal(c, goal)
    return c


def test_experiment_round_trip_and_tenant_isolation(conn):
    """Experiment model inserts, reads back with exact JSON structures, and isolates by user."""
    hyp = Hypothesis(
        intervention="cook dinner on weekdays",
        metric="category_spend",
        direction="lower",
        target=150000,
    )
    mdef = MetricDef(
        metric="category_spend",
        categories=["dining_out", "food_delivery"],
        weekdays_only=True,
    )
    base = Baseline(
        k=6,
        window_values=[200000, 220000, 190000, 210000, 180000, 230000],
        median=205000,
        low=180000,
        high=230000,
        excluded_windows=[{"window": "2026-07-01", "reason": "festival"}],
    )
    exp = Experiment(
        id="exp_01",
        user_id="user_alice",
        title="Weekday Home Cooking Sprint",
        template_code="weekday_home_cooking",
        hypothesis_json=hyp.model_dump(),
        metric_def_json=mdef.model_dump(),
        params_json={"focus": "weekdays"},
        difficulty="medium",
        window_start="2026-09-15",
        window_end="2026-09-28",
        baseline_json=base.model_dump(),
        target_value=150000,
        status="active",
        origin="offer",
        offer_id="off_01",
        goal_id="goal_vacation",
        created_at="2026-09-15T00:00:00Z",
        started_at="2026-09-15T00:00:00Z",
    )
    insert_experiment(conn, exp)

    # Alice can read it
    fetched = get_experiment(conn, "user_alice", "exp_01")
    assert fetched is not None
    assert fetched.title == "Weekday Home Cooking Sprint"
    assert fetched.hypothesis_json["direction"] == "lower"
    assert fetched.baseline_json["median"] == 205000
    assert fetched.status == "active"

    # Bob cannot read Alice's experiment (tenant isolation)
    bob_fetched = get_experiment(conn, "user_bob", "exp_01")
    assert bob_fetched is None
    assert len(list_experiments(conn, "user_bob")) == 0
    assert len(list_experiments(conn, "user_alice")) == 1

    # Update status
    update_experiment_status(
        conn,
        "user_alice",
        "exp_01",
        status="completed",
        ended_at="2026-09-28T23:59:59Z",
    )
    updated = get_experiment(conn, "user_alice", "exp_01")
    assert updated.status == "completed"
    assert updated.ended_at == "2026-09-28T23:59:59Z"


def test_experiment_checkins_and_reviews(conn):
    """Check-ins and reviews persist and enforce enum and range constraints."""
    exp = Experiment(
        id="exp_chk",
        user_id="user_alice",
        title="Delivery Cap",
        template_code="delivery_cap",
        hypothesis_json={"target": 50000},
        metric_def_json={"metric": "merchant_group_spend"},
        params_json={},
        difficulty="easy",
        window_start="2026-09-01",
        window_end="2026-09-14",
        baseline_json={"median": 80000},
        target_value=50000,
        status="active",
        origin="user",
        created_at="2026-09-01T00:00:00Z",
    )
    insert_experiment(conn, exp)

    # 1. Check-in
    chk = ExperimentCheckin(
        id="chk_01",
        user_id="user_alice",
        experiment_id="exp_chk",
        checkin_date="2026-09-07",
        observed_value=22000,
        pace_status="on_pace",
        user_response="going_well",
        created_at="2026-09-07T10:00:00Z",
    )
    insert_experiment_checkin(conn, chk)
    checkins = list_experiment_checkins(conn, "user_alice", "exp_chk")
    assert len(checkins) == 1
    assert checkins[0].pace_status == "on_pace"

    # Checkin with invalid pace_status fails CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO experiment_checkins (
                id, user_id, experiment_id, checkin_date, observed_value, pace_status, created_at
            ) VALUES ('chk_bad', 'user_alice', 'exp_chk', '2026-09-08', 100, 'flying_high', '2026-09-08T00:00:00Z')
            """
        )

    # 2. Review
    integ = IntegrityNote(
        recategorized_count=1,
        recategorized_amount_paise=5000,
        late_txns_count=0,
        late_txns_amount_paise=0,
        confirmation_required=False,
    )
    rev = ExperimentReview(
        id="rev_01",
        user_id="user_alice",
        experiment_id="exp_chk",
        observed_value=45000,
        outcome="beyond_usual_range",
        rank_p_bp=1428,
        effect_value=35000,
        target_met=True,
        integrity_json=integ.model_dump(),
        data_quality_json={"completeness_bp": 9800},
        user_difficulty=2,
        user_helpful=True,
        user_would_repeat=True,
        created_at="2026-09-16T12:00:00Z",
    )
    insert_experiment_review(conn, rev)

    fetched_rev = get_experiment_review(conn, "user_alice", "exp_chk")
    assert fetched_rev is not None
    assert fetched_rev.outcome == "beyond_usual_range"
    assert fetched_rev.target_met is True
    assert fetched_rev.user_helpful is True
    assert fetched_rev.integrity_json["recategorized_count"] == 1


def test_adjustment_proposals_lifecycle(conn):
    """Adjustment proposals handle lifecycle transitions and status updates."""
    prop = AdjustmentProposal(
        id="prop_01",
        user_id="user_alice",
        experiment_id="exp_adj",
        kind="ease_target",
        reason_code="two_consecutive_behind",
        params_json={"new_target_value": 75000},
        status="proposed",
        created_at="2026-09-10T08:00:00Z",
    )
    # Ensure foreign key target exists
    insert_experiment(
        conn,
        Experiment(
            id="exp_adj",
            user_id="user_alice",
            title="Adj Exp",
            template_code="delivery_cap",
            hypothesis_json={},
            metric_def_json={},
            params_json={},
            difficulty="hard",
            window_start="2026-09-01",
            window_end="2026-09-14",
            baseline_json={},
            target_value=50000,
            status="active",
            origin="user",
            created_at="2026-09-01T00:00:00Z",
        ),
    )
    insert_adjustment_proposal(conn, prop)

    fetched = get_adjustment_proposal(conn, "user_alice", "prop_01")
    assert fetched is not None
    assert fetched.status == "proposed"

    update_adjustment_status(
        conn, "user_alice", "prop_01", status="accepted", decided_at="2026-09-10T09:00:00Z"
    )
    fetched2 = get_adjustment_proposal(conn, "user_alice", "prop_01")
    assert fetched2.status == "accepted"
    assert fetched2.decided_at == "2026-09-10T09:00:00Z"


def test_offers_repo_and_status(conn):
    """Offers persist with propensities, seed, and status transitions."""
    offer = Offer(
        id="off_wk1",
        user_id="user_alice",
        week_start="2026-09-15",
        template_code="weekday_home_cooking",
        difficulty="medium",
        params_json={"focus": "weekdays"},
        rank=1,
        propensity_bp=4250,
        policy_version="thompson_v1",
        rng_seed=42,
        reason_json={"median": 205000, "target": 150000},
        status="shown",
        created_at="2026-09-15T00:00:00Z",
    )
    insert_offer(conn, offer)

    fetched = get_offer(conn, "user_alice", "off_wk1")
    assert fetched is not None
    assert fetched.propensity_bp == 4250
    assert fetched.rng_seed == 42
    assert fetched.status == "shown"

    update_offer_status(
        conn, "user_alice", "off_wk1", status="accepted", decided_at="2026-09-15T10:00:00Z"
    )
    fetched2 = get_offer(conn, "user_alice", "off_wk1")
    assert fetched2.status == "accepted"


def test_xp_events_uniqueness_and_append_only_triggers(conn):
    """XP events are idempotent, calculate daily and total XP, and enforce append-only triggers."""
    e1 = XpEvent(
        id="xp_01",
        user_id="user_alice",
        rule_code="checkin_answered",
        points=15,
        ref_kind="checkin",
        ref_id="chk_01",
        period_day="2026-09-07",
        created_at="2026-09-07T10:00:00Z",
    )
    # First insert succeeds
    assert insert_xp_event(conn, e1) is True

    # Duplicate insert returns False (idempotent unique constraint)
    assert insert_xp_event(conn, e1) is False

    # Second distinct event
    e2 = XpEvent(
        id="xp_02",
        user_id="user_alice",
        rule_code="experiment_completed",
        points=40,
        ref_kind="experiment",
        ref_id="exp_chk",
        period_day="2026-09-07",
        created_at="2026-09-07T18:00:00Z",
    )
    assert insert_xp_event(conn, e2) is True

    assert get_user_xp_total(conn, "user_alice") == 55
    assert get_user_xp_for_day(conn, "user_alice", "2026-09-07") == 55
    assert get_user_xp_for_day(conn, "user_alice", "2026-09-08") == 0

    # UPDATE trigger blocks modification (append-only)
    with pytest.raises(
        sqlite3.IntegrityError, match="xp_events is append-only, UPDATE is not allowed"
    ):
        conn.execute("UPDATE xp_events SET points = 100 WHERE id = 'xp_01'")

    # DELETE trigger blocks removal (append-only)
    with pytest.raises(
        sqlite3.IntegrityError, match="xp_events is append-only, DELETE is not allowed"
    ):
        conn.execute("DELETE FROM xp_events WHERE id = 'xp_01'")


def test_badge_awards_uniqueness(conn):
    """Badges are awarded once per user with evidence."""
    b1 = BadgeAward(
        id="ba_01",
        user_id="user_alice",
        badge_code="first_experiment_reviewed",
        awarded_at="2026-09-16T12:00:00Z",
        evidence_json={"experiment_id": "exp_chk"},
    )
    assert insert_badge_award(conn, b1) is True
    assert has_badge(conn, "user_alice", "first_experiment_reviewed") is True

    # Duplicate award is ignored
    assert insert_badge_award(conn, b1) is False
    assert len(list_badge_awards(conn, "user_alice")) == 1


def test_streak_freezes_repo(conn):
    """Streak freeze records persist for grace days and declared exceptions."""
    sf = StreakFreeze(
        id="sf_01",
        user_id="user_alice",
        streak_code="checkin_streak",
        from_date="2026-09-10",
        to_date="2026-09-12",
        reason="exception",
        created_at="2026-09-10T00:00:00Z",
    )
    insert_streak_freeze(conn, sf)
    freezes = list_streak_freezes(conn, "user_alice", "checkin_streak")
    assert len(freezes) == 1
    assert freezes[0].reason == "exception"


def test_migration_preserves_existing_phase3_data():
    """Migrating an existing Phase 3 database preserves all existing tables and data."""
    c = get_connection(":memory:", check_same_thread=False)
    # Apply up to migration 004
    init_db(c)

    # Insert a user and goal
    u = User(id="user_test_preserve", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u)
    g = Goal(
        id="goal_preserve",
        user_id="user_test_preserve",
        name="Emergency",
        kind="emergency_fund",
        target_paise=50000000,
        current_paise=20000000,
        priority=1,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    insert_goal(c, g)

    # Calling init_db again is idempotent and preserves user and goal
    init_db(c)
    row = c.execute("SELECT name, target_paise FROM goals WHERE id = 'goal_preserve'").fetchone()
    assert row["name"] == "Emergency"
    assert row["target_paise"] == 50000000

    # Phase 4 table exists
    c.execute("SELECT COUNT(*) FROM experiments").fetchone()
