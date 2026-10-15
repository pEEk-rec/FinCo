"""
Advice drafting and lifecycle (PLAN_PHASE1 section 5.6).

The LLM receives findings and drafts advice. The output is deterministically validated and,
if it fails or the model returns invalid JSON, falls back to a template. The result is
saved as a draft, which the user can later approve or reject.
"""

import json
import logging
import uuid
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from copilot.audit.events import record_event
from copilot.core.advice import load_templates, render_template, validate_advice
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import to_utc_iso
from copilot.llm.client import StructuredOutputError, structured_call
from copilot.models.findings import AdviceDraft, AdviceDraftBatch, Finding
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

logger = logging.getLogger(__name__)

_PROMPT = """You are a financial advisor. Write short, clear advice based on these findings.

Findings:
{findings}

Rules:
1. Explain what the finding means for the user.
2. DO NOT use any numbers (amounts, percentages, counts, days) that are not exactly in the finding.
3. DO NOT recommend any specific investment products, stocks, or funds.
4. DO NOT instruct the user to transfer or pay money.
5. DO NOT make any guarantees.
6. DO NOT make predictions beyond the provided forecasts.

For each finding, provide one or more advice items."""

_TEMPLATES_PATH = "config/advice_templates.yaml"


# ---------------------------------------------------------------------------------------------
# draft_advice (WRITE_LOGICAL)
# ---------------------------------------------------------------------------------------------


class DraftAdviceInput(ToolInput):
    """Findings to narrate. Generates one or more draft items per finding."""

    findings: list[Finding]


class DraftAdviceOutput(ToolOutput):
    """The drafted items, ready for review."""

    advice_items: list[dict]  # dicts of the domain.AdviceItem


def draft_advice_handler(ctx: "ExecutionContext", findings: list[Finding]) -> DraftAdviceOutput:
    """Draft advice, validate it, apply template fallbacks, and save as 'draft'."""
    from copilot.llm.client import FakeLLMClient

    if not findings:
        return DraftAdviceOutput(advice_items=[])

    try:
        from copilot.core.config import PROJECT_ROOT

        templates = load_templates(PROJECT_ROOT / _TEMPLATES_PATH)
    except Exception as exc:
        raise ToolFailure(ErrorCode.INTERNAL, f"Failed to load advice templates: {exc}") from exc

    findings_by_id = {f.id: f for f in findings}
    findings_json = json.dumps([f.model_dump(mode="json") for f in findings], indent=2)
    prompt = _PROMPT.format(findings=findings_json)

    try:
        # In a real app we'd inject this. For Phase 1 we use a fake that triggers fallback.
        client = FakeLLMClient(["{not json}"] * 5)
        batch = structured_call(client, prompt, AdviceDraftBatch)
        drafts = batch.items
    except StructuredOutputError:
        drafts = []

    # Map each finding to its drafts
    drafts_by_finding: dict[str, list[AdviceDraft]] = {f.id: [] for f in findings}
    for draft in drafts:
        for fid in draft.finding_ids:
            if fid in drafts_by_finding:
                drafts_by_finding[fid].append(draft)

    # Validate and fallback
    items = []
    run_id = ctx.run_id or "run_0"
    clock_iso = (
        to_utc_iso(ctx.clock) if ctx.clock else "1970-01-01T00:00:00Z"
    )

    for finding in findings:
        finding_drafts = drafts_by_finding[finding.id]
        valid_drafts = []
        for draft in finding_drafts:
            if validate_advice(draft, findings_by_id).ok:
                valid_drafts.append(draft)

        if not valid_drafts:
            try:
                text = render_template(finding, templates)
                valid_drafts.append(AdviceDraft(finding_ids=[finding.id], text=text))
            except Exception as exc:
                raise ToolFailure(ErrorCode.INTERNAL, f"Template fallback failed: {exc}") from exc

        # Save to DB
        for draft in valid_drafts:
            aid = str(uuid.uuid4())
            assumptions = templates.assumptions_for(finding.kind)
            evidence = finding.model_dump(mode="json")

            ctx.conn.execute(
                """
                INSERT INTO advice_items (
                    id, user_id, run_id, finding_ids_json, text,
                    evidence_json, assumptions_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    aid,
                    ctx.user_id,
                    run_id,
                    json.dumps(draft.finding_ids),
                    draft.text,
                    json.dumps(evidence),
                    json.dumps(assumptions),
                    clock_iso,
                ),
            )

            items.append(
                {
                    "id": aid,
                    "user_id": ctx.user_id,
                    "run_id": run_id,
                    "finding_ids_json": json.dumps(draft.finding_ids),
                    "text": draft.text,
                    "evidence_json": json.dumps(evidence),
                    "assumptions_json": json.dumps(assumptions),
                    "status": "draft",
                    "decided_at": None,
                    "decided_by": None,
                    "created_at": clock_iso,
                }
            )

    from copilot.core.learning import order_advice_by_utility

    ordered_items = order_advice_by_utility(ctx.conn, ctx.user_id, items)
    return DraftAdviceOutput(advice_items=ordered_items)


# ---------------------------------------------------------------------------------------------
# decide_advice (WRITE_LOGICAL)
# ---------------------------------------------------------------------------------------------


class DecideAdviceInput(ToolInput):
    """User decision on a draft advice item."""

    advice_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]


class DecideAdviceOutput(ToolOutput):
    """The updated item status."""

    advice_id: str
    status: Literal["approved", "rejected"]


def decide_advice_handler(
    ctx: "ExecutionContext", advice_id: str, decision: Literal["approved", "rejected"]
) -> DecideAdviceOutput:
    """Record a user's decision on a draft and audit it."""
    row = ctx.conn.execute(
        "SELECT status, evidence_json FROM advice_items WHERE id = ? AND user_id = ?",
        (advice_id, ctx.user_id),
    ).fetchone()

    if not row:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Advice '{advice_id}' not found.")

    old_status = row[0]
    if old_status != "draft":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, f"Advice '{advice_id}' is already {old_status}."
        )

    clock_iso = (
        to_utc_iso(ctx.clock) if ctx.clock else "1970-01-01T00:00:00Z"
    )

    ctx.conn.execute(
        """
        UPDATE advice_items 
        SET status = ?, decided_at = ?, decided_by = 'user'
        WHERE id = ?
        """,
        (decision, clock_iso, advice_id),
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="advice_decided",
        reason=f"User {decision} advice {advice_id}.",
        run_id=ctx.run_id,
        entity_type="advice",
        entity_id=advice_id,
        before_data={"status": old_status},
        after_data={"status": decision},
        clock=ctx.clock,
    )

    # Record bounded feedback learning signal (PLAN_PHASE3 Section 5.16)
    try:
        from copilot.core.learning import record_feedback

        evidence = {}
        if row[1]:
            try:
                evidence = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except Exception:
                evidence = {}
        f_kind = str(evidence.get("kind", "recommendation"))
        subject = str(
            evidence.get("category_id")
            or evidence.get("merchant_name")
            or evidence.get("goal_id")
            or "global"
        )
        subject_key = f"{f_kind}:{subject}"
        signal: Literal["useful", "not_useful"] = (
            "useful" if decision == "approved" else "not_useful"
        )
        record_feedback(
            ctx.conn,
            user_id=ctx.user_id,
            subject_kind="advice_kind",
            subject_key=subject_key,
            signal=signal,
            clock=ctx.clock,
            run_id=ctx.run_id,
        )
    except Exception as exc:
        logger.debug("Failed to record learning feedback for advice: %s", exc)

    return DecideAdviceOutput(advice_id=advice_id, status=decision)


# ---------------------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------------------


ADVICE_TOOLS = (
    ToolSpec(
        name="draft_advice",
        description="Draft text explaining findings to the user. Verified by safety validator.",
        input_model=DraftAdviceInput,
        output_model=DraftAdviceOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=draft_advice_handler,
    ),
    ToolSpec(
        name="decide_advice",
        description="Record the user's approve/reject decision on a draft advice item.",
        input_model=DecideAdviceInput,
        output_model=DecideAdviceOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=decide_advice_handler,
    ),
)
