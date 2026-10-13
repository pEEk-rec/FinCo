"""
Core logic for detecting own-account transfers and recurring payments.
"""

from collections import defaultdict
from datetime import timedelta
from typing import Any

from copilot.core.money import safe_percent
from copilot.core.timeutil import from_utc_iso, to_utc_iso


def detect_transfers(txs: list[Any], window_hours: int = 48) -> list[tuple[Any, Any]]:
    """
    Find matching debit and credit transactions within `window_hours` and exact same amount.
    Returns a list of (debit_tx, credit_tx) pairs.
    """
    debts = [t for t in txs if t.direction == "debit" and not t.excluded_from_spend]
    credits = [t for t in txs if t.direction == "credit" and not t.excluded_from_spend]

    # Sort both to process chronologically
    debts.sort(key=lambda t: t.occurred_at)
    credits.sort(key=lambda t: t.occurred_at)

    window = timedelta(hours=window_hours)
    links = []

    # We greedily match debits to the earliest available credit within window
    used_credits = set()
    for d in debts:
        d_time = from_utc_iso(d.occurred_at)
        amount = abs(d.amount_paise)

        best_match = None
        for c in credits:
            if c.id in used_credits:
                continue
            if abs(c.amount_paise) != amount:
                continue

            c_time = from_utc_iso(c.occurred_at)
            if abs(c_time - d_time) <= window:
                best_match = c
                break

        if best_match:
            used_credits.add(best_match.id)
            links.append((d, best_match))

    return links


def _determine_cadence_and_kind(dates: list[Any], amounts: list[int]) -> tuple[int, str]:
    """Return cadence_days and kind based on sequence of dates and amounts."""
    # Assuming dates are sorted ascending
    if len(dates) < 2:
        return 0, "other"

    diffs = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    avg_diff = sum(diffs) / len(diffs)

    kind = "other"
    if avg_diff <= 10:
        cadence = 7
    elif avg_diff <= 20:
        cadence = 14
    elif avg_diff <= 45:
        cadence = 30
        if all(a < 0 for a in amounts):
            kind = "income"
        else:
            kind = "subscription"
    elif avg_diff <= 100:
        cadence = 90
    else:
        cadence = 365

    return cadence, kind


def detect_recurring(
    txs: list[Any], tolerance_pct: int = 10, min_occurrences: int = 3
) -> list[dict]:
    """
    Detect recurring series of transactions for the same normalized merchant.
    Returns a list of dictionaries with recurring series data.
    """
    # Group by merchant_normalized
    by_merchant = defaultdict(list)
    for t in txs:
        if not t.merchant_normalized or t.excluded_from_spend or t.is_duplicate_of:
            continue
        by_merchant[t.merchant_normalized].append(t)

    series_list = []

    for merchant, merchant_txs in by_merchant.items():
        if len(merchant_txs) < min_occurrences:
            continue

        merchant_txs.sort(key=lambda t: t.occurred_at)

        # We need to find sequences where amount is within tolerance
        # and frequency is somewhat stable. For Phase 1, we just take the last min_occurrences
        # or the most frequent amount bucket.
        # A simple approach: use the latest transaction's amount, find all within tolerance.

        latest_amount = abs(merchant_txs[-1].amount_paise)
        tolerance = safe_percent(latest_amount, tolerance_pct)

        # Filter to those within tolerance
        valid_txs = [
            t
            for t in merchant_txs
            if abs(abs(t.amount_paise) - latest_amount) <= tolerance
            and t.direction == merchant_txs[-1].direction
        ]

        if len(valid_txs) < min_occurrences:
            continue

        dates = [from_utc_iso(t.occurred_at) for t in valid_txs]
        amounts = [t.amount_paise for t in valid_txs]

        cadence, kind = _determine_cadence_and_kind(dates, amounts)
        if cadence == 0:
            continue

        avg_amount = sum(abs(a) for a in amounts) // len(amounts)
        last_seen = dates[-1]
        next_expected = last_seen + timedelta(days=cadence)

        series_list.append(
            {
                "merchant_normalized": merchant,
                "typical_amount_paise": avg_amount,
                "cadence_days": cadence,
                "last_seen": to_utc_iso(last_seen),
                "next_expected": to_utc_iso(next_expected),
                "confidence": 0.8,
                "kind": kind,
            }
        )

    return series_list
