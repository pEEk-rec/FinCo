"""
Unit and property tests for Stage 4.4: Challenge templates, personalisation, triggers, and offers.
(PLAN_PHASE4 Section 5.4 & Stage 4.4)
"""

import random
import sqlite3
from datetime import datetime, timedelta

import pytest

from copilot.core.baseline import generate_candidate_windows
from copilot.core.challenges import (
    CandidateOffer,
    LLMChallengeProposalBatch,
    LLMChallengeSpec,
    decompose_goal_gap,
    evaluate_triggers,
    filter_safe_candidates,
    fit_candidate_challenge,
    generate_challenge_offers,
    validate_llm_spec,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_goal, insert_user
from copilot.db.repo_phase4 import insert_experiment
from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import Experiment

T0 = "2026-01-01T00:00:00Z"
DT0 = datetime(2026, 9, 1, 10, 0, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="user_alice", created_at=T0))
    insert_user(c, User(id="user_bob", created_at=T0))
    insert_account(
        c,
        Account(id="acc_a", user_id="user_alice", name="Checking", created_at=T0),
    )
    insert_account(
        c,
        Account(id="acc_b", user_id="user_bob", name="Bob Checking", created_at=T0),
    )
    # Alice categories
    insert_category(c, Category(id="dining_out", user_id="user_alice", name="Dining Out", created_at=T0))
    insert_category(c, Category(id="food_delivery", user_id="user_alice", name="Food Delivery", created_at=T0))
    insert_category(c, Category(id="shopping", user_id="user_alice", name="Shopping", created_at=T0))
    insert_category(c, Category(id="entertainment", user_id="user_alice", name="Entertainment", created_at=T0))
    insert_category(c, Category(id="rent", user_id="user_alice", name="Rent", created_at=T0))
    insert_category(c, Category(id="groceries", user_id="user_alice", name="Groceries", created_at=T0))

    # Bob category
    insert_category(c, Category(id="secret_category", user_id="user_bob", name="Bob Secret", created_at=T0))

    yield c
    c.close()


def _insert_txn(
    conn: sqlite3.Connection,
    user_id: str,
    tx_id: str,
    occurred_at: str,
    amount_paise: int,
    cat: str = "dining_out",
    direction: str = "debit",
    needs_review: bool = False,
):
    acc_id = "acc_a" if user_id == "user_alice" else "acc_b"
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            category_id, merchant_raw, description, category_source,
            needs_review, excluded_from_spend, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Merchant', 'desc', 'user', ?, 0, ?)
        """,
        (tx_id, user_id, acc_id, occurred_at, amount_paise, direction, cat, 1 if needs_review else 0, T0),
    )


def test_scripted_fake_llm_specs_rejected_and_audited(conn):
    """
    Fake-LLM specs naming an essential category, an unknown metric,
    another user's category, or an out-of-range duration are rejected and audited.
    """
    user_cats = {"dining_out", "food_delivery", "shopping", "entertainment", "rent", "groceries"}
    essential_cats = {"rent", "food_and_groceries", "healthcare", "utilities", "groceries"}

    # 1. Essential category
    s1 = LLMChallengeSpec(
        metric_code="category_spend",
        categories=["rent"],
        duration_days=14,
        difficulty="medium",
        title="Cut Rent",
        rationale="Save on rent",
    )
    ok1, err1 = validate_llm_spec(s1, user_cats, essential_cats)
    assert not ok1
    assert "essential_category_targeted" in err1

    # 2. Unknown metric
    s2 = LLMChallengeSpec(
        metric_code="crypto_yield",
        categories=["dining_out"],
        duration_days=14,
        difficulty="medium",
        title="Crypto Test",
        rationale="High returns",
    )
    ok2, err2 = validate_llm_spec(s2, user_cats, essential_cats)
    assert not ok2
    assert "unknown_metric" in err2

    # 3. Another user's category
    s3 = LLMChallengeSpec(
        metric_code="category_spend",
        categories=["secret_category"],
        duration_days=14,
        difficulty="medium",
        title="Bob's Category",
        rationale="Cross-tenant test",
    )
    ok3, err3 = validate_llm_spec(s3, user_cats, essential_cats)
    assert not ok3
    assert "unknown_or_cross_user_category" in err3

    # 4. Out-of-range duration (< 7 days or > 56 days)
    s4 = LLMChallengeSpec(
        metric_code="category_spend",
        categories=["dining_out"],
        duration_days=5,
        difficulty="medium",
        title="Too Short",
        rationale="5 days only",
    )
    ok4, err4 = validate_llm_spec(s4, user_cats, essential_cats)
    assert not ok4
    assert "duration_out_of_range" in err4

    # 5. End-to-end audit verification via generate_challenge_offers
    bad_batch = LLMChallengeProposalBatch(specs=[s1, s2, s3, s4])
    fake_llm = FakeLLMClient(replies=[bad_batch.model_dump_json()])
    # offers need some spending on record to be based on
    _insert_txn(conn, "user_alice", "t_any", "2026-08-20T10:00:00Z", 1000)

    offers = generate_challenge_offers(
        conn=conn,
        user_id="user_alice",
        week_start="2026-09-01",
        llm_client=fake_llm,
        clock=DT0,
        run_id="run_test_audit",
    )

    # All bad specs rejected, templates fallback will populate offers
    assert all(o.status == "shown" for o in offers)

    # Check audit events table for challenge_spec_rejected
    audits = conn.execute(
        "SELECT * FROM audit_events WHERE user_id = 'user_alice' AND event_type = 'challenge_spec_rejected'"
    ).fetchall()
    assert len(audits) == 4
    reasons = [a["reason"] for a in audits]
    assert any("essential_category_targeted" in r for r in reasons)
    assert any("unknown_metric" in r for r in reasons)
    assert any("unknown_or_cross_user_category" in r for r in reasons)
    assert any("duration_out_of_range" in r for r in reasons)


def test_numbers_inside_llm_specs_are_ignored_and_replaced_by_computed_targets(conn):
    """
    LLM may hallucinate or propose numbers (e.g. proposed_target=123).
    The system strictly ignores them and computes targets from historical baseline.
    """
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 200000, cat="dining_out")

    # LLM hallucinates an arbitrary number 123
    spec = LLMChallengeSpec(
        metric_code="category_spend",
        categories=["dining_out"],
        duration_days=14,
        difficulty="medium",
        title="Mindful Dining",
        rationale="Cook more at home",
        proposed_target=123,
    )
    batch = LLMChallengeProposalBatch(specs=[spec])
    fake_llm = FakeLLMClient(replies=[batch.model_dump_json()])

    offers = generate_challenge_offers(
        conn=conn,
        user_id="user_alice",
        week_start="2026-09-01",
        llm_client=fake_llm,
        clock=DT0,
    )
    assert offers
    llm_offer = next((o for o in offers if o.params_json.get("title") == "Mindful Dining"), None)
    assert llm_offer is not None

    # Baseline median is 200000 paise. Medium difficulty = 20% reduction = 40000 paise.
    # Target value = 160000 paise (₹1600), NOT 123!
    assert llm_offer.params_json["target_value"] == 160000
    assert llm_offer.params_json["target_value"] != 123


def test_templates_produce_valid_offers_with_llm_unavailable(conn):
    """With LLM client set to None or failing, configured templates still produce valid offers."""
    # Insert transactions in 7-day windows (matching weekday_home_cooking duration=7)
    # 2026-09-01 is a Tuesday; 7-day windows go back aligned to the same weekday.
    # Insert one per window to build a baseline with median > 0.
    windows_7 = generate_candidate_windows("2026-09-01", duration_days=7, k=6)
    for idx, (ws, _we) in enumerate(windows_7, 1):
        # Insert on a Tuesday (window start IS a Tuesday for 2026-09-01 alignment)
        _insert_txn(conn, "user_alice", f"tb7_{idx}", f"{ws}T10:00:00Z", 300000, cat="dining_out")

    # Ask for all the safe candidates, so the check is about which ones are valid, not which
    # of them the seeded policy happens to pick this week.
    offers = generate_challenge_offers(
        conn=conn,
        user_id="user_alice",
        week_start="2026-09-01",
        llm_client=None,
        clock=DT0,
        max_offers=20,
    )
    assert len(offers) > 0
    assert all(o.status == "shown" for o in offers)
    # weekday_home_cooking is a valid candidate here (baseline_median=300000)
    assert any(o.template_code == "weekday_home_cooking" for o in offers)



def test_triggers_fire_on_injected_patterns_and_stay_silent_otherwise(conn):
    """Each trigger fires strictly when its condition is met and remains silent otherwise."""
    # 1. Clean state -> silent
    clean_triggers = evaluate_triggers(conn, "user_alice", clock=DT0)
    assert len(clean_triggers) == 0

    # 2. Inject unreviewed transactions >= 5 -> many_open_reviews
    for i in range(5):
        _insert_txn(conn, "user_alice", f"unrev_{i}", "2026-08-15T10:00:00Z", 1000, needs_review=True)
    t_rev = evaluate_triggers(conn, "user_alice", clock=DT0)
    assert "many_open_reviews" in t_rev
    assert "weekend_heavy" not in t_rev
    assert "goal_at_risk" not in t_rev

    # Clean unreviewed
    conn.execute("DELETE FROM transactions WHERE needs_review = 1")

    # 3. Inject an active goal that spending history shows is off track.
    # (A goal with a deficit but no history to judge by is "unknown", not at risk.)
    for month in ("2026-06", "2026-07", "2026-08"):
        _insert_txn(conn, "user_alice", f"hist_{month}", f"{month}-10T10:00:00Z", 500000)
    insert_goal(
        conn,
        Goal(
            id="g_trip",
            user_id="user_alice",
            name="Trip to Goa",
            kind="savings",
            target_paise=5000000,
            current_paise=1000000,
            deadline="2026-12-31",
            priority=1,
            created_at=T0,
            updated_at=T0,
        ),
    )
    t_goal = evaluate_triggers(conn, "user_alice", clock=DT0)
    assert "goal_at_risk" in t_goal
    assert "goal_off_track" in t_goal
    assert "weekend_heavy" not in t_goal


def test_targets_rounded_to_50_and_floored_at_50_percent_of_median(conn):
    """Targets are rounded to the nearest ₹50 (5000 paise) and floored at 50% of baseline median."""
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    # Median = 123456 paise
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 123456, cat="dining_out")

    spec = LLMChallengeSpec(
        metric_code="category_spend",
        categories=["dining_out"],
        duration_days=14,
        difficulty="medium",  # 20% reduction
        title="Rounding Test",
        rationale="Check ₹50 rounding",
    )
    cand = fit_candidate_challenge(conn, "user_alice", spec=spec, week_start="2026-09-01", clock=DT0)
    assert cand is not None

    # raw_target = 123456 - (123456 * 0.20) = 123456 - 24691 = 98765 paise
    # 98765 % 5000 = 3765 (>= 2500) -> rounds up to 100000 paise (₹1000)
    assert cand.target_value % 5000 == 0
    assert cand.target_value == 100000

    # Floor test: hard difficulty (30% reduction) on small median
    conn.execute("DELETE FROM transactions")
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 10000, cat="dining_out")
    cand_floor = fit_candidate_challenge(conn, "user_alice", spec=spec, week_start="2026-09-01", clock=DT0)
    assert cand_floor is not None
    # 50% floor of 10000 is 5000
    assert cand_floor.target_value >= 5000


def test_essential_categories_never_targeted_property_test(conn):
    """Property test: over 50 random category samples, essential categories are never targeted."""
    all_cats = [
        "dining_out", "food_delivery", "shopping", "entertainment",
        "rent", "groceries", "food_and_groceries", "healthcare", "utilities", "education", "emis_and_loans"
    ]
    for cat in all_cats:
        c_name = cat.replace("_", " ").title()
        if not conn.execute("SELECT id FROM categories WHERE id = ?", (cat,)).fetchone():
            insert_category(conn, Category(id=cat, user_id="user_alice", name=c_name, created_at=T0))

    rng = random.Random(42)
    for _ in range(50):
        # Pick 1 to 3 random categories
        sample = rng.sample(all_cats, rng.randint(1, 3))
        cand = CandidateOffer(
            template_code="random_test",
            metric_code="category_spend",
            categories=sample,
            duration_days=14,
            difficulty="medium",
            title="Random Test",
            rationale="Test",
            target_value=50000,
            baseline_median=100000,
            expected_effect_paise=50000,
        )
        safe = filter_safe_candidates(conn, "user_alice", [cand], week_start="2026-09-01", clock=DT0)
        has_essential = any(
            c in {"rent", "food_and_groceries", "healthcare", "utilities", "education", "emis_and_loans", "groceries"}
            for c in sample
        )
        if has_essential:
            assert len(safe) == 0, f"Candidate with essential categories {sample} was not filtered!"
        else:
            assert len(safe) == 1, f"Candidate with non-essential categories {sample} was falsely filtered!"


def test_same_category_conflict_filtered(conn):
    """Candidates overlapping categories of an active experiment are filtered out."""
    # Active experiment on dining_out
    insert_experiment(
        conn,
        Experiment(
            id="exp_active",
            user_id="user_alice",
            title="Active Dining",
            template_code="t1",
            hypothesis_json={},
            metric_def_json={"categories": ["dining_out"]},
            params_json={},
            difficulty="medium",
            window_start="2026-09-01",
            window_end="2026-09-15",
            baseline_json={},
            target_value=150000,
            status="active",
            origin="offer",
            created_at=T0,
            started_at=T0,
        ),
    )

    cand1 = CandidateOffer(
        template_code="t1",
        metric_code="category_spend",
        categories=["dining_out"],
        duration_days=14,
        difficulty="medium",
        title="Dining Offer",
        rationale="r",
        target_value=100000,
        baseline_median=200000,
        expected_effect_paise=100000,
    )
    cand2 = CandidateOffer(
        template_code="t2",
        metric_code="category_spend",
        categories=["shopping"],
        duration_days=14,
        difficulty="medium",
        title="Shopping Offer",
        rationale="r",
        target_value=100000,
        baseline_median=200000,
        expected_effect_paise=100000,
    )

    safe = filter_safe_candidates(conn, "user_alice", [cand1, cand2], week_start="2026-09-01", clock=DT0)
    assert len(safe) == 1
    assert safe[0].categories == ["shopping"]


def test_cooldown_boundary_day29_day30_day31(conn):
    """
    Cooldown boundary test:
    - Event completed 29 days ago -> in cooldown (filtered)
    - Event completed 30 days ago -> cooldown expired (allowed)
    - Event completed 31 days ago -> cooldown expired (allowed)
    """
    today = datetime(2026, 9, 1, 10, 0, tzinfo=IST)

    # 1. Day 29: completed 29 days ago
    d29 = (today - timedelta(days=29)).strftime("%Y-%m-%dT10:00:00Z")
    insert_experiment(
        conn,
        Experiment(
            id="exp_d29",
            user_id="user_alice",
            title="D29 Exp",
            template_code="weekday_home_cooking",
            hypothesis_json={},
            metric_def_json={"categories": ["dining_out"]},
            params_json={},
            difficulty="medium",
            window_start="2026-08-01",
            window_end="2026-08-03",
            baseline_json={},
            target_value=100000,
            status="completed",
            origin="offer",
            created_at=d29,
            ended_at=d29,
        ),
    )

    cand = CandidateOffer(
        template_code="weekday_home_cooking",
        metric_code="category_spend",
        categories=["dining_out"],
        duration_days=14,
        difficulty="medium",
        title="D29 Check",
        rationale="r",
        target_value=100000,
        baseline_median=200000,
        expected_effect_paise=100000,
    )

    # Day 29 should be filtered out
    assert len(filter_safe_candidates(conn, "user_alice", [cand], clock=today)) == 0

    # 2. Update to Day 30
    d30 = (today - timedelta(days=30)).strftime("%Y-%m-%dT10:00:00Z")
    conn.execute("UPDATE experiments SET ended_at = ?, created_at = ? WHERE id = 'exp_d29'", (d30, d30))
    # Day 30 should be allowed
    assert len(filter_safe_candidates(conn, "user_alice", [cand], clock=today)) == 1

    # 3. Update to Day 31
    d31 = (today - timedelta(days=31)).strftime("%Y-%m-%dT10:00:00Z")
    conn.execute("UPDATE experiments SET ended_at = ?, created_at = ? WHERE id = 'exp_d29'", (d31, d31))
    # Day 31 should be allowed
    assert len(filter_safe_candidates(conn, "user_alice", [cand], clock=today)) == 1


def test_goal_decomposition_never_claims_completion(conn):
    """
    Decomposing a goal gap produces candidate experiments without ANY promise words.
    Forbidden: 'will reach', 'will achieve', 'guarantee', 'guaranteed', 'promises'.
    """
    # Insert in 7-day windows (weekday_home_cooking duration=7, weekdays_only=True)
    windows_7 = generate_candidate_windows("2026-09-01", duration_days=7, k=6)
    for idx, (ws, _we) in enumerate(windows_7, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 200000, cat="dining_out")

    insert_goal(
        conn,
        Goal(
            id="goal_japan",
            user_id="user_alice",
            name="Japan Trip",
            kind="savings",
            target_paise=30000000,  # ₹300,000
            current_paise=10000000,  # ₹100,000
            deadline="2027-03-31",
            priority=1,
            created_at=T0,
            updated_at=T0,
        ),
    )

    decomp = decompose_goal_gap(conn, "user_alice", "goal_japan", clock=DT0)
    assert decomp.goal_id == "goal_japan"
    assert decomp.deficit_paise == 20000000
    assert decomp.required_monthly_paise is not None and decomp.required_monthly_paise > 0
    assert len(decomp.candidate_experiments) > 0

    forbidden_phrases = ["will reach", "will achieve", "guarantee", "guaranteed", "promises"]
    for exp in decomp.candidate_experiments:
        stmt_lower = exp.statement.lower()
        for phrase in forbidden_phrases:
            assert phrase not in stmt_lower, f"Forbidden phrase '{phrase}' found in statement: {exp.statement}"
        assert exp.gap_share_pct > 0
        assert "would cover" in stmt_lower


def test_offers_are_drafts_only(conn):
    """All created offers have status='shown' and require explicit user opt-in to become experiments."""
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 150000, cat="dining_out")

    offers = generate_challenge_offers(
        conn=conn,
        user_id="user_alice",
        week_start="2026-09-01",
        clock=DT0,
    )
    assert len(offers) > 0
    for o in offers:
        assert o.status == "shown"
        assert o.decided_at is None
        assert o.rank >= 1
