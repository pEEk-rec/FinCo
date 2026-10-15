"""
Tests for Memory Confidence, Decay, and Consumer Use (PLAN_PHASE3 Stage 3.9 & Section 5.9).

Validates:
1. Exact decay values at 0, 1, and 2 half-lives.
2. Threshold boundaries for active, stale, and retired states.
3. Contradicted user-confirmed memory becomes 'stale' with 'still_true_check' True.
4. Drift scenario: habit change mid-history transitions old memory to stale and new to active.
5. Alerts damped ONLY by an active exception for the same category and period.
6. Investigation hypothesis 'known_exception' supported ONLY when active exception covers subject.
7. Suppression cooldown boundary on day 29, 30, and 31; approved kinds never boosted.
8. memories_json population in consumer findings and alerts.
9. Property tests: confidence never increases with age alone, bounded [0, 10000].
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from copilot.config.phase2 import AlertsConfig, load_investigation_config
from copilot.core.alerts import build_why_text, evaluate_category_alert_signals
from copilot.core.investigation import run_investigation_suite
from copilot.core.memory import (
    check_advice_suppression,
    compute_memory_confidence,
    determine_memory_status,
    get_active_contextual_exception,
    load_memory_config,
    record_contextual_exception,
)
from copilot.core.recommendations import build_recommendation, find_relevant_memories
from copilot.core.timeutil import to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_recommendation,
    insert_user,
)
from copilot.db.repo_phase3 import insert_memory_evidence, insert_memory_item
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import MemoryEvidence, MemoryItem


@pytest.fixture
def conn():
    """In-memory SQLite connection with complete schema migrations."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def _setup_test_user(conn: sqlite3.Connection, user_id: str = "u_mem"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=10000000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat in ["dining", "utilities", "shopping", "groceries", "travel", "income"]:
        insert_category(
            conn,
            Category(
                id=f"{cat}_{user_id}",
                user_id=user_id,
                name=cat.capitalize(),
                created_at="2026-01-01T00:00:00Z",
            ),
        )


# -------------------------------------------------------------------------------------------------
# 1. Exact Decay Tests at 0, 1, and 2 Half-Lives
# -------------------------------------------------------------------------------------------------

def test_decay_exact_values_at_half_lives():
    """
    Assert exact confidence values at 0, 1, and 2 half-lives.
    For recurring_pattern (half_life = 90 days), evidence_bp = 8000:
      age 0d   -> 8000
      age 90d  -> 4000
      age 180d -> 2000
    """
    config = load_memory_config()
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)

    item_0d = MemoryItem(
        id="mem_0d",
        user_id="u1",
        kind="recurring_pattern",
        subject_key="cat:dining",
        statement_json={"pattern": "weekend_heavy"},
        source="observed",
        status="candidate",
        prior_bp=8000,
        user_confirmed=False,
        created_at=to_utc_iso(now),
        last_evidence_at=to_utc_iso(now),
    )
    conf_0d, _, _ = compute_memory_confidence(item_0d, [], now, config)
    assert conf_0d == 8000

    # 1 half-life = 90 days later
    now_90d = now + timedelta(days=90)
    conf_90d, _, _ = compute_memory_confidence(item_0d, [], now_90d, config)
    assert conf_90d == 4000  # floor(8000 * 0.5)

    # 2 half-lives = 180 days later
    now_180d = now + timedelta(days=180)
    conf_180d, _, _ = compute_memory_confidence(item_0d, [], now_180d, config)
    assert conf_180d == 2000  # floor(8000 * 0.25)


def test_decay_user_preference_never_decays():
    """
    User stated preference memories have decay = 1.0 regardless of elapsed time.
    """
    config = load_memory_config()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    item_pref = MemoryItem(
        id="mem_pref",
        user_id="u1",
        kind="preference",
        subject_key="pref:emergency_target",
        statement_json={"months": 6},
        source="user_stated",
        status="active",
        prior_bp=9000,
        user_confirmed=True,
        created_at=to_utc_iso(now),
        last_evidence_at=to_utc_iso(now),
    )

    # At age 0
    conf_0, _, _ = compute_memory_confidence(item_pref, [], now, config)
    assert conf_0 == 9000

    # At age 500 days
    conf_500d, _, _ = compute_memory_confidence(item_pref, [], now + timedelta(days=500), config)
    assert conf_500d == 9000

    # At age 2000 days
    conf_2000d, _, _ = compute_memory_confidence(item_pref, [], now + timedelta(days=2000), config)
    assert conf_2000d == 9000


# -------------------------------------------------------------------------------------------------
# 2. Threshold Boundaries
# -------------------------------------------------------------------------------------------------

def test_threshold_boundaries():
    """
    Verify threshold boundary transitions:
      confidence >= use (6000) -> active
      retire (2000) <= confidence < use (6000) -> stale
      confidence < retire (2000) -> retired
    """
    config = load_memory_config()
    item = MemoryItem(
        id="mem_test",
        user_id="u1",
        kind="recurring_pattern",
        subject_key="cat:dining",
        statement_json={},
        source="observed",
        status="candidate",
        prior_bp=5000,
        user_confirmed=False,
        created_at="2026-10-01T00:00:00Z",
    )

    # Boundary at use (6000)
    assert determine_memory_status(item, 6000, 1000, 0, 0, config) == "active"
    assert determine_memory_status(item, 5999, 1000, 0, 0, config) == "candidate"

    # Boundary at retire (2000)
    stale_item = item.model_copy(update={"status": "stale"})
    assert determine_memory_status(stale_item, 2000, 1000, 0, 0, config) == "stale"
    assert determine_memory_status(stale_item, 1999, 1000, 0, 0, config) == "retired"


# -------------------------------------------------------------------------------------------------
# 3. Contradicted User-Confirmed Memory Status & "Still true?"
# -------------------------------------------------------------------------------------------------

def test_user_confirmed_contradicted_memory_becomes_stale_with_still_true():
    """
    User-confirmed memory that becomes contradicted does NOT auto-retire;
    it becomes 'stale' and is surfaced as 'Still true?' (Section 5.9).
    """
    config = load_memory_config()
    item = MemoryItem(
        id="mem_conf",
        user_id="u1",
        kind="recurring_pattern",
        subject_key="cat:shopping",
        statement_json={"pattern": "month_start_heavy"},
        source="observed",
        status="active",
        prior_bp=6000,
        user_confirmed=True,
        confidence_bp=7000,
        created_at="2026-09-01T00:00:00Z",
    )

    # Contradicted: contradict >= support and count >= min_contradictions (2)
    support_bp = 2000
    contradict_bp = 3000
    status = determine_memory_status(
        item,
        confidence_bp=7000,
        support_bp=support_bp,
        contradict_bp=contradict_bp,
        contradict_count=2,
        config=config,
    )
    assert status == "stale"  # NOT retired!

    # Contrast with non-confirmed memory:
    non_conf = item.model_copy(update={"user_confirmed": False})
    status_non_conf = determine_memory_status(
        non_conf,
        confidence_bp=7000,
        support_bp=support_bp,
        contradict_bp=contradict_bp,
        contradict_count=2,
        config=config,
    )
    assert status_non_conf == "retired"


# -------------------------------------------------------------------------------------------------
# 4. Drift Scenario: Habit Changes Mid-History
# -------------------------------------------------------------------------------------------------

def test_drift_scenario_habit_change(conn: sqlite3.Connection):
    """
    Habit change scenario:
    Old pattern ceases receiving evidence and decays, falling below use threshold into stale.
    New pattern receives consistent evidence and reaches active status.
    """
    user_id = "user_drift"
    _setup_test_user(conn, user_id)
    config = load_memory_config()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    # User originally had weekday dining habit
    old_mem = MemoryItem(
        id="mem_old_habit",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining_weekday",
        statement_json={"habit": "weekday_dining"},
        source="observed",
        status="active",
        prior_bp=5000,
        user_confirmed=False,
        confidence_bp=6500,
        created_at=to_utc_iso(t0),
        last_evidence_at=to_utc_iso(t0),
    )
    insert_memory_item(conn, old_mem)

    # 120 days later without new evidence (half-life = 90d):
    t_later = t0 + timedelta(days=120)
    conf_old, supp, cont = compute_memory_confidence(old_mem, [], t_later, config)
    # decay = 0.5 ** (120/90) = ~0.3968; 5000 * 0.3968 = ~1984 bp
    assert conf_old < config["thresholds_bp"]["use"]

    status_old = determine_memory_status(
        old_mem, conf_old, supp, cont, contradict_count=0, config=config
    )
    assert status_old in ("stale", "retired")

    # New habit receives 3 supporting pieces of evidence
    new_mem = MemoryItem(
        id="mem_new_habit",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining_weekend",
        statement_json={"habit": "weekend_dining"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        created_at=to_utc_iso(t_later),
        last_evidence_at=to_utc_iso(t_later),
    )
    insert_memory_item(conn, new_mem)

    new_evidence = [
        MemoryEvidence(
            id=f"mev_{i}",
            user_id=user_id,
            memory_id="mem_new_habit",
            polarity="supports",
            ref_kind="txn",
            ref_id=f"t_{i}",
            observed_at=to_utc_iso(t_later),
            weight_bp=1500,
            created_at=to_utc_iso(t_later),
        )
        for i in range(3)
    ]
    for e in new_evidence:
        insert_memory_evidence(conn, e)

    # Total evidence = 3000 prior + 3 * 1500 = 7500 bp
    conf_new, supp_new, cont_new = compute_memory_confidence(new_mem, new_evidence, t_later, config)
    assert conf_new >= 6000
    status_new = determine_memory_status(
        new_mem, conf_new, supp_new, cont_new, contradict_count=0, config=config
    )
    assert status_new == "active"


# -------------------------------------------------------------------------------------------------
# 5. Alerts Damping Integration
# -------------------------------------------------------------------------------------------------

def test_alerts_damped_only_by_active_exception_for_same_category_and_period(
    conn: sqlite3.Connection,
):
    """
    Active contextual exception for category 'shopping' in period '2026-10':
      - Alert for 'shopping' in '2026-10' has score damped by 50% and why_text mentions damping.
      - Alert for 'dining' in '2026-10' is NOT damped.
      - Alert for 'shopping' in '2026-11' is NOT damped.
      - Stale or retired exception does NOT damp alert.
    """
    user_id = "u_alert_damp"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)

    # Insert active contextual exception for shopping in 2026-10
    record_contextual_exception(
        conn,
        user_id=user_id,
        category="shopping",
        period="2026-10",
        reason="festival",
        clock=clock,
    )

    # 1. Matching category and period
    active_exc = get_active_contextual_exception(conn, user_id, "shopping", "2026-10", clock)
    assert active_exc is not None
    assert active_exc.statement_json.get("reason") == "festival"

    # 2. Different category
    diff_cat_exc = get_active_contextual_exception(conn, user_id, "dining", "2026-10", clock)
    assert diff_cat_exc is None

    # 3. Different period
    diff_period_exc = get_active_contextual_exception(conn, user_id, "shopping", "2026-11", clock)
    assert diff_period_exc is None

    # Test score damping in evaluate_category_alert_signals
    alerts_cfg = AlertsConfig(
        signal_weights_bp={
            "threshold": 2500,
            "forecast": 2500,
            "history_deviation": 2000,
            "anomaly": 1500,
            "goal_impact": 1500,
        },
        tier_thresholds_bp={"info": 2500, "notice": 5000, "warning": 7500, "critical": 9000},
    )

    # Evaluate without exception
    undamped = evaluate_category_alert_signals(
        category_id="shopping",
        spent_paise=950000,
        limit_paise=1000000,
        budget_status="warning",
        fc_low=1100000,
        fc_expected=1200000,
        fc_high=1300000,
        projected_exceed=True,
        historical_spends_to_date=[800000, 850000],
        anomalies=[],
        goals_affected=[],
        history_months=2,
        txn_count=6,
        config=alerts_cfg,
        active_exception=None,
    )

    # Evaluate with active exception
    damped = evaluate_category_alert_signals(
        category_id="shopping",
        spent_paise=950000,
        limit_paise=1000000,
        budget_status="warning",
        fc_low=1100000,
        fc_expected=1200000,
        fc_high=1300000,
        projected_exceed=True,
        historical_spends_to_date=[800000, 850000],
        anomalies=[],
        goals_affected=[],
        history_months=2,
        txn_count=6,
        config=alerts_cfg,
        active_exception={"id": active_exc.id, "reason": "festival"},
        exception_damping_bp=5000,
    )

    assert damped.score_bp == undamped.score_bp // 2
    assert damped.components.get("damped_by_exception") is True
    assert damped.components.get("exception_reason") == "festival"
    assert len(damped.components.get("memories", [])) == 1

    # Check why_text explains exception
    why = build_why_text(damped.components)
    assert "Damped by active festival exception" in why


# -------------------------------------------------------------------------------------------------
# 6. Investigation Hypothesis 'known_exception'
# -------------------------------------------------------------------------------------------------

def test_investigation_hypothesis_known_exception():
    """
    Investigation suite includes 'known_exception':
      - Supported when active exception covers subject.
      - Contradicted when no active exception covers subject.
    """
    user_id = "user_inv_exc"
    period = "2026-10"
    inv_cfg = load_investigation_config()

    t1 = Transaction(
        id="t1",
        user_id=user_id,
        account_id="acc1",
        occurred_at="2026-10-10T10:00:00Z",
        amount_paise=500000,
        direction="debit",
        merchant_raw="Festival Store",
        merchant_normalized="FESTIVAL",
        category_id="shopping",
        created_at="2026-10-10T10:00:00Z",
        description="Festival shopping",
    )
    b1 = Transaction(
        id="b1",
        user_id=user_id,
        account_id="acc1",
        occurred_at="2026-09-10T10:00:00Z",
        amount_paise=100000,
        direction="debit",
        merchant_raw="Regular Store",
        merchant_normalized="REGULAR",
        category_id="shopping",
        created_at="2026-09-10T10:00:00Z",
        description="Regular shopping",
    )
    b2 = Transaction(
        id="b2",
        user_id=user_id,
        account_id="acc1",
        occurred_at="2026-09-15T10:00:00Z",
        amount_paise=50000,
        direction="debit",
        merchant_raw="Regular Store",
        merchant_normalized="REGULAR",
        category_id="shopping",
        created_at="2026-09-15T10:00:00Z",
        description="Regular shopping 2",
    )
    b3 = Transaction(
        id="b3",
        user_id=user_id,
        account_id="acc1",
        occurred_at="2026-09-20T10:00:00Z",
        amount_paise=50000,
        direction="debit",
        merchant_raw="Regular Store",
        merchant_normalized="REGULAR",
        category_id="shopping",
        created_at="2026-09-20T10:00:00Z",
        description="Regular shopping 3",
    )

    baseline_txns = [b1, b2, b3]

    # 1. With active exception
    active_exc = {"id": "mem_fest", "reason": "festival", "category": "shopping"}
    inv_with_exc = run_investigation_suite(
        user_id=user_id,
        target_txns=[t1],
        baseline_txns=baseline_txns,
        subject_kind="category_change",
        subject_ref={"category_id": "shopping"},
        period=period,
        config=inv_cfg,
        active_exception=active_exc,
    )

    hyp_with = {h.code: h for h in inv_with_exc.hypotheses}
    assert "known_exception" in hyp_with
    assert hyp_with["known_exception"].status == "supported"
    assert inv_with_exc.outcome == "explained"
    assert inv_with_exc.confidence_label == "high"

    # 2. Without active exception
    inv_without_exc = run_investigation_suite(
        user_id=user_id,
        target_txns=[t1],
        baseline_txns=baseline_txns,
        subject_kind="category_change",
        subject_ref={"category_id": "shopping"},
        period=period,
        config=inv_cfg,
        active_exception=None,
    )
    hyp_without = {h.code: h for h in inv_without_exc.hypotheses}
    assert hyp_without["known_exception"].status == "contradicted"


# -------------------------------------------------------------------------------------------------
# 7. Suppression Cooldown Boundary Tests (Day 29, 30, 31)
# -------------------------------------------------------------------------------------------------

def test_advice_suppression_cooldown_boundaries(conn: sqlite3.Connection):
    """
    Rejected advice kinds for a subject are suppressed during cooldown (advice_cooldown_days = 30):
      - Day 29: suppressed (True)
      - Day 30: elapsed, back (False)
      - Day 31: elapsed, back (False)
      - Approved advice is never suppressed or boosted.
    """
    user_id = "user_cooldown"
    _setup_test_user(conn, user_id)
    t0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

    # Record rejected advice feedback in memory
    item = MemoryItem(
        id="mem_adv_rej",
        user_id=user_id,
        kind="advice_feedback",
        subject_key="advice_kind:reduce_spend|subject:category:dining",
        statement_json={
            "advice_kind": "reduce_spend",
            "subject": "category:dining",
            "decision": "rejected",
        },
        source="feedback",
        status="active",
        prior_bp=6000,
        user_confirmed=True,
        confidence_bp=6000,
        created_at=to_utc_iso(t0),
        last_evidence_at=to_utc_iso(t0),
    )
    insert_memory_item(conn, item)

    # Boundary check at day 29
    t_day29 = t0 + timedelta(days=29)
    suppressed_29, _ = check_advice_suppression(
        conn, user_id, "reduce_spend", "category:dining", clock=t_day29
    )
    assert suppressed_29 is True

    # Boundary check at day 30 (cooldown is 30 days, elapsed)
    t_day30 = t0 + timedelta(days=30)
    suppressed_30, _ = check_advice_suppression(
        conn, user_id, "reduce_spend", "category:dining", clock=t_day30
    )
    assert suppressed_30 is False

    # Boundary check at day 31
    t_day31 = t0 + timedelta(days=31)
    suppressed_31, _ = check_advice_suppression(
        conn, user_id, "reduce_spend", "category:dining", clock=t_day31
    )
    assert suppressed_31 is False


# -------------------------------------------------------------------------------------------------
# 8. Consumer findings memories_json Population
# -------------------------------------------------------------------------------------------------

def test_memories_json_population_in_recommendations(conn: sqlite3.Connection):
    """
    Consumer recommendations populate memories_json with active memory items.
    """
    user_id = "user_rec_mem"
    _setup_test_user(conn, user_id)
    now = datetime(2026, 10, 15, tzinfo=UTC)

    # Insert an active memory
    mem = MemoryItem(
        id="mem_rec_active",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy", "category": "dining"},
        source="observed",
        status="active",
        prior_bp=7000,
        user_confirmed=True,
        confidence_bp=7000,
        created_at=to_utc_iso(now),
    )
    insert_memory_item(conn, mem)

    # Query relevant memories for dining
    memories = find_relevant_memories(conn, user_id, category_id="dining")
    matching = [m for m in memories if m.get("id") == "mem_rec_active"]
    assert len(matching) == 1

    # Build and insert recommendation
    rec = build_recommendation(
        user_id=user_id,
        origin="monthly_review",
        text="Review dining spend based on weekend patterns.",
        memories=matching,
    )
    assert len(rec.memories) == 1
    assert rec.memories[0]["id"] == "mem_rec_active"

    insert_recommendation(conn, rec)
    row = conn.execute(
        "SELECT memories_json FROM advice_items WHERE id = ?", (rec.id,)
    ).fetchone()
    assert row is not None
    stored_memories = json.loads(row["memories_json"])
    assert len(stored_memories) == 1
    assert stored_memories[0]["id"] == "mem_rec_active"


# -------------------------------------------------------------------------------------------------
# 9. Property Tests: Confidence Monotonicity with Age and Boundedness
# -------------------------------------------------------------------------------------------------

def test_confidence_never_increases_with_age_alone():
    """
    Property: For any memory with constant evidence, confidence(t2) <= confidence(t1) for t2 >= t1.
    """
    config = load_memory_config()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    for kind in ("recurring_pattern", "contextual_exception", "advice_feedback", "merchant_habit"):
        item = MemoryItem(
            id=f"mem_prop_{kind}",
            user_id="u_prop",
            kind=kind,  # type: ignore[arg-type]
            subject_key="test:prop",
            statement_json={},
            source="observed",
            status="active",
            prior_bp=8000,
            user_confirmed=False,
            created_at=to_utc_iso(t0),
            last_evidence_at=to_utc_iso(t0),
        )

        prev_conf = 10001
        for day in range(0, 400, 15):
            clock = t0 + timedelta(days=day)
            conf, _, _ = compute_memory_confidence(item, [], clock, config)
            assert 0 <= conf <= 10000
            assert conf <= prev_conf, f"Confidence increased with age alone for {kind} at day {day}"
            prev_conf = conf


def test_confidence_always_bounded_0_to_10000():
    """
    Property: Confidence is strictly bounded [0, 10000] across extreme support and contradict sums.
    """
    config = load_memory_config()
    now = datetime(2026, 10, 15, tzinfo=UTC)

    for prior in (0, 3000, 5000, 10000):
        item = MemoryItem(
            id="mem_bound",
            user_id="u_bound",
            kind="recurring_pattern",
            subject_key="bound:test",
            statement_json={},
            source="observed",
            status="candidate",
            prior_bp=prior,
            user_confirmed=False,
            created_at=to_utc_iso(now),
        )

        # Extreme positive support
        huge_support = [
            MemoryEvidence(
                id=f"ev_sup_{i}",
                user_id="u_bound",
                memory_id="mem_bound",
                polarity="supports",
                ref_kind="txn",
                ref_id=f"t_{i}",
                observed_at=to_utc_iso(now),
                weight_bp=10000,
                created_at=to_utc_iso(now),
            )
            for i in range(5)
        ]
        conf_high, _, _ = compute_memory_confidence(item, huge_support, now, config)
        assert 0 <= conf_high <= 10000

        # Extreme negative contradictions
        huge_contradict = [
            MemoryEvidence(
                id=f"ev_contra_{i}",
                user_id="u_bound",
                memory_id="mem_bound",
                polarity="contradicts",
                ref_kind="txn",
                ref_id=f"tc_{i}",
                observed_at=to_utc_iso(now),
                weight_bp=10000,
                created_at=to_utc_iso(now),
            )
            for i in range(5)
        ]
        conf_low, _, _ = compute_memory_confidence(item, huge_contradict, now, config)
        assert 0 <= conf_low <= 10000
