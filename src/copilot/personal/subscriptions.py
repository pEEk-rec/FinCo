# ruff: noqa: E501  (SQL lines)
"""
Subscriptions (PLAN_AGENTIC_V2, A12): what renews, when, for how much, and what changed.

Built on the recurring payments FinCo already detects. For each: the next renewal, the monthly cost,
and whether the last charge was higher than the one before it. Whether you still *use* a
subscription is something only you know, so you can mark it unused; FinCo then keeps reminding you
before it renews. Nothing here cancels anything or contacts anyone.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from pydantic import BaseModel

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import now_utc, to_utc_iso


class Subscription(BaseModel):
    series_id: str
    name: str
    amount_paise: int
    cadence_days: int
    monthly_paise: int
    days_until_renewal: int
    price_change_bp: int  # last charge against the one before, in basis points (0 if unchanged)
    note: str | None  # unused | keep | None


def list_subscriptions(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> list[Subscription]:
    now = now_utc(clock)
    notes = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT series_id, note FROM subscription_notes WHERE user_id = ?", (user_id,)
        )
    }
    out = []
    for r in conn.execute(
        "SELECT * FROM recurring_series WHERE user_id = ? AND kind = 'subscription' ORDER BY typical_amount_paise DESC, id",
        (user_id,),
    ):
        last_two = [
            abs(x[0]) for x in conn.execute(
                "SELECT amount_paise FROM transactions WHERE user_id = ? AND merchant_normalized = ? AND direction = 'debit'"
                " ORDER BY occurred_at DESC LIMIT 2", (user_id, r["merchant_normalized"]),
            )
        ]  # fmt: skip
        change = 0
        if len(last_two) == 2 and last_two[1] > 0 and last_two[0] != last_two[1]:
            change = (last_two[0] - last_two[1]) * 10000 // last_two[1]
        due = datetime.fromisoformat(r["next_expected"].replace("Z", "+00:00"))
        out.append(
            Subscription(
                series_id=r["id"],
                name=r["merchant_normalized"].title(),
                amount_paise=r["typical_amount_paise"],
                cadence_days=r["cadence_days"],
                monthly_paise=r["typical_amount_paise"] * 30 // r["cadence_days"],
                days_until_renewal=(due - now).days,
                price_change_bp=change,
                note=notes.get(r["id"]),
            )  # fmt: skip
        )
    return out


def mark(
    conn: sqlite3.Connection,
    user_id: str,
    series_id: str,
    note: str,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> dict:
    if actor != "user":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, "Only you can say whether you use a subscription."
        )
    if note not in ("unused", "keep"):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Say unused or keep.")
    if (
        conn.execute(
            "SELECT 1 FROM recurring_series WHERE user_id = ? AND id = ?", (user_id, series_id)
        ).fetchone()
        is None
    ):
        raise ToolFailure(ErrorCode.NOT_FOUND, "No such subscription.")
    conn.execute(
        "INSERT INTO subscription_notes (id, user_id, series_id, note, created_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, series_id) DO UPDATE SET note = excluded.note, created_at = excluded.created_at",
        (f"sbn_{uuid.uuid4().hex[:12]}", user_id, series_id, note, to_utc_iso(now_utc(clock))),
    )
    record_event(conn, user_id=user_id, actor=actor, event_type="subscription_marked", reason=f"Subscription marked {note}",
                 entity_type="recurring_series", entity_id=series_id, clock=clock)  # fmt: skip
    return {"series_id": series_id, "note": note}
