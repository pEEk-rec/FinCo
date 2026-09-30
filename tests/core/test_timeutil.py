from datetime import UTC, datetime

import pytest

from copilot.core.timeutil import (
    IST,
    from_utc_iso,
    month_bounds,
    month_of,
    normalize_utc_iso,
    now_utc,
    to_utc_iso,
)


def test_to_utc_iso():
    dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert to_utc_iso(dt) == "2023-01-01T12:00:00Z"

    dt_ist = datetime(2023, 1, 1, 17, 30, 0, tzinfo=IST)
    assert to_utc_iso(dt_ist) == "2023-01-01T12:00:00Z"

    with pytest.raises(ValueError):
        to_utc_iso(datetime(2023, 1, 1, 12, 0, 0))  # Naive


def test_from_utc_iso():
    dt = from_utc_iso("2023-01-01T12:00:00Z")
    assert dt.tzinfo == UTC
    assert dt.year == 2023
    assert dt.hour == 12

    # Offsets other than UTC are converted
    assert from_utc_iso("2024-01-31T23:30:00+05:30") == datetime(2024, 1, 31, 18, 0, tzinfo=UTC)


def test_from_utc_iso_rejects_naive_and_garbage():
    with pytest.raises(ValueError, match="no timezone"):
        from_utc_iso("2024-01-31T23:30:00")
    with pytest.raises(ValueError):
        from_utc_iso("yesterday")
    with pytest.raises(TypeError):
        from_utc_iso(12345)  # type: ignore[arg-type]


def test_normalize_utc_iso():
    assert normalize_utc_iso("2024-01-31T23:30:00+05:30") == "2024-01-31T18:00:00Z"
    assert normalize_utc_iso("2024-01-31T18:00:00+00:00") == "2024-01-31T18:00:00Z"
    assert normalize_utc_iso("2024-01-31T18:00:00.999Z") == "2024-01-31T18:00:00Z"


def test_now_utc_injection():
    fake_now = datetime(2024, 5, 5, 10, 0, 0, tzinfo=IST)
    dt = now_utc(clock=fake_now)
    assert dt == fake_now.astimezone(UTC)

    with pytest.raises(ValueError):
        now_utc(clock=datetime(2024, 5, 5))  # Naive


def test_month_bounds():
    start_utc, end_utc = month_bounds(2024, 1)
    # Jan 1st 00:00 IST is Dec 31st 18:30 UTC
    assert start_utc == "2023-12-31T18:30:00Z"
    # Feb 1st 00:00 IST is Jan 31st 18:30 UTC
    assert end_utc == "2024-01-31T18:30:00Z"

    # Leap year check
    start_utc_feb, end_utc_feb = month_bounds(2024, 2)
    assert start_utc_feb == "2024-01-31T18:30:00Z"
    # Mar 1st 00:00 IST is Feb 29th 18:30 UTC
    assert end_utc_feb == "2024-02-29T18:30:00Z"

    # Non-leap year: Mar 1st 00:00 IST is Feb 28th 18:30 UTC
    assert month_bounds(2023, 2)[1] == "2023-02-28T18:30:00Z"

    # December rolls over the year
    assert month_bounds(2024, 12) == ("2024-11-30T18:30:00Z", "2024-12-31T18:30:00Z")


@pytest.mark.parametrize("bad_month", [0, 13])
def test_month_bounds_rejects_bad_month(bad_month):
    with pytest.raises(ValueError, match="Month must be"):
        month_bounds(2024, bad_month)


def test_month_of():
    # 23:30 IST on Jan 31st belongs to Jan
    # 23:30 IST = 18:00 UTC on Jan 31st
    assert month_of("2024-01-31T18:00:00Z") == (2024, 1)

    # 00:30 IST on Feb 1st belongs to Feb
    # 00:30 IST = 19:00 UTC on Jan 31st
    assert month_of("2024-01-31T19:00:00Z") == (2024, 2)

    # Exactly at the boundary belongs to the new month (half-open)
    assert month_of("2024-01-31T18:30:00Z") == (2024, 2)
    assert month_of("2024-01-31T18:29:59Z") == (2024, 1)
