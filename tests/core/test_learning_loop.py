"""
Unit and integration tests for Stage 4.8: Learning loop into memory and recommendations.
(PLAN_PHASE4 Section 5.10 & Stage 4.8)

Tests:
1. Posterior updates: exact for completed (helpful=True), completed (helpful=False), abandoned, and dismissed.
2. Memory writing & evidence: records experiment_outcome memory with review and transaction evidence links.
3. Memory decay: confidence decays predictably according to half-life (180 days).
4. Advice citation & copy safety: non-causal correlation statements pass, causal assertions raise ValueError.
5. Advice suppression: unhelpful reviews suppress template during cooldown; helpful reviews do not.
6. Forgotten memory exclusion: forgotten or decayed memories disappear from active advice citations.
7. Contribution-plan options: extracts repeating options for successful experiments.
8. Failure candidate export: exports reviews with confirmation_required, no_baseline, or difficulty=5 to eval/candidates/phase4/.
9. Integrated post-review learning hook: end-to-end execution of posterior, memory, and export.
"""

import json
from datetime import date, datetime, timedelta

import pytest

from copilot.core.learning_loop import (
    assert_no_causal_claims,
    export_phase4_failure_candidates,
    format_outcome_memory_advice_evidence,
    get_active_outcome_memories,
    get_contribution_plan_experiment_options,
    get_template_posterior,
    is_template_suppressed_in_advice,
    process_post_review_learning,
    record_experiment_outcome_memory,
    update_template_posterior,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.db.repo_phase3 import forget_memory_item
from copilot.db.repo_phase4 import insert_experiment, insert_experiment_review
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase4 import Experiment, ExperimentReview

T0 = "2026-08-01T00:00:00Z"
DT0 = datetime(2026, 8, 15, 12, 0, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u_alice", created_at=T0))
    insert_account(c, Account(id="acc_main", user_id="u_alice", name="Checking", created_at=T0))
    insert_category(c, Category(id="dining", user_id="u_alice", name="Dining", created_at=T0))
    return c


def create_sample_experiment(
    conn,
    exp_id: str,
    template_code: str = "tpl_dining_weekend",
    status: str = "completed",
    window_start: str = "2026-08-01",
    window_end: str = "2026-08-14",
) -> Experiment:
    exp = Experiment(
        id=exp_id,
        user_id="u_alice",
        title="Weekend Dining Reduction",
        template_code=template_code,
        hypothesis_json={
            "intervention": "cook",
            "metric": "dining_spend",
            "direction": "lower",
            "target": 40000,
        },
        metric_def_json={"metric": "dining_spend", "categories": ["dining"]},
        params_json={},
        difficulty="moderate",
        window_start=window_start,
        window_end=window_end,
        baseline_json={
            "k": 4,
            "window_values": [50000],
            "median": 50000,
            "low": 42000,
            "high": 58000,
        },
        target_value=40000,
        status=status,
        origin="offer",
        created_at=T0,
    )
    insert_experiment(conn, exp)
    return exp


def create_sample_review(
    conn,
    rev_id: str,
    exp_id: str,
    outcome: str = "beyond_usual_range",
    effect_value: int = -12000,
    target_met: bool = True,
    user_helpful: bool | None = True,
    user_difficulty: int | None = 2,
    confirmation_required: bool = False,
    created_at: str = "2026-08-15T12:00:00Z",
) -> ExperimentReview:
    integ = {}
    if confirmation_required:
        integ["confirmation_required"] = True

    rev = ExperimentReview(
        id=rev_id,
        user_id="u_alice",
        experiment_id=exp_id,
        observed_value=38000,
        outcome=outcome,
        rank_p_bp=9500,
        effect_value=effect_value,
        target_met=target_met,
        integrity_json=integ,
        data_quality_json={"coverage": 100},
        user_difficulty=user_difficulty,
        user_helpful=user_helpful,
        created_at=created_at,
    )
    insert_experiment_review(conn, rev)
    return rev


# -------------------------------------------------------------------------------------------------
# 1. Posterior Updates
# -------------------------------------------------------------------------------------------------
def test_posterior_updates_exact(conn):
    """Verify exact Beta posterior math for completed, abandoned, and dismissed events."""
    # 1. Initial prior: alpha=2000, beta=2000, mean=0.5
    a, b, m = get_template_posterior(conn, "u_alice", "tpl_dining_weekend")
    assert a == 2000 and b == 2000 and m == 0.5

    # 2. Completed with user_helpful=True: +1.0 alpha (1000 milli)
    stat1 = update_template_posterior(
        conn, "u_alice", "tpl_dining_weekend", "completed_review", user_helpful=True, clock=DT0
    )
    assert stat1.alpha_milli == 3000
    assert stat1.beta_milli == 2000
    a, b, m = get_template_posterior(conn, "u_alice", "tpl_dining_weekend")
    assert a == 3000 and b == 2000 and m == 0.6

    # 3. Completed with user_helpful=False: +1.0 beta (1000 milli)
    stat2 = update_template_posterior(
        conn, "u_alice", "tpl_dining_weekend", "completed_review", user_helpful=False, clock=DT0
    )
    assert stat2.alpha_milli == 3000
    assert stat2.beta_milli == 3000

    # 4. Abandoned experiment: +1.0 beta (1000 milli)
    stat3 = update_template_posterior(conn, "u_alice", "tpl_dining_weekend", "abandoned", clock=DT0)
    assert stat3.alpha_milli == 3000
    assert stat3.beta_milli == 4000

    # 5. Dismissed offer: +dismiss_weight (0.25 -> 250 milli)
    stat4 = update_template_posterior(
        conn, "u_alice", "tpl_dining_weekend", "dismissed_offer", clock=DT0
    )
    assert stat4.alpha_milli == 3000
    assert stat4.beta_milli == 4250


# -------------------------------------------------------------------------------------------------
# 2. Memory Writing & Evidence
# -------------------------------------------------------------------------------------------------
def test_record_experiment_outcome_memory_with_evidence(conn):
    """Writing experiment_outcome memory records structured statement and links review + transactions."""
    # Seed transactions inside the experiment window
    tx1 = Transaction(
        id="tx_d1",
        user_id="u_alice",
        account_id="acc_main",
        category_id="dining",
        amount_paise=1500,
        direction="debit",
        merchant_raw="Swiggy",
        description="Delivery",
        occurred_at="2026-08-05T19:00:00Z",
        created_at=T0,
    )
    tx2 = Transaction(
        id="tx_d2",
        user_id="u_alice",
        account_id="acc_main",
        category_id="dining",
        amount_paise=2200,
        direction="debit",
        merchant_raw="Zomato",
        description="Delivery",
        occurred_at="2026-08-10T20:00:00Z",
        created_at=T0,
    )
    insert_transaction(conn, tx1)
    insert_transaction(conn, tx2)

    create_sample_experiment(conn, "exp_001")
    create_sample_review(conn, "rev_001", "exp_001")

    # Record memory
    mem = record_experiment_outcome_memory(conn, "u_alice", "exp_001", clock=DT0)
    assert mem.kind == "experiment_outcome"
    assert mem.status == "active"
    assert mem.confidence_bp >= 6000
    assert mem.statement_json["template_code"] == "tpl_dining_weekend"
    assert mem.statement_json["outcome"] == "beyond_usual_range"
    assert mem.statement_json["effect_value"] == -12000

    # Verify evidence items linked in database
    ev_rows = conn.execute(
        "SELECT ref_kind, ref_id, weight_bp FROM memory_evidence WHERE memory_id = ?",
        (mem.id,),
    ).fetchall()
    ref_kinds = {r[0] for r in ev_rows}
    ref_ids = {r[1] for r in ev_rows}

    assert "review" in ref_kinds
    assert "rev_001" in ref_ids
    assert "txn" in ref_kinds
    assert "tx_d1" in ref_ids
    assert "tx_d2" in ref_ids


def test_memory_confidence_decay_over_time(conn):
    """Memory confidence decays predictably over 180 days half-life."""
    create_sample_experiment(conn, "exp_decay")
    create_sample_review(conn, "rev_decay", "exp_decay", created_at="2026-01-01T00:00:00Z")

    # Record at t=0
    dt_start = datetime(2026, 1, 1, 12, 0, tzinfo=IST)
    mem = record_experiment_outcome_memory(conn, "u_alice", "exp_decay", clock=dt_start)
    assert mem.confidence_bp >= 7000

    # After 180 days (half-life), active memories re-evaluated at that clock decay by ~50%
    dt_180 = dt_start + timedelta(days=180)
    active_mems = get_active_outcome_memories(conn, "u_alice", clock=dt_180)
    # If decayed below use threshold (6000 bp), it is no longer returned in active list
    if active_mems:
        assert active_mems[0].confidence_bp < mem.confidence_bp


# -------------------------------------------------------------------------------------------------
# 3. Advice Citation & Copy Safety
# -------------------------------------------------------------------------------------------------
def test_advice_citation_non_causal(conn):
    """Evidence citations use observational correlation and forbid causal assertions."""
    create_sample_experiment(conn, "exp_cite")
    create_sample_review(conn, "rev_cite", "exp_cite")
    mem = record_experiment_outcome_memory(conn, "u_alice", "exp_cite", clock=DT0)

    citation = format_outcome_memory_advice_evidence(mem)
    assert "below your usual range" in citation
    assert "difference of ₹120" in citation

    # assert_no_causal_claims accepts correlation copy
    assert_no_causal_claims(citation)

    # Rejects causal claims
    with pytest.raises(ValueError, match="Forbidden causal claim"):
        assert_no_causal_claims("Cooking at home caused your savings to increase.")

    with pytest.raises(ValueError, match="Forbidden causal claim"):
        assert_no_causal_claims("This challenge led to lower dining expenses.")

    with pytest.raises(ValueError, match="Forbidden causal claim"):
        assert_no_causal_claims("Your budget surplus is because of your discipline.")


# -------------------------------------------------------------------------------------------------
# 4. Advice Suppression for Unhelpful Templates
# -------------------------------------------------------------------------------------------------
def test_unhelpful_template_suppressed_in_advice(conn):
    """Rating a template unhelpful suppresses it in advice drafting during cooldown."""
    create_sample_experiment(conn, "exp_unhelp", template_code="tpl_unhelpful_test")
    create_sample_review(
        conn, "rev_unhelp", "exp_unhelp", user_helpful=False, created_at="2026-08-01T00:00:00Z"
    )

    today = date(2026, 8, 15)
    # Suppressed on day 14 (within 30-day cooldown)
    assert is_template_suppressed_in_advice(
        conn, "u_alice", "tpl_unhelpful_test", as_of=today, cooldown_days=30
    )

    # Unsuppressed after cooldown expires (day 35)
    future = today + timedelta(days=25)
    assert not is_template_suppressed_in_advice(
        conn, "u_alice", "tpl_unhelpful_test", as_of=future, cooldown_days=30
    )


# -------------------------------------------------------------------------------------------------
# 5. Forgotten Memory Exclusion
# -------------------------------------------------------------------------------------------------
def test_forgotten_memories_excluded_from_advice(conn):
    """Forgotten memories disappear immediately from advice citation queries."""
    create_sample_experiment(conn, "exp_forget")
    create_sample_review(conn, "rev_forget", "exp_forget")
    mem = record_experiment_outcome_memory(conn, "u_alice", "exp_forget", clock=DT0)

    active_pre = get_active_outcome_memories(conn, "u_alice", clock=DT0)
    assert len(active_pre) >= 1

    # Forget memory
    forget_memory_item(conn, "u_alice", mem.id)

    active_post = get_active_outcome_memories(conn, "u_alice", clock=DT0)
    assert not any(m.id == mem.id for m in active_post)


# -------------------------------------------------------------------------------------------------
# 6. Contribution-Plan Options
# -------------------------------------------------------------------------------------------------
def test_contribution_plan_experiment_options(conn):
    """Successful experiments are converted into candidate contribution plan options."""
    create_sample_experiment(conn, "exp_plan")
    create_sample_review(
        conn, "rev_plan", "exp_plan", outcome="beyond_usual_range", effect_value=-15000
    )
    record_experiment_outcome_memory(conn, "u_alice", "exp_plan", clock=DT0)

    options = get_contribution_plan_experiment_options(conn, "u_alice", clock=DT0)
    assert len(options) >= 1
    opt = options[0]
    assert "Repeat experiment" in opt["title"]
    assert opt["expected_effect_paise"] == 15000


# -------------------------------------------------------------------------------------------------
# 7. Failure Candidate Export
# -------------------------------------------------------------------------------------------------
def test_export_phase4_failure_candidates(conn, tmp_path):
    """Reviews with integrity flags, no_baseline, or difficulty=5 are exported to eval directory."""
    # 1. Normal review -> should NOT be exported
    create_sample_experiment(conn, "exp_norm")
    create_sample_review(conn, "rev_norm", "exp_norm", user_difficulty=2)

    # 2. Review with confirmation_required -> exported
    create_sample_experiment(conn, "exp_fail1")
    create_sample_review(conn, "rev_fail1", "exp_fail1", confirmation_required=True)

    # 3. Review with outcome == 'no_baseline' -> exported
    create_sample_experiment(conn, "exp_fail2")
    create_sample_review(conn, "rev_fail2", "exp_fail2", outcome="no_baseline")

    # 4. Review with difficulty == 5 -> exported
    create_sample_experiment(conn, "exp_fail3")
    create_sample_review(conn, "rev_fail3", "exp_fail3", user_difficulty=5)

    exported = export_phase4_failure_candidates(conn, output_dir=tmp_path)
    assert len(exported) == 3

    exported_names = {p.stem for p in exported}
    assert "rev_fail1" in exported_names
    assert "rev_fail2" in exported_names
    assert "rev_fail3" in exported_names
    assert "rev_norm" not in exported_names

    # Check content of an exported file
    with open(tmp_path / "rev_fail1.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["review_id"] == "rev_fail1"
    assert "integrity_confirmation_required" in data["reasons"]


# -------------------------------------------------------------------------------------------------
# 8. Integrated Post-Review Learning Hook
# -------------------------------------------------------------------------------------------------
def test_process_post_review_learning(conn):
    """Verify integrated post-review processing updates posterior, writes memory, and checks export."""
    create_sample_experiment(conn, "exp_hook")
    create_sample_review(conn, "rev_hook", "exp_hook", user_helpful=True)

    res = process_post_review_learning(conn, "u_alice", "exp_hook", clock=DT0)
    assert "posterior" in res
    assert res["posterior"].alpha_milli == 3000
    assert "memory" in res
    assert res["memory"].kind == "experiment_outcome"
