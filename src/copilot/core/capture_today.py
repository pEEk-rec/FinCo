"""
The Today read model (PLAN_CAPTURE Stage C6c): every payment in and out for one day, in time
order, grouped by what is left for you to do.

  needs_you   asked about and not answered (and ledger rows still waiting for a category)
  auto        tagged without asking, with the reason, each one tap to change
  by_you      tagged by you

A payment is listed once. A captured event that has been matched to a ledger transaction is
shown as the event (it carries the label and the reason) and its ledger row is skipped. Totals
are worked out here, never in the web app, and never count your own transfers or a reversed
payment.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from copilot.core import capture as core
from copilot.core.capture_reconcile import local_day_bounds
from copilot.core.timeutil import IST, now_utc
from copilot.models.capture import GuessView, PaymentEvent

Group = Literal["needs_you", "auto", "by_you"]

#: Plain words for why something was tagged without asking.
REASONS = {
    "known_merchant": "A shop you have tagged before",
    "recurring": "A regular or AutoPay payment",
    "person_k_of_n": "The same as your last few payments to them",
    "person_always_category": "You chose this for them",
    "refund_matched": "A refund of an earlier payment",
    "known_inflow": "Regular income",
    "own_transfer": "Between your own accounts",
    "below_min_amount": "Small, so a guess for now",
    "cash_not_asked": "Cash, guessed for now",
    "rule": "Recognised by a rule",
    "override": "A shop you chose a category for before",
    "cache": "Suggested from similar payments",
    "llm": "Suggested from the shop name",
    "none": "Not tagged yet",
}


class TodayItem(BaseModel):
    id: str
    kind: Literal["event", "ledger"]
    group: Group
    time: str
    direction: Literal["debit", "credit"]
    amount_paise: int
    name: str
    category_name: str | None
    reason: str | None
    reason_code: str | None = None
    simulated: bool
    verified: bool
    reversed: bool = False
    needs_review_link: bool = False
    event: PaymentEvent | None = None
    prompt_id: str | None = None
    prompt_status: str | None = None
    guesses: list[GuessView] = []


class DayTotals(BaseModel):
    in_paise: int
    out_paise: int


class DayCounts(BaseModel):
    needs_you: int
    auto: int
    by_you: int


class TodayView(BaseModel):
    day: str
    is_today: bool
    totals: DayTotals
    counts: DayCounts
    items: list[TodayItem]


def _pretty(label: str, cats: dict[str, str]) -> str:
    return cats.get(label) or label.replace("_", " ").capitalize()


def _time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def build_today(
    conn: sqlite3.Connection, user_id: str, day: str | None, clock: datetime | None = None
) -> TodayView:
    now = now_utc(clock)
    today = now.astimezone(IST).date().isoformat()
    day = day or today
    start, end = local_day_bounds(day)
    cats = {
        r[0]: r[1]
        for r in conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    }

    items: list[TodayItem] = []
    linked_txns: set[str] = set()
    for row in conn.execute(
        "SELECT e.*, p.id AS pid, p.decision AS pdecision, p.reason AS preason,"
        " p.status AS pstatus,"
        " p.guesses_json AS pguesses, l.txn_id AS linked_txn"
        " FROM payment_events e LEFT JOIN prompt_log p ON p.event_id = e.id"
        " LEFT JOIN event_links l ON l.event_id = e.id"
        " WHERE e.user_id = ? AND e.occurred_at >= ? AND e.occurred_at < ?"
        " ORDER BY e.occurred_at, e.id",
        (user_id, start, end),
    ):
        event = core.get_event(conn, user_id, row["id"])
        if event is None:
            continue
        if row["linked_txn"]:
            linked_txns.add(row["linked_txn"])
        label = event.category_id or event.credit_kind
        waiting = row["pstatus"] == "pending"
        if waiting:
            group: Group = "needs_you"
        elif event.category_source == "user":
            group = "by_you"
        else:
            group = "auto"
        reason = None if group == "by_you" else REASONS.get(row["preason"] or "", None)
        if event.counterparty_kind == "self":
            reason = REASONS["own_transfer"]
        guesses = []
        for g in json.loads(row["pguesses"] or "[]"):
            guesses.append(GuessView(**{**g, "name": _pretty(g["label"], cats)}))
        items.append(
            TodayItem(
                id=event.id,
                kind="event",
                group=group,
                time=event.occurred_at,
                direction=event.direction,
                amount_paise=event.amount_paise,
                name=event.display_name,
                category_name=_pretty(label, cats) if label else None,
                reason=reason,
                reason_code=row["preason"],
                simulated=event.simulated,
                verified=event.state == "reconciled",
                reversed=event.state == "reversed" or bool(row["reversed_event_id"]),
                event=event,
                prompt_id=row["pid"],
                prompt_status=row["pstatus"],
                guesses=guesses,
            )
        )

    for t in conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND is_duplicate_of IS NULL"
        " AND occurred_at >= ? AND occurred_at < ? ORDER BY occurred_at, id",
        (user_id, start, end),
    ):
        if t["id"] in linked_txns:
            continue  # shown once, as its captured event
        tagged_by_you = t["category_source"] == "user"
        needs_review = bool(t["needs_review"]) or t["category_id"] is None
        group = "by_you" if tagged_by_you else "needs_you" if needs_review else "auto"
        items.append(
            TodayItem(
                id=t["id"],
                kind="ledger",
                group=group,
                time=t["occurred_at"],
                direction=t["direction"],
                amount_paise=abs(t["amount_paise"]),
                name=(t["merchant_raw"] or "")[:60],
                category_name=cats.get(t["category_id"]),
                reason=None if tagged_by_you else REASONS.get(t["category_source"] or "none"),
                simulated=False,
                verified=True,
                needs_review_link=group == "needs_you",
            )
        )

    items.sort(key=lambda i: (_time(i.time), i.id))
    counted = [
        i for i in items
        if not i.reversed and not (i.event and i.event.counterparty_kind == "self")
    ]  # fmt: skip
    totals = DayTotals(
        in_paise=sum(i.amount_paise for i in counted if i.direction == "credit"),
        out_paise=sum(i.amount_paise for i in counted if i.direction == "debit"),
    )
    counts = DayCounts(
        **{g: sum(1 for i in items if i.group == g) for g in ("needs_you", "auto", "by_you")}
    )
    return TodayView(day=day, is_today=day == today, totals=totals, counts=counts, items=items)


def previous_day(day: str) -> str:
    return (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
