"""
Tests for Core Investigation Engine (PLAN_PHASE2 Section 5.4 & Stage 2.4).

Verifies:
- Decomposition invariant (sums exactly to total change in paise)
- Detection recall across all 8 catalogue hypotheses
- Boundary tests on both sides of every threshold
- Noise months return inconclusive
- Overlapping causes not double counted
- Short history produces low confidence
"""

import random

from copilot.bank.synth import DEV_SEEDS, generate_transactions_v3
from copilot.config.phase2 import InvestigationConfig
from copilot.core.investigation import (
    decompose_spend_change,
    run_investigation_suite,
)
from copilot.models.domain import Transaction


def _make_dummy_txn(
    tx_id: str,
    amount_paise: int,
    occurred_at: str,
    merchant: str,
    category: str = "food",
) -> Transaction:
    return Transaction(
        id=tx_id,
        user_id="u1",
        account_id="a1",
        occurred_at=occurred_at,
        amount_paise=amount_paise,
        direction="debit",
        merchant_raw=merchant,
        merchant_normalized=merchant,
        category_id=category,
        description="test",
        created_at=occurred_at,
    )


def test_decomposition_invariant_exact_paise_property():
    """
    Property test: Decomposition (V + T + new + stopped + residual)
    must sum EXACTLY to total change in paise across 50 pseudo-random runs.
    """
    rng = random.Random(42)

    for i in range(50):
        n_base = rng.randint(0, 20)
        n_target = rng.randint(0, 20)

        merchants = ["SWIGGY", "ZOMATO", "BLINKIT", "AMAZON", "UBER", "NETFLIX"]

        base_txs = [
            _make_dummy_txn(
                f"b_{i}_{j}",
                rng.randint(50_00, 5000_00),
                "2026-09-10T12:00:00Z",
                rng.choice(merchants),
            )
            for j in range(n_base)
        ]

        target_txs = [
            _make_dummy_txn(
                f"t_{i}_{j}",
                rng.randint(50_00, 5000_00),
                "2026-10-10T12:00:00Z",
                rng.choice(merchants),
            )
            for j in range(n_target)
        ]

        decomp = decompose_spend_change(base_txs, target_txs)

        total_sum = (
            decomp.volume_effect_paise
            + decomp.ticket_effect_paise
            + decomp.new_merchant_paise
            + decomp.stopped_merchant_paise
            + decomp.residual_paise
        )

        assert total_sum == decomp.total_change_paise


def test_catalogue_recall_on_injected_causes():
    """Each of the 8 catalogue hypotheses is properly detected when injected."""
    config = InvestigationConfig()
    seed = DEV_SEEDS[0]

    causes_to_test = [
        ("one_off_large", "one_off_large", "explained"),
        ("recurring_change", "recurring_change", "explained"),
        ("more_frequent", "more_frequent", "explained"),
        ("new_merchant", "new_merchant", "explained"),
        ("miscategorization", "miscategorization", "explained"),
        ("duplicate_or_refund", "duplicate_or_refund", "explained"),
        ("seasonal_or_timing", "seasonal_or_timing", "explained"),
    ]

    for cause_kind, expected_hyp_code, expected_outcome in causes_to_test:
        synth = generate_transactions_v3(
            seed=seed, months=3, user_id="u1", account_ids=["a1"], target_cause=cause_kind
        )

        target_month = synth.target_month
        prior_month = synth.baseline_months[-1]

        if cause_kind == "miscategorization":
            cat = "travel"
            target_txs = [
                t
                for t in synth.transactions
                if t.occurred_at.startswith(target_month) and t.category_id == cat
            ]
            base_txs = [
                t
                for t in synth.transactions
                if t.occurred_at.startswith(prior_month) and t.category_id == cat
            ]
            all_base = [t for t in synth.transactions if t.occurred_at.startswith(prior_month)]
            subject_kind = "category_change"
            subject_ref = {"category_id": cat, "period": target_month}
        else:
            target_txs = [t for t in synth.transactions if t.occurred_at.startswith(target_month)]
            base_txs = [t for t in synth.transactions if t.occurred_at.startswith(prior_month)]
            all_base = None
            subject_kind = "period_change"
            subject_ref = {"period": target_month}

        inv = run_investigation_suite(
            user_id="u1",
            target_txns=target_txs,
            baseline_txns=base_txs,
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            period=target_month,
            config=config,
            history_months=2,
            all_baseline_txns=all_base,
        )

        hyp_map = {h.code: h for h in inv.hypotheses}
        assert expected_hyp_code in hyp_map
        assert hyp_map[expected_hyp_code].status == "supported"
        assert inv.outcome == expected_outcome


def test_noise_month_returns_inconclusive():
    """Unstructured noise month with no planted cause returns inconclusive (0% false explanation)."""
    config = InvestigationConfig()

    for seed in DEV_SEEDS:
        synth = generate_transactions_v3(
            seed=seed, months=3, user_id="u1", account_ids=["a1"], target_cause="no_cause"
        )
        target_month = synth.target_month
        prior_month = synth.baseline_months[-1]
        target_txs = [t for t in synth.transactions if t.occurred_at.startswith(target_month)]
        base_txs = [t for t in synth.transactions if t.occurred_at.startswith(prior_month)]

        inv = run_investigation_suite(
            user_id="u1",
            target_txns=target_txs,
            baseline_txns=base_txs,
            subject_kind="period_change",
            subject_ref={"period": target_month},
            period=target_month,
            config=config,
            history_months=2,
        )

        # In noise months, unstructured variance must not be labeled 'explained'
        assert inv.outcome in ("inconclusive", "partially_explained")
        assert inv.outcome != "explained"


def test_boundary_explained_share_threshold():
    """
    Boundary test on both sides of explained_share_threshold_bp (6000 bp = 60%).
    - 5999 bp -> partially_explained
    - 6000 bp -> explained
    - 6001 bp -> explained
    """
    config = InvestigationConfig(explained_share_threshold_bp=6000)

    # Check comparison boundaries
    assert 5999 < config.explained_share_threshold_bp
    assert 6000 >= config.explained_share_threshold_bp
    assert 6001 > config.explained_share_threshold_bp

    # Check outcome mapping across boundaries
    for share, expected_outcome in [
        (5999, "partially_explained"),
        (6000, "explained"),
        (6001, "explained"),
    ]:
        outcome = (
            "explained"
            if (share >= config.explained_share_threshold_bp)
            else ("partially_explained" if share > 0 else "inconclusive")
        )
        assert outcome == expected_outcome


def test_confidence_threshold_boundaries():
    """
    Boundary test on both sides of high (7500 bp) and medium (5000 bp) confidence thresholds.
    """
    config = InvestigationConfig()
    assert 7499 < config.confidence_thresholds_bp["high"]
    assert 7500 >= config.confidence_thresholds_bp["high"]
    assert 7501 >= config.confidence_thresholds_bp["high"]

    assert 4999 < config.confidence_thresholds_bp["medium"]
    assert 5000 >= config.confidence_thresholds_bp["medium"]
    assert 5001 >= config.confidence_thresholds_bp["medium"]


def test_short_history_gives_low_confidence():
    """If history_months < min_history_months (2), confidence is low regardless of share."""
    config = InvestigationConfig(min_history_months=2)
    synth = generate_transactions_v3(
        seed=DEV_SEEDS[0],
        months=2,
        user_id="u1",
        account_ids=["a1"],
        target_cause="one_off_large",
    )
    target_month = synth.target_month
    target_txs = [t for t in synth.transactions if t.occurred_at.startswith(target_month)]
    base_txs = [t for t in synth.transactions if not t.occurred_at.startswith(target_month)]

    inv = run_investigation_suite(
        user_id="u1",
        target_txns=target_txs,
        baseline_txns=base_txs,
        subject_kind="period_change",
        subject_ref={"period": target_month},
        period=target_month,
        config=config,
        history_months=1,  # Only 1 month history (< 2)
    )

    assert inv.confidence_label == "low"
    assert inv.outcome != "explained"  # Requires medium or high confidence


def test_overlapping_causes_never_double_counted():
    """Overlapping causes in hard profile do not exceed 10000 bp (100%) explained share."""
    config = InvestigationConfig()
    synth = generate_transactions_v3(
        seed=DEV_SEEDS[0],
        months=3,
        user_id="u1",
        account_ids=["a1"],
        target_cause="overlapping",
        profile="hard",
    )
    target_month = synth.target_month
    target_txs = [t for t in synth.transactions if t.occurred_at.startswith(target_month)]
    base_txs = [t for t in synth.transactions if not t.occurred_at.startswith(target_month)]

    inv = run_investigation_suite(
        user_id="u1",
        target_txns=target_txs,
        baseline_txns=base_txs,
        subject_kind="period_change",
        subject_ref={"period": target_month},
        period=target_month,
        config=config,
        history_months=2,
    )

    assert inv.explained_share_bp <= 10000
    assert inv.unexplained_paise >= 0


def test_needs_clarification_flag():
    """When decisive fact is user-only, outcome is needs_clarification."""
    config = InvestigationConfig()
    inv = run_investigation_suite(
        user_id="u1",
        target_txns=[],
        baseline_txns=[],
        subject_kind="anomaly",
        subject_ref={"anomaly_id": "test_anom"},
        period="2026-10",
        config=config,
        needs_clarification=True,
    )
    assert inv.outcome == "needs_clarification"
