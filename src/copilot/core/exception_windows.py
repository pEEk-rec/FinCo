"""
Read declared contextual exceptions (a festival month, a trip) as date ranges.

The memory observers record an exception with a `period` ("2026-09" for a month, "2026-09-12"
for a day), while a user can also state an explicit `from_date` and `to_date`. Baselines,
adaptive pauses and streak freezes all need the same answer to "which days does this exception
cover, and for which categories", so it is decided here once.
"""

import json
import sqlite3
from calendar import monthrange
from datetime import date


def exception_range(meta: dict) -> tuple[date, date] | None:
    """The days an exception covers, or None if it names no usable dates."""
    try:
        if meta.get("from_date") and meta.get("to_date"):
            start, end = date.fromisoformat(meta["from_date"]), date.fromisoformat(meta["to_date"])
            return (start, end) if end >= start else None
        period = str(meta.get("period") or "")
        if len(period) == 10:
            day = date.fromisoformat(period)
            return day, day
        if len(period) == 7:
            year, month = int(period[:4]), int(period[5:7])
            return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    except ValueError:
        return None
    return None


def applies_to(meta: dict, categories: list[str] | None) -> bool:
    """An exception with no category applies to everything; otherwise it must name one of them."""
    category = meta.get("category")
    if not category or category in ("all", "*") or not categories:
        return True
    return category in categories


def active_exceptions(
    conn: sqlite3.Connection, user_id: str, categories: list[str] | None = None
) -> list[tuple[str, date, date, str]]:
    """(memory id, first day, last day, reason) of active exceptions relevant to the categories."""
    rows = conn.execute(
        "SELECT id, statement_json FROM memory_items "
        "WHERE user_id = ? AND kind = 'contextual_exception' AND status = 'active'",
        (user_id,),
    ).fetchall()
    out: list[tuple[str, date, date, str]] = []
    for row in rows:
        try:
            meta = json.loads(row["statement_json"]) if row["statement_json"] else {}
        except json.JSONDecodeError:
            continue
        window = exception_range(meta)
        if window and applies_to(meta, categories):
            out.append((row["id"], window[0], window[1], str(meta.get("reason", "exception"))))
    return out
