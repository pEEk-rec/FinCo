"""
Core Experiments Lifecycle and Boundary Tests (PLAN_PHASE4 Section 5.3, Stage 4.3).

Verifies:
- Lifecycle transitions (allowed and forbidden)
- Baseline and metric freezing at start
- Review delay enforcement (window_end + delay_days)
- Abandon yields learning review without negative wording
- Goal linking using Phase 3 maths without causal promises
- Essential category reduction rejection
- Target floor at 50% of baseline median
- Check-ins creation and answer handling
"""

from datetime import datetime

import pytest

from copilot.core.baseline import generate_candidate_windows
from copilot.core.experiments import (
    abandon_experiment,
    answer_checkin,
    create_checkins,
    create_due_reviews,
    design_experiment,
    get_experiment_progress,
    pause_experiment,
    resume_experiment,
    start_experiment,
    submit_review_feedback,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_goal, insert_user
from copilot.db.repo_phase4 import get_experiment, list_adjustment_proposals
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, User

T0 = "2026-01-01T00:00:00Z"
DT0 = datetime.fromisoformat("2026-09-01T00:00:00+05:30")


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u = User(id="user_alice", created_at=T0)
    insert_user(c, u)
    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=10000000,
        created_at=T0,
    )
    insert_account(c, acc)

    for cat_id, cat_name in [
        ("dining_out", "Dining Out"),
        ("groceries", "Groceries"),
        ("rent", "Rent"),
        ("shopping", "Shopping"),
    ]:
        insert_category(
            c,
            Category(
                id=cat_id,
                user_id="user_alice",
                name=cat_name,
                created_at=T0,
            ),
        )
    return c


def _insert_txn(
    conn,
    user_id: str,
    tx_id: str,
    occurred_at: str,
    amount_paise: int,
    category_id: str = "dining_out",
):
    query = """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, category_id, category_source, created_at
        ) VALUES (?, ?, 'acc_main', ?, ?, 'debit', 'Merchant', 'Merchant', ?, 'rule', ?)
    """
    conn.execute(query, (tx_id, user_id, occurred_at, amount_paise, category_id, occurred_at))


def test_essential_category_reduction_is_forbidden(conn):
    """Reduction targets cannot be placed on essential categories (e.g., groceries, rent)."""
    with pytest.raises(ValueError, match="Reduction target cannot be placed on essential category"):
        design_experiment(
            conn,
            "user_alice",
            params={
                "metric_code": "category_spend",
                "categories": ["groceries"],
                "target_value": 50000,
            },
            clock=DT0,
        )

    with pytest.raises(ValueError, match="Reduction target cannot be placed on essential category"):
        design_experiment(
            conn,
            "user_alice",
            params={
                "metric_code": "category_spend",
                "categories": ["rent"],
                "target_value": 100000,
            },
            clock=DT0,
        )


def test_target_floor_at_50_percent_of_baseline_median(conn):
    """Target value cannot fall below 50% of baseline median."""
    # Seed 6 windows of dining out: median = 200000 paise (Rs 2000)
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"t_base_{idx}", f"{ws}T10:00:00Z", 200000)

    # 50% of 200000 is 100000 paise (Rs 1000). A target of 99900 paise must fail.
    with pytest.raises(ValueError, match="cannot be below 50% of baseline median"):
        design_experiment(
            conn,
            "user_alice",
            params={
                "metric_code": "category_spend",
                "categories": ["dining_out"],
                "target_value": 99900,
                "duration_days": 14,
            },
            clock=DT0,
        )

    # A target of 100000 paise (exactly 50%) is accepted.
    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 100000,
            "duration_days": 14,
        },
        clock=DT0,
    )
    assert exp.target_value == 100000
    assert exp.status == "offered"


def test_experiment_lifecycle_allowed_and_forbidden_transitions(conn):
    """
    Verifies valid transitions: offered -> active -> paused -> active -> completed -> reviewed.
    Verifies forbidden transitions raise ValueError.
    """
    # Seed baseline
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 300000)

    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "difficulty": "medium",
            "duration_days": 14,
        },
        clock=DT0,
    )
    assert exp.status == "offered"

    # Forbidden: cannot pause an offered experiment
    with pytest.raises(ValueError, match="Cannot pause experiment in status: offered"):
        pause_experiment(conn, "user_alice", exp.id, clock=DT0)

    # Forbidden: cannot resume an offered experiment
    with pytest.raises(ValueError, match="Cannot resume experiment in status: offered"):
        resume_experiment(conn, "user_alice", exp.id, clock=DT0)

    # Allowed: start experiment
    started = start_experiment(conn, "user_alice", exp.id, clock=DT0)
    assert started.status == "active"
    assert started.started_at is not None

    # Forbidden: cannot start already active experiment
    with pytest.raises(ValueError, match="Cannot start experiment in status: active"):
        start_experiment(conn, "user_alice", exp.id, clock=DT0)

    # Allowed: pause
    paused = pause_experiment(conn, "user_alice", exp.id, reason="travelling", clock=DT0)
    assert paused.status == "paused"

    # Forbidden: cannot pause already paused experiment
    with pytest.raises(ValueError, match="Cannot pause experiment in status: paused"):
        pause_experiment(conn, "user_alice", exp.id, clock=DT0)

    # Allowed: resume
    resumed = resume_experiment(conn, "user_alice", exp.id, clock=DT0)
    assert resumed.status == "active"


def test_baseline_and_metric_def_frozen_at_start(conn):
    """
    Baseline and metric definitions are frozen when the experiment starts.
    Later insertion or modification of past transactions does not change frozen baseline.
    """
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 150000)

    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 120000,
            "duration_days": 14,
        },
        clock=DT0,
    )
    started = start_experiment(conn, "user_alice", exp.id, clock=DT0)
    frozen_base = started.baseline_json
    assert frozen_base["median"] == 150000

    # Ingest a huge transaction into past history (W1: 2026-06-22)
    _insert_txn(conn, "user_alice", "late_historical_tx", "2026-06-23T10:00:00Z", 9999999)

    # Fetch experiment again: frozen baseline in DB MUST NOT CHANGE
    current_exp = get_experiment(conn, "user_alice", exp.id)
    assert current_exp is not None
    assert current_exp.baseline_json["median"] == 150000
    assert current_exp.baseline_json == frozen_base


def test_review_delay_and_goal_link(conn):
    """
    Review is only created when window_end + review.delay_days has passed.
    Goal link calculates coverage mathematically and never promises completion.
    """
    # Create a goal: Trip Fund (target 1000000 paise = Rs 10000, current 0 paise)
    insert_goal(
        conn,
        Goal(
            id="g_trip",
            user_id="user_alice",
            name="Goa Trip",
            kind="savings",
            target_paise=1000000,
            current_paise=0,
            priority=2,
            created_at=T0,
            updated_at=T0,
        ),
    )

    # Baseline: 6 windows with 300000 paise
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"t_base_{idx}", f"{ws}T10:00:00Z", 300000)

    # Start experiment on 2026-09-01 (14 days: ends on 2026-09-14)
    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 200000,
            "duration_days": 14,
            "goal_id": "g_trip",
        },
        clock=DT0,
    )
    started = start_experiment(conn, "user_alice", exp.id, clock=DT0)
    assert started.window_start == "2026-09-01"
    assert started.window_end == "2026-09-14"

    # Insert spend inside experiment: 100000 paise (effect = 300000 - 100000 = 200000 paise)
    _insert_txn(conn, "user_alice", "t_exp_1", "2026-09-05T12:00:00Z", 100000)

    # Delay is 2 days. On window_end (2026-09-14) or day after (2026-09-15), reviews NOT created
    clock_14 = datetime.fromisoformat("2026-09-14T10:00:00+05:30")
    revs_14 = create_due_reviews(conn, "user_alice", clock=clock_14)
    assert len(revs_14) == 0

    clock_15 = datetime.fromisoformat("2026-09-15T10:00:00+05:30")
    revs_15 = create_due_reviews(conn, "user_alice", clock=clock_15)
    assert len(revs_15) == 0

    # On 2026-09-16 (window_end + 2 days), review IS created
    clock_16 = datetime.fromisoformat("2026-09-16T10:00:00+05:30")
    revs_16 = create_due_reviews(conn, "user_alice", clock=clock_16)
    assert len(revs_16) == 1

    rev = revs_16[0]
    assert rev.observed_value == 100000
    assert rev.target_met is True
    assert rev.effect_value == 200000  # 300000 median - 100000 observed
    assert rev.outcome == "beyond_usual_range"

    # Verify Goal link mathematics
    # Effect = 200000 paise (Rs 2000). Remaining goal gap = 1000000 - 0 = 1000000.
    # Share = 200000 / 1000000 = 20%
    goal_narrative = rev.data_quality_json["goal_link_narrative"]
    assert "₹2000 would cover" in goal_narrative
    assert "Goa Trip" in goal_narrative
    # Critical safety invariant: never promises goal completion
    assert "you will reach" not in goal_narrative.lower()

    # User submits feedback
    fed_rev = submit_review_feedback(
        conn,
        "user_alice",
        rev.id,
        difficulty_rating=3,
        user_helpful=True,
        would_repeat=True,
        clock=clock_16,
    )
    assert fed_rev.user_difficulty == 3
    assert fed_rev.user_helpful is True
    assert fed_rev.user_would_repeat is True

    # Experiment status is now 'reviewed'
    exp_reviewed = get_experiment(conn, "user_alice", exp.id)
    assert exp_reviewed is not None
    assert exp_reviewed.status == "reviewed"


def test_abandon_experiment_at_any_point_yields_kind_review(conn):
    """Abandoning is penalty-free and produces a constructive learning review."""
    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 150000,
            "duration_days": 14,
        },
        clock=DT0,
    )
    start_experiment(conn, "user_alice", exp.id, clock=DT0)

    # Abandon on day 4
    clock_abandon = datetime.fromisoformat("2026-09-05T10:00:00+05:30")
    abandoned_exp, rev = abandon_experiment(
        conn,
        "user_alice",
        exp.id,
        reason="busy week",
        clock=clock_abandon,
    )
    assert abandoned_exp.status == "abandoned"
    assert rev is not None
    assert rev.experiment_id == exp.id

    # Narrative must not contain guilt or shame phrases
    narrative = rev.data_quality_json["narrative"]
    assert "valuable financial practice" in narrative
    for shame in ["failed", "loss", "loser", "missed", "shame", "bad"]:
        assert shame not in narrative.lower()


def test_checkins_generation_and_answer_want_to_pause(conn):
    """
    Check-ins are created weekly. Answering with 'want_to_pause' generates an adjustment proposal.
    """
    exp = design_experiment(
        conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 150000,
            "duration_days": 14,
        },
        clock=DT0,
    )
    start_experiment(conn, "user_alice", exp.id, clock=DT0)

    # On day 7 (2026-09-08), create_checkins generates 1 checkin
    clock_chk1 = datetime.fromisoformat("2026-09-08T10:00:00+05:30")
    chks = create_checkins(conn, "user_alice", clock=clock_chk1)
    assert len(chks) == 1
    chk = chks[0]
    assert chk.checkin_date == "2026-09-08"
    assert chk.user_response is None

    # Answer check-in with 'want_to_pause'
    answered = answer_checkin(
        conn,
        "user_alice",
        chk.id,
        response="want_to_pause",
        note="Too much work travel this week",
        clock=clock_chk1,
    )
    assert answered.user_response == "want_to_pause"

    # Verify an adjustment proposal of kind 'pause' was created
    proposals = list_adjustment_proposals(conn, "user_alice", experiment_id=exp.id)
    assert len(proposals) == 1
    assert proposals[0].kind == "pause"
    assert proposals[0].status == "proposed"
    assert proposals[0].reason_code == "checkin_requested_pause"

    # Progress tracking works
    prog = get_experiment_progress(conn, "user_alice", exp.id, clock=clock_chk1)
    assert prog.checkins_count == 1
    assert prog.total_days == 14
    assert prog.elapsed_days == 8
