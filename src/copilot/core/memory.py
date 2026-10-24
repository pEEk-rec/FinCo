"""
Behavioural memory store, observers, and deterministic confidence decay
(PLAN_PHASE3 Section 5.8, 5.9, Stage 3.8).

Key invariants:
1. Zero LLM provider calls in any memory function. All logic is 100% deterministic.
2. Structured statements only; never store free prose beyond bounded allowed reason labels.
3. Observed memories start as 'candidate'; become 'active' when confidence >= use threshold
   (6000 bp) or immediately when confirmed by the user.
4. Forgetting removes content from all query paths while recording a content-free audit event.
5. Multi-tenant isolation enforced on every query and mutation.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo_phase3 import (
    forget_memory_item,
    get_memory_by_subject,
    get_memory_item,
    insert_memory_evidence,
    insert_memory_item,
    list_memory_evidence,
    list_memory_items,
    update_memory_statement,
    update_memory_status,
)
from copilot.models.phase3 import MemoryEvidence, MemoryItem


# ---------------------------------------------------------------------------------------------
# Configuration Loader
# ---------------------------------------------------------------------------------------------
def load_memory_config() -> dict[str, Any]:
    """Load behavioural memory and decay configuration from config/memory.yaml."""
    cfg_path = Path(__file__).resolve().parents[3] / "config" / "memory.yaml"
    if not cfg_path.exists():
        return {
            "advice_cooldown_days": 30,
            "thresholds_bp": {"use": 6000, "stale": 4000, "retire": 2000},
            "half_lives_days": {
                "recurring_pattern": 90,
                "contextual_exception": 365,
                "advice_feedback": 120,
                "merchant_habit": 180,
                "experiment_outcome": 180,
                "preference": 0,
            },
            "support_cap_bp": 10000,
            "min_contradictions_to_retire": 2,
            "k_s": 1.0,
            "k_c": 1.5,
            "allowed_exception_reasons": [
                "festival",
                "travel",
                "one_off_purchase",
                "medical",
                "family_event",
                "other",
            ],
            "observers": {
                "min_weeks": 2,
                "weekend_ratio_threshold_bp": 15000,
                "month_start_threshold_bp": 5000,
                "payday_spike_threshold_bp": 4000,
            },
        }
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------------------------
# Candidate Data Classes
# ---------------------------------------------------------------------------------------------
@dataclass
class CandidateEvidence:
    polarity: Literal["supports", "contradicts"]
    ref_kind: Literal["txn", "advice", "audit_event", "anomaly", "investigation", "capture_label"]
    ref_id: str
    observed_at: str
    weight_bp: int = 1000


@dataclass
class MemoryCandidate:
    kind: Literal[
        "recurring_pattern",
        "contextual_exception",
        "advice_feedback",
        "preference",
        "merchant_habit",
    ]
    subject_key: str
    statement_json: dict[str, Any]
    source: Literal["observed", "user_stated", "feedback", "capture_label"]
    prior_bp: int = 3000
    user_confirmed: bool = False
    evidence_items: list[CandidateEvidence] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# 5 Deterministic Observers (PLAN_PHASE3 Section 5.8)
# ---------------------------------------------------------------------------------------------


def observe_recurring_patterns(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime,
    config: dict[str, Any] | None = None,
) -> list[MemoryCandidate]:
    """
    Observer 1: Detects stable spend patterns (weekend-heavy, month-start, payday spikes)
    across complete/recent transaction activity.
    """
    cfg = config or load_memory_config()
    obs_cfg = cfg.get("observers", {})
    min_weeks = obs_cfg.get("min_weeks", 2)
    weekend_ratio_threshold_bp = obs_cfg.get("weekend_ratio_threshold_bp", 15000)
    month_start_threshold_bp = obs_cfg.get("month_start_threshold_bp", 5000)
    payday_spike_threshold_bp = obs_cfg.get("payday_spike_threshold_bp", 4000)

    rows = conn.execute(
        """
        SELECT id, category_id, occurred_at, amount_paise
        FROM transactions
        WHERE user_id = ? AND direction = 'debit'
          AND is_duplicate_of IS NULL AND excluded_from_spend = 0
        ORDER BY occurred_at ASC
        """,
        (user_id,),
    ).fetchall()

    if not rows:
        return []

    # Group transactions by category_id
    cat_txs: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cid = r[1] or "uncategorized"
        cat_txs.setdefault(cid, []).append(
            {
                "id": r[0],
                "category_id": cid,
                "occurred_at": r[2],
                "amount_paise": r[3],
            }
        )

    candidates: list[MemoryCandidate] = []

    for cat_id, tx_list in cat_txs.items():
        if len(tx_list) < 4:
            continue

        # Parse timestamps to dates and evaluate span in weeks
        parsed_dates = []
        for tx in tx_list:
            try:
                dt = from_utc_iso(tx["occurred_at"])
                parsed_dates.append((dt, tx))
            except Exception:
                continue

        if not parsed_dates:
            continue

        earliest_dt = min(d[0] for d in parsed_dates)
        latest_dt = max(d[0] for d in parsed_dates)
        span_days = (latest_dt.date() - earliest_dt.date()).days
        if span_days < (min_weeks * 7 - 3):
            # Not enough weeks of history to conclude a recurring pattern
            continue

        # 1. Pattern: weekend_heavy
        weekend_spend = 0
        weekday_spend = 0
        weekend_txs: list[dict[str, Any]] = []

        for dt, tx in parsed_dates:
            weekday = dt.weekday()  # Mon=0, ..., Fri=4, Sat=5, Sun=6
            if weekday in (5, 6):
                weekend_spend += tx["amount_paise"]
                weekend_txs.append(tx)
            else:
                weekday_spend += tx["amount_paise"]

        if weekday_spend > 0 and weekend_spend > 0:
            avg_weekend_daily = weekend_spend / 2.0
            avg_weekday_daily = weekday_spend / 5.0
            if avg_weekday_daily > 0:
                ratio_bp = int((avg_weekend_daily / avg_weekday_daily) * 10000)
                if ratio_bp >= weekend_ratio_threshold_bp:
                    ev_items = [
                        CandidateEvidence(
                            polarity="supports",
                            ref_kind="txn",
                            ref_id=tx["id"],
                            observed_at=tx["occurred_at"],
                            weight_bp=1200,
                        )
                        for tx in weekend_txs[-8:]
                    ]
                    candidates.append(
                        MemoryCandidate(
                            kind="recurring_pattern",
                            subject_key=f"category:{cat_id}",
                            statement_json={
                                "category": cat_id,
                                "pattern": "weekend_heavy",
                                "ratio_bp": ratio_bp,
                            },
                            source="observed",
                            prior_bp=3000,
                            user_confirmed=False,
                            evidence_items=ev_items,
                        )
                    )
                    continue  # Found primary pattern for this category

        # 2. Pattern: month_start_heavy (spend in days 1 to 7)
        total_spend = sum(tx["amount_paise"] for _, tx in parsed_dates)
        month_start_spend = 0
        month_start_txs: list[dict[str, Any]] = []
        for dt, tx in parsed_dates:
            if dt.day <= 7:
                month_start_spend += tx["amount_paise"]
                month_start_txs.append(tx)

        if total_spend > 0:
            month_start_bp = int((month_start_spend * 10000) // total_spend)
            if month_start_bp >= month_start_threshold_bp:
                ev_items = [
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="txn",
                        ref_id=tx["id"],
                        observed_at=tx["occurred_at"],
                        weight_bp=1500,
                    )
                    for tx in month_start_txs[-6:]
                ]
                candidates.append(
                    MemoryCandidate(
                        kind="recurring_pattern",
                        subject_key=f"category:{cat_id}",
                        statement_json={
                            "category": cat_id,
                            "pattern": "month_start_heavy",
                            "ratio_bp": month_start_bp,
                        },
                        source="observed",
                        prior_bp=3000,
                        user_confirmed=False,
                        evidence_items=ev_items,
                    )
                )
                continue

        # 3. Pattern: payday_spike (spend in days 1 to 3 or 28 to 31)
        payday_spend = 0
        payday_txs: list[dict[str, Any]] = []
        for dt, tx in parsed_dates:
            if dt.day in (1, 2, 3):
                payday_spend += tx["amount_paise"]
                payday_txs.append(tx)

        if total_spend > 0:
            payday_bp = int((payday_spend * 10000) // total_spend)
            if payday_bp >= payday_spike_threshold_bp:
                ev_items = [
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="txn",
                        ref_id=tx["id"],
                        observed_at=tx["occurred_at"],
                        weight_bp=1500,
                    )
                    for tx in payday_txs[-6:]
                ]
                candidates.append(
                    MemoryCandidate(
                        kind="recurring_pattern",
                        subject_key=f"category:{cat_id}",
                        statement_json={
                            "category": cat_id,
                            "pattern": "payday_spike",
                            "ratio_bp": payday_bp,
                        },
                        source="observed",
                        prior_bp=3000,
                        user_confirmed=False,
                        evidence_items=ev_items,
                    )
                )

    return candidates


def observe_contextual_exceptions(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime,
    config: dict[str, Any] | None = None,
) -> list[MemoryCandidate]:
    """
    Observer 2: Observes user-dismissed alerts or anomalies with short allowed reason labels.
    """
    cfg = config or load_memory_config()
    allowed_reasons = set(cfg.get("allowed_exception_reasons", []))

    candidates: list[MemoryCandidate] = []

    # 1. Dismissed alerts
    rows = conn.execute(
        """
        SELECT id, subject_key, period, dismiss_reason, decided_at, created_at, components_json
        FROM alerts
        WHERE user_id = ? AND status = 'dismissed' AND dismiss_reason IS NOT NULL
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    for r in rows:
        alert_id, sub_key, period, reason, decided_at, created_at, comp_json = r
        clean_reason = str(reason).strip().lower()
        if clean_reason not in allowed_reasons:
            continue

        cat = "general"
        if sub_key.startswith("category:"):
            cat = sub_key.split("category:", 1)[1]
        elif comp_json:
            try:
                comp = json.loads(comp_json)
                cat = comp.get("category_id") or comp.get("category") or cat
            except Exception:
                pass

        obs_time = decided_at or created_at
        subject_key = f"category:{cat}|period:{period}"

        candidates.append(
            MemoryCandidate(
                kind="contextual_exception",
                subject_key=subject_key,
                statement_json={
                    "category": cat,
                    "period": period,
                    "reason": clean_reason,
                },
                source="feedback",
                prior_bp=6000,
                user_confirmed=True,
                evidence_items=[
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="anomaly",
                        ref_id=alert_id,
                        observed_at=obs_time,
                        weight_bp=6000,
                    )
                ],
            )
        )

    # 2. Audit events for anomaly dismissal or manual one-offs
    ev_rows = conn.execute(
        """
        SELECT id, occurred_at, entity_id, reason, after_json
        FROM audit_events
        WHERE user_id = ? AND event_type IN ('anomaly_dismissed', 'contextual_exception_recorded')
        ORDER BY occurred_at DESC
        """,
        (user_id,),
    ).fetchall()

    for r in ev_rows:
        ev_id, occurred_at, entity_id, ev_reason, after_json = r
        if not after_json:
            continue
        try:
            after = json.loads(after_json)
        except Exception:
            continue

        reason_val = after.get("reason", "").strip().lower()
        if reason_val not in allowed_reasons:
            continue

        cat = after.get("category") or "general"
        period = after.get("period") or occurred_at[:7]
        subject_key = f"category:{cat}|period:{period}"

        # Avoid duplicates with alerts
        if any(c.subject_key == subject_key for c in candidates):
            continue

        candidates.append(
            MemoryCandidate(
                kind="contextual_exception",
                subject_key=subject_key,
                statement_json={
                    "category": cat,
                    "period": period,
                    "reason": reason_val,
                },
                source="user_stated",
                prior_bp=6000,
                user_confirmed=True,
                evidence_items=[
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="audit_event",
                        ref_id=ev_id,
                        observed_at=occurred_at,
                        weight_bp=6000,
                    )
                ],
            )
        )

    return candidates


def observe_advice_feedback(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime,
    config: dict[str, Any] | None = None,
) -> list[MemoryCandidate]:
    """
    Observer 3: Observes user approval or rejection of advice items.
    """
    candidates: list[MemoryCandidate] = []

    rows = conn.execute(
        """
        SELECT id, text, status, decided_at, evidence_json, calculations_json
        FROM advice_items
        WHERE user_id = ? AND status IN ('approved', 'rejected') AND decided_at IS NOT NULL
        ORDER BY decided_at DESC
        """,
        (user_id,),
    ).fetchall()

    for r in rows:
        aid, text, decision, decided_at, ev_json, calc_json = r

        advice_kind = "reduce_spend"
        subject = "global"

        if ev_json:
            try:
                ev = json.loads(ev_json)
                if isinstance(ev, dict):
                    advice_kind = ev.get("kind") or ev.get("advice_kind") or advice_kind
                    cat = ev.get("category") or ev.get("category_id")
                    if cat:
                        subject = f"category:{cat}"
            except Exception:
                pass

        if subject == "global" and calc_json:
            try:
                calc = json.loads(calc_json)
                cat = calc.get("category") or calc.get("category_id")
                if cat:
                    subject = f"category:{cat}"
            except Exception:
                pass

        subject_key = f"advice_kind:{advice_kind}|subject:{subject}"

        candidates.append(
            MemoryCandidate(
                kind="advice_feedback",
                subject_key=subject_key,
                statement_json={
                    "advice_kind": advice_kind,
                    "subject": subject,
                    "decision": decision,
                },
                source="feedback",
                prior_bp=6000,
                user_confirmed=True,
                evidence_items=[
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="advice",
                        ref_id=aid,
                        observed_at=decided_at,
                        weight_bp=6000,
                    )
                ],
            )
        )

    return candidates


def observe_preferences(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime,
    config: dict[str, Any] | None = None,
) -> list[MemoryCandidate]:
    """
    Observer 4: Observes user-stated settings from user_preferences.
    """
    candidates: list[MemoryCandidate] = []

    rows = conn.execute(
        """
        SELECT id, key, value_json, updated_at
        FROM user_preferences
        WHERE user_id = ?
        ORDER BY updated_at ASC
        """,
        (user_id,),
    ).fetchall()

    for r in rows:
        pid, key, val_json, updated_at = r
        try:
            val = json.loads(val_json)
        except Exception:
            val = val_json

        subject_key = f"preference:{key}"
        candidates.append(
            MemoryCandidate(
                kind="preference",
                subject_key=subject_key,
                statement_json={"key": key, "value": val},
                source="user_stated",
                prior_bp=10000,
                user_confirmed=True,
                evidence_items=[
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="audit_event",
                        ref_id=pid,
                        observed_at=updated_at,
                        weight_bp=10000,
                    )
                ],
            )
        )

    return candidates


def _simulated_only_merchants(conn: sqlite3.Connection, user_id: str) -> set[str]:
    """Merchant names that only simulated payments ever used, unless simulation may teach."""
    from copilot.config.capture import load_capture_config
    from copilot.core.capture_logic import normalise_name

    if load_capture_config().learn_from_simulated:
        return set()
    simulated: set[str] = set()
    real: set[str] = set()
    for name, sim in conn.execute(
        "SELECT display_name, simulated FROM payment_events WHERE user_id = ?", (user_id,)
    ):
        (simulated if sim else real).add(normalise_name(name))
    return simulated - real


def observe_merchant_habits(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime,
    config: dict[str, Any] | None = None,
) -> list[MemoryCandidate]:
    """
    Observer 5: Observes user merchant category overrides and capture labels.
    """
    candidates: list[MemoryCandidate] = []
    simulated_only = _simulated_only_merchants(conn, user_id)

    rows = conn.execute(
        """
        SELECT id, merchant_normalized, category_id, created_at
        FROM merchant_overrides
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    ).fetchall()

    for r in rows:
        oid, merchant, cat_id, created_at = r
        if merchant in simulated_only:
            continue  # a pretend payment is not a habit (unless a demo says it is)
        subject_key = f"merchant:{merchant}"

        candidates.append(
            MemoryCandidate(
                kind="merchant_habit",
                subject_key=subject_key,
                statement_json={
                    "merchant": merchant,
                    "category": cat_id,
                },
                source="user_stated",
                prior_bp=7000,
                user_confirmed=True,
                evidence_items=[
                    CandidateEvidence(
                        polarity="supports",
                        ref_kind="audit_event",
                        ref_id=oid,
                        observed_at=created_at,
                        weight_bp=7000,
                    )
                ],
            )
        )

    return candidates


# ---------------------------------------------------------------------------------------------
# Deterministic Confidence & Status Evaluation (PLAN_PHASE3 Section 5.9)
# ---------------------------------------------------------------------------------------------


def compute_memory_confidence(
    item: MemoryItem,
    evidence_list: list[MemoryEvidence],
    now: datetime,
    config: dict[str, Any],
) -> tuple[int, int, int]:
    """
    Compute confidence_bp according to Section 5.9:
      support      = sum of weight_bp of supporting evidence (capped at support_cap_bp)
      contradict   = sum of weight_bp of contradicting evidence
      evidence_bp  = clamp(prior_bp + k_s * support - k_c * contradict, 0, 10000)
      age_days     = days between last_evidence_at (or last_confirmed_at, or created_at) and now
      decay        = 0.5 ** (age_days / half_life_days[kind])
                     (computed with Decimal; preference decay = 1)
      confidence   = floor(evidence_bp * decay)


    Returns (confidence_bp, support_bp, contradict_bp).
    """
    support_cap = config.get("support_cap_bp", 10000)
    k_s = float(config.get("k_s", 1.0))
    k_c = float(config.get("k_c", 1.5))

    raw_support = sum(e.weight_bp for e in evidence_list if e.polarity == "supports")
    contradict = sum(e.weight_bp for e in evidence_list if e.polarity == "contradicts")
    support = min(raw_support, support_cap)

    raw_ev = item.prior_bp + int(k_s * support) - int(k_c * contradict)
    evidence_bp = max(0, min(10000, raw_ev))

    # Age calculation: days between last_evidence_at
    # (or last_confirmed_at, whichever is later) and now (Section 5.9)
    candidates = []
    if item.last_evidence_at:
        candidates.append(item.last_evidence_at)
    if item.last_confirmed_at:
        candidates.append(item.last_confirmed_at)
    if not candidates and item.created_at:
        candidates.append(item.created_at)

    anchor_iso = max(candidates) if candidates else None
    try:
        anchor_dt = from_utc_iso(anchor_iso)
        age_seconds = max(0.0, (now_utc(now) - anchor_dt).total_seconds())
        age_days = age_seconds / 86400.0
    except Exception:
        age_days = 0.0

    half_lives = config.get("half_lives_days", {})
    half_life = half_lives.get(item.kind, 90)

    if item.kind == "preference" or half_life <= 0 or item.source == "user_stated":
        decay = Decimal("1.0")
    else:
        if age_days <= 0.0:
            decay = Decimal("1.0")
        else:
            exponent = age_days / float(half_life)
            decay_float = 0.5**exponent
            decay = Decimal(str(decay_float))

    confidence = int(math.floor(Decimal(str(evidence_bp)) * decay))
    confidence_bp = max(0, min(10000, confidence))

    return confidence_bp, support, contradict


def determine_memory_status(
    item: MemoryItem,
    confidence_bp: int,
    support_bp: int,
    contradict_bp: int,
    contradict_count: int,
    config: dict[str, Any],
) -> str:
    """
    Evaluates state transitions for a memory item (PLAN_PHASE3 Section 5.8 & 5.9).
    """
    if item.status == "forgotten":
        return "forgotten"
    if item.status == "rejected":
        return "rejected"

    thresholds = config.get("thresholds_bp", {"use": 6000, "stale": 4000, "retire": 2000})
    min_contradictions = config.get("min_contradictions_to_retire", 2)

    is_contradicted = (contradict_bp >= support_bp) and (contradict_count >= min_contradictions)

    if item.user_confirmed:
        if is_contradicted:
            # User confirmed memories that become contradicted do NOT auto-retire;
            # they become stale and are surfaced as "Still true?" (Section 5.9).
            return "stale"
        return "active"

    # Non-confirmed memories
    if is_contradicted:
        return "retired"

    if confidence_bp >= thresholds.get("use", 6000):
        return "active"
    elif confidence_bp >= thresholds.get("retire", 2000):
        if item.status == "candidate":
            return "candidate"
        return "stale"
    else:
        return "retired"


# ---------------------------------------------------------------------------------------------
# Core Memory Operations
# ---------------------------------------------------------------------------------------------


def refresh_memories(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> dict[str, Any]:
    """
    Runs all 5 observers, inserts/updates candidate items, records new evidence,
    and recomputes confidence and lifecycle statuses.
    Idempotent for the same clock and database state.
    """
    now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)
    clock_iso = to_utc_iso(now_dt)
    cfg = load_memory_config()

    candidates: list[MemoryCandidate] = []
    candidates.extend(observe_recurring_patterns(conn, user_id, now_dt, cfg))
    candidates.extend(observe_contextual_exceptions(conn, user_id, now_dt, cfg))
    candidates.extend(observe_advice_feedback(conn, user_id, now_dt, cfg))
    candidates.extend(observe_preferences(conn, user_id, now_dt, cfg))
    candidates.extend(observe_merchant_habits(conn, user_id, now_dt, cfg))

    new_candidates_count = 0

    for cand in candidates:
        existing = get_memory_by_subject(conn, user_id, cand.kind, cand.subject_key)
        if existing is not None:
            if existing.status == "forgotten":
                # Do not recreate or update forgotten memories
                continue
            target_id = existing.id
        else:
            # Create new memory item
            new_id = f"mem_{uuid.uuid4().hex[:12]}"
            init_status = "active" if cand.user_confirmed else "candidate"
            last_ev = cand.evidence_items[0].observed_at if cand.evidence_items else clock_iso
            item = MemoryItem(
                id=new_id,
                user_id=user_id,
                kind=cand.kind,
                subject_key=cand.subject_key,
                statement_json=cand.statement_json,
                source=cand.source,
                status=init_status,
                prior_bp=cand.prior_bp,
                user_confirmed=cand.user_confirmed,
                confidence_bp=0,
                created_at=clock_iso,
                last_evidence_at=last_ev,
                last_confirmed_at=clock_iso if cand.user_confirmed else None,
            )
            insert_memory_item(conn, item)
            target_id = new_id
            new_candidates_count += 1

        # Check existing evidence to avoid duplicates on repeat runs
        existing_evidence = list_memory_evidence(conn, user_id, target_id)
        existing_refs = {(e.ref_kind, e.ref_id) for e in existing_evidence}

        for ev in cand.evidence_items:
            if (ev.ref_kind, ev.ref_id) not in existing_refs:
                mev = MemoryEvidence(
                    id=f"mev_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    memory_id=target_id,
                    polarity=ev.polarity,
                    ref_kind=ev.ref_kind,
                    ref_id=ev.ref_id,
                    observed_at=ev.observed_at,
                    weight_bp=ev.weight_bp,
                    created_at=clock_iso,
                )
                insert_memory_evidence(conn, mev)
                existing_refs.add((ev.ref_kind, ev.ref_id))

    # Recompute confidence and statuses for all memories of this user
    all_items = list_memory_items(conn, user_id)
    counts = {"active": 0, "candidate": 0, "stale": 0, "retired": 0, "rejected": 0, "forgotten": 0}

    for item in all_items:
        if item.status == "forgotten":
            counts["forgotten"] += 1
            continue

        ev_list = list_memory_evidence(conn, user_id, item.id)
        conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, cfg)
        cont_count = sum(1 for e in ev_list if e.polarity == "contradicts")

        new_status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, cont_count, cfg)
        if new_status != item.status:
            update_memory_status(conn, user_id, item.id, status=new_status)

        counts[new_status] = counts.get(new_status, 0) + 1

    return {
        "user_id": user_id,
        "refreshed_at": clock_iso,
        "new_candidates": new_candidates_count,
        "counts": counts,
    }


def forget_memory(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    clock: datetime | None = None,
    actor: str = "user",
    run_id: str | None = None,
) -> bool:
    """
    Clears statement_json and evidence rows, sets status = 'forgotten',
    and records a content-free audit event (PLAN_PHASE3 Section 4 & 5.8).
    """
    item = get_memory_item(conn, user_id, memory_id)
    if not item:
        return False

    success = forget_memory_item(conn, user_id, memory_id)
    if success:
        record_event(
            conn,
            user_id=user_id,
            actor=actor,
            event_type="memory_forgotten",
            reason=f"Memory {memory_id} forgotten by user.",
            run_id=run_id,
            entity_type="memory",
            entity_id=memory_id,
            before_data={
                "memory_id": memory_id,
                "kind": item.kind,
                "subject_key": item.subject_key,
            },
            after_data={"status": "forgotten"},
            clock=clock,
        )
    return success


def edit_memory_statement_bounded(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    updates: dict[str, Any],
    clock: datetime | None = None,
    actor: str = "user",
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Edits a memory item's statement_json strictly over bounded fields (PLAN_PHASE3 Section 5.8).
    """
    item = get_memory_item(conn, user_id, memory_id)
    if not item:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Memory {memory_id} not found.")

    if item.status == "forgotten":
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Cannot edit forgotten memory {memory_id}.")

    cfg = load_memory_config()
    allowed_reasons = set(cfg.get("allowed_exception_reasons", []))

    new_statement = dict(item.statement_json)

    # Enforce bounded fields per kind
    if item.kind == "recurring_pattern":
        allowed_fields = {"pattern", "ratio_bp"}
        for k, v in updates.items():
            if k not in allowed_fields:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Field '{k}' cannot be edited on {item.kind}.",
                )
            if k == "ratio_bp" and (not isinstance(v, int) or v < 0 or v > 100000):
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    "ratio_bp must be integer between 0 and 100000.",
                )
            new_statement[k] = v

    elif item.kind == "contextual_exception":
        allowed_fields = {"reason"}
        for k, v in updates.items():
            if k not in allowed_fields:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Field '{k}' cannot be edited on {item.kind}.",
                )
            if str(v).strip().lower() not in allowed_reasons:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Reason '{v}' not allowed. Allowed: {sorted(allowed_reasons)}",
                )
            new_statement[k] = str(v).strip().lower()

    elif item.kind == "preference":
        allowed_fields = {"value"}
        for k, v in updates.items():
            if k not in allowed_fields:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Field '{k}' cannot be edited on {item.kind}.",
                )
            new_statement[k] = v

    elif item.kind == "merchant_habit":
        allowed_fields = {"category"}
        for k, v in updates.items():
            if k not in allowed_fields:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Field '{k}' cannot be edited on {item.kind}.",
                )
            new_statement[k] = v

    elif item.kind == "advice_feedback":
        allowed_fields = {"decision"}
        for k, v in updates.items():
            if k not in allowed_fields:
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    f"Field '{k}' cannot be edited on {item.kind}.",
                )
            if v not in ("approved", "rejected"):
                raise ToolFailure(
                    ErrorCode.INVALID_INPUT,
                    "decision must be 'approved' or 'rejected'.",
                )
            new_statement[k] = v

    else:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Editing statement for kind {item.kind} not supported.",
        )

    update_memory_statement(conn, user_id, memory_id, new_statement)

    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="memory_edited",
        reason=f"Memory {memory_id} statement edited by user.",
        run_id=run_id,
        entity_type="memory",
        entity_id=memory_id,
        before_data={"statement": item.statement_json},
        after_data={"statement": new_statement},
        clock=clock,
    )

    return new_statement


def record_contextual_exception(
    conn: sqlite3.Connection,
    user_id: str,
    category: str,
    period: str,
    reason: str,
    txn_id: str | None = None,
    clock: datetime | None = None,
    actor: str = "user",
    run_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> MemoryItem:
    """
    Directly records a contextual exception memory item with validated reason label.

    `period` names a month ("2026-09") or a day. A user can also give `from_date` and `to_date`
    (inclusive) for a stretch inside a month, such as a trip; challenge pauses, baselines and
    streak freezes then cover exactly those days.
    """
    if (from_date is None) != (to_date is None):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Give both from_date and to_date, or neither.")
    if from_date and to_date:
        try:
            first, last = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except ValueError as exc:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Dates must be YYYY-MM-DD.") from exc
        if last < first or (last - first).days > 92:
            raise ToolFailure(
                ErrorCode.INVALID_INPUT, "The range must be in order and at most 93 days."
            )
        period = from_date[:7]
    cfg = load_memory_config()
    allowed_reasons = set(cfg.get("allowed_exception_reasons", []))
    clean_reason = reason.strip().lower()
    if clean_reason not in allowed_reasons:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Invalid reason '{reason}'. Allowed: {sorted(allowed_reasons)}",
        )

    now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)
    clock_iso = to_utc_iso(now_dt)

    span = f"{from_date}..{to_date}" if from_date and to_date else period
    subject_key = f"category:{category}|period:{span}"
    existing = get_memory_by_subject(conn, user_id, "contextual_exception", subject_key)

    statement = {
        "category": category,
        "period": period,
        "reason": clean_reason,
    }
    if from_date and to_date:
        statement["from_date"] = from_date
        statement["to_date"] = to_date
    if txn_id:
        statement["txn_id"] = txn_id

    if existing and existing.status != "forgotten":
        update_memory_statement(conn, user_id, existing.id, statement)
        update_memory_status(conn, user_id, existing.id, status="active", user_confirmed=True)
        memory_id = existing.id
    else:
        memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        item = MemoryItem(
            id=memory_id,
            user_id=user_id,
            kind="contextual_exception",
            subject_key=subject_key,
            statement_json=statement,
            source="user_stated",
            status="active",
            prior_bp=6000,
            user_confirmed=True,
            confidence_bp=6000,
            created_at=clock_iso,
            last_evidence_at=clock_iso,
            last_confirmed_at=clock_iso,
        )
        insert_memory_item(conn, item)

    # Insert evidence
    mev = MemoryEvidence(
        id=f"mev_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        memory_id=memory_id,
        polarity="supports",
        ref_kind="txn" if txn_id else "audit_event",
        ref_id=txn_id or f"audit_{uuid.uuid4().hex[:8]}",
        observed_at=clock_iso,
        weight_bp=6000,
        created_at=clock_iso,
    )
    insert_memory_evidence(conn, mev)

    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="contextual_exception_recorded",
        reason=f"Contextual exception for category '{category}' in {period}: {clean_reason}",
        run_id=run_id,
        entity_type="memory",
        entity_id=memory_id,
        before_data={},
        after_data={"statement": statement},
        clock=clock,
    )

    item = get_memory_item(conn, user_id, memory_id)
    assert item is not None
    return item


# ---------------------------------------------------------------------------------------------
# Memory Consumer Integration Helpers (PLAN_PHASE3 Section 5.8 & 5.9)
# ---------------------------------------------------------------------------------------------


def get_active_contextual_exception(
    conn: sqlite3.Connection,
    user_id: str,
    category: str,
    period: str,
    clock: datetime | None = None,
) -> MemoryItem | None:
    """
    Find active contextual exception memory item covering category and period.
    Section 5.8 & 5.9: Only active items are used. If conflicting, higher confidence wins.
    """
    cfg = load_memory_config()
    now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)

    rows = conn.execute(
        """
        SELECT id FROM memory_items
        WHERE user_id = ? AND kind = 'contextual_exception' AND status != 'forgotten'
        """,
        (user_id,),
    ).fetchall()

    matching_items: list[tuple[int, MemoryItem]] = []
    clean_cat = category.strip().lower()

    for (mid,) in rows:
        item = get_memory_item(conn, user_id, mid)
        if not item:
            continue
        stmt = item.statement_json or {}
        stmt_cat = str(stmt.get("category", "")).strip().lower()
        stmt_period = str(stmt.get("period", "")).strip()

        matches_cat = (
            stmt_cat in (clean_cat, "general", "all") or f"category:{clean_cat}" in item.subject_key
        )
        matches_period = stmt_period == period or f"period:{period}" in item.subject_key

        if matches_cat and matches_period:
            ev_list = list_memory_evidence(conn, user_id, item.id)
            conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, cfg)
            contras = sum(1 for e in ev_list if e.polarity == "contradicts")
            cur_status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, contras, cfg)
            if cur_status == "active":
                matching_items.append((conf_bp, item))

    if not matching_items:
        return None

    # Higher confidence wins
    matching_items.sort(key=lambda x: x[0], reverse=True)
    return matching_items[0][1]


def check_advice_suppression(
    conn: sqlite3.Connection,
    user_id: str,
    advice_kind: str,
    subject: str = "global",
    clock: datetime | None = None,
) -> tuple[bool, MemoryItem | None]:
    """
    Check if advice kind for subject is currently suppressed by a user rejection.
    Section 5.8 & 5.9:
      - Rejected advice kinds for a subject are suppressed during cooldown
        (advice_cooldown_days = 30).
      - On day 29: suppressed. On day 30: cooldown elapsed, back on day 31.
      - Approved kinds are NOT boosted (no reinforcement loops).
    """
    cfg = load_memory_config()
    cooldown_days = cfg.get("advice_cooldown_days", 30)
    now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)

    rows = conn.execute(
        """
        SELECT id FROM memory_items
        WHERE user_id = ? AND kind = 'advice_feedback' AND status != 'forgotten'
        """,
        (user_id,),
    ).fetchall()

    for (mid,) in rows:
        item = get_memory_item(conn, user_id, mid)
        if not item:
            continue
        stmt = item.statement_json or {}
        if stmt.get("decision") != "rejected":
            continue

        item_kind = stmt.get("advice_kind")
        item_sub = stmt.get("subject", "global")

        matches_kind = item_kind == advice_kind or item_kind == "all"
        matches_sub = item_sub in (subject, "global") or subject in (item_sub, "global")

        if matches_kind and matches_sub:
            ev_list = list_memory_evidence(conn, user_id, item.id)
            conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, cfg)
            contras = sum(1 for e in ev_list if e.polarity == "contradicts")
            cur_status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, contras, cfg)
            if cur_status != "active":
                continue

            candidates = []
            if item.last_evidence_at:
                candidates.append(item.last_evidence_at)
            if item.last_confirmed_at:
                candidates.append(item.last_confirmed_at)
            if not candidates and item.created_at:
                candidates.append(item.created_at)

            anchor_iso = max(candidates) if candidates else None
            try:
                anchor_dt = from_utc_iso(anchor_iso)
                age_days = (now_dt - anchor_dt).total_seconds() / 86400.0
            except Exception:
                age_days = 0.0

            if age_days < float(cooldown_days):
                # Suppressed during cooldown!
                return True, item

    return False, None
