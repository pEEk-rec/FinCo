"""
Anomaly detection logic.
"""

from typing import Any


def detect_anomalies(txs: list[Any]) -> list[dict]:
    """
    Detect anomalies in a list of transactions (assumed to be chronologically ordered).

    Returns a list of anomaly dictionaries.
    """
    anomalies = []

    # 1. Duplicates
    # Ingestion already flags them
    for tx in txs:
        if tx.is_duplicate_of:
            anomalies.append(
                {
                    "kind": "duplicate_charge",
                    "transaction_ids": (tx.is_duplicate_of, tx.id),
                    "score": 1.0,
                    "details": "Same charge twice",
                }
            )

    # Track seen merchants to detect new merchants
    seen_merchants = set()

    for tx in txs:
        # Ignore credits and excluded
        if tx.direction == "credit" or tx.excluded_from_spend or tx.is_duplicate_of:
            if tx.merchant_normalized:
                seen_merchants.add(tx.merchant_normalized)
            continue

        merchant = tx.merchant_normalized or tx.merchant_raw
        amount = tx.amount_paise

        if merchant not in seen_merchants and len(seen_merchants) > 5:
            anomalies.append(
                {
                    "kind": "new_merchant",
                    "transaction_ids": (tx.id,),
                    "score": 0.8,
                    "details": f"First purchase at {merchant}",
                }
            )

        # Large transaction anomaly
        # amount > 1500000 (15000) is large in our dataset
        if amount > 1500000:
            anomalies.append(
                {
                    "kind": "large_transaction",
                    "transaction_ids": (tx.id,),
                    "score": 0.9,
                    "details": "Unusually large purchase",
                }
            )

        seen_merchants.add(merchant)

    return anomalies
