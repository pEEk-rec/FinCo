"""
Stage 4.8: Learning loop into memory and recommendations.
(PLAN_PHASE4 Section 5.10 & Stage 4.8)

Invariants:
1. Posterior updates: Beta conjugate model in feedback_stats (subject_kind = 'challenge_template').
   Reward = completed & reviewed with user_helpful not false.
   Abandoned = failure.
   Dismissed offer = small failure weight (dismiss_weight, default 0.25).
2. Memory: Writes 'experiment_outcome' memory with structured statements and evidence links
   (review id, window transactions). Decays per Phase 3 memory half-life.
3. Advice integration:
   - Advice drafting cites active experiment_outcome memories as evidence without causal claims.
   - Unhelpful templates are suppressed in advice / offers for the cooldown duration.
   - Contribution-plan options include repeating successful experiments.
   - Forgotten / retired memories are excluded from advice drafting.
4. Failures become eval cases:
   - Reviews with integrity flags (confirmation_required), no_baseline, or difficulty 5 are
     exported to eval/candidates/phase4/ for owner evaluation (SDLC flywheel; no runtime self-mod).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from copilot.config.phase4 import OffersConfig, load_offers_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.memory import (
    compute_memory_confidence,
    determine_memory_status,
    load_memory_config,
)
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.repo_phase3 import (
    get_feedback_stat,
    insert_memory_evidence,
    insert_memory_item,
    list_memory_evidence,
    list_memory_items,
    upsert_feedback_stat,
)
from copilot.db.repo_phase4 import get_experiment, get_experiment_review
from copilot.models.phase3 import FeedbackStat, MemoryEvidence, MemoryItem

logger = logging.getLogger(__name__)

FORBIDDEN_CAUSAL_TERMS = [
    "caused",
    "causes",
    "because of",
    "guaranteed",
    "leads to",
    "led to",
    "resulted from",
    "responsible for",
    "made you save",
]


# ---------------------------------------------------------------------------------------------
# 1. Posterior Updates for Challenge Templates (Beta Conjugate Model)
# ---------------------------------------------------------------------------------------------
def get_template_posterior(
    conn: sqlite3.Connection,
    user_id: str,
    template_code: str,
    config: OffersConfig | None = None,
) -> tuple[int, int, float]:
    """
    Retrieve the current Beta posterior parameters (alpha_milli, beta_milli, mean)
    for a challenge template. Falls back to config priors if unrecorded.
    """
    cfg = config or load_offers_config()
    stat = get_feedback_stat(conn, user_id, "challenge_template", template_code)
    if stat is not None:
        alpha_milli = stat.alpha_milli
        beta_milli = stat.beta_milli
    else:
        alpha_milli = cfg.beta_prior_alpha * 1000
        beta_milli = cfg.beta_prior_beta * 1000

    total = alpha_milli + beta_milli
    mean = alpha_milli / total if total > 0 else 0.5
    return alpha_milli, beta_milli, mean


def update_template_posterior(
    conn: sqlite3.Connection,
    user_id: str,
    template_code: str,
    event_type: Literal["completed_review", "abandoned", "dismissed_offer"],
    user_helpful: bool | None = None,
    config: OffersConfig | None = None,
    clock: datetime | None = None,
) -> FeedbackStat:
    """
    Update Beta conjugate posterior for a challenge template:
    - completed_review with user_helpful != False: +1.0 alpha (1000 milli)
    - completed_review with user_helpful == False: +1.0 beta (1000 milli)
    - abandoned: +1.0 beta (1000 milli)
    - dismissed_offer: +dismiss_weight beta (default 0.25 -> 250 milli)
    """
    cfg = config or load_offers_config()
    now_dt = clock or datetime.now(tz=IST)
    now_iso = to_utc_iso(now_dt)

    current_alpha, current_beta, _ = get_template_posterior(conn, user_id, template_code, cfg)

    if event_type == "completed_review":
        if user_helpful is False:
            delta_alpha = 0
            delta_beta = 1000
        else:
            delta_alpha = 1000
            delta_beta = 0
    elif event_type == "abandoned":
        delta_alpha = 0
        delta_beta = 1000
    elif event_type == "dismissed_offer":
        delta_alpha = 0
        delta_beta = int(round(cfg.dismiss_weight * 1000))
    else:
        raise ValueError(f"Unknown event type: {event_type}")

    stat = FeedbackStat(
        id=f"fbs_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        subject_kind="challenge_template",
        subject_key=template_code,
        alpha_milli=current_alpha + delta_alpha,
        beta_milli=current_beta + delta_beta,
        updated_at=now_iso,
    )

    upsert_feedback_stat(
        conn,
        user_id,
        "challenge_template",
        template_code,
        current_alpha + delta_alpha,
        current_beta + delta_beta,
        now_iso,
    )
    return stat


# ---------------------------------------------------------------------------------------------
# 2. Writing 'experiment_outcome' Memory Item
# ---------------------------------------------------------------------------------------------
def record_experiment_outcome_memory(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> MemoryItem:
    """
    Write a structured 'experiment_outcome' behavioural memory item with evidence links
    (review id, transaction IDs in window).
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found for user {user_id}")

    rev = get_experiment_review(conn, user_id, experiment_id)
    if rev is None:
        raise ValueError(f"Experiment review for {experiment_id} not found")

    now_dt = clock or datetime.now(tz=IST)
    now_iso = to_utc_iso(now_dt)

    template_code = exp.template_code or "custom_experiment"
    metric_code = exp.metric_def_json.get("metric", "unknown")

    statement = {
        "template_code": template_code,
        "experiment_id": exp.id,
        "title": exp.title,
        "metric_code": metric_code,
        "outcome": rev.outcome,
        "effect_value": rev.effect_value,
        "target_met": rev.target_met,
        "user_helpful": rev.user_helpful,
        "user_difficulty": rev.user_difficulty,
        "window_start": exp.window_start,
        "window_end": exp.window_end,
    }

    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
    user_confirmed = rev.user_helpful is not None

    item = MemoryItem(
        id=memory_id,
        user_id=user_id,
        kind="experiment_outcome",
        subject_key=f"challenge_template:{template_code}",
        statement_json=statement,
        source="observed",
        status="active",
        prior_bp=8000,
        user_confirmed=user_confirmed,
        confidence_bp=8000,
        created_at=now_iso,
        last_evidence_at=rev.created_at,
        last_confirmed_at=now_iso if user_confirmed else None,
    )
    insert_memory_item(conn, item)

    # 1. Link Review as Evidence
    ev_rev = MemoryEvidence(
        id=f"mev_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        memory_id=memory_id,
        polarity="supports",
        ref_kind="review",
        ref_id=rev.id,
        observed_at=rev.created_at,
        weight_bp=6000,
        created_at=now_iso,
    )
    insert_memory_evidence(conn, ev_rev)

    # 2. Link Window Transactions as Evidence (up to 10 matching transactions)
    categories = exp.metric_def_json.get("categories", [])
    if categories:
        placeholders = ",".join("?" for _ in categories)
        tx_rows = conn.execute(
            f"""
            SELECT id, occurred_at FROM transactions
            WHERE user_id = ?
              AND category_id IN ({placeholders})
              AND occurred_at >= ? AND occurred_at <= ?
            ORDER BY occurred_at DESC
            LIMIT 10
            """,
            (user_id, *categories, f"{exp.window_start}T00:00:00Z", f"{exp.window_end}T23:59:59Z"),
        ).fetchall()
        for tx_id, tx_occ in tx_rows:
            ev_tx = MemoryEvidence(
                id=f"mev_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                memory_id=memory_id,
                polarity="supports",
                ref_kind="txn",
                ref_id=tx_id,
                observed_at=tx_occ,
                weight_bp=1000,
                created_at=now_iso,
            )
            insert_memory_evidence(conn, ev_tx)

    # Recompute confidence with decay
    cfg = load_memory_config()
    ev_list = list_memory_evidence(conn, user_id, memory_id)
    conf_bp, _, _ = compute_memory_confidence(item, ev_list, now_dt, cfg)

    # Confidence is evaluated dynamically in memory
    item.confidence_bp = conf_bp

    return item


# ---------------------------------------------------------------------------------------------
# 3. Advice & Recommendations Integration (Non-causal Wording & Suppression)
# ---------------------------------------------------------------------------------------------
def assert_no_causal_claims(text: str) -> None:
    """
    Ensure advice or narration copy never claims causation between an intervention
    and a financial outcome (correlation only: 'when you did X, Y was ₹Z').
    """
    lower = text.lower()
    for term in FORBIDDEN_CAUSAL_TERMS:
        if term in lower:
            raise ValueError(f"Forbidden causal claim found: '{term}' in '{text}'")


def format_outcome_memory_advice_evidence(memory_item: MemoryItem) -> str:
    """
    Format an active experiment_outcome memory into an evidence statement for advice drafting.
    Cites observed spending correlation without causal assertions.
    """
    st = memory_item.statement_json
    title = st.get("title", "your challenge")
    w_start = st.get("window_start", "")
    outcome = st.get("outcome", "")
    effect_val = st.get("effect_value", 0)

    try:
        dt_start = date.fromisoformat(w_start)
        month_name = dt_start.strftime("%B")
    except Exception:
        month_name = "recently"

    if outcome == "beyond_usual_range":
        outcome_phrase = "below your usual range"
    elif outcome == "within_usual_range":
        outcome_phrase = "within your usual range"
    else:
        outcome_phrase = "tracked"

    effect_rupees = abs(effect_val) // 100
    statement = (
        f"When you tried {title} in {month_name}, "
        f"spending was {outcome_phrase} (difference of ₹{effect_rupees:,})."
    )

    assert_no_causal_claims(statement)
    return statement


def is_template_suppressed_in_advice(
    conn: sqlite3.Connection,
    user_id: str,
    template_code: str,
    as_of: date | None = None,
    cooldown_days: int | None = None,
) -> bool:
    """
    Check if a template is suppressed in advice because the user recently rated it unhelpful.
    """
    cfg = load_offers_config()
    limit_days = cooldown_days or cfg.cooldown_days
    today = as_of or datetime.now(tz=IST).date()
    cutoff_iso = f"{(today - timedelta(days=limit_days)).isoformat()}T00:00:00Z"

    row = conn.execute(
        """
        SELECT r.id FROM experiment_reviews r
        JOIN experiments e ON r.experiment_id = e.id
        WHERE r.user_id = ?
          AND e.template_code = ?
          AND r.user_helpful = 0
          AND r.created_at >= ?
        LIMIT 1
        """,
        (user_id, template_code, cutoff_iso),
    ).fetchone()

    return row is not None


def get_active_outcome_memories(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> list[MemoryItem]:
    """
    Retrieve active experiment_outcome memories that meet the 'use' confidence threshold (6000 bp).
    Forgotten, retired, or rejected memories are excluded.
    """
    now_dt = clock or datetime.now(tz=IST)
    mem_cfg = load_memory_config()
    use_threshold = mem_cfg.get("thresholds_bp", {}).get("use", 6000)

    items = list_memory_items(conn, user_id, kind="experiment_outcome")
    active: list[MemoryItem] = []

    for it in items:
        if it.status in ("forgotten", "retired", "rejected"):
            continue

        ev_list = list_memory_evidence(conn, user_id, it.id)
        conf_bp, s_bp, c_bp = compute_memory_confidence(it, ev_list, now_dt, mem_cfg)
        status = determine_memory_status(it, conf_bp, s_bp, c_bp, len(ev_list), mem_cfg)

        if status == "active" and conf_bp >= use_threshold:
            it.confidence_bp = conf_bp
            active.append(it)

    return active


def get_contribution_plan_experiment_options(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Derive candidate options for contribution plans based on historical experiments
    that landed below the usual range.
    """
    active_mems = get_active_outcome_memories(conn, user_id, clock)
    options: list[dict[str, Any]] = []

    for m in active_mems:
        st = m.statement_json
        outcome = st.get("outcome")
        effect_val = st.get("effect_value", 0)
        title = st.get("title", "challenge")
        template_code = st.get("template_code", "")

        # Only include experiments that successfully reduced spend below usual range
        if outcome == "beyond_usual_range" or (st.get("target_met") and effect_val < 0):
            saving_paise = abs(effect_val)
            saving_rupees = saving_paise // 100
            options.append({
                "id": f"opt_exp_{uuid.uuid4().hex[:8]}",
                "template_code": template_code,
                "title": f"Repeat experiment '{title}': historical effect ~₹{saving_rupees:,}",
                "expected_effect_paise": saving_paise,
                "evidence_memory_id": m.id,
            })

    return options


# ---------------------------------------------------------------------------------------------
# 4. Failures Become Eval Cases (Agentic SDLC Flywheel)
# ---------------------------------------------------------------------------------------------
def export_phase4_failure_candidates(
    conn: sqlite3.Connection,
    output_dir: str | Path | None = None,
) -> list[Path]:
    """
    Export reviews with integrity questions (confirmation_required), no_baseline,
    or user difficulty 5 to eval/candidates/phase4/ as draft evaluation test cases.
    """
    if output_dir is None:
        target_dir = PROJECT_ROOT / "eval" / "candidates" / "phase4"
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    exported_files: list[Path] = []

    # Query reviews matching failure criteria
    rows = conn.execute(
        """
        SELECT r.id, r.user_id, r.experiment_id, r.observed_value, r.outcome,
               r.rank_p_bp, r.effect_value, r.target_met, r.integrity_json,
               r.data_quality_json, r.user_difficulty, r.user_helpful, r.created_at,
               e.template_code, e.title, e.hypothesis_json, e.metric_def_json
        FROM experiment_reviews r
        JOIN experiments e ON r.experiment_id = e.id
        """
    ).fetchall()

    for r in rows:
        rev_id = r[0]
        outcome = r[4]
        integ = json.loads(r[8]) if r[8] else {}
        difficulty = r[10]

        reasons = []
        if integ.get("confirmation_required") is True:
            reasons.append("integrity_confirmation_required")
        if outcome == "no_baseline":
            reasons.append("no_baseline_review")
        if difficulty == 5:
            reasons.append("max_difficulty_rating_5")

        if not reasons:
            continue

        candidate_data = {
            "review_id": rev_id,
            "experiment_id": r[2],
            "user_id": r[1],
            "reasons": reasons,
            "template_code": r[13],
            "title": r[14],
            "hypothesis": json.loads(r[15]) if r[15] else {},
            "metric_def": json.loads(r[16]) if r[16] else {},
            "review": {
                "observed_value": r[3],
                "outcome": outcome,
                "rank_p_bp": r[5],
                "effect_value": r[6],
                "target_met": bool(r[7]),
                "integrity": integ,
                "user_difficulty": difficulty,
                "user_helpful": r[11],
                "created_at": r[12],
            },
        }

        candidate_path = target_dir / f"{rev_id}.json"
        with open(candidate_path, "w", encoding="utf-8") as f:
            json.dump(candidate_data, f, indent=2)

        exported_files.append(candidate_path)

    return exported_files


# ---------------------------------------------------------------------------------------------
# 5. Integrated Review Hook
# ---------------------------------------------------------------------------------------------
def process_post_review_learning(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> dict[str, Any]:
    """
    Run full learning loop after an experiment review is recorded:
    1. Update template posterior
    2. Write experiment_outcome memory
    3. Export failure candidates if criteria met
    """
    exp = get_experiment(conn, user_id, experiment_id)
    rev = get_experiment_review(conn, user_id, experiment_id)
    if exp is None or rev is None:
        return {}

    template_code = exp.template_code or "custom"

    # 1. Update Posterior
    stat = update_template_posterior(
        conn, user_id, template_code, "completed_review", rev.user_helpful, clock=clock
    )

    # 2. Write Memory
    mem = record_experiment_outcome_memory(conn, user_id, experiment_id, clock=clock)

    # 3. Export Failure Candidate if needed
    exported = export_phase4_failure_candidates(conn)

    return {
        "posterior": stat,
        "memory": mem,
        "exported_count": len(exported),
    }
