"""
Consent lifecycle tools (approve, revoke) and the monthly-review build tool.

These close a governance gap: consent changes and review generation used to be direct
database writes from the CLI. Through these tools they pass the executor, policy and audit.
"""

import json
from typing import TYPE_CHECKING, Literal

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import get as get_tool
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

ConsentStatus = Literal["pending", "active", "expired", "revoked"]


class ConsentDecisionInput(ToolInput):
    """The consent to change."""

    consent_id: str


class ConsentDecisionOutput(ToolOutput):
    """The consent's status after the change, and the audit event recording it."""

    consent_id: str
    status: ConsentStatus
    audit_event_id: str


def _set_status(
    ctx: "ExecutionContext", consent_id: str, allowed_from: tuple[str, ...], to: ConsentStatus
) -> ConsentDecisionOutput:
    row = ctx.conn.execute(
        "SELECT status, expires_at FROM consents WHERE id = ? AND user_id = ?",
        (consent_id, ctx.user_id),
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Consent '{consent_id}' not found.")
    status, expires_at = row[0], row[1]
    now = to_utc_iso(now_utc(ctx.clock))
    if to == "active" and expires_at and expires_at <= now:
        raise ToolFailure(ErrorCode.STALE_DATA, "This consent has expired. Request a new one.")
    if status not in allowed_from:
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Consent is {status}; cannot become {to}.")
    ctx.conn.execute(
        "UPDATE consents SET status = ? WHERE id = ? AND user_id = ?", (to, consent_id, ctx.user_id)
    )
    event_id = record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type=f"consent_{'approved' if to == 'active' else 'revoked'}",
        reason=f"Consent changed from {status} to {to}.",
        run_id=ctx.run_id,
        entity_type="consent",
        entity_id=consent_id,
        before_data={"status": status},
        after_data={"status": to},
        clock=ctx.clock,
    )
    return ConsentDecisionOutput(consent_id=consent_id, status=to, audit_event_id=event_id)


def approve_consent_handler(ctx: "ExecutionContext", consent_id: str) -> ConsentDecisionOutput:
    """Pending -> active (refused once expired)."""
    return _set_status(ctx, consent_id, ("pending",), "active")


def revoke_consent_handler(ctx: "ExecutionContext", consent_id: str) -> ConsentDecisionOutput:
    """Pending or active -> revoked. Imported data stays; future imports are refused."""
    return _set_status(ctx, consent_id, ("pending", "active"), "revoked")


class BuildReviewInput(ToolInput):
    """The month to review."""

    year: int
    month: int


class BuildReviewOutput(ToolOutput):
    """The new review version."""

    review_id: str
    period: str
    version: int


def build_review_handler(ctx: "ExecutionContext", year: int, month: int) -> BuildReviewOutput:
    """Build and persist the next version of the monthly review (deterministic builder)."""
    from copilot.review.builder import build_monthly_review

    review = build_monthly_review(ctx.conn, ctx.user_id, year, month, ctx.run_id, clock=ctx.clock)
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="monthly_review_built",
        reason=f"Monthly review {review.period} version {review.version} generated.",
        run_id=ctx.run_id,
        entity_type="monthly_review",
        entity_id=review.id,
        after_data={"period": review.period, "version": review.version},
        metadata=json.loads(json.dumps({"year": year, "month": month})),
        clock=ctx.clock,
    )
    return BuildReviewOutput(review_id=review.id, period=review.period, version=review.version)


CONSENT_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="approve_consent",
        description="Activate a pending bank data consent so statements can be imported.",
        input_model=ConsentDecisionInput,
        output_model=ConsentDecisionOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=approve_consent_handler,
    ),
    ToolSpec(
        name="revoke_consent",
        description="Revoke a bank data consent; future imports are refused.",
        input_model=ConsentDecisionInput,
        output_model=ConsentDecisionOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=revoke_consent_handler,
    ),
    ToolSpec(
        name="build_monthly_review",
        description="Generate the next version of the monthly review for a month.",
        input_model=BuildReviewInput,
        output_model=BuildReviewOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=build_review_handler,
    ),
)


def register_consent_tools(register_fn=register) -> None:
    """Register the consent and review tools (skipping any already registered)."""
    for spec in CONSENT_TOOLS:
        if get_tool(spec.name) is None:
            register_fn(spec)
