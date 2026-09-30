from decimal import Decimal

import pytest

from copilot.core.money import paise_to_rupees_str, rupees_to_paise, safe_percent


def test_rupees_to_paise():
    assert rupees_to_paise("499.50") == 49950
    assert rupees_to_paise("100") == 10000
    assert rupees_to_paise(100) == 10000
    assert rupees_to_paise(Decimal("499.50")) == 49950
    
    with pytest.raises(TypeError, match="Floats are not allowed"):
        rupees_to_paise(499.5)
        
    with pytest.raises(ValueError):
        rupees_to_paise("499.501")

def test_paise_to_rupees_str():
    assert paise_to_rupees_str(49950) == "499.50"
    assert paise_to_rupees_str(10000) == "100.00"
    assert paise_to_rupees_str(-5050) == "-50.50"
    assert paise_to_rupees_str(5) == "0.05"
    
    with pytest.raises(TypeError):
        paise_to_rupees_str(499.5) # type: ignore

def test_safe_percent():
    # 50% of 100 paise = 50 paise
    assert safe_percent(100, 50) == 50
    # 12.5% of 100 = 12.5 -> round half up to 13
    assert safe_percent(100, "12.5") == 13
    # 12.5% of 10 = 1.25 -> round half up to 1
    assert safe_percent(10, Decimal("12.5")) == 1
    # 12.5% of 12 = 1.5 -> round half up to 2
    assert safe_percent(12, "12.5") == 2
    
    with pytest.raises(TypeError, match="Floats are not allowed"):
        safe_percent(100, 12.5)
