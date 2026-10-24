"""
Account Aggregator tools (PLAN_CAPTURE Stage C7). Consent changes belong to the user alone; the
daily cycle is a runtime job. Every one goes through `execute_tool`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from copilot.core import aa_consent, aa_fetch
from copilot.core.aa_source import SandboxAASource
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


def _clock(ctx: ExecutionContext) -> datetime | None:
    return ctx.clock if isinstance(ctx.clock, datetime) else None


class NoInput(ToolInput):
    pass


class ConsentOut(ToolOutput):
    consent: aa_consent.BankLinkView | None


def aa_status_handler(ctx: ExecutionContext, **kwargs) -> ConsentOut:
    NoInput.model_validate(kwargs)
    return ConsentOut(consent=aa_consent.current_consent(ctx.conn, ctx.user_id))


def create_consent_handler(ctx: ExecutionContext, **kwargs) -> ConsentOut:
    NoInput.model_validate(kwargs)
    view = aa_consent.create_consent(
        ctx.conn, ctx.user_id, actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx)
    )
    return ConsentOut(consent=view)


class ConsentActionInput(ToolInput):
    consent_id: str
    action: Literal["approve", "pause", "resume", "revoke"]


def consent_action_handler(ctx: ExecutionContext, **kwargs) -> ConsentOut:
    p = ConsentActionInput.model_validate(kwargs)
    if p.action == "approve":
        row = ctx.conn.execute(
            "SELECT connector, external_ref FROM aa_consents WHERE user_id = ? AND id = ?",
            (ctx.user_id, p.consent_id),
        ).fetchone()
        if row and row["connector"] == "sandbox":
            src = aa_fetch.default_source(ctx.conn, ctx.user_id, row, _clock(ctx))
            if not isinstance(src, SandboxAASource) or src.status() != "ACTIVE":
                raise ToolFailure(
                    ErrorCode.DENIED_BY_POLICY,
                    "The aggregator has not reported this consent as approved yet.",
                )
    view = aa_consent.transition(
        ctx.conn, ctx.user_id, p.consent_id, p.action,  # type: ignore[arg-type]
        actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx),
    )  # fmt: skip
    return ConsentOut(consent=view)


class FetchInput(ToolInput):
    consent_id: str | None = None
    force: bool = False


class FetchOut(ToolOutput, aa_fetch.FetchReport):
    pass


class CycleOut(ToolOutput, aa_fetch.CycleReport):
    fetches: list[aa_fetch.FetchReport]


def fetch_handler(ctx: ExecutionContext, **kwargs) -> FetchOut:
    p = FetchInput.model_validate(kwargs)
    cid = p.consent_id
    if cid is None:
        cur = aa_consent.current_consent(ctx.conn, ctx.user_id)
        if cur is None:
            raise ToolFailure(ErrorCode.NOT_FOUND, "No bank link is set up.")
        cid = cur.id
    row = aa_consent.require_active(ctx.conn, ctx.user_id, cid, _clock(ctx))
    source = aa_fetch.default_source(ctx.conn, ctx.user_id, row, _clock(ctx))
    if source is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "This bank link has no data source configured.")
    report = aa_fetch.fetch_now(
        ctx.conn, ctx.user_id, cid, source, actor=ctx.actor, run_id=ctx.run_id,
        clock=_clock(ctx), force=p.force,
    )  # fmt: skip
    return FetchOut(**report.model_dump())


def cycle_handler(ctx: ExecutionContext, **kwargs) -> CycleOut:
    NoInput.model_validate(kwargs)
    report = aa_fetch.run_cycle(
        ctx.conn, ctx.user_id, actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx)
    )
    return CycleOut(**report.model_dump())


AA_TOOLS = (
    ToolSpec(
        name="aa_status",
        description="The bank link: what it covers, why, how often, how long, and its state.",
        input_model=NoInput,
        output_model=ConsentOut,
        side_effect=SideEffect.READ,
        handler=aa_status_handler,
    ),
    ToolSpec(
        name="create_aa_consent",
        description="Ask to link the bank through an Account Aggregator (the user approves it).",
        input_model=NoInput,
        output_model=ConsentOut,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_consent_handler,
    ),
    ToolSpec(
        name="set_aa_consent_state",
        description="Approve, pause, resume or revoke the bank link. Revoking stops fetches.",
        input_model=ConsentActionInput,
        output_model=ConsentOut,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=consent_action_handler,
    ),
    ToolSpec(
        name="fetch_aa_data",
        description="Fetch transactions under an active bank link and reconcile them.",
        input_model=FetchInput,
        output_model=FetchOut,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=fetch_handler,
    ),
    ToolSpec(
        name="run_aa_cycle",
        description="Runtime job: end old links, delete old copies, fetch what is due.",
        input_model=NoInput,
        output_model=CycleOut,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=cycle_handler,
    ),
)


def register_aa_tools(register_fn=register) -> None:
    for spec in AA_TOOLS:
        register_fn(spec)
