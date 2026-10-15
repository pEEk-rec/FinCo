"""
Core Virtual Buckets Engine (PLAN_PHASE3 Section 5.3 & Stage 3.4).

Pure calculations and deterministic ledger operations for virtual spending,
goal, commitment, and flexible buckets.

Financial invariants:
1. Strict integer paise for all money math; no floats.
2. Allocations are an append-only ledger and never change transactions or bank balances.
3. Bucket spend is derived directly from transactions; recategorising a transaction
   moves spend between buckets while conserving totals.
4. Paired reassignments always sum to exactly zero.
5. Liquid balance invariant: available_unallocated + reserved_total == liquid_balance.
6. Rollover of reset_monthly buckets releases unspent funds in the closing period
   and is strictly idempotent.
"""

import calendar
import sqlite3
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from copilot.config.phase3 import BucketsConfig
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import IST, month_bounds, now_utc
from copilot.models.phase3 import (
    AllocationSummary,
    Bucket,
    BucketBalance,
)

_DEFAULT_BUCKETS_CONFIG_PATH = PROJECT_ROOT / "config" / "buckets.yaml"


def load_buckets_config(path: Path | None = None) -> BucketsConfig:
    """Load and validate virtual buckets configuration from YAML."""
    p = path or _DEFAULT_BUCKETS_CONFIG_PATH
    if not p.is_file():
        return BucketsConfig(
            low_threshold_bp=2000,
            draft_ttl_days=7,
            allowed_kinds=["spending", "goal", "commitment", "flexible"],
            allowed_period_policies=["reset_monthly", "accumulate"],
            default_period_policy={
                "spending": "reset_monthly",
                "goal": "accumulate",
                "commitment": "accumulate",
                "flexible": "reset_monthly",
            },
        )
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return BucketsConfig.model_validate(data)


def current_period_str(d: date | datetime | None = None) -> str:
    """Return the IST calendar month period YYYY-MM for a date or datetime."""
    if d is None:
        return now_utc().astimezone(IST).strftime("%Y-%m")
    if isinstance(d, datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(IST).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def get_liquid_balance(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: str | None = None,
) -> int:
    """
    Derive the user's total liquid balance across all deposit accounts.
    Opening balances minus transaction debits plus credits.
    """
    acc_row = conn.execute(
        "SELECT COALESCE(SUM(opening_balance_paise), 0) FROM accounts WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    opening = acc_row[0] if acc_row else 0

    if as_of:
        tx_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM transactions
            WHERE user_id = ? AND occurred_at <= ?
            """,
            (user_id, as_of),
        ).fetchone()
    else:
        tx_row = conn.execute(
            "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    tx_sum = tx_row[0] if tx_row else 0
    return opening - tx_sum


def bucket_allocated_paise(
    conn: sqlite3.Connection,
    user_id: str,
    bucket: Bucket,
    period: str,
) -> int:
    """
    Derive total allocated paise for a bucket in a period.
    - reset_monthly: only allocations in that exact period.
    - accumulate: sum of allocations up to and including that period.
    """
    if bucket.period_policy == "reset_monthly":
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM bucket_allocations
            WHERE user_id = ? AND bucket_id = ? AND period = ?
            """,
            (user_id, bucket.id, period),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_paise), 0)
            FROM bucket_allocations
            WHERE user_id = ? AND bucket_id = ? AND period <= ?
            """,
            (user_id, bucket.id, period),
        ).fetchone()

    return row[0] if row else 0


def bucket_spent_paise(
    conn: sqlite3.Connection,
    user_id: str,
    bucket: Bucket,
    period: str,
) -> int:
    """
    Derive net spent paise for a bucket in a period directly from transactions.
    - Matches transactions mapped via bucket_categories or commitment_matches.
    - Excludes duplicates and transactions marked excluded_from_spend.
    - Debits increase spend; credits (refunds) reduce spend within the bucket.
    - reset_monthly: transactions in that IST month.
    - accumulate: transactions up to the end of that IST month.
    - Net spend is floored at 0 (refunds larger than spend do not create negative spend).
    """
    year, month = int(period[:4]), int(period[5:7])
    start_utc, end_utc = month_bounds(year, month)

    time_clause = (
        "AND t.occurred_at >= ? AND t.occurred_at < ?"
        if bucket.period_policy == "reset_monthly"
        else "AND t.occurred_at < ?"
    )
    time_params = (start_utc, end_utc) if bucket.period_policy == "reset_monthly" else (end_utc,)

    query = f"""
        SELECT COALESCE(SUM(t.amount_paise), 0)
        FROM transactions t
        WHERE t.user_id = ?
          AND t.is_duplicate_of IS NULL
          AND (t.excluded_from_spend IS NULL OR t.excluded_from_spend = 0)
          {time_clause}
          AND (
            t.category_id IN (
                SELECT category_id FROM bucket_categories
                WHERE user_id = ? AND bucket_id = ?
            )
            OR (
                ? IS NOT NULL AND t.id IN (
                    SELECT txn_id FROM commitment_matches
                    WHERE user_id = ? AND commitment_id = ?
                )
            )
          )
    """
    params = (
        (user_id,)
        + time_params
        + (user_id, bucket.id, bucket.commitment_id, user_id, bucket.commitment_id)
    )

    row = conn.execute(query, params).fetchone()
    raw_spent = row[0] if row else 0
    return max(0, raw_spent)


def bucket_balance(
    conn: sqlite3.Connection,
    user_id: str,
    bucket: Bucket,
    period: str,
    low_threshold_bp: int = 2000,
) -> BucketBalance:
    """
    Derive current balance and status (ok, low, depleted) for a bucket in a period.
    - balance = allocated - spent.
    - depleted: balance < 0.
    - low: allocated > 0 and balance * 10000 < low_threshold_bp * allocated.
    - ok: otherwise.
    """
    allocated = bucket_allocated_paise(conn, user_id, bucket, period)
    spent = bucket_spent_paise(conn, user_id, bucket, period)
    balance = allocated - spent

    if balance < 0:
        status: Any = "depleted"
    elif allocated > 0 and (balance * 10000) < (low_threshold_bp * allocated):
        status = "low"
    else:
        status = "ok"

    return BucketBalance(
        bucket_id=bucket.id,
        name=bucket.name,
        kind=bucket.kind,
        period=period,
        allocated_paise=allocated,
        spent_paise=spent,
        balance_paise=balance,
        status=status,
    )


def get_allocation_summary(
    conn: sqlite3.Connection,
    user_id: str,
    period: str | None = None,
    low_threshold_bp: int = 2000,
) -> AllocationSummary:
    """
    Derive full allocation summary across all active buckets in the specified period.
    Guarantees the invariant: available_unallocated + reserved_total == liquid_balance.
    """
    period_str = period or current_period_str()
    rows = conn.execute(
        "SELECT * FROM buckets WHERE user_id = ? AND status = 'active' ORDER BY sort_order, name",
        (user_id,),
    ).fetchall()
    active_buckets = [Bucket.model_validate(dict(r)) for r in rows]

    balances: list[BucketBalance] = []
    reserved_total = 0
    for b in active_buckets:
        bal = bucket_balance(conn, user_id, b, period_str, low_threshold_bp=low_threshold_bp)
        balances.append(bal)
        if bal.balance_paise > 0:
            reserved_total += bal.balance_paise

    liquid = get_liquid_balance(conn, user_id)
    available = liquid - reserved_total
    over_allocated = max(0, -available)

    return AllocationSummary(
        period=period_str,
        liquid_balance_paise=liquid,
        reserved_total_paise=reserved_total,
        available_unallocated_paise=available,
        over_allocated_by_paise=over_allocated,
        buckets=balances,
    )


def would_exceed(
    conn: sqlite3.Connection,
    user_id: str,
    bucket: Bucket,
    amount_paise: int,
    period: str | None = None,
    low_threshold_bp: int = 2000,
) -> bool:
    """
    Pure check: would spending amount_paise cause the bucket balance to become negative?
    """
    period_str = period or current_period_str()
    bal = bucket_balance(conn, user_id, bucket, period_str, low_threshold_bp=low_threshold_bp)
    return (bal.balance_paise - amount_paise) < 0


def rollover_buckets(
    conn: sqlite3.Connection,
    user_id: str,
    closing_period: str,
) -> list[str]:
    """
    Idempotent month rollover for reset_monthly buckets:
    - For active reset_monthly buckets with unspent balance > 0 in closing_period,
      releases the unspent balance via a release row dated in the closing period.
    - Depleted buckets (balance < 0) are NOT released, preserving their overspend record.
    - Accumulate buckets are not touched.
    - Repeated calls for the same closing_period insert nothing and preserve idempotency.
    """
    rows = conn.execute(
        """
        SELECT * FROM buckets
        WHERE user_id = ? AND status = 'active' AND period_policy = 'reset_monthly'
        ORDER BY sort_order, name
        """,
        (user_id,),
    ).fetchall()
    reset_buckets = [Bucket.model_validate(dict(r)) for r in rows]

    year, month = int(closing_period[:4]), int(closing_period[5:7])
    last_day = calendar.monthrange(year, month)[1]
    closing_ts = f"{closing_period}-{last_day:02d}T23:59:59Z"

    created_ids: list[str] = []
    for b in reset_buckets:
        allocated = bucket_allocated_paise(conn, user_id, b, closing_period)
        spent = bucket_spent_paise(conn, user_id, b, closing_period)
        unspent = allocated - spent
        if unspent > 0:
            alloc_id = f"ba_ro_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO bucket_allocations (
                    id, user_id, bucket_id, amount_paise, kind,
                    period, pair_id, source, draft_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alloc_id,
                    user_id,
                    b.id,
                    -unspent,
                    "release",
                    closing_period,
                    None,
                    "system_rollover",
                    None,
                    closing_ts,
                ),
            )
            created_ids.append(alloc_id)

    return created_ids
