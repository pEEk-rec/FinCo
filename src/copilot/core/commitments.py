"""
Pure deterministic engine for Financial Commitments and Occurrences (PLAN_PHASE3 Section 5.1).
Calculates exact due dates, recurrence schedules, matching against transactions, and statuses.
"""

import calendar
import datetime
from typing import Any

from copilot.models.phase3 import Commitment, Occurrence


def _parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


def _format_date(d: datetime.date) -> str:
    return d.isoformat()


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def expand_occurrences(
    commitment: Commitment,
    window_from: str,
    window_to: str,
) -> list[Occurrence]:
    """
    Expand a commitment into all occurrences within [window_from, window_to] inclusive (IST).

    Rules (PLAN_PHASE3 5.1):
    - Paused, ended, rejected commitments produce NO occurrences.
    - Draft commitments produce occurrences only when explicitly expanded (for testing/inspection),
      but are excluded from projections.
    - monthly with day 29-31 falls on the last day of shorter months (e.g. Feb 28/29, Apr 30).
    - yearly on 29 Feb falls on 28 Feb in non-leap years.
    - every_n_days anchored at schedule_json.anchor.
    - Respects start_date and end_date.
    """
    if commitment.status in ("paused", "ended", "rejected"):
        return []

    win_start = _parse_date(window_from)
    win_end = _parse_date(window_to)
    com_start = _parse_date(commitment.start_date)
    com_end = _parse_date(commitment.end_date) if commitment.end_date else None

    # Determine bounds
    eff_start = max(win_start, com_start)
    eff_end = min(win_end, com_end) if com_end else win_end

    if eff_start > eff_end:
        return []

    # Amounts calculation (PLAN_PHASE3 5.1)
    if commitment.certainty == "firm":
        amt = commitment.amount_paise or 0
        amt_low = amt_expected = amt_high = amt
    else:
        amt_low = commitment.amount_min_paise or 0
        amt_high = commitment.amount_max_paise or amt_low
        # mid rounded half up:
        amt_expected = (amt_low + amt_high + 1) // 2

    occurrences: list[Occurrence] = []
    sched = commitment.schedule_json
    kind = commitment.schedule_kind

    if kind == "once":
        due_str = sched.get("date") or sched.get("due_date")
        if due_str:
            due_d = _parse_date(due_str)
            if eff_start <= due_d <= eff_end:
                occurrences.append(
                    Occurrence(
                        commitment_id=commitment.id,
                        due_date=_format_date(due_d),
                        amount_low_paise=amt_low,
                        amount_expected_paise=amt_expected,
                        amount_high_paise=amt_high,
                        direction=commitment.direction,
                        name=commitment.name,
                        category_id=commitment.category_id,
                        status="upcoming",
                    )
                )

    elif kind == "monthly":
        target_day = int(sched.get("day") or sched.get("day_of_month") or 1)
        # Iterate over year-months covering [eff_start, eff_end]
        cur_year = eff_start.year
        cur_month = eff_start.month
        end_year = eff_end.year
        end_month = eff_end.month

        while (cur_year, cur_month) <= (end_year, end_month):
            max_day = _last_day_of_month(cur_year, cur_month)
            actual_day = min(target_day, max_day)
            due_d = datetime.date(cur_year, cur_month, actual_day)

            if eff_start <= due_d <= eff_end and due_d >= com_start:
                if com_end is None or due_d <= com_end:
                    occurrences.append(
                        Occurrence(
                            commitment_id=commitment.id,
                            due_date=_format_date(due_d),
                            amount_low_paise=amt_low,
                            amount_expected_paise=amt_expected,
                            amount_high_paise=amt_high,
                            direction=commitment.direction,
                            name=commitment.name,
                            category_id=commitment.category_id,
                            status="upcoming",
                        )
                    )
            # Advance to next month
            if cur_month == 12:
                cur_month = 1
                cur_year += 1
            else:
                cur_month += 1

    elif kind == "weekly":
        # target_weekday: 0=Monday, 6=Sunday
        target_weekday = int(sched.get("day_of_week", 0))
        # Find first matching weekday on or after com_start
        cur = com_start
        days_ahead = (target_weekday - cur.weekday()) % 7
        cur = cur + datetime.timedelta(days=days_ahead)

        while cur <= eff_end:
            if cur >= eff_start:
                occurrences.append(
                    Occurrence(
                        commitment_id=commitment.id,
                        due_date=_format_date(cur),
                        amount_low_paise=amt_low,
                        amount_expected_paise=amt_expected,
                        amount_high_paise=amt_high,
                        direction=commitment.direction,
                        name=commitment.name,
                        category_id=commitment.category_id,
                        status="upcoming",
                    )
                )
            cur += datetime.timedelta(days=7)

    elif kind == "yearly":
        target_month = int(sched.get("month", 1))
        target_day = int(sched.get("day", 1))
        for yr in range(eff_start.year, eff_end.year + 1):
            if target_month == 2 and target_day == 29 and not calendar.isleap(yr):
                due_d = datetime.date(yr, 2, 28)
            else:
                max_d = _last_day_of_month(yr, target_month)
                due_d = datetime.date(yr, target_month, min(target_day, max_d))

            if eff_start <= due_d <= eff_end and due_d >= com_start:
                if com_end is None or due_d <= com_end:
                    occurrences.append(
                        Occurrence(
                            commitment_id=commitment.id,
                            due_date=_format_date(due_d),
                            amount_low_paise=amt_low,
                            amount_expected_paise=amt_expected,
                            amount_high_paise=amt_high,
                            direction=commitment.direction,
                            name=commitment.name,
                            category_id=commitment.category_id,
                            status="upcoming",
                        )
                    )

    elif kind == "every_n_days":
        n = int(sched.get("n", 1))
        anchor = _parse_date(sched.get("anchor", commitment.start_date))
        if n > 0:
            # Step from anchor forwards or backwards to cover eff_start to eff_end
            if anchor < com_start:
                # Step up to com_start
                delta_days = (com_start - anchor).days
                steps = (delta_days + n - 1) // n
                first = anchor + datetime.timedelta(days=steps * n)
            else:
                first = anchor

            cur = first
            # If first is beyond eff_start, step backwards if anchor is before first
            while cur > eff_start and (cur - datetime.timedelta(days=n)) >= com_start:
                cur -= datetime.timedelta(days=n)

            while cur <= eff_end:
                if cur >= eff_start and cur >= com_start:
                    if com_end is None or cur <= com_end:
                        occurrences.append(
                            Occurrence(
                                commitment_id=commitment.id,
                                due_date=_format_date(cur),
                                amount_low_paise=amt_low,
                                amount_expected_paise=amt_expected,
                                amount_high_paise=amt_high,
                                direction=commitment.direction,
                                name=commitment.name,
                                category_id=commitment.category_id,
                                status="upcoming",
                            )
                        )
                cur += datetime.timedelta(days=n)

    # Sort occurrences by due_date
    occurrences.sort(key=lambda o: o.due_date)
    return occurrences


def match_occurrences(
    occurrences: list[Occurrence],
    transactions: list[dict[str, Any]],
    tolerance_bp: int = 500,
    date_tolerance_days: int = 3,
    as_of_date: str = "2024-03-18",
) -> list[tuple[Occurrence, dict[str, Any] | None, str, int]]:
    """
    Match occurrences against transactions.

    Returns list of tuples: (occurrence, matched_txn, match_method, confidence_bp)

    Rules (PLAN_PHASE3 5.1):
    1. Recurring series match first if txn has recurring_series_id matching commitment.
    2. Otherwise match by same direction, amount within tolerance_bp,
       date within date_tolerance_days. Category match is preferred among candidates.
    3. One transaction matches AT MOST ONE occurrence.
    4. Status determination on occurrence:
       - paid: matched amount >= low bound.
       - partially_paid: matched amount < low bound.
       - overdue: due_date + date_tolerance_days < as_of_date, and no match.
       - upcoming: due_date + date_tolerance_days >= as_of_date, and no match.
    """
    as_of = _parse_date(as_of_date)
    matched_txn_ids: set[str] = set()
    results: list[tuple[Occurrence, dict[str, Any] | None, str, int]] = []

    # Sort occurrences by due_date ascending
    sorted_occs = sorted(occurrences, key=lambda o: o.due_date)

    for occ in sorted_occs:
        occ_due = _parse_date(occ.due_date)
        best_txn: dict[str, Any] | None = None
        best_method = "none"
        best_conf = 0
        best_score = -1

        for txn in transactions:
            txn_id = txn["id"]
            if txn_id in matched_txn_ids:
                continue

            # Direction check:
            # FinCo sign convention: debit > 0 is outflow, credit < 0 is inflow.
            # Txn dict may have direction: 'debit'/'credit' or amount_paise signed.
            txn_dir = txn.get("direction")
            if not txn_dir:
                amt = txn.get("amount_paise", 0)
                txn_dir = "outflow" if amt > 0 else "inflow"
            else:
                txn_dir = "outflow" if txn_dir == "debit" else "inflow"

            if txn_dir != occ.direction:
                continue

            txn_date = _parse_date(txn["occurred_at"][:10])
            days_diff = abs((txn_date - occ_due).days)
            if days_diff > date_tolerance_days:
                continue

            txn_amount = abs(txn["amount_paise"])
            expected = occ.amount_expected_paise
            tolerance_paise = max(1, (expected * tolerance_bp) // 10000)

            # Amount check
            amt_diff = abs(txn_amount - expected)
            if amt_diff > tolerance_paise:
                # Also allow if within [low, high] bounds
                if not (occ.amount_low_paise <= txn_amount <= occ.amount_high_paise):
                    continue

            # Check for series match
            series_id = txn.get("recurring_series_id")
            score = 0
            method = "amount_date"
            conf = 7000

            if series_id and series_id == txn.get("recurring_series_id"):
                method = "series"
                conf = 9500
                score += 1000

            # Category preference
            if occ.category_id and occ.category_id == txn.get("category_id"):
                score += 100
                conf = min(10000, conf + 500)

            # Proximity in date and amount
            score += (date_tolerance_days - days_diff) * 10
            score -= amt_diff // 1000

            if score > best_score:
                best_score = score
                best_txn = txn
                best_method = method
                best_conf = conf

        # Determine status
        if best_txn is not None:
            matched_txn_ids.add(best_txn["id"])
            txn_amt = abs(best_txn["amount_paise"])
            if txn_amt >= occ.amount_low_paise:
                occ.status = "paid"
            else:
                occ.status = "partially_paid"
            results.append((occ, best_txn, best_method, best_conf))
        else:
            if (occ_due + datetime.timedelta(days=date_tolerance_days)) < as_of:
                occ.status = "overdue"
            else:
                occ.status = "upcoming"
            results.append((occ, None, "none", 0))

    return results
