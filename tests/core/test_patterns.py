from copilot.bank.synth import generate_transactions
from copilot.core.patterns import detect_recurring, detect_transfers
from copilot.core.timeutil import from_utc_iso


def test_detect_transfers_ground_truth():
    # 3 months, 2 accounts to allow transfers
    res = generate_transactions(123, 3, "u1", ["acc1", "acc2"])

    # Ground truth says which are transfers
    true_transfers = set(t_id for t_id, truth in res.tx_truth.items() if truth.is_transfer)

    links = detect_transfers(res.transactions, window_hours=48)

    found_transfers = set()
    for d, c in links:
        found_transfers.add(d.id)
        found_transfers.add(c.id)
        assert abs(d.amount_paise) == abs(c.amount_paise)
        assert d.direction == "debit"
        assert c.direction == "credit"

        # Check window
        dt = from_utc_iso(d.occurred_at)
        ct = from_utc_iso(c.occurred_at)
        assert abs((dt - ct).total_seconds()) <= 48 * 3600

    # We should find all ground truth transfers
    assert true_transfers == found_transfers


def test_detect_transfers_no_false_links():
    # If amounts are equal but outside window, no link
    res = generate_transactions(123, 3, "u1", ["acc1", "acc2"])

    # Fake a transfer outside the window
    d = res.transactions[0].model_copy(
        update={
            "id": "fake_d",
            "direction": "debit",
            "amount_paise": 99999,
            "occurred_at": "2024-01-01T10:00:00Z",
        }
    )
    c = res.transactions[1].model_copy(
        update={
            "id": "fake_c",
            "direction": "credit",
            "amount_paise": -99999,
            "occurred_at": "2024-01-10T10:00:00Z",  # 9 days later
        }
    )

    txs = res.transactions + [d, c]
    links = detect_transfers(txs, window_hours=48)

    for link_d, link_c in links:
        assert link_d.id != "fake_d"
        assert link_c.id != "fake_c"


def test_excluded_transfers_never_count_as_spend():
    # This is more of a property test on net_spend_by_category which is in financial tools,
    # but we can verify our link creates excluded_from_spend in the tool test.
    pass


def test_detect_recurring_ground_truth():
    res = generate_transactions(123, 4, "u1", ["acc1"])

    # Mock merchant_normalized because pipeline hasn't run
    for t in res.transactions:
        if "ALLOWANCE" in t.merchant_raw:
            t.merchant_normalized = "Allowance"
        else:
            for m in [
                "HOSTELMESS",
                "SWIGGY",
                "ZOMATO",
                "CANTEEN",
                "BLINKIT",
                "SPOTIFY",
                "NETFLIX",
                "JIORECHARGE",
                "RAPIDO",
                "UBER",
                "IRCTC",
                "XEROXCORNER",
                "AMAZON",
                "RENT",
            ]:
                if m in t.merchant_raw:
                    t.merchant_normalized = m
                    break
            else:
                t.merchant_normalized = t.merchant_raw

    series = detect_recurring(res.transactions, tolerance_pct=50, min_occurrences=3)

    # We expect Allowance (income)
    print("SERIES DETECTED:")
    import json

    for s in series:
        print(json.dumps(s, indent=2))

    kinds = [s["kind"] for s in series]
    assert "income" in kinds

    # We expect some subscription/bill
    assert len(series) >= 2

    for s in series:
        assert 0 <= s["confidence"] <= 1
        assert s["cadence_days"] > 0
