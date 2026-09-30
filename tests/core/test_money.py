from decimal import Decimal

import pytest

from copilot.core.money import paise_to_rupees_str, rupees_to_paise, safe_percent


def test_rupees_to_paise():
    assert rupees_to_paise("499.50") == 49950
    assert rupees_to_paise("100") == 10000
    assert rupees_to_paise(100) == 10000
    assert rupees_to_paise(Decimal("499.50")) == 49950
    assert rupees_to_paise(" 499.50 ") == 49950
    assert rupees_to_paise("-50.5") == -5050
    assert rupees_to_paise("499.500") == 49950

    with pytest.raises(TypeError, match="float is not allowed"):
        rupees_to_paise(499.5)

    with pytest.raises(ValueError, match="fractional paise"):
        rupees_to_paise("499.501")


@pytest.mark.parametrize("bad", [True, False, None, [1]])
def test_rupees_to_paise_rejects_non_money_types(bad):
    with pytest.raises(TypeError):
        rupees_to_paise(bad)


@pytest.mark.parametrize("bad", ["abc", "", "1e3", "1_000", "NaN", "Infinity", "12.", ".5"])
def test_rupees_to_paise_rejects_malformed_strings(bad):
    with pytest.raises(ValueError):
        rupees_to_paise(bad)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_rupees_to_paise_rejects_non_finite_decimal(bad):
    with pytest.raises(ValueError, match="finite"):
        rupees_to_paise(bad)


def test_paise_to_rupees_str():
    assert paise_to_rupees_str(49950) == "499.50"
    assert paise_to_rupees_str(10000) == "100.00"
    assert paise_to_rupees_str(-5050) == "-50.50"
    assert paise_to_rupees_str(5) == "0.05"
    assert paise_to_rupees_str(0) == "0.00"

    with pytest.raises(TypeError):
        paise_to_rupees_str(499.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        paise_to_rupees_str(True)


def test_safe_percent():
    # 50% of 100 paise = 50 paise
    assert safe_percent(100, 50) == 50
    # 12.5% of 100 = 12.5 -> round half up to 13
    assert safe_percent(100, "12.5") == 13
    # 12.5% of 10 = 1.25 -> 1
    assert safe_percent(10, Decimal("12.5")) == 1
    # 12.5% of 12 = 1.5 -> 2
    assert safe_percent(12, "12.5") == 2
    # 1.49 -> 1 (just below half)
    assert safe_percent(149, 1) == 1
    assert safe_percent(0, 50) == 0

    with pytest.raises(TypeError, match="float is not allowed"):
        safe_percent(100, 12.5)


def test_safe_percent_negative_rounds_half_away_from_zero():
    # -12.5 -> -13, the mirror of 12.5 -> 13
    assert safe_percent(-25, 50) == -13
    assert safe_percent(-12, "12.5") == -2


@pytest.mark.parametrize("bad_paise", [100.7, True, "100", Decimal("100")])
def test_safe_percent_rejects_non_int_paise(bad_paise):
    with pytest.raises(TypeError, match="Paise must be an integer"):
        safe_percent(bad_paise, 10)


@pytest.mark.parametrize("bad_pct", [True, "abc", "NaN"])
def test_safe_percent_rejects_bad_pct(bad_pct):
    with pytest.raises((TypeError, ValueError)):
        safe_percent(100, bad_pct)
