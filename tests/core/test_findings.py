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


def test_matches_boundaries():
    # 1. "₹1.2k" -> written=1200, quantum=100.
    # tolerance = min(50, 60) = 50. Accepted: [1150, 1250]
    m_1_2k = extract_numbers("₹1.2k")[0]
    assert m_1_2k.value == Decimal("1200")
    assert m_1_2k.quantum == Decimal("100")
    assert matches(m_1_2k.value, Decimal("1150"), m_1_2k.quantum)
    assert matches(m_1_2k.value, Decimal("1250"), m_1_2k.quantum)
    assert matches(m_1_2k.value, Decimal("1234.50"), m_1_2k.quantum)
    assert not matches(m_1_2k.value, Decimal("1149.99"), m_1_2k.quantum)
    assert not matches(m_1_2k.value, Decimal("1250.01"), m_1_2k.quantum)

    # 2. "1 lakh" -> written=100000, quantum=100000.
    # tolerance = min(50000, 5000) = 5000. Accepted: [95000, 105000]
    m_1l = extract_numbers("1 lakh")[0]
    assert m_1l.value == Decimal("100000")
    assert m_1l.quantum == Decimal("100000")
    assert matches(m_1l.value, Decimal("95000"), m_1l.quantum)
    assert matches(m_1l.value, Decimal("105000"), m_1l.quantum)
    assert matches(m_1l.value, Decimal("100000"), m_1l.quantum)
    assert not matches(m_1l.value, Decimal("94999"), m_1l.quantum)
    assert not matches(m_1l.value, Decimal("105001"), m_1l.quantum)
    # Must fail cases
    assert not matches(m_1l.value, Decimal("60000"), m_1l.quantum)
    assert not matches(m_1l.value, Decimal("150000"), m_1l.quantum)

    # 3. "1.5 lakh" -> written=150000, quantum=10000.
    # tolerance = min(5000, 7500) = 5000. Accepted: [145000, 155000]
    m_1_5l = extract_numbers("1.5 lakh")[0]
    assert m_1_5l.value == Decimal("150000")
    assert m_1_5l.quantum == Decimal("10000")
    assert matches(m_1_5l.value, Decimal("145000"), m_1_5l.quantum)
    assert matches(m_1_5l.value, Decimal("155000"), m_1_5l.quantum)
    assert not matches(m_1_5l.value, Decimal("144999"), m_1_5l.quantum)
    assert not matches(m_1_5l.value, Decimal("155001"), m_1_5l.quantum)
    assert not matches(m_1_5l.value, Decimal("140000"), m_1_5l.quantum)
    assert not matches(m_1_5l.value, Decimal("160000"), m_1_5l.quantum)

    # 4. "2 crore" -> written=20000000, quantum=10000000.
    # tolerance = min(5000000, 1000000) = 1000000. Accepted: [19000000, 21000000]
    m_2cr = extract_numbers("2 crore")[0]
    assert m_2cr.value == Decimal("20000000")
    assert m_2cr.quantum == Decimal("10000000")
    assert matches(m_2cr.value, Decimal("19000000"), m_2cr.quantum)
    assert matches(m_2cr.value, Decimal("21000000"), m_2cr.quantum)
    assert not matches(m_2cr.value, Decimal("18999999"), m_2cr.quantum)
    assert not matches(m_2cr.value, Decimal("21000001"), m_2cr.quantum)

    # 5. Plain rupee amount: "₹500" -> written=500, quantum=1.
    # tolerance = min(0.5, 25) = 0.5. Accepted: [499.5, 500.5]
    m_plain = extract_numbers("₹500")[0]
    assert m_plain.value == Decimal("500")
    assert m_plain.quantum == Decimal("1")
    assert matches(m_plain.value, Decimal("499.50"), m_plain.quantum)
    assert matches(m_plain.value, Decimal("500"), m_plain.quantum)
    assert matches(m_plain.value, Decimal("500.50"), m_plain.quantum)
    assert not matches(m_plain.value, Decimal("499.49"), m_plain.quantum)
    assert not matches(m_plain.value, Decimal("500.51"), m_plain.quantum)


def test_validate_advice_lakh_boundaries():
    findings_60k = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2024-10",
            subject="Rent",
            description="Spend on rent",
            numbers=[FindingNumber(label="spend", value=6000000, unit="paise")],
        ),
    }
    v1 = validate_advice(
        AdviceDraft(text="You spent 1 lakh on rent", finding_ids=["f1"]), findings_60k
    )
    assert not v1.ok

    findings_150k = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2024-10",
            subject="Rent",
            description="Spend on rent",
            numbers=[FindingNumber(label="spend", value=15000000, unit="paise")],
        ),
    }
    v2 = validate_advice(
        AdviceDraft(text="You spent 1 lakh on rent", finding_ids=["f1"]), findings_150k
    )
    assert not v2.ok

    findings_98k = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2024-10",
            subject="Rent",
            description="Spend on rent",
            numbers=[FindingNumber(label="spend", value=9800000, unit="paise")],
        ),
    }
    v3 = validate_advice(
        AdviceDraft(text="You spent 1 lakh on rent", finding_ids=["f1"]), findings_98k
    )
    assert v3.ok
