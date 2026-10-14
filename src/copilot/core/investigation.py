"""
Pure deterministic investigation engine (PLAN_PHASE2 Section 5.4 & Stage 2.4).

Closed hypothesis catalogue, pure evidence functions, decomposition invariant,
and deterministic confidence / outcome scoring.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from copilot.config.phase2 import InvestigationConfig
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.agentic import (
    EvidenceItem,
    EvidenceResult,
    Hypothesis,
    HypothesisStatus,
    Investigation,
    InvestigationOutcome,
    InvestigationSubjectKind,
)
from copilot.models.domain import Transaction


@dataclass(frozen=True)
class Decomposition:
    """
    Spend change decomposition between baseline and target period.

    INVARIANT:
    volume_effect_paise + ticket_effect_paise + new_merchant_paise +
    stopped_merchant_paise + residual_paise == total_change_paise
    """

    volume_effect_paise: int
    ticket_effect_paise: int
    new_merchant_paise: int
    stopped_merchant_paise: int
    residual_paise: int
    total_change_paise: int


def _filter_spend_txns(txns: list[Transaction]) -> list[Transaction]:
    """Filter to active debit transactions excluding transfers and duplicates."""
    return [
        t
        for t in txns
        if t.direction == "debit"
        and t.amount_paise > 0
        and not getattr(t, "excluded_from_spend", False)
        and not getattr(t, "is_duplicate_of", None)
    ]


def _merchant_key(t: Transaction) -> str:
    """Extract a canonical merchant identifier from a transaction."""
    norm = getattr(t, "merchant_normalized", None)
    if norm:
        return norm.strip().upper()
    raw = t.merchant_raw or ""
    # Simplify common UPI tokens if raw
    for part in raw.split("-"):
        part = part.strip()
        if len(part) >= 3 and not part.startswith("REF") and not part.startswith("UPI"):
            return part.upper()
    return raw.strip().upper()


def decompose_spend_change(
    baseline_txns: list[Transaction], target_txns: list[Transaction]
) -> Decomposition:
    """
    Decompose spend change into volume, ticket, new merchant, and stopped merchant effects.

    Guarantees exact conservation of paise: sum of effects + residual == total_change_paise.
    """
    b_spend = _filter_spend_txns(baseline_txns)
    t_spend = _filter_spend_txns(target_txns)

    total_base = sum(t.amount_paise for t in b_spend)
    total_target = sum(t.amount_paise for t in t_spend)
    total_change = total_target - total_base

    if not b_spend and not t_spend:
        return Decomposition(0, 0, 0, 0, 0, 0)

    # Merchant groupings
    b_by_merch: dict[str, list[Transaction]] = defaultdict(list)
    for t in b_spend:
        b_by_merch[_merchant_key(t)].append(t)

    t_by_merch: dict[str, list[Transaction]] = defaultdict(list)
    for t in t_spend:
        t_by_merch[_merchant_key(t)].append(t)

    b_merchants = set(b_by_merch.keys())
    t_merchants = set(t_by_merch.keys())

    new_merchants = t_merchants - b_merchants
    stopped_merchants = b_merchants - t_merchants
    common_merchants = b_merchants & t_merchants

    new_merchant_paise = sum(
        sum(t.amount_paise for t in t_by_merch[m]) for m in new_merchants
    )
    stopped_merchant_paise = -sum(
        sum(t.amount_paise for t in b_by_merch[m]) for m in stopped_merchants
    )

    # Common merchants volume & ticket decomposition
    b_common_txns = [t for m in common_merchants for t in b_by_merch[m]]
    t_common_txns = [t for m in common_merchants for t in t_by_merch[m]]

    n_base = len(b_common_txns)
    n_target = len(t_common_txns)
    s_base_common = sum(t.amount_paise for t in b_common_txns)
    s_target_common = sum(t.amount_paise for t in t_common_txns)
    delta_common = s_target_common - s_base_common

    if n_base > 0 and n_target > 0:
        avg_base_ticket = s_base_common // n_base
        volume_effect_paise = (n_target - n_base) * avg_base_ticket
        ticket_effect_paise = delta_common - volume_effect_paise
    elif n_base == 0 and n_target > 0:
        volume_effect_paise = s_target_common
        ticket_effect_paise = 0
    elif n_base > 0 and n_target == 0:
        volume_effect_paise = -s_base_common
        ticket_effect_paise = 0
    else:
        volume_effect_paise = 0
        ticket_effect_paise = 0

    sum_effects = (
        volume_effect_paise
        + ticket_effect_paise
        + new_merchant_paise
        + stopped_merchant_paise
    )
    residual_paise = total_change - sum_effects

    return Decomposition(
        volume_effect_paise=volume_effect_paise,
        ticket_effect_paise=ticket_effect_paise,
        new_merchant_paise=new_merchant_paise,
        stopped_merchant_paise=stopped_merchant_paise,
        residual_paise=residual_paise,
        total_change_paise=total_change,
    )


# -------------------------------------------------------------------------------------------------
# 8 Closed Catalogue Hypotheses Tests
# -------------------------------------------------------------------------------------------------


def test_one_off_large(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: A few large transactions explain the change."""
    t_spend = _filter_spend_txns(target_txns)
    b_spend = _filter_spend_txns(baseline_txns)

    if not t_spend or total_change_paise <= 0:
        return "neutral", 0, 0, []

    b_amounts = [t.amount_paise for t in b_spend] or [100_00]
    b_median = sorted(b_amounts)[len(b_amounts) // 2]

    # Sort target transactions descending
    sorted_target = sorted(t_spend, key=lambda t: t.amount_paise, reverse=True)
    top_tx = sorted_target[0]
    top_2_sum = sum(t.amount_paise for t in sorted_target[:2])

    evidence_items = []
    # Test whether baseline history has comparable amount for this merchant
    b_amounts_for_merch = [
        t.amount_paise for t in b_spend if _merchant_key(t) == _merchant_key(top_tx)
    ]
    has_comparable = any(amt >= int(0.80 * top_tx.amount_paise) for amt in b_amounts_for_merch)

    is_large = (
        not has_comparable
        and top_tx.amount_paise > (3 * b_median)
        and top_tx.amount_paise >= int(0.35 * total_change_paise)
        and total_change_paise >= 2000_00
    )
    res_status: EvidenceResult = "supports" if is_large else "contradicts"
    contribution = min(total_change_paise, top_tx.amount_paise - b_median) if is_large else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="one_off_large",
        test_code="top_ticket_outlier",
        result=res_status,
        strength_bp=8000 if is_large else 2000,
        numbers={
            "top_amount_paise": top_tx.amount_paise,
            "baseline_median_paise": b_median,
            "top_2_sum_paise": top_2_sum,
            "has_comparable": has_comparable,
        },
        txn_ids=[top_tx.id],
    )
    evidence_items.append(ev)

    if is_large:
        score_bp = min(10000, int((contribution / max(1, total_change_paise)) * 10000))
        return "supported", score_bp, contribution, evidence_items
    return "neutral", 0, 0, evidence_items


def test_more_frequent(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    decomp: Decomposition,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Same typical ticket, more transactions (volume effect)."""
    t_spend = _filter_spend_txns(target_txns)
    b_spend = _filter_spend_txns(baseline_txns)

    if not t_spend or total_change_paise <= 0:
        return "neutral", 0, 0, []

    n_target = len(t_spend)
    n_base = len(b_spend)
    avg_t = sum(t.amount_paise for t in t_spend) // max(1, n_target)
    avg_b = sum(t.amount_paise for t in b_spend) // max(1, n_base)

    # Ticket within +/- 35%, while volume increased by at least 25% or >= 3 txns
    ticket_stable = abs(avg_t - avg_b) <= int(0.35 * max(1, avg_b))
    vol_higher = n_target > n_base and (n_target - n_base) >= 2
    vol_share_pos = decomp.volume_effect_paise >= int(0.35 * total_change_paise)
    vol_meaningful = total_change_paise >= 2500_00

    supported = ticket_stable and vol_higher and vol_share_pos and vol_meaningful
    contribution = min(total_change_paise, max(0, decomp.volume_effect_paise)) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="more_frequent",
        test_code="volume_effect_share",
        result="supports" if supported else "neutral",
        strength_bp=7500 if supported else 2500,
        numbers={
            "n_target": n_target,
            "n_base": n_base,
            "avg_target_paise": avg_t,
            "avg_base_paise": avg_b,
            "volume_effect_paise": decomp.volume_effect_paise,
        },
        txn_ids=[t.id for t in t_spend],
    )

    if supported:
        score_bp = min(10000, int((contribution / max(1, total_change_paise)) * 10000))
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_higher_ticket(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    decomp: Decomposition,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Same count, larger average amount (price/ticket effect)."""
    t_spend = _filter_spend_txns(target_txns)
    b_spend = _filter_spend_txns(baseline_txns)

    if not t_spend or total_change_paise <= 0:
        return "neutral", 0, 0, []

    n_target = len(t_spend)
    n_base = len(b_spend)
    count_stable = abs(n_target - n_base) <= max(2, int(0.30 * max(1, n_base)))
    ticket_share_pos = decomp.ticket_effect_paise >= int(0.35 * total_change_paise)
    ticket_meaningful = total_change_paise >= 2500_00

    supported = count_stable and ticket_share_pos and ticket_meaningful
    contribution = min(total_change_paise, max(0, decomp.ticket_effect_paise)) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="higher_ticket",
        test_code="ticket_effect_share",
        result="supports" if supported else "neutral",
        strength_bp=7500 if supported else 2500,
        numbers={
            "n_target": n_target,
            "n_base": n_base,
            "ticket_effect_paise": decomp.ticket_effect_paise,
        },
        txn_ids=[t.id for t in t_spend],
    )

    if supported:
        score_bp = min(10000, int((contribution / max(1, total_change_paise)) * 10000))
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_new_merchant(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    decomp: Decomposition,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Spend from merchants absent in lookback window."""
    t_spend = _filter_spend_txns(target_txns)
    b_spend = _filter_spend_txns(baseline_txns)

    if not t_spend or total_change_paise <= 0:
        return "neutral", 0, 0, []

    b_merchants = {_merchant_key(t) for t in b_spend}
    new_txs = [
        t for t in t_spend if _merchant_key(t) not in b_merchants
    ]

    new_spend = sum(t.amount_paise for t in new_txs)
    supported = (
        new_spend > 0
        and new_spend >= int(0.30 * total_change_paise)
        and (new_spend >= 1500_00 or total_change_paise >= 2000_00)
    )
    contribution = min(total_change_paise, new_spend) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="new_merchant",
        test_code="new_merchant_spend",
        result="supports" if supported else "neutral",
        strength_bp=8000 if supported else 2000,
        numbers={
            "new_merchants_count": len({_merchant_key(t) for t in new_txs}),
            "new_merchant_spend_paise": new_spend,
        },
        txn_ids=[t.id for t in new_txs],
    )

    if supported:
        score_bp = min(10000, int((contribution / max(1, total_change_paise)) * 10000))
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_recurring_change(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Recurring series changed amount, appeared, or stopped."""
    t_spend = _filter_spend_txns(target_txns)
    b_spend = _filter_spend_txns(baseline_txns)

    if not t_spend or total_change_paise <= 0:
        return "neutral", 0, 0, []

    # Recurring candidates: merchants appearing once per month in target and baseline
    t_counts = Counter(_merchant_key(t) for t in t_spend)
    b_counts = Counter(_merchant_key(t) for t in b_spend)

    t_by_m = {
        _merchant_key(t): t.amount_paise
        for t in t_spend
        if t_counts[_merchant_key(t)] == 1
    }
    b_by_m = {
        _merchant_key(t): t.amount_paise
        for t in b_spend
        if b_counts[_merchant_key(t)] == 1
    }

    delta_rec = 0
    changed_tx_ids = []
    for m, amt in t_by_m.items():
        if m in b_by_m:
            diff = amt - b_by_m[m]
            base_amt = b_by_m[m]
            pct_jump = diff / max(1, base_amt)
            if diff >= 300_00 and pct_jump >= 0.20 and diff >= int(0.20 * total_change_paise):
                delta_rec += diff
                changed_tx_ids.extend([t.id for t in t_spend if _merchant_key(t) == m])

    supported = delta_rec > 0 and delta_rec >= int(0.20 * total_change_paise)
    contribution = min(total_change_paise, delta_rec) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="recurring_change",
        test_code="recurring_delta",
        result="supports" if supported else "neutral",
        strength_bp=8500 if supported else 2000,
        numbers={"recurring_delta_paise": delta_rec},
        txn_ids=changed_tx_ids,
    )

    if supported:
        score_bp = min(10000, int((contribution / max(1, total_change_paise)) * 10000))
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_miscategorization(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Spend moved because a merchant category differs from history."""
    # Find historical dominant category per merchant
    b_merch_cat = defaultdict(list)
    for t in _filter_spend_txns(baseline_txns):
        cat = getattr(t, "category_id", None)
        if cat:
            b_merch_cat[_merchant_key(t)].append(cat)

    dom_cat = {}
    for m, cats in b_merch_cat.items():
        dom_cat[m] = Counter(cats).most_common(1)[0][0]

    miscategorized_txs = []
    misc_spend = 0
    for t in _filter_spend_txns(target_txns):
        m = _merchant_key(t)
        cat = getattr(t, "category_id", None)
        if m in dom_cat and cat and cat != dom_cat[m]:
            miscategorized_txs.append(t)
            misc_spend += t.amount_paise

    supported = misc_spend > 0 and (
        misc_spend >= 1500_00
        or misc_spend >= int(0.20 * max(1, total_change_paise))
        or total_change_paise <= 0
    )
    contribution = min(max(abs(total_change_paise), misc_spend), misc_spend) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="miscategorization",
        test_code="category_shift",
        result="supports" if supported else "neutral",
        strength_bp=8500 if supported else 2000,
        numbers={"miscategorized_spend_paise": misc_spend},
        txn_ids=[t.id for t in miscategorized_txs],
    )

    if supported:
        score_bp = min(
            10000, max(7500, int((contribution / max(1, abs(total_change_paise))) * 10000))
        )
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_duplicate_or_refund(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    total_change_paise: int,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: Duplicate charge or matching refund distorts the total."""
    dup_txs = [t for t in target_txns if getattr(t, "is_duplicate_of", None)]
    refund_txs = [
        t for t in target_txns if t.direction == "credit" and "REFUND" in (t.merchant_raw or "")
    ]

    dup_amount = sum(t.amount_paise for t in dup_txs)
    refund_amount = sum(abs(t.amount_paise) for t in refund_txs)
    distort_paise = dup_amount + refund_amount

    supported = distort_paise > 0 and (
        distort_paise >= 1000_00
        or distort_paise >= int(0.15 * max(1, abs(total_change_paise)))
        or total_change_paise <= 0
    )
    contribution = (
        min(max(abs(total_change_paise), distort_paise), distort_paise) if supported else 0
    )

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="duplicate_or_refund",
        test_code="duplicate_and_refund_distortion",
        result="supports" if supported else "neutral",
        strength_bp=9000 if supported else 2000,
        numbers={"duplicate_paise": dup_amount, "refund_paise": refund_amount},
        txn_ids=[t.id for t in dup_txs + refund_txs],
    )

    if supported:
        score_bp = min(
            10000, max(7500, int((contribution / max(1, abs(total_change_paise))) * 10000))
        )
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


def test_seasonal_or_timing(
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    period: str,
    total_change_paise: int,
    investigation_id: str,
    user_id: str,
) -> tuple[HypothesisStatus, int, int, list[EvidenceItem]]:
    """Test hypothesis: The month has different shape or partial month."""
    t_spend = _filter_spend_txns(target_txns)
    if not t_spend:
        return "neutral", 0, 0, []

    # Check date span
    days = {int(t.occurred_at[8:10]) for t in t_spend if len(t.occurred_at) >= 10}
    is_partial = len(days) > 0 and max(days) <= 12

    supported = is_partial
    contribution = abs(total_change_paise) if supported else 0

    ev = EvidenceItem(
        id=str(uuid.uuid4()),
        investigation_id=investigation_id,
        user_id=user_id,
        hypothesis_code="seasonal_or_timing",
        test_code="partial_month_span",
        result="supports" if supported else "neutral",
        strength_bp=7500 if supported else 2000,
        numbers={"max_day_observed": max(days) if days else 0, "is_partial": is_partial},
        txn_ids=[t.id for t in t_spend],
    )

    if supported:
        score_bp = 8000
        return "supported", score_bp, contribution, [ev]
    return "neutral", 0, 0, [ev]


# -------------------------------------------------------------------------------------------------
# Investigation Synthesis & Evaluation
# -------------------------------------------------------------------------------------------------


def run_investigation_suite(
    user_id: str,
    target_txns: list[Transaction],
    baseline_txns: list[Transaction],
    subject_kind: InvestigationSubjectKind,
    subject_ref: dict[str, Any],
    period: str,
    config: InvestigationConfig,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    needs_clarification: bool = False,
    history_months: int = 3,
    all_baseline_txns: list[Transaction] | None = None,
) -> Investigation:
    """
    Execute full investigation suite across all 8 catalogue hypotheses.

    Enforces deterministic scoring, data sufficiency checks, and outcome synthesis.
    """
    inv_id = str(uuid.uuid4())
    decomp = decompose_spend_change(baseline_txns, target_txns)
    total_change = decomp.total_change_paise

    hypotheses: list[Hypothesis] = []
    evidence_items: list[EvidenceItem] = []

    tests = [
        (
            "one_off_large",
            lambda: test_one_off_large(target_txns, baseline_txns, total_change, inv_id, user_id),
        ),
        (
            "more_frequent",
            lambda: test_more_frequent(
                target_txns, baseline_txns, total_change, decomp, inv_id, user_id
            ),
        ),
        (
            "higher_ticket",
            lambda: test_higher_ticket(
                target_txns, baseline_txns, total_change, decomp, inv_id, user_id
            ),
        ),
        (
            "new_merchant",
            lambda: test_new_merchant(
                target_txns, baseline_txns, total_change, decomp, inv_id, user_id
            ),
        ),
        (
            "recurring_change",
            lambda: test_recurring_change(
                target_txns, baseline_txns, total_change, inv_id, user_id
            ),
        ),
        (
            "miscategorization",
            lambda: test_miscategorization(
                target_txns, all_baseline_txns or baseline_txns, total_change, inv_id, user_id
            ),
        ),
        (
            "duplicate_or_refund",
            lambda: test_duplicate_or_refund(
                target_txns, baseline_txns, total_change, inv_id, user_id
            ),
        ),
        (
            "seasonal_or_timing",
            lambda: test_seasonal_or_timing(
                target_txns, baseline_txns, period, total_change, inv_id, user_id
            ),
        ),
    ]

    supported_contributions: list[tuple[str, int, int]] = []

    for code, test_fn in tests:
        status, score_bp, contrib, ev_list = test_fn()
        hypotheses.append(
            Hypothesis(
                id=str(uuid.uuid4()),
                investigation_id=inv_id,
                user_id=user_id,
                code=code,
                status=status,
                score_bp=score_bp,
                contribution_paise=contrib,
            )
        )
        evidence_items.extend(ev_list)
        if status == "supported" and contrib > 0:
            supported_contributions.append((code, contrib, score_bp))

    # Overlapping causes rule: Pick top non-overlapping supported contribution
    # or max contribution so we never double count
    if supported_contributions:
        # Sort by score descending
        supported_contributions.sort(key=lambda item: (item[2], item[1]), reverse=True)
        primary_contrib = supported_contributions[0][1]
        primary_score = supported_contributions[0][2]
    else:
        primary_contrib = 0
        primary_score = 0

    if total_change != 0:
        calculated_share = int((primary_contrib / abs(total_change)) * 10000)
        explained_share_bp = min(
            10000, max(primary_score if primary_score >= 7500 else 0, calculated_share)
        )
    else:
        explained_share_bp = 10000 if primary_contrib > 0 else 0

    unexplained_paise = max(0, abs(total_change) - primary_contrib)

    # Data sufficiency evaluation
    b_spend = _filter_spend_txns(baseline_txns)
    insufficient_history = history_months < config.min_history_months
    insufficient_txs = len(b_spend) < 3

    if insufficient_history or insufficient_txs:
        confidence_label = "low"
    else:
        if explained_share_bp >= config.confidence_thresholds_bp.get("high", 7500):
            confidence_label = "high"
        elif explained_share_bp >= config.confidence_thresholds_bp.get("medium", 5000):
            confidence_label = "medium"
        else:
            confidence_label = "low"

    # Noise floor rule (Section 5.4): A noisy month with small change (< 12% and < 2500 INR)
    # has no significant structure to explain and must return inconclusive, unless a decisive
    # structural cause is supported.
    total_base = sum(t.amount_paise for t in b_spend)
    has_decisive_structural_cause = any(
        h.status == "supported"
        and h.code in (
            "one_off_large",
            "new_merchant",
            "miscategorization",
            "duplicate_or_refund",
            "recurring_change",
            "seasonal_or_timing",
        )
        and h.score_bp >= config.explained_share_threshold_bp
        for h in hypotheses
    )
    is_noise_level = (
        subject_kind == "period_change"
        and abs(total_change) < max(2500_00, int(0.12 * total_base))
        and not has_decisive_structural_cause
    )

    # Outcome synthesis
    outcome: InvestigationOutcome
    if needs_clarification:
        outcome = "needs_clarification"
    elif is_noise_level:
        outcome = "inconclusive"
    elif (
        explained_share_bp >= config.explained_share_threshold_bp
        and confidence_label in ("high", "medium")
    ):
        outcome = "explained"
    elif explained_share_bp > 0:
        outcome = "partially_explained"
    else:
        outcome = "inconclusive"

    return Investigation(
        id=inv_id,
        task_id=task_id,
        user_id=user_id,
        run_id=run_id,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        outcome=outcome,
        confidence_label=confidence_label,
        explained_share_bp=explained_share_bp,
        unexplained_paise=unexplained_paise,
        rounds=1,
        hypotheses=hypotheses,
        evidence=evidence_items,
        created_at=to_utc_iso(now_utc()),
    )
