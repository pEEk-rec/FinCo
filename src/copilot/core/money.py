"""
Money primitives using integer paise.
All amounts must be handled as integer paise to avoid floating-point errors.
"""

from decimal import ROUND_HALF_UP, Decimal


def rupees_to_paise(value: str | int | Decimal) -> int:
    """
    Convert a rupees value to integer paise.
    Rejects floats to ensure exact representation.
    """
    if isinstance(value, float):
        raise TypeError("Floats are not allowed for money. Pass a string, int, or Decimal.")
    
    # Use Decimal for exact parsing and conversion
    dec_val = Decimal(value)
    # Multiply by 100 and enforce it's an exact integer
    paise_val = dec_val * 100
    if paise_val != int(paise_val):
        raise ValueError(f"Value {value} has fractional paise, which is not supported.")
    
    return int(paise_val)

def paise_to_rupees_str(paise: int) -> str:
    """
    Convert integer paise to a formatted rupees string (e.g. '499.50').
    """
    if not isinstance(paise, int):
        raise TypeError("Paise must be an integer.")
    
    sign = "-" if paise < 0 else ""
    abs_paise = abs(paise)
    rupees = abs_paise // 100
    paisa = abs_paise % 100
    return f"{sign}{rupees}.{paisa:02d}"

def safe_percent(paise: int, pct: int | Decimal | str) -> int:
    """
    Calculate a percentage of a paise amount, rounding half up to the nearest integer.
    `pct` should be a percentage value like 50 for 50%, or '12.5' for 12.5%.
    """
    if isinstance(pct, float):
        raise TypeError("Floats are not allowed. Pass pct as string, int, or Decimal.")
    
    pct_dec = Decimal(pct)
    paise_dec = Decimal(paise)
    
    result = (paise_dec * pct_dec) / Decimal(100)
    return int(result.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
