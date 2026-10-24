"""
Tests for Synthetic Generator v3 with hidden ground truth (Stage 2.4).
"""

from copilot.bank.synth import (
    DEV_SEEDS,
    HELD_OUT_SEEDS,
    generate_transactions_v3,
)


def test_synth_v3_determinism_dev_seeds():
    """Same seed and parameters produce bitwise identical output."""
    for s in DEV_SEEDS:
        res1 = generate_transactions_v3(seed=s, months=3, user_id="u1", account_ids=["a1"])
        res2 = generate_transactions_v3(seed=s, months=3, user_id="u1", account_ids=["a1"])
        assert len(res1.transactions) == len(res2.transactions)
        assert [t.id for t in res1.transactions] == [t.id for t in res2.transactions]
        assert [t.amount_paise for t in res1.transactions] == [
            t.amount_paise for t in res2.transactions
        ]


def test_synth_v3_all_injected_causes_dev_seeds():
    """All 8 individual injected causes are properly generated in ground truth."""
    causes = [
        "one_off_large",
        "recurring_change",
        "more_frequent",
        "new_merchant",
        "miscategorization",
        "duplicate_or_refund",
        "seasonal_or_timing",
        "no_cause",
    ]
    seed = DEV_SEEDS[0]
    for c in causes:
        res = generate_transactions_v3(
            seed=seed, months=3, user_id="u1", account_ids=["a1"], target_cause=c
        )
        assert len(res.ground_truth_causes) == 1
        gt = res.ground_truth_causes[0]
        assert gt.kind == c
        assert gt.month == res.target_month
        assert len(res.transactions) > 0


def test_synth_v3_hard_profile():
    """Hard profile includes obscure aliases, noisier narrations, and overlapping causes."""
    res_hard = generate_transactions_v3(
        seed=DEV_SEEDS[1],
        months=2,
        user_id="u1",
        account_ids=["a1"],
        target_cause="overlapping",
        profile="hard",
    )
    assert res_hard.profile == "hard"
    assert len(res_hard.baseline_months) == 1  # Short history
    # Check that overlapping planted multiple causes
    kinds = {c.kind for c in res_hard.ground_truth_causes}
    assert "more_frequent" in kinds
    assert "new_merchant" in kinds

    # Check for presence of POS/DEBIT noise pattern
    has_pos_noise = any("POS/DEBIT" in (t.merchant_raw or "") for t in res_hard.transactions)
    assert has_pos_noise


def test_synth_v3_held_out_seeds_never_overlap():
    """Held-out seeds are completely disjoint from dev seeds."""
    dev_set = set(DEV_SEEDS)
    held_out_set = set(HELD_OUT_SEEDS)
    assert len(dev_set & held_out_set) == 0
