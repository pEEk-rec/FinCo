from decimal import Decimal

from copilot.core.advice import (
    extract_numbers,
    matches,
    validate_advice,
)
from copilot.models.findings import AdviceDraft, Finding, FindingNumber


def test_extract_numbers():
    text = "You spent ₹1,234.50 on food, up 10% from last month, making 1.2k total and 1 lakh soon."
    numbers = extract_numbers(text)

    # ₹1,234.50
    assert numbers[0].value == Decimal("1234.50")
    assert numbers[0].quantum == Decimal("0.01")
    assert numbers[0].kind == "amount"

    # 10%
    assert numbers[1].value == Decimal("10")
    assert numbers[1].quantum == Decimal("1")
    assert numbers[1].kind == "percent"

    # 1.2k
    assert numbers[2].value == Decimal("1200")
    assert numbers[2].quantum == Decimal("100")
    assert numbers[2].kind == "amount"

    # 1 lakh
    assert numbers[3].value == Decimal("100000")
    assert numbers[3].quantum == Decimal("100000")
    assert numbers[3].kind == "amount"


def test_matches_rounding():
    # True value 123450 paise (1234.50 rupees)
    t = Decimal("1234.50")

    # exact matches
    assert matches(Decimal("1234.50"), t, Decimal("0.01"))

    # integer matching: rounds half up to 1235, or truncate to 1234
    assert matches(Decimal("1235"), t, Decimal("1"))
    assert matches(Decimal("1234"), t, Decimal("1"))

    # 1.2k matches 1200 (truncate)
    assert matches(Decimal("1200"), t, Decimal("100"))

    # 1.3k does not match 1234.50
    assert not matches(Decimal("1300"), t, Decimal("100"))


def test_validate_advice():
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2024-10",
            subject="Food",
            description="High spend on food",
            numbers=[
                FindingNumber(label="spend", value=123450, unit="paise"),
                FindingNumber(label="pct", value=10, unit="percent"),
            ],
        ),
    }

    # Valid advice (exact number)
    v = validate_advice(
        AdviceDraft(text="You spent ₹1,234.50 on food", finding_ids=["f1"]), findings
    )
    assert v.ok

    # Valid advice (rounded k number)
    v = validate_advice(AdviceDraft(text="You spent ₹1.2k on food", finding_ids=["f1"]), findings)
    assert v.ok

    # Valid advice (context numbers: month '10' and year '2024' are allowed)
    v = validate_advice(
        AdviceDraft(text="In October 2024 you spent ₹1.2k", finding_ids=["f1"]), findings
    )
    assert v.ok

    # Invalid advice (hallucinated percent)
    v = validate_advice(AdviceDraft(text="You spent 12% on food", finding_ids=["f1"]), findings)
    assert not v.ok
    assert any("not in the cited findings" in msg for msg in v.violations)

    # Invalid advice (forbidden word 'transfer')
    v = validate_advice(
        AdviceDraft(text="You should transfer ₹1,234 to savings", finding_ids=["f1"]), findings
    )
    assert not v.ok
    assert any("moving or paying money" in msg for msg in v.violations)

    # Invalid advice (unknown finding)
    v = validate_advice(AdviceDraft(text="You spent ₹1,234 on food", finding_ids=["f3"]), findings)
    assert not v.ok
    assert any("unknown finding" in msg for msg in v.violations)
