"""
Metric Catalogue for Phase 4 Financial Experiments (PLAN_PHASE4 Section 5.1).
Every metric is a pure function (user_id, window_start, window_end, params, conn) -> int.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from copilot.core.timeutil import IST, from_utc_iso, to_utc_iso

METRIC_DIRECTIONS: dict[str, str] = {
    "category_spend": "lower",
    "merchant_group_spend": "lower",
    "txn_count": "lower",
    "no_spend_days": "higher",
    "bucket_adherence_days": "higher",
    "goal_allocation": "higher",
    "checkin_rate": "higher",
    "tagging_completeness": "higher",
}

METRIC_CATALOGUE: set[str] = set(METRIC_DIRECTIONS.keys())


def _date_to_utc_bounds(start_str: str, end_str: str) -> tuple[str, str]:
    """Convert YYYY-MM-DD IST window bounds to [start_utc, end_utc) ISO strings."""
    s_date = date.fromisoformat(start_str)
    e_date = date.fromisoformat(end_str)
    start_ist = datetime(s_date.year, s_date.month, s_date.day, 0, 0, 0, tzinfo=IST)
    end_ist = (
        datetime(e_date.year, e_date.month, e_date.day, 0, 0, 0, tzinfo=IST)
        + timedelta(days=1)
    )
    return to_utc_iso(start_ist), to_utc_iso(end_ist)


def _get_commitment_matched_txns(conn: sqlite3.Connection, user_id: str) -> set[str]:
    """Fetch txn_ids that are matched to commitments to exclude from experiment metrics."""
    query = "SELECT DISTINCT txn_id FROM commitment_matches WHERE user_id = ?"
    rows = conn.execute(query, (user_id,)).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------------------------
# 1. category_spend
# ---------------------------------------------------------------------------------------------
def calculate_category_spend(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    categories: list[str],
    weekdays_only: bool = False,
) -> int:
    """
    Sum of debits in listed non-essential categories minus refunds (floored at 0).
    Excludes transfers, duplicates, and commitment-matched transactions.
    """
    if not categories:
        return 0
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    matched = _get_commitment_matched_txns(conn, user_id)

    query = """
        SELECT id, occurred_at, amount_paise, direction, category_id,
               excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    rows = conn.execute(query, (user_id, start_utc, end_utc)).fetchall()

    net_paise = 0
    cat_set = set(categories)

    for r in rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None or r["id"] in matched:
            continue
        if r["category_id"] not in cat_set:
            continue
        if weekdays_only:
            tx_dt = from_utc_iso(r["occurred_at"]).astimezone(IST)
            if tx_dt.weekday() >= 5:  # Saturday or Sunday
                continue

        # In FinCo debit is positive amount_paise, refund/credit is negative amount_paise
        net_paise += r["amount_paise"]

    return max(0, net_paise)


# ---------------------------------------------------------------------------------------------
# 2. merchant_group_spend
# ---------------------------------------------------------------------------------------------
def calculate_merchant_group_spend(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    merchants: list[str],
    categories: list[str] | None = None,
    weekdays_only: bool = False,
) -> int:
    """
    Sum of debits to user-chosen merchant group minus refunds (floored at 0).
    """
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    matched = _get_commitment_matched_txns(conn, user_id)

    query = """
        SELECT id, occurred_at, amount_paise, direction, merchant_raw, merchant_normalized,
               category_id, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    rows = conn.execute(query, (user_id, start_utc, end_utc)).fetchall()

    merchant_tokens = [m.lower().strip() for m in merchants if m.strip()]
    cat_set = set(categories) if categories else None
    net_paise = 0

    for r in rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None or r["id"] in matched:
            continue
        if weekdays_only:
            tx_dt = from_utc_iso(r["occurred_at"]).astimezone(IST)
            if tx_dt.weekday() >= 5:
                continue

        m_name = (r["merchant_normalized"] or r["merchant_raw"] or "").lower()
        matches_merchant = (
            any(tok in m_name for tok in merchant_tokens) if merchant_tokens else False
        )
        matches_category = (r["category_id"] in cat_set) if cat_set else False

        if matches_merchant or (not merchant_tokens and matches_category):
            net_paise += r["amount_paise"]

    return max(0, net_paise)


# ---------------------------------------------------------------------------------------------
# 3. txn_count
# ---------------------------------------------------------------------------------------------
def calculate_txn_count(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    categories: list[str] | None = None,
    weekdays_only: bool = False,
) -> int:
    """
    Number of debits in listed categories.
    """
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    matched = _get_commitment_matched_txns(conn, user_id)

    query = """
        SELECT id, occurred_at, direction, category_id, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ? AND direction = 'debit'
    """
    rows = conn.execute(query, (user_id, start_utc, end_utc)).fetchall()
    cat_set = set(categories) if categories else None
    count = 0

    for r in rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None or r["id"] in matched:
            continue
        if cat_set and r["category_id"] not in cat_set:
            continue
        if weekdays_only:
            tx_dt = from_utc_iso(r["occurred_at"]).astimezone(IST)
            if tx_dt.weekday() >= 5:
                continue
        count += 1

    return count


# ---------------------------------------------------------------------------------------------
# 4. no_spend_days
# ---------------------------------------------------------------------------------------------
def calculate_no_spend_days(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    categories: list[str] | None = None,
    weekdays_only: bool = False,
) -> int:
    """
    Days with zero debits in listed non-essential categories.
    """
    s_date = date.fromisoformat(start_date)
    e_date = date.fromisoformat(end_date)
    total_days = (e_date - s_date).days + 1

    candidate_days: list[date] = []
    for i in range(total_days):
        d = s_date + timedelta(days=i)
        if weekdays_only and d.weekday() >= 5:
            continue
        candidate_days.append(d)

    if not candidate_days:
        return 0

    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    matched = _get_commitment_matched_txns(conn, user_id)

    query = """
        SELECT id, occurred_at, category_id, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ? AND direction = 'debit'
    """
    rows = conn.execute(query, (user_id, start_utc, end_utc)).fetchall()
    cat_set = set(categories) if categories else None
    spend_days: set[date] = set()

    for r in rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None or r["id"] in matched:
            continue
        if cat_set and r["category_id"] not in cat_set:
            continue
        tx_day = from_utc_iso(r["occurred_at"]).astimezone(IST).date()
        spend_days.add(tx_day)

    no_spend = sum(1 for d in candidate_days if d not in spend_days)
    return no_spend


# ---------------------------------------------------------------------------------------------
# 5. bucket_adherence_days
# ---------------------------------------------------------------------------------------------
def calculate_bucket_adherence_days(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    bucket_id: str | None = None,
) -> int:
    """
    Days a chosen spending bucket stays at or above zero.

    Uses the real Phase-3 tables: ``buckets`` and ``bucket_allocations``.
    The net allocation for the window's month-period is computed by summing
    all allocate/reassign_in entries and subtracting release/reassign_out.
    If no bucket is configured for this user, every day is counted adherent.
    """
    s_date = date.fromisoformat(start_date)
    e_date = date.fromisoformat(end_date)
    total_days = (e_date - s_date).days + 1
    period = s_date.strftime("%Y-%m")

    # Resolve which bucket(s) to check
    if bucket_id:
        bid_rows = conn.execute(
            "SELECT id FROM buckets WHERE user_id = ? AND id = ? AND status = 'active'",
            (user_id, bucket_id),
        ).fetchall()
    else:
        bid_rows = conn.execute(
            "SELECT id FROM buckets WHERE user_id = ? AND status = 'active' AND kind = 'spending'",
            (user_id,),
        ).fetchall()

    if not bid_rows:
        return total_days  # No bucket configured → defaults adherent

    # Net allocation for the period across all matching buckets
    bids = [r[0] for r in bid_rows]
    placeholders = ",".join("?" * len(bids))
    alloc_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(
            CASE kind
                WHEN 'allocate'    THEN  amount_paise
                WHEN 'reassign_in' THEN  amount_paise
                WHEN 'release'     THEN -amount_paise
                WHEN 'reassign_out'THEN -amount_paise
                ELSE 0
            END
        ), 0)
        FROM bucket_allocations
        WHERE user_id = ? AND bucket_id IN ({placeholders}) AND period = ?
        """,
        (user_id, *bids, period),
    ).fetchone()
    allocated = int(alloc_row[0]) if alloc_row else 0

    if allocated <= 0:
        return total_days  # Nothing allocated → defaults adherent

    # Accumulate daily spend within the window
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    matched = _get_commitment_matched_txns(conn, user_id)

    t_query = """
        SELECT id, occurred_at, amount_paise, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
        ORDER BY occurred_at ASC
    """
    tx_rows = conn.execute(t_query, (user_id, start_utc, end_utc)).fetchall()

    daily_spend: dict[date, int] = {}
    for r in tx_rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None or r["id"] in matched:
            continue
        tx_day = from_utc_iso(r["occurred_at"]).astimezone(IST).date()
        daily_spend[tx_day] = daily_spend.get(tx_day, 0) + r["amount_paise"]

    adherent_days = 0
    running_spend = 0
    for i in range(total_days):
        d = s_date + timedelta(days=i)
        running_spend += daily_spend.get(d, 0)
        if allocated - running_spend >= 0:
            adherent_days += 1

    return adherent_days


# ---------------------------------------------------------------------------------------------
# 6. goal_allocation
# ---------------------------------------------------------------------------------------------
def calculate_goal_allocation(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    goal_id: str | None = None,
) -> int:
    """
    Net logical allocations to a goal bucket or manual goal contributions in the window (paise).
    """
    query = """
        SELECT COALESCE(SUM(amount_paise), 0)
        FROM goal_contributions
        WHERE user_id = ? AND occurred_on >= ? AND occurred_on <= ?
    """
    params: list[Any] = [user_id, start_date, end_date]
    if goal_id:
        query += " AND goal_id = ?"
        params.append(goal_id)

    row = conn.execute(query, tuple(params)).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------------------------
# 7. checkin_rate
# ---------------------------------------------------------------------------------------------
def calculate_checkin_rate(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    experiment_id: str | None = None,
) -> int:
    """
    Share of scheduled check-ins answered in basis points (0 to 10000).
    """
    query = """
        SELECT user_response FROM experiment_checkins
        WHERE user_id = ? AND checkin_date >= ? AND checkin_date <= ?
    """
    params: list[Any] = [user_id, start_date, end_date]
    if experiment_id:
        query += " AND experiment_id = ?"
        params.append(experiment_id)

    rows = conn.execute(query, tuple(params)).fetchall()
    if not rows:
        return 10000  # Zero checkins scheduled, 100% adherence

    answered = sum(
        1 for r in rows if r["user_response"] is not None and r["user_response"] != "skip"
    )
    return (answered * 10000) // len(rows)


# ---------------------------------------------------------------------------------------------
# 8. tagging_completeness
# ---------------------------------------------------------------------------------------------
def calculate_tagging_completeness(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
) -> int:
    """
    Share of window's transactions with a non-guess category in basis points (0 to 10000).
    """
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)

    query = """
        SELECT id, category_id, category_source, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    rows = conn.execute(query, (user_id, start_utc, end_utc)).fetchall()
    non_excluded = [
        r for r in rows if not (r["excluded_from_spend"] or r["is_duplicate_of"] is not None)
    ]

    if not non_excluded:
        return 10000  # Zero txns -> 100% complete

    valid_sources = {"user", "override", "rule", "manual"}
    tagged = sum(
        1
        for r in non_excluded
        if r["category_id"] is not None and r["category_source"] in valid_sources
    )
    return (tagged * 10000) // len(non_excluded)


# ---------------------------------------------------------------------------------------------
# Unified Metric Dispatcher
# ---------------------------------------------------------------------------------------------
def calculate_metric(
    conn: sqlite3.Connection,
    user_id: str,
    metric_code: str,
    start_date: str,
    end_date: str,
    params: dict[str, Any] | None = None,
) -> int:
    """
    Unified entry point for computing any metric over an IST date window.
    """
    p = params or {}
    categories = p.get("categories", [])
    merchants = p.get("merchants", [])
    weekdays_only = p.get("weekdays_only", False)
    goal_id = p.get("goal_id")
    bucket_id = p.get("bucket_id")
    experiment_id = p.get("experiment_id")

    if metric_code == "category_spend":
        return calculate_category_spend(
            conn, user_id, start_date, end_date, categories, weekdays_only
        )
    if metric_code == "merchant_group_spend":
        return calculate_merchant_group_spend(
            conn, user_id, start_date, end_date, merchants, categories, weekdays_only
        )
    if metric_code == "txn_count":
        return calculate_txn_count(conn, user_id, start_date, end_date, categories, weekdays_only)
    if metric_code == "no_spend_days":
        return calculate_no_spend_days(
            conn, user_id, start_date, end_date, categories, weekdays_only
        )
    if metric_code == "bucket_adherence_days":
        return calculate_bucket_adherence_days(conn, user_id, start_date, end_date, bucket_id)
    if metric_code == "goal_allocation":
        return calculate_goal_allocation(conn, user_id, start_date, end_date, goal_id)
    if metric_code == "checkin_rate":
        return calculate_checkin_rate(conn, user_id, start_date, end_date, experiment_id)
    if metric_code == "tagging_completeness":
        return calculate_tagging_completeness(conn, user_id, start_date, end_date)

    raise ValueError(f"Unknown metric code: {metric_code}")
