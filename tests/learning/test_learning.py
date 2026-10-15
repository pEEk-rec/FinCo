"""
Tests for Bounded Feedback Learning Engine (PLAN_PHASE3 Section 5.16 & Stage 3.14).

Covers:
1. Exact Beta posterior updates (alpha_milli, beta_milli, p, m).
2. Multiplier bounds clamping at m_min and m_max.
3. Hard floors: alerts for exceeded budgets, not_covered commitments, and off_track goals
   are never reduced below base severity or suppressed.
4. Contextual-reason dismissals go to memory as exceptions, never to learning.
5. Generic dismissals and mutes update beta (negative signal).
6. Acknowledgments and acted-on reallocations update alpha (positive signal).
7. Advice approvals/rejections update stats and order advice drafts by utility p.
8. Reset restores priors (alpha=2, beta=2, m=1.0).
9. Why-text transparency: mentions learning only when severity changed.
10. Deterministic reproducibility: identical inputs produce identical outputs.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from copilot.cli.main import app
from copilot.config.phase2 import AlertsConfig
from copilot.config.phase3 import LearningConfig
from copilot.core.learning import (
    apply_learning_to_alert,
    compute_sensitivity_multiplier,
    get_learned_multiplier,
    is_hard_floor_alert,
    order_advice_by_utility,
    record_feedback,
    reset_learning,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_alert, insert_user
from copilot.db.repo_phase3 import (
    get_feedback_stat,
    insert_bucket,
    insert_reallocation_draft,
    list_memory_items,
)
from copilot.governance.policy import PolicySettings, load_policy
from copilot.models.agentic import Alert
from copilot.models.domain import User
from copilot.models.phase3 import Bucket, ReallocationDraft
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

PROJECT_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
def policy() -> PolicySettings:
    return load_policy(PROJECT_ROOT / "config" / "policy.yaml")


@pytest.fixture
def test_db() -> sqlite3.Connection:
    """In-memory SQLite database initialized with all schemas and base tenant u1."""
    ensure_tools_registered()
    conn = get_connection(":memory:")
    init_db(conn)

    # Insert test user and category
    u = User(id="u1", created_at="2026-01-01T00:00:00Z")
    insert_user(conn, u)
    conn.execute(
        "INSERT OR IGNORE INTO categories (id, user_id, name, created_at) "
        "VALUES ('cat_dining', 'u1', 'Dining', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO categories (id, user_id, name, created_at) "
        "VALUES ('cat_groceries', 'u1', 'Groceries', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO budgets (id, user_id, category_id, period, limit_paise) "
        "VALUES ('b_din', 'u1', 'cat_dining', '2026-10', 1000000)"  # ₹10,000
    )
    conn.commit()
    return conn


@pytest.fixture
def default_config() -> LearningConfig:
    return LearningConfig(
        prior_alpha=2,
        prior_beta=2,
        eta=0.5,
        m_min=0.5,
        m_max=1.5,
        hard_floor_severities=["exceeded", "not_covered", "off_track"],
    )


@pytest.fixture
def alerts_config() -> AlertsConfig:
    return AlertsConfig(
        cooldown_days=7,
        default_max_open_alerts=5,
        quiet_mode=True,
        signal_weights_bp={
            "threshold": 2500,
            "forecast": 2500,
            "history_deviation": 2000,
            "anomaly": 1500,
            "goal_impact": 1500,
        },
        tier_thresholds_bp={
            "critical": 9000,
            "warning": 7500,
            "notice": 5000,
            "info": 2500,
        },
    )


# -------------------------------------------------------------------------------------------------
# 1. Posterior Updates & Multiplier Clamping
# -------------------------------------------------------------------------------------------------
def test_posterior_updates_exact(test_db: sqlite3.Connection, default_config: LearningConfig):
    """Verify exact Beta posterior updates and sensitivity multiplier formula."""
    user_id = "u1"
    kind = "alert_kind"
    subj = "budget_risk:cat_dining"

    # Prior state: alpha=2000, beta=2000 -> p=0.5, m=1.0
    m, p, a_m, b_m = get_learned_multiplier(test_db, user_id, kind, subj, default_config)
    assert a_m == 2000
    assert b_m == 2000
    assert p == 0.5
    assert m == 1.0

    # Useful signal 1: alpha=3000, beta=2000 -> p = 3/5 = 0.6
    # m = 1 + 0.5*(2*0.6 - 1) = 1 + 0.5*(0.2) = 1.1
    stat1 = record_feedback(test_db, user_id, kind, subj, "useful", default_config)
    assert stat1.alpha_milli == 3000
    assert stat1.beta_milli == 2000
    m1, p1, _, _ = get_learned_multiplier(test_db, user_id, kind, subj, default_config)
    assert p1 == 0.6
    assert m1 == 1.1

    # Useful signal 2: alpha=4000, beta=2000 -> p = 4/6 = 0.6667
    # m = 1 + 0.5*(2*0.66667 - 1) = 1 + 0.5*(0.3333) = 1.1667
    stat2 = record_feedback(test_db, user_id, kind, subj, "useful", default_config)
    assert stat2.alpha_milli == 4000
    m2, p2, _, _ = get_learned_multiplier(test_db, user_id, kind, subj, default_config)
    assert round(p2, 4) == 0.6667
    assert round(m2, 4) == 1.1667

    # Negative signal: beta=3000 -> alpha=4000, beta=3000 -> p = 4/7 = 0.5714
    stat3 = record_feedback(test_db, user_id, kind, subj, "not_useful", default_config)
    assert stat3.beta_milli == 3000
    m3, p3, _, _ = get_learned_multiplier(test_db, user_id, kind, subj, default_config)
    assert round(p3, 4) == 0.5714
    assert m3 == round(1.0 + 0.5 * (2 * (4 / 7) - 1), 4)


def test_multiplier_bounds(test_db: sqlite3.Connection, default_config: LearningConfig):
    """Verify multiplier strictly clamps at m_min (0.5) and m_max (1.5)."""
    # Direct formula bounds clamping
    assert compute_sensitivity_multiplier(1.5, default_config) == 1.5
    assert compute_sensitivity_multiplier(-0.5, default_config) == 0.5

    # Config with aggressive eta where raw multiplier exceeds bounds
    cfg = LearningConfig(
        prior_alpha=2,
        prior_beta=2,
        eta=1.0,
        m_min=0.6,
        m_max=1.4,
        hard_floor_severities=["exceeded", "not_covered", "off_track"],
    )
    user_id = "u1"
    kind = "alert_kind"
    subj_pos = "budget_risk:cat_pos"
    subj_neg = "budget_risk:cat_neg"

    # Extreme positive: 50 positive signals -> p ~ 0.96 -> raw_m > 1.4 -> clamped to 1.4
    for _ in range(50):
        record_feedback(test_db, user_id, kind, subj_pos, "useful", cfg)

    m_pos, p_pos, _, _ = get_learned_multiplier(test_db, user_id, kind, subj_pos, cfg)
    assert p_pos > 0.95
    assert m_pos == 1.4

    # Extreme negative: 50 negative signals -> p ~ 0.04 -> raw_m < 0.6 -> clamped to 0.6
    for _ in range(50):
        record_feedback(test_db, user_id, kind, subj_neg, "not_useful", cfg)

    m_neg, p_neg, _, _ = get_learned_multiplier(test_db, user_id, kind, subj_neg, cfg)
    assert p_neg < 0.05
    assert m_neg == 0.6


# -------------------------------------------------------------------------------------------------
# 2. Hard Floors Protection (Property Test)
# -------------------------------------------------------------------------------------------------
def test_hard_floors_never_reduced(default_config: LearningConfig, alerts_config: AlertsConfig):
    """
    Property test: Across random feedback sequences and arbitrary negative multipliers,
    alerts with hard floors (exceeded budget, not_covered commitment, off_track goal)
    are NEVER reduced below their base severity and never suppressed.
    """
    random.seed(42)

    hard_floor_contexts = [
        {"budget_status": "exceeded", "spent_paise": 1200000, "limit_paise": 1000000},
        {"budget_status": "ok", "spent_paise": 1000000, "limit_paise": 1000000},
        {"commitment_status": "not_covered"},
        {"commitment_status": "shortfall"},
        {"goals_affected": ["off_track"]},
        {"budget_status": "exceeded", "goals_affected": ["off_track"]},
    ]

    base_severities: list[tuple[int, str]] = [
        (9500, "critical"),
        (8000, "warning"),
        (6000, "notice"),
        (3000, "info"),
    ]

    for ctx in hard_floor_contexts:
        assert is_hard_floor_alert(ctx, default_config) is True

        for base_score, base_sev in base_severities:
            # Simulate random low multipliers in [0.1, 0.9]
            for _ in range(20):
                random_m = random.uniform(0.1, 0.95)
                adj_score, adj_sev, note = apply_learning_to_alert(
                    base_score_bp=base_score,
                    base_severity=base_sev,  # type: ignore
                    multiplier=random_m,
                    is_hard_floor=True,
                    config=alerts_config,
                )

                # Floor invariant: severity must NOT drop below base_sev
                sev_rank = {"info": 1, "notice": 2, "warning": 3, "critical": 4}
                assert adj_sev is not None
                assert sev_rank[adj_sev] >= sev_rank[base_sev]
                assert adj_score >= base_score
                # Note should not claim lowered priority because floor prevented lowering
                if adj_sev == base_sev:
                    assert note is None


# -------------------------------------------------------------------------------------------------
# 3. Contextual Dismissals vs. Generic Dismissals
# -------------------------------------------------------------------------------------------------
def test_contextual_reason_dismissals_go_to_memory(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """
    Verify that dismissing an alert with contextual reason (e.g. 'festival: Diwali shopping')
    records a memory item of kind 'contextual_exception' and does NOT touch feedback_stats.
    """
    # Create fixture open alert
    alert = Alert(
        id="alt_fest_1",
        user_id="u1",
        kind="budget_risk",
        subject_key="cat_dining",
        period="2026-10",
        score_bp=8000,
        severity="warning",
        components={"category_id": "cat_dining"},
        why_text="Spending is elevated.",
        status="open",
        dedup_key="u1:2026-10:budget_risk:cat_dining",
        run_id="run_1",
        created_at="2026-10-15T10:00:00Z",
    )
    insert_alert(test_db, alert)

    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_1",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    # Dismiss with contextual reason 'festival: Diwali celebration'
    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": "alt_fest_1", "action": "dismiss", "reason": "festival: Diwali celebration"},
    )
    assert res.ok
    assert res.data.status == "dismissed"

    # Invariant 1: Feedback stats NOT modified for this subject
    stat = get_feedback_stat(test_db, "u1", "alert_kind", "budget_risk:cat_dining")
    assert stat is None  # Remains at unrecorded default prior

    # Invariant 2: Contextual exception recorded in long-term memory
    mems = list_memory_items(test_db, "u1", kind="contextual_exception")
    assert len(mems) >= 1
    assert any("festival" in str(m.statement_json) for m in mems)


def test_generic_dismissals_update_beta(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """Verify that generic dismissal without contextual reason updates beta (negative feedback)."""
    alert = Alert(
        id="alt_gen_1",
        user_id="u1",
        kind="budget_risk",
        subject_key="cat_groceries",
        period="2026-10",
        score_bp=7500,
        severity="warning",
        components={"category_id": "cat_groceries"},
        why_text="Groceries pace is high.",
        status="open",
        dedup_key="u1:2026-10:budget_risk:cat_groceries",
        run_id="run_2",
        created_at="2026-10-15T10:00:00Z",
    )
    insert_alert(test_db, alert)

    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_2",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    # Dismiss with no reason
    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": "alt_gen_1", "action": "dismiss", "reason": None},
    )
    assert res.ok
    assert res.data.status == "dismissed"

    # Feedback stats updated: beta incremented from 2000 to 3000
    stat = get_feedback_stat(test_db, "u1", "alert_kind", "budget_risk:cat_groceries")
    assert stat is not None
    assert stat.alpha_milli == 2000
    assert stat.beta_milli == 3000


def test_acknowledgment_updates_alpha(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """Verify acknowledging an alert updates alpha (positive feedback signal)."""
    alert = Alert(
        id="alt_ack_1",
        user_id="u1",
        kind="budget_risk",
        subject_key="cat_groceries",
        period="2026-10",
        score_bp=7500,
        severity="warning",
        components={"category_id": "cat_groceries"},
        why_text="Groceries pace is high.",
        status="open",
        dedup_key="u1:2026-10:budget_risk:cat_groceries",
        run_id="run_3",
        created_at="2026-10-15T10:00:00Z",
    )
    insert_alert(test_db, alert)

    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_3",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    res = execute_tool(ctx, "decide_alert", {"alert_id": "alt_ack_1", "action": "acknowledge"})
    assert res.ok
    assert res.data.status == "acknowledged"

    stat = get_feedback_stat(test_db, "u1", "alert_kind", "budget_risk:cat_groceries")
    assert stat is not None
    assert stat.alpha_milli == 3000
    assert stat.beta_milli == 2000


def test_muted_category_updates_beta(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """Verify muting a category updates beta (negative feedback signal)."""
    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_mute",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    res = execute_tool(ctx, "set_alert_preference", {"category_id": "cat_dining", "muted": True})
    assert res.ok

    stat = get_feedback_stat(test_db, "u1", "alert_kind", "budget_risk:cat_dining")
    assert stat is not None
    assert stat.beta_milli == 3000


def test_acted_on_reallocation_updates_alpha(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """Verify applying an approved reallocation draft updates alpha (useful signal)."""
    # Create two buckets
    b1 = Bucket(
        id="b_src",
        user_id="u1",
        name="Discretionary",
        kind="spending",
        period_policy="reset_monthly",
        created_at="2026-10-01T00:00:00Z",
    )
    b2 = Bucket(
        id="b_dst",
        user_id="u1",
        name="Dining",
        kind="spending",
        period_policy="reset_monthly",
        created_at="2026-10-01T00:00:00Z",
    )
    insert_bucket(test_db, b1)
    insert_bucket(test_db, b2)

    draft = ReallocationDraft(
        id="d_act_1",
        user_id="u1",
        from_bucket_id="b_src",
        to_bucket_id="b_dst",
        amount_paise=50000,
        reason_json={"reason": "rebalance discretionary to dining"},
        status="approved",
        created_at="2026-10-15T00:00:00Z",
    )
    insert_reallocation_draft(test_db, draft)

    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_realloc",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    res = execute_tool(ctx, "apply_reallocation", {"draft_id": "d_act_1"})
    assert res.ok
    assert res.data.draft.status == "applied"

    # Stat for target Dining bucket updated with alpha
    stat = get_feedback_stat(test_db, "u1", "alert_kind", "budget_risk:Dining")
    assert stat is not None
    assert stat.alpha_milli == 3000


# -------------------------------------------------------------------------------------------------
# 4. Advice Approvals, Rejections, and Ordering
# -------------------------------------------------------------------------------------------------
def test_advice_approval_and_rejection_updates_stats(
    test_db: sqlite3.Connection, policy: PolicySettings
):
    """Verify deciding advice updates feedback stats and orders advice by utility p."""
    # Insert two advice items
    test_db.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text,
            evidence_json, assumptions_json, status, created_at
        ) VALUES (
            'adv_1', 'u1', 'r1', '[]', 'Cut dining spend by ₹500',
            '{"kind": "overspend_pace", "category_id": "dining"}', '[]', 'draft', '2026-10-15T00:00:00Z'
        )
        """
    )
    test_db.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text,
            evidence_json, assumptions_json, status, created_at
        ) VALUES (
            'adv_2', 'u1', 'r1', '[]', 'Review broadband plan',
            '{"kind": "recurring_increase", "merchant_name": "Airtel"}', '[]', 'draft', '2026-10-15T00:00:00Z'
        )
        """
    )
    test_db.commit()

    ctx = ExecutionContext(
        conn=test_db,
        user_id="u1",
        actor="user",
        run_id="run_adv",
        policy=policy,
        clock=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )

    # Approve adv_1 -> useful for overspend_pace:dining
    out1 = execute_tool(ctx, "decide_advice", {"advice_id": "adv_1", "decision": "approved"})
    assert out1.ok
    assert out1.data.status == "approved"
    stat1 = get_feedback_stat(test_db, "u1", "advice_kind", "overspend_pace:dining")
    assert stat1 is not None
    assert stat1.alpha_milli == 3000

    # Reject adv_2 -> not_useful for recurring_increase:Airtel
    out2 = execute_tool(ctx, "decide_advice", {"advice_id": "adv_2", "decision": "rejected"})
    assert out2.ok
    assert out2.data.status == "rejected"
    stat2 = get_feedback_stat(test_db, "u1", "advice_kind", "recurring_increase:Airtel")
    assert stat2 is not None
    assert stat2.beta_milli == 3000

    # Test order_advice_by_utility
    items = [
        {"id": "adv_2", "evidence": {"kind": "recurring_increase", "merchant_name": "Airtel"}},
        {"id": "adv_1", "evidence": {"kind": "overspend_pace", "category_id": "dining"}},
    ]
    # adv_1 has p = 3/5 = 0.6; adv_2 has p = 2/5 = 0.4
    ordered = order_advice_by_utility(test_db, "u1", items)
    assert ordered[0]["id"] == "adv_1"
    assert ordered[1]["id"] == "adv_2"


# -------------------------------------------------------------------------------------------------
# 5. Why-Text Attribution & Reset
# -------------------------------------------------------------------------------------------------
def test_why_text_learning_attribution(alerts_config: AlertsConfig):
    """Verify learning notes are appended to why-text only when severity actually changed."""
    # Case 1: Multiplier damps score from warning (7500) to notice (4500) -> 4500 is info tier (2500..5000)
    # 7500 * 0.6 = 4500
    adj_score, adj_sev, note = apply_learning_to_alert(
        base_score_bp=7500,
        base_severity="warning",
        multiplier=0.6,
        is_hard_floor=False,
        config=alerts_config,
    )
    assert adj_sev == "info"
    assert note is not None
    assert "shown at lower priority because you usually dismiss" in note

    # Case 2: Multiplier shifts score slightly but severity tier is UNCHANGED
    # 8000 * 0.95 = 7600 -> still warning
    adj_score2, adj_sev2, note2 = apply_learning_to_alert(
        base_score_bp=8000,
        base_severity="warning",
        multiplier=0.95,
        is_hard_floor=False,
        config=alerts_config,
    )
    assert adj_sev2 == "warning"
    assert note2 is None  # Invariant: why-text does not mention learning when tier is unchanged!

    # Case 3: Multiplier boosts score from notice (6000) to warning (7800)
    # 6000 * 1.3 = 7800
    adj_score3, adj_sev3, note3 = apply_learning_to_alert(
        base_score_bp=6000,
        base_severity="notice",
        multiplier=1.3,
        is_hard_floor=False,
        config=alerts_config,
    )
    assert adj_sev3 == "warning"
    assert note3 is not None
    assert "shown at higher priority because you usually find" in note3


def test_reset_restores_priors(test_db: sqlite3.Connection, default_config: LearningConfig):
    """Verify reset_learning deletes rows and restores prior distribution."""
    user_id = "u1"
    subj = "budget_risk:cat_dining"

    record_feedback(test_db, user_id, "alert_kind", subj, "useful", default_config)
    record_feedback(test_db, user_id, "alert_kind", subj, "useful", default_config)

    m_before, p_before, _, _ = get_learned_multiplier(test_db, user_id, "alert_kind", subj, default_config)
    assert p_before > 0.5
    assert m_before > 1.0

    # Reset specific subject
    cnt = reset_learning(test_db, user_id=user_id, subject_key=subj)
    assert cnt == 1

    # Multiplier and p revert exactly to prior
    m_after, p_after, a_after, b_after = get_learned_multiplier(
        test_db, user_id, "alert_kind", subj, default_config
    )
    assert a_after == 2000
    assert b_after == 2000
    assert p_after == 0.5
    assert m_after == 1.0


# -------------------------------------------------------------------------------------------------
# 6. CLI Commands: learning show & learning reset
# -------------------------------------------------------------------------------------------------
def test_cli_learning_show_and_reset(test_db: sqlite3.Connection, tmp_path: Path):
    """Verify CLI commands copilot learning show and copilot learning reset."""
    db_file = tmp_path / "finco_learning.db"
    conn = get_connection(db_file)
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2026-01-01T00:00:00Z"))
    conn.commit()

    # Record some feedback
    record_feedback(conn, "u1", "alert_kind", "budget_risk:groceries", "useful")
    record_feedback(conn, "u1", "advice_kind", "overspend_pace:dining", "not_useful")
    conn.commit()
    conn.close()

    # 1. Show command
    res_show = runner.invoke(app, ["learning", "show", "--user", "u1", "--db", str(db_file)], env={"COLUMNS": "200"})
    assert res_show.exit_code == 0
    assert "budget_risk:groceries" in res_show.output
    assert "overspend_pace:dining" in res_show.output

    # 2. Show command with JSON output
    res_json = runner.invoke(app, ["learning", "show", "--user", "u1", "--db", str(db_file), "--json"])
    assert res_json.exit_code == 0
    assert '"subject_key": "budget_risk:groceries"' in res_json.output

    # 3. Reset specific subject
    res_reset_sub = runner.invoke(
        app,
        ["learning", "reset", "--user", "u1", "--subject", "budget_risk:groceries", "--db", str(db_file)],
    )
    assert res_reset_sub.exit_code == 0
    assert "Reset 1 feedback stat(s)" in res_reset_sub.output

    # 4. Reset all remaining subjects
    res_reset_all = runner.invoke(
        app,
        ["learning", "reset", "--user", "u1", "--db", str(db_file)],
    )
    assert res_reset_all.exit_code == 0
    assert "Reset 1 feedback stat(s)" in res_reset_all.output


# -------------------------------------------------------------------------------------------------
# 7. Deterministic Reproducibility
# -------------------------------------------------------------------------------------------------
def test_deterministic_reproducibility(default_config: LearningConfig, alerts_config: AlertsConfig):
    """Verify identical inputs produce identical scores and severities every time."""
    for _ in range(50):
        adj_score1, adj_sev1, note1 = apply_learning_to_alert(
            base_score_bp=7200,
            base_severity="warning",
            multiplier=1.2,
            is_hard_floor=False,
            config=alerts_config,
        )
        adj_score2, adj_sev2, note2 = apply_learning_to_alert(
            base_score_bp=7200,
            base_severity="warning",
            multiplier=1.2,
            is_hard_floor=False,
            config=alerts_config,
        )
        assert adj_score1 == adj_score2
        assert adj_sev1 == adj_sev2
        assert note1 == note2
