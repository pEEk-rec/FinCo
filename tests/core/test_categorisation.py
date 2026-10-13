from copilot.core.categorisation import CategorizationRule, evaluate_rules, normalize_merchant


def test_normalize_merchant():
    aliases = {"swiggy pvt ltd": "swiggy", "zomato online": "zomato"}
    cases = [
        ("UPI-SWIGGY-1234567890@okhdfcbank", "swiggy"),
        ("IMPS-9876543210-ALICE", "alice"),
        ("NEFT-CR-ALLOWANCE-REF2181241943", "allowance"),
        ("POS 1234 12/03/24 GROCERY STORE", "grocery store"),
        ("ECOM/ZOMATO ONLINE/1234", "zomato"),
        ("ZOMATO ONLINE", "zomato"),
        ("Swiggy Pvt Ltd", "swiggy"),
        ("ATM WDL 12-03-24", "wdl"),
        ("Rent for June /txn 1234", "rent for june"),
        ("Payment to @somebody", "payment to"),
        ("A    B   C", "a b c"),
        ("A B C", "a b c"),
    ]
    for raw, expected in cases:
        assert normalize_merchant(raw, aliases) == expected


def test_evaluate_rules():
    rules = [
        CategorizationRule(match="swiggy", is_regex=False, category_id="food", confidence=0.9),
        CategorizationRule(
            match=".*store.*", is_regex=True, category_id="groceries", confidence=0.8
        ),
        CategorizationRule(
            match="salary",
            is_regex=False,
            category_id="income",
            confidence=1.0,
            direction="credit",
            min_amount_paise=5000000,
        ),
    ]

    assert evaluate_rules("swiggy", 10000, "debit", rules) == ("food", 0.9)
    assert evaluate_rules("grocery store", 10000, "debit", rules) == ("groceries", 0.8)
    assert evaluate_rules("salary", 6000000, "credit", rules) == ("income", 1.0)
    # Direction mismatch
    assert evaluate_rules("salary", 6000000, "debit", rules) is None
    # Amount too small
    assert evaluate_rules("salary", 10000, "credit", rules) is None
    # No match
    assert evaluate_rules("uber", 5000, "debit", rules) is None
