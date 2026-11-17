# ruff: noqa: E501  (SQL lines)
"""
Shared expenses (PLAN_AGENTIC_V2, A12): roommates and trips.

Who paid, who owes whom, and the fewest settle-ups. It only *records and shows*: a settlement here
means two people say they settled between themselves. There is no payment, no payment link, no
transfer, anywhere. Every split is exact integer paise (largest remainder) and the balances of a
group always add up to zero.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from pydantic import BaseModel

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import now_utc, to_utc_iso


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def split_exact(total: int, weights: dict[str, int]) -> dict[str, int]:
    """`total` split by integer weights into integers that add up to exactly `total`."""
    s = sum(weights.values())
    if s <= 0:
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Shares need at least one positive weight.")
    base = {k: total * w // s for k, w in weights.items()}
    left = total - sum(base.values())
    for k in sorted(weights, key=lambda k: (-(total * weights[k] % s), k))[:left]:
        base[k] += 1
    return base


def create_group(
    conn: sqlite3.Connection,
    user_id: str,
    name: str,
    others: list[str],
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> str:
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can start a group.")
    names = [n.strip() for n in others if n.strip()]
    if not names or len({n.lower() for n in names}) != len(names):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Give at least one other person, each once.")
    gid = _id("sgr")
    now = to_utc_iso(now_utc(clock))
    conn.execute(
        "INSERT INTO split_groups (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
        (gid, user_id, name.strip()[:60], now),
    )
    conn.execute(
        "INSERT INTO split_members (id, user_id, group_id, name, is_me) VALUES (?, ?, ?, 'Me', 1)",
        (_id("smb"), user_id, gid),
    )
    for n in names:
        conn.execute(
            "INSERT INTO split_members (id, user_id, group_id, name, is_me) VALUES (?, ?, ?, ?, 0)",
            (_id("smb"), user_id, gid, n[:40]),
        )
    record_event(conn, user_id=user_id, actor=actor, event_type="split_group_created", reason="A sharing group was started",
                 entity_type="split_group", entity_id=gid, clock=clock)  # fmt: skip
    return gid


def members(conn: sqlite3.Connection, user_id: str, group_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM split_members WHERE user_id = ? AND group_id = ? ORDER BY is_me DESC, name",
        (user_id, group_id),
    ).fetchall()
    if not rows:
        raise ToolFailure(ErrorCode.NOT_FOUND, "No such group.")
    return rows


def add_expense(
    conn: sqlite3.Connection,
    user_id: str,
    group_id: str,
    paid_by: str,
    amount_paise: int,
    note: str,
    *,
    weights: dict[str, int] | None = None,
    txn_id: str | None = None,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> str:
    """Record that `paid_by` paid; split equally among everyone, or by integer weights per member."""
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can add a shared expense.")
    if amount_paise <= 0:
        raise ToolFailure(ErrorCode.INVALID_INPUT, "An expense must be more than nothing.")
    ids = {m["id"] for m in members(conn, user_id, group_id)}
    if paid_by not in ids:
        raise ToolFailure(ErrorCode.INVALID_INPUT, "The payer is not in this group.")
    w = weights or {m: 1 for m in ids}
    if not set(w) <= ids or any(v < 0 for v in w.values()):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Shares must be for members of this group.")
    shares = split_exact(amount_paise, {k: v for k, v in w.items() if v > 0})
    eid = _id("sex")
    conn.execute(
        "INSERT INTO split_expenses (id, user_id, group_id, paid_by, amount_paise, note, shares_json, txn_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            eid,
            user_id,
            group_id,
            paid_by,
            amount_paise,
            note.strip()[:80],
            json.dumps(shares),
            txn_id,
            to_utc_iso(now_utc(clock)),
        ),
    )
    record_event(conn, user_id=user_id, actor=actor, event_type="split_expense_added", reason="A shared expense was recorded",
                 entity_type="split_expense", entity_id=eid, after_data={"amount_paise": amount_paise, "shares": shares}, clock=clock)  # fmt: skip
    return eid


def record_settlement(
    conn: sqlite3.Connection,
    user_id: str,
    group_id: str,
    from_member: str,
    to_member: str,
    amount_paise: int,
    *,
    txn_id: str | None = None,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> str:
    """Record that two people say they settled up. This records; it never pays."""
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can record a settlement.")
    ids = {m["id"] for m in members(conn, user_id, group_id)}
    if from_member == to_member or not {from_member, to_member} <= ids or amount_paise <= 0:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            "Pick two different members of the group and a positive amount.",
        )
    sid = _id("sst")
    conn.execute(
        "INSERT INTO split_settlements (id, user_id, group_id, from_member, to_member, amount_paise, txn_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid,
            user_id,
            group_id,
            from_member,
            to_member,
            amount_paise,
            txn_id,
            to_utc_iso(now_utc(clock)),
        ),
    )
    record_event(conn, user_id=user_id, actor=actor, event_type="split_settlement_recorded", reason="A settlement was recorded (nothing was paid here)",
                 entity_type="split_settlement", entity_id=sid, after_data={"amount_paise": amount_paise}, clock=clock)  # fmt: skip
    return sid


class Balance(BaseModel):
    member_id: str
    name: str
    is_me: bool
    net_paise: int  # positive: is owed money; negative: owes money


class SettleUp(BaseModel):
    from_member: str
    to_member: str
    amount_paise: int


class GroupView(BaseModel):
    group_id: str
    balances: list[Balance]
    settle_up: list[SettleUp]
    total_paise: int


def balances(conn: sqlite3.Connection, user_id: str, group_id: str) -> GroupView:
    mem = members(conn, user_id, group_id)
    net = {m["id"]: 0 for m in mem}
    total = 0
    for e in conn.execute(
        "SELECT * FROM split_expenses WHERE user_id = ? AND group_id = ?", (user_id, group_id)
    ):
        total += e["amount_paise"]
        net[e["paid_by"]] += e["amount_paise"]
        for m, owed in json.loads(e["shares_json"]).items():
            net[m] -= owed
    for s in conn.execute(
        "SELECT * FROM split_settlements WHERE user_id = ? AND group_id = ?", (user_id, group_id)
    ):
        net[s["from_member"]] += s["amount_paise"]  # the one who paid is owed less
        net[s["to_member"]] -= s["amount_paise"]
    assert sum(net.values()) == 0, "a group's balances must add up to zero"
    debtors = sorted(((v, k) for k, v in net.items() if v < 0))
    creditors = sorted(((v, k) for k, v in net.items() if v > 0), reverse=True)
    plan: list[SettleUp] = []
    d, c = [list(x) for x in debtors], [list(x) for x in creditors]
    i = j = 0
    while i < len(d) and j < len(c):
        pay = min(-d[i][0], c[j][0])
        plan.append(SettleUp(from_member=d[i][1], to_member=c[j][1], amount_paise=pay))
        d[i][0] += pay
        c[j][0] -= pay
        if d[i][0] == 0:
            i += 1
        if c[j][0] == 0:
            j += 1
    return GroupView(
        group_id=group_id,
        balances=[
            Balance(
                member_id=m["id"], name=m["name"], is_me=bool(m["is_me"]), net_paise=net[m["id"]]
            )
            for m in mem
        ],
        settle_up=plan,
        total_paise=total,
    )
