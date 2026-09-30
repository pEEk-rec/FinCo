"""
Time primitives enforcing UTC storage and IST-based bounds.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def now_utc(clock: datetime | None = None) -> datetime:
    """
    Get the current UTC time. 
    Accepts an optional `clock` for testing purposes.
    """
    if clock is not None:
        if clock.tzinfo is None:
            raise ValueError("Injected clock must be timezone-aware.")
        return clock.astimezone(timezone.utc)
    return datetime.now(timezone.utc)

def to_utc_iso(dt: datetime) -> str:
    """
    Convert a timezone-aware datetime to a UTC ISO-8601 string.
    """
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware.")
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.isoformat(timespec='seconds').replace('+00:00', 'Z')

def from_utc_iso(s: str) -> datetime:
    """
    Parse a UTC ISO-8601 string into a timezone-aware UTC datetime.
    """
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def month_bounds(year: int, month: int) -> tuple[str, str]:
    """
    Get half-open bounds [start, end) for a given year and month in IST,
    returned as UTC ISO strings.
    """
    start_ist = datetime(year, month, 1, 0, 0, 0, tzinfo=IST)
    
    # Calculate next month
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
        
    end_ist = datetime(next_year, next_month, 1, 0, 0, 0, tzinfo=IST)
    
    return to_utc_iso(start_ist), to_utc_iso(end_ist)

def month_of(utc_iso: str) -> tuple[int, int]:
    """
    Get the (year, month) in IST for a given UTC ISO string.
    """
    dt = from_utc_iso(utc_iso)
    ist_dt = dt.astimezone(IST)
    return ist_dt.year, ist_dt.month
