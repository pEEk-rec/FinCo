"""
Time primitives enforcing UTC storage and IST-based bounds.

Canonical storage format is second-precision UTC with a 'Z' suffix, e.g. "2024-01-31T18:30:00Z".
Because every stored timestamp has this exact shape, SQL string comparison orders them correctly.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc(clock: datetime | None = None) -> datetime:
    """
    Get the current UTC time.

    Pass `clock` (a timezone-aware datetime) to pin "now" in tests.
    """
    if clock is not None:
        if clock.tzinfo is None:
            raise ValueError("Injected clock must be timezone-aware.")
        return clock.astimezone(UTC)
    return datetime.now(UTC)


def to_utc_iso(dt: datetime) -> str:
    """Convert a timezone-aware datetime to the canonical UTC ISO-8601 string (seconds, 'Z')."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware.")
    utc_dt = dt.astimezone(UTC)
    return utc_dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def from_utc_iso(s: str) -> datetime:
    """
    Parse an ISO-8601 string with an explicit offset into an aware UTC datetime.

    Strings without an offset are rejected: a naive timestamp is ambiguous.
    """
    if not isinstance(s, str):
        raise TypeError("Timestamp must be a string.")
    text = s[:-1] + "+00:00" if s.endswith("Z") else s
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp {s!r} has no timezone offset.")
    return dt.astimezone(UTC)


def normalize_utc_iso(s: str) -> str:
    """Parse any offset-aware ISO string and return it in canonical UTC form."""
    return to_utc_iso(from_utc_iso(s))


def month_bounds(year: int, month: int) -> tuple[str, str]:
    """
    Get half-open bounds [start, end) for a calendar month in IST, as canonical UTC strings.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1..12, got {month}.")
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    start_ist = datetime(year, month, 1, tzinfo=IST)
    end_ist = datetime(next_year, next_month, 1, tzinfo=IST)
    return to_utc_iso(start_ist), to_utc_iso(end_ist)


def month_of(utc_iso: str) -> tuple[int, int]:
    """Get the (year, month) in IST for a UTC ISO string."""
    ist_dt = from_utc_iso(utc_iso).astimezone(IST)
    return ist_dt.year, ist_dt.month
