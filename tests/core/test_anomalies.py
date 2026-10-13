from copilot.bank.synth import generate_transactions
from copilot.core.anomalies import detect_anomalies


def test_detect_anomalies_ground_truth():
    res = generate_transactions(456, 4, "u1", ["acc1"])

    # Manually flag the duplicate as the ingestion pipeline would
    for truth in res.ground_truth:
        if truth.kind == "duplicate_charge":
            orig_id, dup_id = truth.transaction_ids
            for tx in res.transactions:
                if tx.id == dup_id:
                    # using dict/model approach: tx is a Pydantic model
                    tx.is_duplicate_of = orig_id
                    break

    anomalies = detect_anomalies(res.transactions)

    detected_kinds = {a["kind"]: a["transaction_ids"] for a in anomalies}
    print("TRUTH:", [(t.kind, t.transaction_ids) for t in res.ground_truth])
    print("DETECTED:", detected_kinds)

    for truth in res.ground_truth:
        matching_ids = [set(a["transaction_ids"]) for a in anomalies if a["kind"] == truth.kind]
        assert set(truth.transaction_ids) in matching_ids
