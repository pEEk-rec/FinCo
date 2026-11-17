# ruff: noqa: E501  (SQL and prose lines)
"""
The budget co-pilot (PLAN_AGENTIC_V2, A9): the model never does arithmetic here.

`propose_budget` splits a month's income: fixed commitments first, goal funding and savings next,
essentials at what they usually cost, and the rest across the other categories in the order the user
said they matter, each kept within half to one and a half times its usual spend. Every figure is
integer paise and the lines add up exactly: income = category limits + goals + savings + unallocated.
If the profile has no confirmed income the answer is "I need to know your income", not a guess.

`replan_options` looks at the month so far and, for a category heading over its limit, offers
concrete trade-offs with exact numbers. Nothing changes until the user picks one.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import IST, month_bounds, now_utc, to_utc_iso
from copilot.db.repo import insert_budget, list_budgets, list_goals
from copilot.domain.essentials import is_essential
from copilot.domain.goals import required_monthly_paise
from copilot.models.domain import Budget
from copilot.personal import profile as prof

#: how much more or less than usual a category may be given, per hundred
LOW_PCT, HIGH_PCT = 50, 150
#: weight per hundred for the user's 1st, 2nd and 3rd priority, and for everything else
PRIORITY_PCT = (140, 125, 110)
OTHER_PCT = 90
HISTORY_MONTHS = 3


def rupees(paise: int) -> str:
    """Plain rupees for a sentence (the web app formats its own figures)."""
    whole, frac = divmod(paise, 100)
    return f"Rs {whole:,}" + (f".{frac:02d}" if frac else "")


class Line(BaseModel):
    category_id: str
    limit_paise: int
    fixed_paise: int
    usual_paise: int
    reason: str


class Proposal(BaseModel):
    status: Literal["ok", "needs_profile", "shortfall", "essentials_exceed"]
    period: str
    income_paise: int
    fixed_paise: int
    goals_paise: int
    savings_paise: int
    lines: list[Line]
    unallocated_paise: int
    shortfall_paise: int
    note: str


def _history(conn: sqlite3.Connection, user_id: str, today: date) -> dict[str, int]:
    """Average monthly spend per category over the last complete months that have any data."""
    totals: dict[str, int] = {}
    months = 0
    y, m = today.year, today.month
    for _ in range(HISTORY_MONTHS):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        start, end = month_bounds(y, m)
        rows = conn.execute(
            "SELECT category_id, SUM(amount_paise) FROM transactions WHERE user_id = ? AND direction = 'debit'"
            " AND excluded_from_spend = 0 AND is_duplicate_of IS NULL AND category_id IS NOT NULL"
            " AND occurred_at >= ? AND occurred_at < ? GROUP BY category_id",
            (user_id, start, end),
        ).fetchall()
        if rows:
            months += 1
            for cat, total in rows:
                totals[cat] = totals.get(cat, 0) + total
    return {c: t // months for c, t in totals.items()} if months else {}


def _share(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Split `total` by weights into integers that add up to `total` (largest remainder)."""
    s = sum(weights.values())
    if total <= 0 or s <= 0:
        return {k: 0 for k in weights}
    base = {k: total * w // s for k, w in weights.items()}
    left = total - sum(base.values())
    order = sorted(weights, key=lambda k: (-(total * weights[k] % s), k))
    for k in order[:left]:
        base[k] += 1
    return base


def allocate(
    *,
    income: int,
    fixed_by_cat: dict[str, int],
    goals: int,
    savings: int,
    usual: dict[str, int],
    essentials: set[str],
    priorities: list[str],
    period: str,
) -> Proposal:
    fixed_total = sum(fixed_by_cat.values())
    remainder = income - fixed_total - goals - savings
    base = dict(status="ok", period=period, income_paise=income, fixed_paise=fixed_total,
                goals_paise=goals, savings_paise=savings)  # fmt: skip
    if income <= 0:
        return Proposal(**{**base, "status": "needs_profile"}, lines=[], unallocated_paise=0,
                        shortfall_paise=0, note="I need to know how your money arrives before I can plan a month.")  # fmt: skip
    if remainder < 0:
        return Proposal(**{**base, "status": "shortfall"}, lines=[], unallocated_paise=0,
                        shortfall_paise=-remainder,
                        note="Fixed payments, goals and savings already add up to more than your income.")  # fmt: skip
    variable = {
        c: max(0, usual.get(c, 0) - fixed_by_cat.get(c, 0)) for c in set(usual) | set(fixed_by_cat)
    }
    ess = {c: v for c, v in variable.items() if c in essentials and v > 0}
    ess_total = sum(ess.values())
    alloc: dict[str, int] = {}
    status, shortfall, note = (
        "ok",
        0,
        "A plan within your usual range, leaning to what you said matters.",
    )
    if remainder < ess_total:
        alloc = _share(remainder, ess)
        status, shortfall = "essentials_exceed", ess_total - remainder
        note = "Even the essentials, at what they usually cost, need more than what is left."
        disc: dict[str, int] = {}
    else:
        alloc = dict(ess)
        disc = {c: v for c, v in variable.items() if c not in essentials and v > 0}
    pool = remainder - sum(alloc.values())
    if disc and pool > 0:
        rank = {c: i for i, c in enumerate(priorities)}
        weight = {
            c: v
            * (PRIORITY_PCT[rank[c]] if c in rank and rank[c] < len(PRIORITY_PCT) else OTHER_PCT)
            for c, v in disc.items()
        }
        share = _share(pool, weight)
        for c, v in share.items():
            lo, hi = disc[c] * LOW_PCT // 100, disc[c] * HIGH_PCT // 100
            alloc[c] = max(lo, min(hi, v))
        spent = sum(alloc[c] for c in disc)
        while (
            spent > pool
        ):  # the floors can overshoot: take back from the largest, one paisa at a time
            c = max(disc, key=lambda k: (alloc[k] - disc[k] * LOW_PCT // 100, k))
            take = min(spent - pool, max(0, alloc[c] - disc[c] * LOW_PCT // 100))
            if take == 0:
                break
            alloc[c] -= take
            spent -= take
        for c in disc:
            alloc.setdefault(c, 0)
    unallocated = remainder - sum(alloc.values())
    cats = sorted(set(alloc) | set(fixed_by_cat))
    lines = [
        Line(
            category_id=c,
            limit_paise=alloc.get(c, 0) + fixed_by_cat.get(c, 0),
            fixed_paise=fixed_by_cat.get(c, 0),
            usual_paise=usual.get(c, 0),
            reason=(
                "essential, at its usual cost"
                if c in essentials
                else f"priority {priorities.index(c) + 1}"
                if c in priorities
                else "within its usual range"
            ),
        )  # fmt: skip
        for c in cats
    ]
    return Proposal(**{**base, "status": status}, lines=lines, unallocated_paise=unallocated,
                    shortfall_paise=shortfall, note=note)  # fmt: skip


def propose_budget(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> Proposal:
    today = now_utc(clock).astimezone(IST).date()
    values = prof.get_profile(conn, user_id).values
    income = values.get("income") or {"expected_paise": 0}
    fixed: dict[str, int] = {}
    for c in values.get("fixed_commitments", []):
        fixed[c["category_id"]] = fixed.get(c["category_id"], 0) + c["amount_paise"]
    names = {
        r[0]: r[1]
        for r in conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    }
    goals = sum(required_monthly_paise(g, today) or 0 for g in list_goals(conn, user_id, "active"))
    return allocate(
        income=income["expected_paise"],
        fixed_by_cat=fixed,
        goals=goals,
        savings=values.get("savings_intent_paise", 0),
        usual=_history(conn, user_id, today),
        essentials={c for c in names if is_essential(c, names[c])},
        priorities=values.get("priorities", []),
        period=f"{today.year:04d}-{today.month:02d}",
    )


def apply_plan(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> dict:
    """Make the proposal the month's budgets. The plan is recomputed here, never taken on trust."""
    if actor != "user":
        raise ToolFailure(ErrorCode.DENIED_BY_POLICY, "Only you can change your budgets.")
    plan = propose_budget(conn, user_id, clock)
    if plan.status != "ok":
        raise ToolFailure(ErrorCode.INVALID_INPUT, plan.note)
    before = {b.category_id: b.limit_paise for b in list_budgets(conn, user_id)}
    for line in plan.lines:
        if line.category_id in before:
            conn.execute(
                "UPDATE budgets SET limit_paise = ? WHERE user_id = ? AND category_id = ?",
                (line.limit_paise, user_id, line.category_id),
            )
        else:
            insert_budget(conn, Budget(id=f"bud_{uuid.uuid4().hex[:12]}", user_id=user_id,
                                       category_id=line.category_id, limit_paise=line.limit_paise,
                                       warn_threshold_pct=80))  # fmt: skip
    pid = f"bpl_{uuid.uuid4().hex[:12]}"
    now = to_utc_iso(now_utc(clock))
    conn.execute(
        "INSERT INTO budget_plans (id, user_id, period, status, plan_json, before_json, created_at, decided_at)"
        " VALUES (?, ?, ?, 'applied', ?, ?, ?, ?)",
        (pid, user_id, plan.period, plan.model_dump_json(), json.dumps(before), now, now),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="budget_plan_applied",
        reason=f"Budget plan for {plan.period} applied", run_id=run_id, entity_type="budget_plan",
        entity_id=pid, before_data=before,
        after_data={ln.category_id: ln.limit_paise for ln in plan.lines}, clock=clock,
    )  # fmt: skip
    return {"plan_id": pid, "lines": len(plan.lines)}


# ---- replanning ----------------------------------------------------------------------------------------
class Option(BaseModel):
    id: str
    kind: Literal["move", "trim", "goal_delay"]
    category_id: str
    text: str
    amount_paise: int = 0
    from_category: str | None = None
    days: int = 0
    per_day_paise: int = 0
    applies_by_itself: bool = False  # only a move changes budgets, and only when the user picks it


class Replan(BaseModel):
    category_id: str
    overrun_paise: int
    projected_paise: int
    limit_paise: int
    options: list[Option]


def replan_options(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> list[Replan]:
    now = now_utc(clock).astimezone(IST)
    today = now.date()
    dim = calendar.monthrange(today.year, today.month)[1]
    start, end = month_bounds(today.year, today.month)
    elapsed = max(1, today.day)
    left = dim - today.day
    names = {
        r[0]: r[1]
        for r in conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    }
    spent = dict(
        conn.execute(
            "SELECT category_id, SUM(amount_paise) FROM transactions WHERE user_id = ? AND direction = 'debit'"
            " AND excluded_from_spend = 0 AND is_duplicate_of IS NULL AND category_id IS NOT NULL"
            " AND occurred_at >= ? AND occurred_at < ? GROUP BY category_id",
            (user_id, start, end),
        ).fetchall()
    )
    priorities = prof.confirmed(conn, user_id, "priorities", [])
    budgets = {b.category_id: b.limit_paise for b in list_budgets(conn, user_id)}
    proj = {c: spent.get(c, 0) * dim // elapsed for c in budgets}
    over = sorted(
        ((proj[c] - lim, c) for c, lim in budgets.items() if proj[c] > lim), reverse=True
    )[:2]
    slack = {c: budgets[c] - proj[c] for c in budgets if proj[c] < budgets[c]}
    donors = sorted(
        slack, key=lambda c: (-(priorities.index(c) if c in priorities else 99), -slack[c], c)
    )
    goals = [
        g
        for g in list_goals(conn, user_id, "active")
        if (required_monthly_paise(g, today) or 0) > 0
    ]
    out: list[Replan] = []
    for overrun, cat in over:
        opts: list[Option] = []
        for d in donors:
            if d == cat:
                continue
            amount = min(overrun, slack[d])
            if amount > 0:
                opts.append(Option(id=f"{cat}:move:{d}", kind="move", category_id=cat, from_category=d,
                                   amount_paise=amount, applies_by_itself=True,
                                   text=f"Move {rupees(amount)} of limit from {names.get(d, d)} to {names.get(cat, cat)}."))  # fmt: skip
                break
        if left > 0:
            per_day = -(-overrun // left)
            opts.append(Option(id=f"{cat}:trim", kind="trim", category_id=cat, per_day_paise=per_day,
                               text=f"Spend {rupees(per_day)} a day less on {names.get(cat, cat)} for the rest of the month."))  # fmt: skip
        if goals:
            g = goals[0]
            monthly = required_monthly_paise(g, today) or 1
            days = -(-overrun * 30 // monthly)
            opts.append(Option(id=f"{cat}:goal:{g.id}", kind="goal_delay", category_id=cat, days=days,
                               text=f"Keep spending as it is and {g.name} moves about {days} days."))  # fmt: skip
        out.append(Replan(category_id=cat, overrun_paise=overrun, projected_paise=proj[cat],
                          limit_paise=budgets[cat], options=opts))  # fmt: skip
    return out


def apply_move(
    conn: sqlite3.Connection,
    user_id: str,
    from_category: str,
    to_category: str,
    amount_paise: int,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> dict:
    """Move limit from one category to another, if the user picked that trade-off."""
    if actor != "user":
        raise ToolFailure(ErrorCode.DENIED_BY_POLICY, "Only you can change your budgets.")
    if amount_paise <= 0 or from_category == to_category:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, "Pick two different categories and a positive amount."
        )
    limits = {b.category_id: b.limit_paise for b in list_budgets(conn, user_id)}
    if from_category not in limits or to_category not in limits:
        raise ToolFailure(ErrorCode.NOT_FOUND, "Both categories need a budget.")
    if limits[from_category] < amount_paise:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, "That category does not have that much limit to give."
        )
    before = {from_category: limits[from_category], to_category: limits[to_category]}
    after = {
        from_category: before[from_category] - amount_paise,
        to_category: before[to_category] + amount_paise,
    }
    for c, v in after.items():
        conn.execute(
            "UPDATE budgets SET limit_paise = ? WHERE user_id = ? AND category_id = ?",
            (v, user_id, c),
        )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="budget_move_applied",
        reason="Budget limit moved between categories", run_id=run_id, entity_type="budget",
        entity_id=to_category, before_data=before, after_data=after, clock=clock,
    )  # fmt: skip
    return {"before": before, "after": after}


__all__ = ["allocate", "apply_move", "apply_plan", "propose_budget", "replan_options", "rupees"]
