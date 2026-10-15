"""
Bounded Feedback Learning Engine (PLAN_PHASE3 Section 5.16 & Stage 3.14).

Invariants:
1. Small, explainable learner using Beta conjugate posteriors (alpha, beta in thousandths).
2. Clamped sensitivity multiplier m = clamp(1 + eta * (2p - 1), m_min, m_max).
3. Zero exploration: strictly uses posterior mean p (no Thompson sampling or random exploration).
4. Hard floors: alerts for 'exceeded' budgets, 'not_covered' firm commitments, and 'off_track'
   goals are never reduced below base severity or suppressed.
5. Contextual dismissals (e.g. festival, travel) go to memory as exceptions, never to learning.
6. Transparency: learned multipliers are inspectable, explainable in why-text only when severity
   changes, and fully resettable per subject or globally.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Literal

from copilot.audit.events import record_event
from copilot.config.phase2 import AlertsConfig
from copilot.config.phase3 import LearningConfig, load_learning_config
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import (
    delete_feedback_stat,
    get_feedback_stat,
    upsert_feedback_stat,
)
from copilot.db.repo_phase3 import (
    list_feedback_stats as repo_list_feedback_stats,
)
from copilot.models.agentic import AlertSeverity
from copilot.models.phase3 import FeedbackStat

logger = logging.getLogger(__name__)

SEV_RANK: dict[str, int] = {
    "info": 1,
    "notice": 2,
    "warning": 3,
    "critical": 4,
}


def compute_posterior_mean(alpha_milli: int, beta_milli: int) -> float:
    """
    Compute posterior mean p = alpha / (alpha + beta) from integer milli-counts.
    Returns float in range (0.0, 1.0).
    """
    total = alpha_milli + beta_milli
    if total <= 0:
        return 0.5
    return alpha_milli / total


def compute_sensitivity_multiplier(p: float, config: LearningConfig) -> float:
    """
    Compute sensitivity multiplier:
        m = clamp(1 + eta * (2p - 1), m_min, m_max)
    """
    raw_m = 1.0 + config.eta * (2.0 * p - 1.0)
    clamped_m = max(config.m_min, min(config.m_max, raw_m))
    return round(clamped_m, 4)


def get_learned_multiplier(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str,
    subject_key: str,
    config: LearningConfig | None = None,
) -> tuple[float, float, int, int]:
    """
    Retrieve learned sensitivity multiplier, posterior mean p, alpha_milli, and beta_milli
    for a given user and subject. Falls back to config priors if unrecorded.
    Returns (multiplier, p, alpha_milli, beta_milli).
    """
    cfg = config or load_learning_config()
    stat = get_feedback_stat(conn, user_id, subject_kind, subject_key)
    if stat is not None:
        alpha_milli = stat.alpha_milli
        beta_milli = stat.beta_milli
    else:
        alpha_milli = cfg.prior_alpha * 1000
        beta_milli = cfg.prior_beta * 1000

    p = compute_posterior_mean(alpha_milli, beta_milli)
    multiplier = compute_sensitivity_multiplier(p, cfg)
    return multiplier, p, alpha_milli, beta_milli


def record_feedback(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str,
    subject_key: str,
    signal: Literal["useful", "not_useful"],
    config: LearningConfig | None = None,
    clock: datetime | None = None,
    actor: str = "user",
    run_id: str | None = None,
) -> FeedbackStat:
    """
    Update Beta posterior state based on explicit user feedback signal:
    - useful (acknowledged, acted on, approved) -> alpha += 1.0 (1000 milli)
    - not_useful (dismissed without reason, muted, rejected) -> beta += 1.0 (1000 milli)
    """
    cfg = config or load_learning_config()
    existing = get_feedback_stat(conn, user_id, subject_kind, subject_key)

    if existing is not None:
        alpha_milli = existing.alpha_milli
        beta_milli = existing.beta_milli
    else:
        alpha_milli = cfg.prior_alpha * 1000
        beta_milli = cfg.prior_beta * 1000

    before_data = {
        "alpha_milli": alpha_milli,
        "beta_milli": beta_milli,
        "p": round(compute_posterior_mean(alpha_milli, beta_milli), 4),
    }

    if signal == "useful":
        alpha_milli += 1000
    elif signal == "not_useful":
        beta_milli += 1000
    else:
        raise ValueError(f"Unknown feedback signal '{signal}'")

    now = clock if isinstance(clock, datetime) else now_utc()
    updated_at = to_utc_iso(now)

    upsert_feedback_stat(
        conn,
        user_id=user_id,
        subject_kind=subject_kind,
        subject_key=subject_key,
        alpha_milli=alpha_milli,
        beta_milli=beta_milli,
        updated_at=updated_at,
    )

    new_p = compute_posterior_mean(alpha_milli, beta_milli)
    new_m = compute_sensitivity_multiplier(new_p, cfg)

    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="learning_updated",
        reason=f"Recorded '{signal}' feedback for {subject_kind}:{subject_key}",
        run_id=run_id,
        entity_type="feedback_stat",
        entity_id=f"{subject_kind}:{subject_key}",
        before_data=before_data,
        after_data={
            "alpha_milli": alpha_milli,
            "beta_milli": beta_milli,
            "p": round(new_p, 4),
            "multiplier": new_m,
            "signal": signal,
        },
        clock=clock,
    )

    updated_stat = get_feedback_stat(conn, user_id, subject_kind, subject_key)
    if updated_stat is None:
        raise RuntimeError(f"Failed to fetch updated feedback stat for {subject_key}")
    return updated_stat


def is_hard_floor_alert(
    context: dict[str, Any],
    config: LearningConfig | None = None,
) -> bool:
    """
    Check if an alert candidate matches any hard floor criterion from PLAN_PHASE3 Section 5.16:
    1. exceeded budget: budget_status == 'exceeded' or spent_paise >= limit_paise (when limit > 0)
    2. not_covered commitment: status in ('not_covered', 'shortfall')
    3. off_track goal: 'off_track' in goals_affected
    """
    cfg = config or load_learning_config()
    floors = cfg.hard_floor_severities

    # 1. Budget status check
    b_status = str(context.get("budget_status", "")).lower()
    spent = int(context.get("spent_paise", 0))
    limit = int(context.get("limit_paise", 0))
    if "exceeded" in floors:
        if b_status == "exceeded" or (limit > 0 and spent >= limit):
            return True

    # 2. Commitment status check
    cmt_status = str(context.get("commitment_status", "")).lower()
    if "not_covered" in floors:
        if cmt_status in ("not_covered", "shortfall"):
            return True

    # 3. Goal status check
    goals_affected = context.get("goals_affected", [])
    if "off_track" in floors:
        if "off_track" in goals_affected:
            return True

    return False


def apply_learning_to_alert(
    base_score_bp: int,
    base_severity: AlertSeverity | None,
    multiplier: float,
    is_hard_floor: bool,
    config: AlertsConfig,
) -> tuple[int, AlertSeverity | None, str | None]:
    """
    Apply learned sensitivity multiplier to an alert's score and severity.
    Enforces hard floors: learning can never suppress or reduce hard floor alerts below
    base severity.
    Returns:
        (adjusted_score_bp, adjusted_severity, learning_why_note)
    """
    if is_hard_floor:
        # Multiplier is clamped to at least 1.0 (never damps)
        effective_m = max(1.0, multiplier)
    else:
        effective_m = multiplier

    adjusted_score_bp = min(10000, max(0, int(round(base_score_bp * effective_m))))

    # Map adjusted score to severity tier
    thresholds = config.tier_thresholds_bp
    adjusted_severity: AlertSeverity | None = None
    if adjusted_score_bp >= thresholds.get("critical", 9000):
        adjusted_severity = "critical"
    elif adjusted_score_bp >= thresholds.get("warning", 7500):
        adjusted_severity = "warning"
    elif adjusted_score_bp >= thresholds.get("notice", 5000):
        adjusted_severity = "notice"
    elif adjusted_score_bp >= thresholds.get("info", 2500):
        adjusted_severity = "info"

    # Enforce hard floor severity lower-bound
    if is_hard_floor and base_severity is not None:
        if adjusted_severity is None or (
            SEV_RANK.get(adjusted_severity, 0) < SEV_RANK.get(base_severity, 0)
        ):
            adjusted_severity = base_severity
            adjusted_score_bp = max(adjusted_score_bp, base_score_bp)

    # Determine learning why note: ONLY generated if severity actually changed
    learning_why_note: str | None = None
    if adjusted_severity != base_severity:
        if adjusted_score_bp < base_score_bp:
            learning_why_note = (
                "shown at lower priority because you usually dismiss these alerts"
            )
        elif adjusted_score_bp > base_score_bp:
            learning_why_note = (
                "shown at higher priority because you usually find these alerts useful"
            )

    return adjusted_score_bp, adjusted_severity, learning_why_note


def order_advice_by_utility(
    conn: sqlite3.Connection,
    user_id: str,
    advice_items: list[Any],
    config: LearningConfig | None = None,
) -> list[Any]:
    """
    Order advice drafts or items within a response by posterior mean utility p descending.
    Ties broken stably by original position / ID.
    """
    cfg = config or load_learning_config()

    def get_utility(item: Any) -> tuple[float, str]:
        # Extract kind and subject from item (dict or model instance)
        if isinstance(item, dict):
            evidence = item.get("evidence") or item.get("evidence_json") or {}
            if isinstance(evidence, str):
                import json
                try:
                    evidence = json.loads(evidence)
                except Exception:
                    evidence = {}
            f_kind = str(evidence.get("kind") or item.get("kind", "general"))
            subject = str(
                evidence.get("category_id")
                or evidence.get("merchant_name")
                or evidence.get("goal_id")
                or item.get("subject_key")
                or "global"
            )
            item_id = str(item.get("id", ""))
        else:
            evidence = getattr(item, "evidence", None) or getattr(item, "evidence_json", None)
            if isinstance(evidence, str):
                import json
                try:
                    evidence = json.loads(evidence)
                except Exception:
                    evidence = {}
            if isinstance(evidence, dict):
                f_kind = str(evidence.get("kind", "general"))
                subject = str(
                    evidence.get("category_id")
                    or evidence.get("merchant_name")
                    or evidence.get("goal_id")
                    or "global"
                )
            else:
                f_kind = getattr(item, "kind", "general")
                subject = getattr(item, "subject_key", "global")
            item_id = str(getattr(item, "id", ""))

        subj_key = f"{f_kind}:{subject}"
        _, p, _, _ = get_learned_multiplier(conn, user_id, "advice_kind", subj_key, cfg)
        return p, item_id

    return sorted(advice_items, key=lambda it: get_utility(it)[0], reverse=True)


def reset_learning(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str | None = None,
    subject_key: str | None = None,
    clock: datetime | None = None,
    actor: str = "user",
) -> int:
    """
    Reset feedback statistics for a tenant, restoring prior distribution alpha_0, beta_0.
    Returns number of reset subjects.
    """
    deleted_count = delete_feedback_stat(
        conn, user_id=user_id, subject_kind=subject_kind, subject_key=subject_key
    )

    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="learning_reset",
        reason=f"Reset feedback stats for user {user_id} (subject_key={subject_key or 'all'})",
        entity_type="feedback_stat",
        metadata={
            "user_id": user_id,
            "subject_kind": subject_kind,
            "subject_key": subject_key,
            "reset_count": deleted_count,
        },
        clock=clock,
    )
    return deleted_count


def list_tenant_learning_stats(
    conn: sqlite3.Connection,
    user_id: str,
    config: LearningConfig | None = None,
) -> list[dict[str, Any]]:
    """
    List all active feedback stats for a tenant with computed p and multiplier.
    """
    cfg = config or load_learning_config()
    stats = repo_list_feedback_stats(conn, user_id)
    results: list[dict[str, Any]] = []

    for s in stats:
        p = compute_posterior_mean(s.alpha_milli, s.beta_milli)
        m = compute_sensitivity_multiplier(p, cfg)
        is_floor = (
            "exceeded" in s.subject_key
            or "not_covered" in s.subject_key
            or "off_track" in s.subject_key
        )
        results.append({
            "id": s.id,
            "user_id": s.user_id,
            "subject_kind": s.subject_kind,
            "subject_key": s.subject_key,
            "alpha_milli": s.alpha_milli,
            "beta_milli": s.beta_milli,
            "alpha": s.alpha_milli / 1000.0,
            "beta": s.beta_milli / 1000.0,
            "p": round(p, 4),
            "multiplier": m,
            "hard_floor_protected": is_floor,
            "updated_at": s.updated_at,
        })
    return results
