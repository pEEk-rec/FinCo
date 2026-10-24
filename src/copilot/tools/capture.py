"""
Capture tools (PLAN_CAPTURE Stage C1). Every capture action goes through `execute_tool`:
policy, validation, a savepoint and an audit row. Recording a payment may be done by the
system (the webhook or the simulator); labelling is the user's alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field, StrictInt

from copilot.core import capture as core
from copilot.models.capture import (
    CounterpartyPolicy,
    CounterpartyProfile,
    PaymentEvent,
    PromptView,
)
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

_UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


def _clock(ctx: ExecutionContext) -> datetime | None:
    return ctx.clock if isinstance(ctx.clock, datetime) else None


class RecordPaymentEventInput(ToolInput):
    source: Literal["sms", "notification", "manual", "simulator"]
    amount_paise: StrictInt = Field(gt=0)
    direction: Literal["debit", "credit"]
    display_name: str = Field(min_length=1, max_length=120)
    occurred_at: str = Field(pattern=_UTC)
    vpa: str | None = Field(default=None, max_length=80)
    account_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    utr: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{6,24}$")
    bank: str | None = Field(default=None, max_length=24)
    channel: Literal["upi", "card", "atm", "neft", "imps", "autopay", "other"] = "other"
    simulated: bool = False
    #: Set on a reversal alert: the UTR of the payment it undoes.
    reversal_of_utr: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{6,24}$")


class RecordPaymentEventOutput(ToolOutput):
    event: PaymentEvent
    created: bool
    decision: str
    reason: str
    guesses: list[dict]


def record_payment_event_handler(ctx: ExecutionContext, **kwargs) -> RecordPaymentEventOutput:
    p = RecordPaymentEventInput.model_validate(kwargs)
    rec = core.record_payment_event(
        ctx.conn,
        ctx.user_id,
        source=p.source,
        amount_paise=p.amount_paise,
        direction=p.direction,
        display_name=p.display_name,
        occurred_at=p.occurred_at,
        vpa=p.vpa,
        account_last4=p.account_last4,
        utr=p.utr,
        bank=p.bank,
        channel=p.channel,
        simulated=p.simulated or p.source == "simulator",
        actor=ctx.actor,
        run_id=ctx.run_id,
        clock=_clock(ctx),
        llm_client=ctx.llm_client,
        reversal_of_utr=p.reversal_of_utr,
    )
    return RecordPaymentEventOutput(
        event=rec.event,
        created=rec.created,
        decision=rec.decision.action,
        reason=rec.decision.reason,
        guesses=[g.model_dump() for g in rec.guesses],
    )


class LabelPaymentEventInput(ToolInput):
    event_id: str
    category_id: str | None = None
    credit_kind: str | None = None
    note: str | None = Field(default=None, max_length=200)
    rank_picked: int | None = Field(default=None, ge=0, le=5)
    linked_event_id: str | None = None


class LabelPaymentEventOutput(ToolOutput):
    event: PaymentEvent
    audit_event_id: str | None = None


def label_payment_event_handler(ctx: ExecutionContext, **kwargs) -> LabelPaymentEventOutput:
    p = LabelPaymentEventInput.model_validate(kwargs)
    event = core.label_payment_event(
        ctx.conn,
        ctx.user_id,
        p.event_id,
        category_id=p.category_id,
        credit_kind=p.credit_kind,
        note=p.note,
        rank_picked=p.rank_picked,
        linked_event_id=p.linked_event_id,
        actor=ctx.actor,
        run_id=ctx.run_id,
        clock=_clock(ctx),
    )
    row = ctx.conn.execute(
        "SELECT id FROM audit_events WHERE user_id = ? AND event_type = 'payment_labeled'"
        " AND entity_id = ? ORDER BY rowid DESC LIMIT 1",
        (ctx.user_id, p.event_id),
    ).fetchone()
    return LabelPaymentEventOutput(event=event, audit_event_id=row[0] if row else None)


class SimulatePaymentInput(ToolInput):
    bank: Literal["hdfc", "sbi", "icici", "axis", "kotak"]
    kind: Literal["debit", "credit", "card", "atm", "autopay", "reversal"]
    amount_paise: StrictInt = Field(gt=0, le=100_000_000)
    counterparty: str = Field(default="", max_length=80)
    vpa: str | None = Field(default=None, max_length=80)
    utr: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    account_last4: str = Field(default="1234", pattern=r"^\d{4}$")


class SimulatePaymentOutput(RecordPaymentEventOutput):
    #: The synthetic alert that was rendered, so a demo can show what the phone would have sent.
    sample_text: str


def simulate_payment_handler(ctx: ExecutionContext, **kwargs) -> SimulatePaymentOutput:
    from copilot.core.capture_sim import simulate_alert
    from copilot.core.timeutil import now_utc

    p = SimulatePaymentInput.model_validate(kwargs)
    needs_name = p.kind not in ("atm", "reversal")
    if needs_name and not (p.counterparty.strip() or p.vpa):
        raise ValueError("Say who the payment was to.")
    when = now_utc(_clock(ctx))
    parsed, text = simulate_alert(
        p.bank,
        p.kind,
        p.amount_paise,
        p.counterparty.strip() or (p.vpa or "").split("@")[0] or "Payee",
        when,
        vpa=p.vpa,
        utr=p.utr,
        account_last4=p.account_last4,
    )
    rec = core.record_payment_event(
        ctx.conn,
        ctx.user_id,
        **core.record_args_from_parsed(parsed, source="simulator", simulated=True),
        actor=ctx.actor,
        run_id=ctx.run_id,
        clock=_clock(ctx),
        llm_client=ctx.llm_client,
    )
    return SimulatePaymentOutput(
        event=rec.event,
        created=rec.created,
        decision=rec.decision.action,
        reason=rec.decision.reason,
        guesses=[g.model_dump() for g in rec.guesses],
        sample_text=text,
    )


class PendingPromptsInput(ToolInput):
    limit: int = Field(default=50, ge=1, le=200)


class PendingPromptsOutput(ToolOutput):
    prompts: list[PromptView]


def pending_prompts_handler(ctx: ExecutionContext, **kwargs) -> PendingPromptsOutput:
    p = PendingPromptsInput.model_validate(kwargs)
    return PendingPromptsOutput(prompts=core.pending_prompts(ctx.conn, ctx.user_id, p.limit))


class SetCounterpartyPolicyInput(ToolInput):
    counterparty_key: str = Field(min_length=1)
    policy: CounterpartyPolicy
    category_id: str | None = None


class SetCounterpartyPolicyOutput(ToolOutput):
    profile: CounterpartyProfile


def set_counterparty_policy_handler(ctx: ExecutionContext, **kwargs) -> SetCounterpartyPolicyOutput:
    p = SetCounterpartyPolicyInput.model_validate(kwargs)
    profile = core.set_counterparty_policy(
        ctx.conn,
        ctx.user_id,
        p.counterparty_key,
        p.policy,
        p.category_id,
        actor=ctx.actor,
        run_id=ctx.run_id,
        clock=_clock(ctx),
    )
    return SetCounterpartyPolicyOutput(profile=profile)


class ExpirePromptsInput(ToolInput):
    pass


class ExpirePromptsOutput(ToolOutput):
    expired: int


def expire_prompts_handler(ctx: ExecutionContext, **kwargs) -> ExpirePromptsOutput:
    ExpirePromptsInput.model_validate(kwargs)
    n = core.expire_prompts(ctx.conn, ctx.user_id, clock=_clock(ctx), run_id=ctx.run_id)
    return ExpirePromptsOutput(expired=n)


class ReconcileInput(ToolInput):
    pass


class ReconcileOutput(ToolOutput):
    matched: int
    ambiguous: int
    orphaned: int
    unchanged: int
    label_conflicts: int


def reconcile_handler(ctx: ExecutionContext, **kwargs) -> ReconcileOutput:
    from copilot.core.capture_reconcile import reconcile_events

    ReconcileInput.model_validate(kwargs)
    r = reconcile_events(
        ctx.conn, ctx.user_id, actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx)
    )
    return ReconcileOutput(
        matched=r.matched,
        ambiguous=r.ambiguous,
        orphaned=r.orphaned,
        unchanged=r.unchanged,
        label_conflicts=r.label_conflicts,
    )


class CoverageInput(ToolInput):
    include_simulated: bool = False


class CoverageRowOut(ToolOutput):
    account_id: str | None
    ledger_txns: int
    alerts: int
    share_bp: int
    warn: bool
    message: str


class CoverageOutput(ToolOutput):
    rows: list[CoverageRowOut]
    month_ledger_paise: int
    month_provisional_paise: int
    month_total_paise: int
    unverified_events: int


def coverage_handler(ctx: ExecutionContext, **kwargs) -> CoverageOutput:
    from copilot.core.capture_reconcile import combined_spend, coverage_health
    from copilot.core.timeutil import IST, month_bounds, now_utc

    p = CoverageInput.model_validate(kwargs)
    now = now_utc(_clock(ctx))
    local = now.astimezone(IST)
    start, end = month_bounds(local.year, local.month)
    spend = combined_spend(ctx.conn, ctx.user_id, start, end, include_simulated=p.include_simulated)
    return CoverageOutput(
        rows=[CoverageRowOut(**r.__dict__) for r in coverage_health(ctx.conn, ctx.user_id, now)],
        month_ledger_paise=spend.ledger_paise,
        month_provisional_paise=spend.provisional_paise,
        month_total_paise=spend.total_paise,
        unverified_events=spend.unverified_events,
    )


class SetAccountLast4Input(ToolInput):
    account_id: str
    last4: str = Field(pattern=r"^\d{4}$")


class SetAccountLast4Output(ToolOutput):
    account_id: str
    last4: str


def set_account_last4_handler(ctx: ExecutionContext, **kwargs) -> SetAccountLast4Output:
    from copilot.core.capture_reconcile import set_account_last4

    p = SetAccountLast4Input.model_validate(kwargs)
    set_account_last4(
        ctx.conn, ctx.user_id, p.account_id, p.last4, actor=ctx.actor, clock=_clock(ctx)
    )
    return SetAccountLast4Output(account_id=p.account_id, last4=p.last4)


class RegisterPushInput(ToolInput):
    endpoint: str = Field(min_length=12, max_length=600)
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=6, max_length=100)
    label: str = Field(default="This device", min_length=1, max_length=40)


class RegisterPushOutput(ToolOutput):
    subscription_id: str


def register_push_handler(ctx: ExecutionContext, **kwargs) -> RegisterPushOutput:
    from copilot.core import capture_push

    p = RegisterPushInput.model_validate(kwargs)
    sid = capture_push.subscribe(
        ctx.conn,
        ctx.user_id,
        p.endpoint,
        p.p256dh,
        p.auth,
        p.label,
        actor=ctx.actor,
        clock=_clock(ctx),
    )
    return RegisterPushOutput(subscription_id=sid)


class RemovePushInput(ToolInput):
    endpoint: str = Field(min_length=12, max_length=600)


class RemovePushOutput(ToolOutput):
    removed: bool


def remove_push_handler(ctx: ExecutionContext, **kwargs) -> RemovePushOutput:
    from copilot.core import capture_push

    p = RemovePushInput.model_validate(kwargs)
    return RemovePushOutput(
        removed=capture_push.unsubscribe(
            ctx.conn, ctx.user_id, p.endpoint, actor=ctx.actor, clock=_clock(ctx)
        )
    )


CAPTURE_TOOLS = (
    ToolSpec(
        name="register_push_subscription",
        description="Turn notifications on for this device.",
        input_model=RegisterPushInput,
        output_model=RegisterPushOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=register_push_handler,
    ),
    ToolSpec(
        name="remove_push_subscription",
        description="Turn notifications off for this device.",
        input_model=RemovePushInput,
        output_model=RemovePushOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=remove_push_handler,
    ),
    ToolSpec(
        name="reconcile_payment_events",
        description="Match captured payments to ledger transactions (never on ambiguity).",
        input_model=ReconcileInput,
        output_model=ReconcileOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=reconcile_handler,
    ),
    ToolSpec(
        name="capture_coverage",
        description="Did the bank alerts keep up with the ledger, and what is provisional spend.",
        input_model=CoverageInput,
        output_model=CoverageOutput,
        side_effect=SideEffect.READ,
        handler=coverage_handler,
    ),
    ToolSpec(
        name="set_account_last4",
        description="Say which account ends in which four digits, so alerts tie to it.",
        input_model=SetAccountLast4Input,
        output_model=SetAccountLast4Output,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=set_account_last4_handler,
    ),
    ToolSpec(
        name="record_payment_event",
        description="Record a payment captured from a bank alert, the simulator or by hand.",
        input_model=RecordPaymentEventInput,
        output_model=RecordPaymentEventOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=record_payment_event_handler,
    ),
    ToolSpec(
        name="label_payment_event",
        description="Give a captured payment the category the user chose.",
        input_model=LabelPaymentEventInput,
        output_model=LabelPaymentEventOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=label_payment_event_handler,
    ),
    ToolSpec(
        name="simulate_payment_event",
        description="Simulate a bank alert end to end (clearly labelled as simulated).",
        input_model=SimulatePaymentInput,
        output_model=SimulatePaymentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=simulate_payment_handler,
    ),
    ToolSpec(
        name="pending_prompts",
        description="List payments waiting for the user to say what they were.",
        input_model=PendingPromptsInput,
        output_model=PendingPromptsOutput,
        side_effect=SideEffect.READ,
        handler=pending_prompts_handler,
    ),
    ToolSpec(
        name="set_counterparty_policy",
        description="Choose how a payee is handled: learn, always ask, or always one category.",
        input_model=SetCounterpartyPolicyInput,
        output_model=SetCounterpartyPolicyOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=set_counterparty_policy_handler,
    ),
    ToolSpec(
        name="expire_capture_prompts",
        description="Runtime job: unanswered prompts past their time apply their best guess.",
        input_model=ExpirePromptsInput,
        output_model=ExpirePromptsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=expire_prompts_handler,
    ),
)


def register_capture_tools(register_fn=register) -> None:
    for spec in CAPTURE_TOOLS:
        register_fn(spec)
