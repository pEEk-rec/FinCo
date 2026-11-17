# ruff: noqa: E501  (long lines)
"""
Personal model tools (PLAN_AGENTIC_V2, A8 to A12). Every one goes through `execute_tool`.

What the agent may do: read the profile, suggest values from the user's money (unconfirmed), propose
a budget and trade-offs, look for something worth saying (the check-in), and show balances. What only
the user may do: state or confirm a profile value, apply a budget plan or a move, answer a check-in,
record a shared expense or a settlement, and say whether a subscription is used.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from copilot.agents import checkin as ck
from copilot.learning import nudges
from copilot.personal import budget as bc
from copilot.personal import profile as prof
from copilot.personal import splits as sp
from copilot.personal import subscriptions as subs
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


def _clock(ctx: ExecutionContext) -> datetime | None:
    return ctx.clock if isinstance(ctx.clock, datetime) else None


class Empty(ToolInput):
    pass


class Data(ToolOutput):
    data: Any = None


# ---- profile ----------------------------------------------------------------------------------------------
class FieldIn(ToolInput):
    field: str


class SetFieldIn(ToolInput):
    field: str
    value: Any


def profile_get(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    view = prof.get_profile(ctx.conn, ctx.user_id)
    return Data(
        data={
            **view.model_dump(),
            "interview": [{"field": f, "question": q} for f, q in prof.INTERVIEW],
        }
    )


def profile_set(ctx: ExecutionContext, **kw) -> Data:
    p = SetFieldIn.model_validate(kw)
    return Data(
        data=prof.set_field(
            ctx.conn,
            ctx.user_id,
            p.field,
            p.value,
            actor=ctx.actor,
            run_id=ctx.run_id,
            clock=_clock(ctx),
        )
    )


def profile_confirm(ctx: ExecutionContext, **kw) -> Data:
    p = FieldIn.model_validate(kw)
    return Data(
        data=prof.confirm_field(ctx.conn, ctx.user_id, p.field, actor=ctx.actor, clock=_clock(ctx))
    )


def profile_delete(ctx: ExecutionContext, **kw) -> Data:
    p = FieldIn.model_validate(kw)
    return Data(
        data={
            "deleted": prof.delete_field(
                ctx.conn, ctx.user_id, p.field, actor=ctx.actor, clock=_clock(ctx)
            )
        }
    )


def profile_infer(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(data={"suggested": prof.store_inferred(ctx.conn, ctx.user_id, _clock(ctx))})


# ---- budget -----------------------------------------------------------------------------------------------
class MoveIn(ToolInput):
    from_category: str
    to_category: str
    amount_paise: int = Field(gt=0)


def budget_propose(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(data=bc.propose_budget(ctx.conn, ctx.user_id, _clock(ctx)).model_dump())


def budget_apply(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(
        data=bc.apply_plan(
            ctx.conn, ctx.user_id, actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx)
        )
    )


def budget_replan(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(
        data=[r.model_dump() for r in bc.replan_options(ctx.conn, ctx.user_id, _clock(ctx))]
    )


def budget_move(ctx: ExecutionContext, **kw) -> Data:
    p = MoveIn.model_validate(kw)
    return Data(
        data=bc.apply_move(
            ctx.conn,
            ctx.user_id,
            p.from_category,
            p.to_category,
            p.amount_paise,
            actor=ctx.actor,
            run_id=ctx.run_id,
            clock=_clock(ctx),
        )
    )


# ---- check-ins and nudges -----------------------------------------------------------------------------------
class RunCheckinIn(ToolInput):
    ignore_timing: bool = False


class RespondIn(ToolInput):
    checkin_id: str
    response: str


class CheckinOut(ToolOutput):
    sent: bool
    reason: str
    checkin: ck.Checkin | None = None
    dropped: list[list[str]] = []


def checkin_run(ctx: ExecutionContext, **kw) -> CheckinOut:
    p = RunCheckinIn.model_validate(kw)
    out = ck.run_checkin(
        ctx.conn,
        ctx.user_id,
        actor=ctx.actor,
        run_id=ctx.run_id,
        clock=_clock(ctx),
        ignore_timing=p.ignore_timing,
    )
    return CheckinOut(
        sent=out.checkin is not None,
        reason=out.reason,
        checkin=out.checkin,
        dropped=[list(d) for d in out.dropped],
    )


def checkin_respond(ctx: ExecutionContext, **kw) -> Data:
    p = RespondIn.model_validate(kw)
    return Data(
        data=ck.respond(
            ctx.conn, ctx.user_id, p.checkin_id, p.response, actor=ctx.actor, clock=_clock(ctx)
        )
    )


def checkin_list(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(data={"checkins": [c.model_dump() for c in ck.list_checkins(ctx.conn, ctx.user_id)],
                      "verification": ck.verification_rate(ctx.conn, ctx.user_id), "arms": nudges.table(ctx.conn, ctx.user_id)})  # fmt: skip


# ---- shared expenses and subscriptions -----------------------------------------------------------------------
class GroupIn(ToolInput):
    name: str = Field(min_length=1, max_length=60)
    others: list[str] = Field(min_length=1, max_length=20)


class ExpenseIn(ToolInput):
    group_id: str
    paid_by: str
    amount_paise: int = Field(gt=0)
    note: str = Field(default="", max_length=80)
    weights: dict[str, int] | None = None
    transaction_id: str | None = None


class SettleIn(ToolInput):
    group_id: str
    from_member: str
    to_member: str
    amount_paise: int = Field(gt=0)
    transaction_id: str | None = None


class GroupViewIn(ToolInput):
    group_id: str


class MarkIn(ToolInput):
    series_id: str
    note: str


def split_create(ctx: ExecutionContext, **kw) -> Data:
    p = GroupIn.model_validate(kw)
    gid = sp.create_group(
        ctx.conn, ctx.user_id, p.name, p.others, actor=ctx.actor, clock=_clock(ctx)
    )
    return Data(
        data={
            "group_id": gid,
            "members": [
                {"id": m["id"], "name": m["name"]} for m in sp.members(ctx.conn, ctx.user_id, gid)
            ],
        }
    )


def split_add(ctx: ExecutionContext, **kw) -> Data:
    p = ExpenseIn.model_validate(kw)
    eid = sp.add_expense(
        ctx.conn,
        ctx.user_id,
        p.group_id,
        p.paid_by,
        p.amount_paise,
        p.note,
        weights=p.weights,
        txn_id=p.transaction_id,
        actor=ctx.actor,
        clock=_clock(ctx),
    )
    return Data(data={"expense_id": eid})


def split_settle(ctx: ExecutionContext, **kw) -> Data:
    p = SettleIn.model_validate(kw)
    sid = sp.record_settlement(
        ctx.conn,
        ctx.user_id,
        p.group_id,
        p.from_member,
        p.to_member,
        p.amount_paise,
        txn_id=p.transaction_id,
        actor=ctx.actor,
        clock=_clock(ctx),
    )
    return Data(data={"settlement_id": sid})


def split_view(ctx: ExecutionContext, **kw) -> Data:
    p = GroupViewIn.model_validate(kw)
    return Data(data=sp.balances(ctx.conn, ctx.user_id, p.group_id).model_dump())


def subs_list(ctx: ExecutionContext, **kw) -> Data:
    Empty.model_validate(kw)
    return Data(
        data=[s.model_dump() for s in subs.list_subscriptions(ctx.conn, ctx.user_id, _clock(ctx))]
    )


def subs_mark(ctx: ExecutionContext, **kw) -> Data:
    p = MarkIn.model_validate(kw)
    return Data(
        data=subs.mark(
            ctx.conn, ctx.user_id, p.series_id, p.note, actor=ctx.actor, clock=_clock(ctx)
        )
    )


def _spec(name, desc, model, handler, effect=SideEffect.WRITE_LOGICAL, out=Data):
    return ToolSpec(
        name=name,
        description=desc,
        input_model=model,
        output_model=out,
        side_effect=effect,
        handler=handler,
    )


R, W = SideEffect.READ, SideEffect.WRITE_LOGICAL
PERSONAL_TOOLS = (
    _spec(
        "profile_get",
        "Your profile: confirmed values, suggestions, and what is missing.",
        Empty,
        profile_get,
        R,
    ),
    _spec("profile_set", "State a value for your profile.", SetFieldIn, profile_set),
    _spec("profile_confirm", "Accept a suggestion for your profile.", FieldIn, profile_confirm),
    _spec("profile_delete", "Remove a part of your profile.", FieldIn, profile_delete),
    _spec(
        "profile_infer",
        "Suggest profile values from your own money (unconfirmed).",
        Empty,
        profile_infer,
    ),
    _spec(
        "budget_propose",
        "A month's budget from your income, commitments, goals and priorities.",
        Empty,
        budget_propose,
        R,
    ),
    _spec("budget_apply", "Make the proposed budget this month's budgets.", Empty, budget_apply),
    _spec(
        "budget_replan",
        "Ways to rebalance categories heading over their limit.",
        Empty,
        budget_replan,
        R,
    ),
    _spec("budget_move", "Move budget limit from one category to another.", MoveIn, budget_move),
    _spec(
        "run_checkin",
        "Look for the one thing worth saying, check it, and say it (or stay quiet).",
        RunCheckinIn,
        checkin_run,
        W,
        CheckinOut,
    ),
    _spec(
        "respond_checkin",
        "Answer a check-in: acted, dismissed or not useful.",
        RespondIn,
        checkin_respond,
    ),
    _spec(
        "list_checkins",
        "Recent check-ins, how many survived their own check, and how you like to be helped.",
        Empty,
        checkin_list,
        R,
    ),
    _spec(
        "create_split_group", "Start a sharing group (roommates, a trip).", GroupIn, split_create
    ),
    _spec("add_split_expense", "Record a shared expense and who owes what.", ExpenseIn, split_add),
    _spec(
        "record_split_settlement",
        "Record that two people settled up (nothing is paid here).",
        SettleIn,
        split_settle,
    ),
    _spec(
        "split_balances",
        "Who owes whom in a group, and the fewest settle-ups.",
        GroupViewIn,
        split_view,
        R,
    ),
    _spec(
        "list_subscriptions",
        "Subscriptions: next renewal, monthly cost, price changes.",
        Empty,
        subs_list,
        R,
    ),
    _spec("mark_subscription", "Say whether you still use a subscription.", MarkIn, subs_mark),
)
_ = BaseModel  # (kept for typing helpers in later stages)


def register_personal_tools(register_fn=register) -> None:
    for spec in PERSONAL_TOOLS:
        register_fn(spec)
