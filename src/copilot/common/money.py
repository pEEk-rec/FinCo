"""
Money primitives using integer paise.

All amounts must be handled as integer paise to avoid floating-point errors.
Display format is plain rupees with two decimals and no currency symbol, e.g. "499.50".
"""

import re
from decimal import ROUND_HALF_UP, Decimal

# Plain decimal number: optional sign, digits, optional fraction. No exponents or underscores.
_MONEY_STR = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _to_decimal(value: object, what: str) -> Decimal:
    """Convert an int, Decimal or plain numeric string to a finite Decimal, rejecting the rest."""
    # bool is a subclass of int, so it must be rejected before the int check.
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{what}: {type(value).__name__} is not allowed. Pass str, int or Decimal.")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, str):
        text = value.strip()
        if not _MONEY_STR.match(text):
            raise ValueError(f"{what}: {value!r} is not a plain decimal number.")
        dec = Decimal(text)
    else:
        raise TypeError(f"{what}: {type(value).__name__} is not allowed. Pass str, int or Decimal.")
    if not dec.is_finite():
        raise ValueError(f"{what}: {value!r} is not a finite number.")
    return dec


def _require_paise(paise: object) -> int:
    """Return `paise` if it is a real int (not bool), else raise TypeError."""
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("Paise must be an integer.")
    return paise


def rupees_to_paise(value: str | int | Decimal) -> int:
    """
    Convert a rupees value to integer paise.

    Accepts str ("499.50"), int (rupees) or Decimal. Rejects floats, bools, NaN/Infinity,
    exponent notation and values with fractional paise (e.g. "1.005").
    """
    paise = _to_decimal(value, "rupees") * 100
    if paise != paise.to_integral_value():
        raise ValueError(f"Value {value!r} has fractional paise, which is not supported.")
    return int(paise)


def paise_to_rupees_str(paise: int) -> str:
    """Convert integer paise to a rupees string with two decimals, e.g. 49950 -> '499.50'."""
    _require_paise(paise)
    sign = "-" if paise < 0 else ""
    rupees, paisa = divmod(abs(paise), 100)
    return f"{sign}{rupees}.{paisa:02d}"


def safe_percent(paise: int, pct: int | Decimal | str) -> int:
    """
    Return `pct` percent of `paise`, rounded to whole paise with ROUND_HALF_UP.

    `pct` is a percentage like 50 or "12.5". ROUND_HALF_UP in `decimal` rounds halves away
    from zero, so 12.5 -> 13 and -12.5 -> -13 (symmetric for refunds).
    """
    _require_paise(paise)
    result = Decimal(paise) * _to_decimal(pct, "pct") / Decimal(100)
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
