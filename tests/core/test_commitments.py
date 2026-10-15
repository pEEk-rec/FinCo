"""
Tests for commitments core engine (PLAN_PHASE3 Stage 3.2).
Tests occurrence expansion edge cases, leap years, calendar clamping, and matching invariants.
"""

from copilot.core.commitments import expand_occurrences, match_occurrences
from copilot.models.phase3 import Commitment, Occurrence


def test_expand_monthly_31st_shorter_months():
    """Monthly on the 31st clamps to the last day of shorter months (e.g. Feb 28/29, Apr 30)."""
    comm = Commitment(
        id="c1",
        user_id="u1",
        name="Rent",
        direction="outflow",
        kind="rent",
        amount_paise=5000000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 31},
        start_date="2024-01-01",
        status="active",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )

    occs = expand_occurrences(comm, "2024-01-01", "2024-05-31")
    due_dates = [o.due_date for o in occs]
    # 2024 is a leap year: Jan 31, Feb 29, Mar 31, Apr 30, May 31
    assert due_dates == [
        "2024-01-31",
        "2024-02-29",
        "2024-03-31",
        "2024-04-30",
        "2024-05-31",
    ]


def test_expand_yearly_feb_29_leap_and_non_leap():
    """Yearly on Feb 29 produces Feb 29 in leap years and Feb 28 in non-leap years."""
    comm = Commitment(
        id="c2",
        user_id="u1",
        name="Leap Day Insurance",
        direction="outflow",
        kind="bill",
        amount_paise=1000000,
        certainty="firm",
        schedule_kind="yearly",
        schedule_json={"month": 2, "day": 29},
        start_date="2023-01-01",
        status="active",
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z",
    )

    occs = expand_occurrences(comm, "2023-01-01", "2026-12-31")
    due_dates = [o.due_date for o in occs]
    # 2023: 2023-02-28, 2024 (leap): 2024-02-29, 2025: 2025-02-28, 2026: 2026-02-28
    assert due_dates == [
        "2023-02-28",
        "2024-02-29",
        "2025-02-28",
        "2026-02-28",
    ]


def test_expand_every_n_days_across_boundaries():
    """every_n_days steps accurately across month and year boundaries anchored at anchor."""
    comm = Commitment(
        id="c3",
        user_id="u1",
        name="Bi-weekly cleaning",
        direction="outflow",
        kind="other",
        amount_paise=150000,
        certainty="firm",
        schedule_kind="every_n_days",
        schedule_json={"n": 14, "anchor": "2023-12-15"},
        start_date="2023-12-01",
        status="active",
        created_at="2023-12-01T00:00:00Z",
        updated_at="2023-12-01T00:00:00Z",
    )

    occs = expand_occurrences(comm, "2023-12-01", "2024-02-01")
    due_dates = [o.due_date for o in occs]
    # Anchored at 2023-12-15. Stepping backwards: 2023-12-01. Stepping forwards: 2023-12-29, 2024-01-12, 2024-01-26
    assert due_dates == [
        "2023-12-01",
        "2023-12-15",
        "2023-12-29",
        "2024-01-12",
        "2024-01-26",
    ]


def test_expand_start_and_end_date_bounds():
    """Occurrences are strictly constrained by start_date and end_date."""
    comm = Commitment(
        id="c4",
        user_id="u1",
        name="Gym Membership",
        direction="outflow",
        kind="subscription",
        amount_paise=200000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 10},
        start_date="2024-03-01",
        end_date="2024-05-15",
        status="active",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )

    occs = expand_occurrences(comm, "2024-01-01", "2024-12-31")
    due_dates = [o.due_date for o in occs]
    # March 10, April 10, May 10 (June 10 is past end_date 2024-05-15)
    assert due_dates == ["2024-03-10", "2024-04-10", "2024-05-10"]


def test_expand_paused_ended_rejected_produce_no_occurrences():
    """Paused, ended, or rejected commitments produce no occurrences."""
    for st in ("paused", "ended", "rejected"):
        comm = Commitment(
            id=f"c_{st}",
            user_id="u1",
            name=f"Inactive {st}",
            direction="outflow",
            kind="bill",
            amount_paise=100000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day": 5},
            start_date="2024-01-01",
            status=st,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        assert expand_occurrences(comm, "2024-01-01", "2024-12-31") == []


def test_estimated_amounts_mid_rounded_half_up():
    """Estimated commitments calculate mid rounded half up."""
    comm = Commitment(
        id="c_est",
        user_id="u1",
        name="Utility Bill",
        direction="outflow",
        kind="bill",
        amount_min_paise=100000,
        amount_max_paise=150001,
        certainty="estimated",
        schedule_kind="monthly",
        schedule_json={"day": 15},
        start_date="2024-01-01",
        status="active",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    occs = expand_occurrences(comm, "2024-01-01", "2024-01-31")
    assert len(occs) == 1
    occ = occs[0]
    assert occ.amount_low_paise == 100000
    assert occ.amount_high_paise == 150001
    # (100000 + 150001 + 1) // 2 = 125001
    assert occ.amount_expected_paise == 125001


def test_match_occurrences_one_to_one_invariant():
    """One transaction must match at most one occurrence."""
    occ1 = Occurrence(
        commitment_id="c1",
        due_date="2024-03-01",
        amount_low_paise=50000,
        amount_expected_paise=50000,
        amount_high_paise=50000,
        direction="outflow",
        name="Sub",
        status="upcoming",
    )
    occ2 = Occurrence(
        commitment_id="c1",
        due_date="2024-03-02",
        amount_low_paise=50000,
        amount_expected_paise=50000,
        amount_high_paise=50000,
        direction="outflow",
        name="Sub",
        status="upcoming",
    )

    single_txn = [
        {
            "id": "tx1",
            "occurred_at": "2024-03-01T10:00:00Z",
            "amount_paise": 50000,
            "direction": "debit",
        }
    ]

    matches = match_occurrences([occ1, occ2], single_txn, as_of_date="2024-03-10")
    matched_txns = [t for _, t, _, _ in matches if t is not None]
    assert len(matched_txns) == 1
    assert matches[0][0].status == "paid"
    assert matches[1][0].status == "overdue"


def test_match_tolerances_and_status_determination():
    """Matching tests tolerance in date and amount, and marks statuses accurately."""
    occ = Occurrence(
        commitment_id="c1",
        due_date="2024-03-05",
        amount_low_paise=100000,
        amount_expected_paise=100000,
        amount_high_paise=100000,
        direction="outflow",
        name="Electricity",
        status="upcoming",
    )

    # 1. Txn within tolerance: 2 days later, amount 98000 (within 5% = 5000 paise tolerance)
    tx1 = {
        "id": "tx1",
        "occurred_at": "2024-03-07T12:00:00Z",
        "amount_paise": 98000,
        "direction": "debit",
    }
    matches = match_occurrences([occ], [tx1], tolerance_bp=500, date_tolerance_days=3, as_of_date="2024-03-10")
    assert matches[0][1] is not None
    assert matches[0][0].status == "partially_paid"  # 98000 < low bound 100000

    # 2. Overdue: no match and due_date + date_tolerance < as_of_date
    matches_overdue = match_occurrences([occ], [], date_tolerance_days=3, as_of_date="2024-03-10")
    assert matches_overdue[0][0].status == "overdue"

    # 3. Upcoming: no match but due_date + date_tolerance >= as_of_date
    matches_upcoming = match_occurrences([occ], [], date_tolerance_days=3, as_of_date="2024-03-04")
    assert matches_upcoming[0][0].status == "upcoming"
