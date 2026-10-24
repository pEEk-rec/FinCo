"""
Unit tests for Stage 4.7: Progress, XP rules, allowlist enforcement, badges, and copy safety.
(PLAN_PHASE4 Section 5.7, 5.8 & Stage 4.7)

Tests:
1. Static check rejects forbidden rules (essential categories, skipping commitments, borrowing).
2. Idempotent awarding: duplicate attempts return None and write exactly 1 row.
3. Daily cap boundary: points capped at 100/day, XP never decreases.
4. Abandoned-and-reviewed experiment earns learning XP (experiment_reviewed_abandoned).
5. Integrity confirmation gate: target_met XP blocked if confirmation_required and not user_confirmed.
6. Neutral level calculations: neutral names, exact thresholds, no wealth/shame framing.
7. Badge predicates: deterministic awarding with evidence, idempotent.
8. Copy scanner: rejects pressure phrases, forbidden encouragements, shame terms, and social comparison.
9. Progress summary: aggregated representation across levels, badges, bests, and streaks.
"""

from datetime import datetime

import pytest

from copilot.config.phase4 import (
    ForbiddenRulesConfig,
    LevelsConfig,
    RewardsConfig,
    RewardsXpConfig,
    XpRuleConfig,
    load_rewards_config,
)
from copilot.core.rewards import (
    award_experiment_outcome_xp,
    award_xp,
    calculate_user_level,
    can_award_target_met_xp,
    check_and_award_badges,
    get_user_progress,
    scan_copy_safety,
    validate_reward_rules,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import (
    get_user_xp_for_day,
    get_user_xp_total,
    insert_experiment,
    insert_experiment_review,
    list_badge_awards,
    list_xp_events,
)
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import (
    Experiment,
    ExperimentReview,
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


def make_experiment(id: str, status: str = "completed") -> Experiment:
    return Experiment(
        id=id,
        user_id="u_alice",
        title="Dining Reduction",
        hypothesis_json={
            "intervention": "cook",
            "metric": "dining_spend",
            "direction": "lower",
            "target": 50000,
        },
        metric_def_json={"metric": "dining_spend", "categories": ["dining"]},
        params_json={},
        difficulty="moderate",
        window_start="2026-08-01",
        window_end="2026-08-15",
        baseline_json={
            "k": 4,
            "window_values": [60000],
            "median": 60000,
            "low": 50000,
            "high": 70000,
        },
        target_value=50000,
        status=status,
        origin="user",
        created_at=T0,
    )


def make_review(
    id: str,
    experiment_id: str,
    target_met: bool = True,
    confirmation_required: bool = False,
    user_confirmed: bool = False,
    user_helpful: bool | None = None,
    user_difficulty: int | None = None,
) -> ExperimentReview:
    integ = {}
    if confirmation_required:
        integ["confirmation_required"] = True
    if user_confirmed:
        integ["user_confirmed"] = True

    return ExperimentReview(
        id=id,
        user_id="u_alice",
        experiment_id=experiment_id,
        observed_value=45000,
        outcome="beyond_usual_range",
        rank_p_bp=9000,
        effect_value=-15000,
        target_met=target_met,
        integrity_json=integ,
        data_quality_json={"coverage": 100},
        user_difficulty=user_difficulty,
        user_helpful=user_helpful,
        created_at=T0,
    )


# -------------------------------------------------------------------------------------------------
# 1. Static Rule Validation
# -------------------------------------------------------------------------------------------------
def test_static_validation_approved_config_passes():
    """Default rewards configuration passes static validation with zero forbidden references."""
    cfg = load_rewards_config()
    validate_reward_rules(cfg)


def test_static_validation_rejects_essential_category_rule():
    """Rules targeting essential category cuts or skipping commitments must be rejected."""
    with pytest.raises(ValueError, match="forbidden term 'rent'"):
        RewardsConfig(
            rules={
                "cut_rent": XpRuleConfig(
                    points=50, max_daily_share=50, description="Reward for reducing rent payments"
                ),
            },
            levels=LevelsConfig(thresholds=[0, 100], names=["Beginner", "Pro"]),
            xp=RewardsXpConfig(daily_cap=100),
            forbidden_metrics_and_categories=ForbiddenRulesConfig(
                metrics=["loan_amount"],
                categories=["rent", "groceries", "health", "utilities", "emis"],
            ),
        )


def test_static_validation_rejects_borrowing_or_trading_rules():
    """Rules encouraging borrowing or trading must be rejected."""
    with pytest.raises(ValueError, match="encourages risky behaviour"):
        validate_reward_rules(
            RewardsConfig.model_construct(
                rules={
                    "take_credit": XpRuleConfig.model_construct(
                        points=50, max_daily_share=50, description="Bonus for borrowing short term"
                    ),
                },
                levels=LevelsConfig.model_construct(thresholds=[0, 100], names=["Beginner", "Pro"]),
                xp=RewardsXpConfig.model_construct(daily_cap=100),
                forbidden_metrics_and_categories=ForbiddenRulesConfig.model_construct(
                    metrics=["loan_amount"],
                    categories=["rent", "emis"],
                ),
            )
        )


# -------------------------------------------------------------------------------------------------
# 2. Idempotency & Daily Cap Boundary
# -------------------------------------------------------------------------------------------------
def test_award_xp_idempotent(conn):
    """Awarding twice for the exact same event writes exactly one row and returns None second time."""
    ev1 = award_xp(
        conn,
        user_id="u_alice",
        rule_code="checkin_answered",
        ref_kind="checkin",
        ref_id="chk_001",
        period_day="2026-09-01",
    )
    assert ev1 is not None
    assert ev1.points == 15

    # Second attempt with same ref_kind and ref_id
    ev2 = award_xp(
        conn,
        user_id="u_alice",
        rule_code="checkin_answered",
        ref_kind="checkin",
        ref_id="chk_001",
        period_day="2026-09-01",
    )
    assert ev2 is None

    # Total rows in xp_events is exactly 1
    events = list_xp_events(conn, "u_alice")
    assert len(events) == 1
    assert get_user_xp_total(conn, "u_alice") == 15


def test_award_xp_daily_cap(conn):
    """Daily cap (100) strictly bounds awarded points and floors remaining points."""
    # 1. Award 40 pts (experiment_completed)
    ev1 = award_xp(conn, "u_alice", "experiment_completed", "experiment", "exp_1", "2026-09-01")
    assert ev1 is not None and ev1.points == 40

    # 2. Award 40 pts (experiment_completed on another experiment)
    ev2 = award_xp(conn, "u_alice", "experiment_completed", "experiment", "exp_2", "2026-09-01")
    assert ev2 is not None and ev2.points == 40
    assert get_user_xp_for_day(conn, "u_alice", "2026-09-01") == 80

    # 3. Award 30 pts (target_met) -> Only 20 pts remaining in daily cap
    ev3 = award_xp(conn, "u_alice", "target_met", "experiment", "exp_1", "2026-09-01")
    assert ev3 is not None
    assert ev3.points == 20  # Clamped to 20
    assert get_user_xp_for_day(conn, "u_alice", "2026-09-01") == 100

    # 4. Subsequent awards on the same day yield None (cap hit)
    ev4 = award_xp(conn, "u_alice", "checkin_answered", "checkin", "chk_2", "2026-09-01")
    assert ev4 is None
    assert get_user_xp_for_day(conn, "u_alice", "2026-09-01") == 100
    assert get_user_xp_total(conn, "u_alice") == 100

    # 5. Next day awards succeed normally
    ev_next = award_xp(conn, "u_alice", "checkin_answered", "checkin", "chk_3", "2026-09-02")
    assert ev_next is not None and ev_next.points == 15
    assert get_user_xp_for_day(conn, "u_alice", "2026-09-02") == 15
    assert get_user_xp_total(conn, "u_alice") == 115


# -------------------------------------------------------------------------------------------------
# 3. Experiment Outcome XP & Integrity Gate
# -------------------------------------------------------------------------------------------------
def test_abandoned_and_reviewed_earns_learning_xp(conn):
    """Finishing an abandoned-and-reviewed experiment earns learning XP (20 pts)."""
    exp = make_experiment("exp_abandoned", status="abandoned")
    insert_experiment(conn, exp)

    # Before review: 0 XP
    awarded_pre = award_experiment_outcome_xp(conn, "u_alice", "exp_abandoned", DT0)
    assert len(awarded_pre) == 0

    # Insert review
    rev = make_review("rev_abandoned", "exp_abandoned", target_met=False, user_helpful=True)
    insert_experiment_review(conn, rev)

    # After review: earns learning XP
    awarded_post = award_experiment_outcome_xp(conn, "u_alice", "exp_abandoned", DT0)
    assert len(awarded_post) == 1
    assert awarded_post[0].rule_code == "experiment_reviewed_abandoned"
    assert awarded_post[0].points == 20


def test_integrity_gate_blocks_target_met_xp_until_confirmed(conn):
    """If confirmation_required is True, target_met XP is blocked until user_confirmed is True."""
    exp = make_experiment("exp_integ", status="completed")
    insert_experiment(conn, exp)

    # Review with target_met=True but confirmation_required=True and user_confirmed missing
    rev_unconfirmed = make_review(
        "rev_integ", "exp_integ", target_met=True, confirmation_required=True
    )
    insert_experiment_review(conn, rev_unconfirmed)

    # Check can_award_target_met_xp
    assert not can_award_target_met_xp(conn, "u_alice", "exp_integ")

    # award_experiment_outcome_xp awards experiment_completed (40) but NOT target_met (30)
    awarded = award_experiment_outcome_xp(conn, "u_alice", "exp_integ", DT0)
    assert len(awarded) == 1
    assert awarded[0].rule_code == "experiment_completed"

    # Now simulate user confirmation by updating review integrity_json
    conn.execute(
        """
        UPDATE experiment_reviews
        SET integrity_json = json_set(integrity_json, '$.user_confirmed', 1)
        WHERE id = 'rev_integ'
        """
    )
    conn.commit()

    assert can_award_target_met_xp(conn, "u_alice", "exp_integ")

    # Calling again awards the target_met XP
    awarded_second = award_experiment_outcome_xp(conn, "u_alice", "exp_integ", DT0)
    assert len(awarded_second) == 1
    assert awarded_second[0].rule_code == "target_met"
    assert awarded_second[0].points == 30


# -------------------------------------------------------------------------------------------------
# 4. Neutral Level Calculations
# -------------------------------------------------------------------------------------------------
def test_calculate_user_level_neutral_names():
    """Verify level indices, neutral titles, and next level progress math."""
    # Level 1: 0 - 99 XP
    lvl, name, in_lvl, next_xp = calculate_user_level(0)
    assert lvl == 1 and name == "Level 1 - Starter" and in_lvl == 0 and next_xp == 100

    lvl, name, in_lvl, next_xp = calculate_user_level(75)
    assert lvl == 1 and name == "Level 1 - Starter" and in_lvl == 75 and next_xp == 100

    # Level 2: 100 - 249 XP
    lvl, name, in_lvl, next_xp = calculate_user_level(100)
    assert lvl == 2 and name == "Level 2 - Explorer" and in_lvl == 0 and next_xp == 150

    # Level 3: 250 - 499 XP
    lvl, name, in_lvl, next_xp = calculate_user_level(250)
    assert lvl == 3 and name == "Level 3 - Builder" and in_lvl == 0 and next_xp == 250

    # Level 8: 5000+ XP (Max level)
    lvl, name, in_lvl, next_xp = calculate_user_level(6000)
    assert lvl == 8 and name == "Level 8 - Anchor" and in_lvl == 1000 and next_xp is None


# -------------------------------------------------------------------------------------------------
# 5. Badge Predicates & Evidence
# -------------------------------------------------------------------------------------------------
def test_badges_awarded_with_evidence(conn):
    """Test deterministic predicates for badges and evidence recording."""
    # Initially no badges
    newly = check_and_award_badges(conn, "u_alice", DT0)
    assert len(newly) == 0

    # 1. first_experiment_reviewed
    exp = make_experiment("exp_b1", status="completed")
    insert_experiment(conn, exp)
    rev = make_review("rev_b1", "exp_b1", target_met=True)
    insert_experiment_review(conn, rev)

    b1 = check_and_award_badges(conn, "u_alice", DT0)
    b_codes = [b.badge_code for b in b1]
    assert "first_experiment_reviewed" in b_codes
    ev_award = next(b for b in b1 if b.badge_code == "first_experiment_reviewed")
    assert ev_award.evidence_json["experiment_id"] == "exp_b1"

    # Calling again is idempotent (no duplicate badges)
    b1_dup = check_and_award_badges(conn, "u_alice", DT0)
    assert len(b1_dup) == 0

    # 2. emergency_anchor
    conn.execute(
        """
        INSERT INTO goals (id, user_id, name, kind, target_paise, current_paise, priority, status, created_at, updated_at)
        VALUES ('g_ef', 'u_alice', 'Emergency Fund', 'emergency_fund', 5000000, 5000000, 1, 'active', ?, ?)
        """,
        (T0, T0),
    )
    conn.commit()

    b2 = check_and_award_badges(conn, "u_alice", DT0)
    assert any(b.badge_code == "emergency_anchor" for b in b2)

    # 3. goal_finisher
    conn.execute(
        """
        INSERT INTO goals (id, user_id, name, kind, target_paise, current_paise, priority, status, created_at, updated_at)
        VALUES ('g_vacay', 'u_alice', 'Trip', 'savings', 2000000, 2000000, 2, 'done', ?, ?)
        """,
        (T0, T0),
    )
    conn.commit()

    b3 = check_and_award_badges(conn, "u_alice", DT0)
    assert any(b.badge_code == "goal_finisher" for b in b3)

    # All badges in database
    all_b = list_badge_awards(conn, "u_alice")
    assert len(all_b) >= 3


# -------------------------------------------------------------------------------------------------
# 6. Copy Safety Scanner
# -------------------------------------------------------------------------------------------------
def test_copy_scanner_safe_text_passes():
    """Supportive and neutral copy passes without error."""
    clean = "You maintained a 5-day habit. Great work reflecting on your spending!"
    scan_copy_safety(clean)


def test_copy_scanner_rejects_pressure_phrases():
    """Urgency or pressure words must trigger an error."""
    with pytest.raises(ValueError, match="Forbidden pressure phrase found"):
        scan_copy_safety("Hurry up, only 2 hours left before you lose your reward!")

    with pytest.raises(ValueError, match="Forbidden pressure phrase found"):
        scan_copy_safety("Act now to save your weekly streak!")


def test_copy_scanner_rejects_forbidden_encouragements():
    """Encouraging skipping essentials or reducing rent must trigger an error."""
    with pytest.raises(ValueError, match="Forbidden encouragement phrase found"):
        scan_copy_safety("You can hit your target by skip rent this month.")

    with pytest.raises(ValueError, match="Forbidden encouragement phrase found"):
        scan_copy_safety("Try skip groceries to save money.")


def test_copy_scanner_rejects_social_comparison_and_shame():
    """Comparisons with other people and shame terms must trigger errors."""
    with pytest.raises(ValueError, match="Forbidden social comparison term found"):
        scan_copy_safety("You saved more than other users.")

    with pytest.raises(ValueError, match="Forbidden shame term found"):
        scan_copy_safety("You broke streak yesterday.")


# -------------------------------------------------------------------------------------------------
# 7. Progress Aggregation
# -------------------------------------------------------------------------------------------------
def test_get_user_progress(conn):
    """get_user_progress aggregates XP, level, badges, personal bests, and streaks."""
    # Award some XP
    award_xp(conn, "u_alice", "checkin_answered", "checkin", "c1", "2026-09-01")
    award_xp(conn, "u_alice", "checkin_answered", "checkin", "c2", "2026-09-01")

    progress = get_user_progress(conn, "u_alice", DT0)
    assert progress.total_xp == 30
    assert progress.level_number == 1
    assert progress.level_name == "Level 1 - Starter"
    assert progress.xp_in_level == 30
    assert progress.xp_for_next_level == 100
    assert isinstance(progress.badges, list)
    assert isinstance(progress.personal_bests, list)
    assert isinstance(progress.active_streaks, dict)
