"""
Behavioural Memory Tools and Registry (PLAN_PHASE3 Section 5.8, 5.9, Stage 3.8).

Provides:
- list_memories: read memories and patterns (planner-selectable)
- explain_memory: read structured statement and evidence (planner-selectable)
- confirm_memory: user tool to confirm memory (user actor only)
- reject_memory: user tool to reject memory (user actor only)
- edit_memory_statement: user tool to edit bounded statement fields (user actor only)
- forget_memory: user tool to clear content and forget (user actor only)
- refresh_memories: agent/user tool to run observers and recompute confidence/status
- record_contextual_exception: user/agent tool to record an exception reason
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ConfigDict, Field

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.memory import (
    compute_memory_confidence,
    edit_memory_statement_bounded,
    forget_memory,
    load_memory_config,
    record_contextual_exception,
    refresh_memories,
)
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import (
    get_memory_item,
    list_memory_evidence,
    list_memory_items,
    update_memory_status,
)
from copilot.models.phase3 import MemoryItem
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. Models
# -------------------------------------------------------------------------------------------------

class MemorySummary(ToolOutput):
    """Summary representation of a behavioural memory item."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    subject_key: str
    statement_json: dict[str, Any]
    source: str
    status: str
    confidence_bp: int
    user_confirmed: bool
    created_at: str
    last_evidence_at: str | None = None
    last_confirmed_at: str | None = None
    evidence_count: int = 0
    is_conflicted: bool = False
    still_true_check: bool = False


class EvidenceItemView(ToolOutput):
    """View model for a single piece of memory evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str
    polarity: str
    ref_kind: str
    ref_id: str
    observed_at: str
    weight_bp: int


class ListMemoriesInput(ToolInput):
    """Input parameters for listing behavioural memories."""

    status: (
        Literal["candidate", "active", "stale", "retired", "rejected", "forgotten"]
        | None
    ) = Field(
        default=None,
        description="Filter by memory status.",
    )

    kind: Literal[
        "recurring_pattern",
        "contextual_exception",
        "advice_feedback",
        "preference",
        "merchant_habit",
    ] | None = Field(
        default=None,
        description="Filter by memory kind.",
    )
    subject_key: str | None = Field(
        default=None,
        description="Filter by subject key.",
    )
    include_forgotten: bool = Field(
        default=False,
        description="Whether to include forgotten items (content-free).",
    )


class ListMemoriesOutput(ToolOutput):
    """Output containing matched behavioural memories."""

    memories: list[MemorySummary]


class ExplainMemoryInput(ToolInput):
    """Input parameters for explaining a memory item."""

    memory_id: str = Field(..., description="ID of the memory item to explain.")


class ExplainMemoryOutput(ToolOutput):
    """Output containing detailed memory statement and supporting/contradicting evidence."""

    memory: MemorySummary
    evidence: list[EvidenceItemView]


class ConfirmMemoryInput(ToolInput):
    """Input parameters for confirming a memory item."""

    memory_id: str = Field(..., description="ID of the memory item to confirm.")


class ConfirmMemoryOutput(ToolOutput):
    """Output confirmation result."""

    memory_id: str
    status: str
    user_confirmed: bool


class RejectMemoryInput(ToolInput):
    """Input parameters for rejecting a memory item."""

    memory_id: str = Field(..., description="ID of the memory item to reject.")


class RejectMemoryOutput(ToolOutput):
    """Output rejection result."""

    memory_id: str
    status: str


class EditMemoryStatementInput(ToolInput):
    """Input parameters for editing bounded statement fields."""

    memory_id: str = Field(..., description="ID of the memory item to edit.")
    updates: dict[str, Any] = Field(..., description="Dictionary of bounded fields to update.")


class EditMemoryStatementOutput(ToolOutput):
    """Output containing updated statement."""

    memory_id: str
    statement_json: dict[str, Any]


class ForgetMemoryInput(ToolInput):
    """Input parameters for forgetting a memory item."""

    memory_id: str = Field(..., description="ID of the memory item to forget.")


class ForgetMemoryOutput(ToolOutput):
    """Output confirming memory was forgotten."""

    memory_id: str
    forgotten: bool


class RefreshMemoriesInput(ToolInput):
    """Input parameters for running observers and recomputing memory status."""


class RefreshMemoriesOutput(ToolOutput):
    """Summary of memories refreshed."""

    user_id: str
    refreshed_at: str
    new_candidates: int
    counts: dict[str, int]


class RecordContextualExceptionInput(ToolInput):
    """Input for recording a contextual exception reason."""

    category: str = Field(..., description="Category for the exception.")
    period: str = Field(..., description="Period in YYYY-MM format.")
    reason: str = Field(..., description="Reason from allowed list (e.g. festival, travel).")
    txn_id: str | None = Field(default=None, description="Optional associated transaction ID.")


class RecordContextualExceptionOutput(ToolOutput):
    """Output containing the recorded exception memory item."""

    memory_id: str
    statement_json: dict[str, Any]
    status: str


# -------------------------------------------------------------------------------------------------
# 2. Handlers
# -------------------------------------------------------------------------------------------------

def _resolve_clock(ctx: ExecutionContext) -> datetime:
    if isinstance(ctx.clock, datetime):
        return now_utc(ctx.clock)
    if hasattr(ctx.clock, "now"):
        return now_utc(ctx.clock.now())
    return datetime.now(UTC)


def list_memories_handler(ctx: ExecutionContext, **kwargs) -> ListMemoriesOutput:
    params = ListMemoriesInput.model_validate(kwargs)
    now_dt = _resolve_clock(ctx)
    cfg = load_memory_config()

    items = list_memory_items(
        ctx.conn,
        user_id=ctx.user_id,
        status=params.status,
        kind=params.kind,
        subject_key=params.subject_key,
    )

    if not params.include_forgotten and params.status != "forgotten":
        items = [i for i in items if i.status != "forgotten"]

    # Detect conflicts among active memories with same (kind, subject_key)
    active_keys: dict[tuple[str, str], list[MemoryItem]] = {}
    for i in items:
        if i.status == "active":
            active_keys.setdefault((i.kind, i.subject_key), []).append(i)

    summaries: list[MemorySummary] = []
    for item in items:
        ev_list = list_memory_evidence(ctx.conn, ctx.user_id, item.id)
        if item.status == "forgotten":
            conf_bp = 0
            supp_bp = 0
            cont_bp = 0
            still_true = False
        else:
            conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, cfg)
            min_contras = cfg.get("min_contradictions_to_retire", 2)
            contras = sum(1 for e in ev_list if e.polarity == "contradicts")
            is_contradicted = (cont_bp >= supp_bp) and (contras >= min_contras)
            still_true = bool(item.user_confirmed and is_contradicted)

        is_conflicted = len(active_keys.get((item.kind, item.subject_key), [])) > 1

        summaries.append(
            MemorySummary(
                id=item.id,
                kind=item.kind,
                subject_key=item.subject_key,
                statement_json=item.statement_json,
                source=item.source,
                status=item.status,
                confidence_bp=conf_bp,
                user_confirmed=item.user_confirmed,
                created_at=item.created_at,
                last_evidence_at=item.last_evidence_at,
                last_confirmed_at=item.last_confirmed_at,
                evidence_count=len(ev_list),
                is_conflicted=is_conflicted,
                still_true_check=still_true,
            )
        )

    return ListMemoriesOutput(memories=summaries)


def explain_memory_handler(ctx: ExecutionContext, **kwargs) -> ExplainMemoryOutput:
    params = ExplainMemoryInput.model_validate(kwargs)
    now_dt = _resolve_clock(ctx)
    cfg = load_memory_config()

    item = get_memory_item(ctx.conn, ctx.user_id, params.memory_id)
    if not item:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Memory '{params.memory_id}' not found.")

    ev_list = list_memory_evidence(ctx.conn, ctx.user_id, item.id)
    conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, cfg)
    min_contras = cfg.get("min_contradictions_to_retire", 2)
    contras = sum(1 for e in ev_list if e.polarity == "contradicts")
    is_contradicted = (cont_bp >= supp_bp) and (contras >= min_contras)
    still_true = bool(item.user_confirmed and is_contradicted)

    summary = MemorySummary(
        id=item.id,
        kind=item.kind,
        subject_key=item.subject_key,
        statement_json=item.statement_json,
        source=item.source,
        status=item.status,
        confidence_bp=conf_bp,
        user_confirmed=item.user_confirmed,
        created_at=item.created_at,
        last_evidence_at=item.last_evidence_at,
        last_confirmed_at=item.last_confirmed_at,
        evidence_count=len(ev_list),
        is_conflicted=False,
        still_true_check=still_true,
    )

    evidence_views = [
        EvidenceItemView(
            id=e.id,
            polarity=e.polarity,
            ref_kind=e.ref_kind,
            ref_id=e.ref_id,
            observed_at=e.observed_at,
            weight_bp=e.weight_bp,
        )
        for e in ev_list
    ]

    return ExplainMemoryOutput(memory=summary, evidence=evidence_views)


def confirm_memory_handler(ctx: ExecutionContext, **kwargs) -> ConfirmMemoryOutput:
    params = ConfirmMemoryInput.model_validate(kwargs)
    now_dt = _resolve_clock(ctx)
    clock_iso = to_utc_iso(now_dt)

    item = get_memory_item(ctx.conn, ctx.user_id, params.memory_id)
    if not item:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Memory '{params.memory_id}' not found.")

    if item.status == "forgotten":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Cannot confirm forgotten memory '{params.memory_id}'.",
        )

    update_memory_status(
        ctx.conn,
        user_id=ctx.user_id,
        memory_id=params.memory_id,
        status="active",
        last_confirmed_at=clock_iso,
        user_confirmed=True,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="memory_confirmed",
        reason=f"User confirmed memory {params.memory_id}.",
        run_id=ctx.run_id,
        entity_type="memory",
        entity_id=params.memory_id,
        before_data={"status": item.status, "user_confirmed": item.user_confirmed},
        after_data={"status": "active", "user_confirmed": True},
        clock=ctx.clock,
    )

    return ConfirmMemoryOutput(
        memory_id=params.memory_id,
        status="active",
        user_confirmed=True,
    )


def reject_memory_handler(ctx: ExecutionContext, **kwargs) -> RejectMemoryOutput:
    params = RejectMemoryInput.model_validate(kwargs)

    item = get_memory_item(ctx.conn, ctx.user_id, params.memory_id)
    if not item:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Memory '{params.memory_id}' not found.")

    if item.status == "forgotten":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Cannot reject forgotten memory '{params.memory_id}'.",
        )


    update_memory_status(
        ctx.conn,
        user_id=ctx.user_id,
        memory_id=params.memory_id,
        status="rejected",
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="memory_rejected",
        reason=f"User rejected memory {params.memory_id}.",
        run_id=ctx.run_id,
        entity_type="memory",
        entity_id=params.memory_id,
        before_data={"status": item.status},
        after_data={"status": "rejected"},
        clock=ctx.clock,
    )

    return RejectMemoryOutput(
        memory_id=params.memory_id,
        status="rejected",
    )


def edit_memory_statement_handler(ctx: ExecutionContext, **kwargs) -> EditMemoryStatementOutput:
    params = EditMemoryStatementInput.model_validate(kwargs)

    new_stmt = edit_memory_statement_bounded(
        ctx.conn,
        user_id=ctx.user_id,
        memory_id=params.memory_id,
        updates=params.updates,
        clock=ctx.clock,
        actor=ctx.actor,
        run_id=ctx.run_id,
    )

    return EditMemoryStatementOutput(
        memory_id=params.memory_id,
        statement_json=new_stmt,
    )


def forget_memory_handler(ctx: ExecutionContext, **kwargs) -> ForgetMemoryOutput:
    params = ForgetMemoryInput.model_validate(kwargs)

    success = forget_memory(
        ctx.conn,
        user_id=ctx.user_id,
        memory_id=params.memory_id,
        clock=ctx.clock,
        actor=ctx.actor,
        run_id=ctx.run_id,
    )

    if not success:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Memory '{params.memory_id}' not found.")

    return ForgetMemoryOutput(
        memory_id=params.memory_id,
        forgotten=True,
    )


def refresh_memories_handler(ctx: ExecutionContext, **kwargs) -> RefreshMemoriesOutput:
    _ = RefreshMemoriesInput.model_validate(kwargs)
    now_dt = _resolve_clock(ctx)

    res = refresh_memories(
        ctx.conn,
        user_id=ctx.user_id,
        clock=now_dt,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="memories_refreshed",
        reason="Refreshed memory observers and recomputed confidence/statuses.",
        run_id=ctx.run_id,
        entity_type="memory_collection",
        entity_id=ctx.user_id,
        before_data={},
        after_data=res["counts"],
        clock=ctx.clock,
    )

    return RefreshMemoriesOutput(
        user_id=res["user_id"],
        refreshed_at=res["refreshed_at"],
        new_candidates=res["new_candidates"],
        counts=res["counts"],
    )


def record_contextual_exception_handler(
    ctx: ExecutionContext, **kwargs
) -> RecordContextualExceptionOutput:
    params = RecordContextualExceptionInput.model_validate(kwargs)

    item = record_contextual_exception(
        ctx.conn,
        user_id=ctx.user_id,
        category=params.category,
        period=params.period,
        reason=params.reason,
        txn_id=params.txn_id,
        clock=ctx.clock,
        actor=ctx.actor,
        run_id=ctx.run_id,
    )

    return RecordContextualExceptionOutput(
        memory_id=item.id,
        statement_json=item.statement_json,
        status=item.status,
    )


# -------------------------------------------------------------------------------------------------
# 3. Tool Specs & Registration
# -------------------------------------------------------------------------------------------------

MEMORY_SPECS = [
    ToolSpec(
        name="list_memories",
        description="List observed and user-confirmed behavioural memories with confidence levels.",
        input_model=ListMemoriesInput,
        output_model=ListMemoriesOutput,
        side_effect=SideEffect.READ,
        handler=list_memories_handler,
    ),
    ToolSpec(
        name="explain_memory",
        description="Explain evidence and confidence calculations for a behavioural memory item.",
        input_model=ExplainMemoryInput,
        output_model=ExplainMemoryOutput,
        side_effect=SideEffect.READ,
        handler=explain_memory_handler,
    ),
    ToolSpec(
        name="confirm_memory",
        description="Confirm a candidate memory item to immediately promote it to active status.",
        input_model=ConfirmMemoryInput,
        output_model=ConfirmMemoryOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=confirm_memory_handler,
    ),
    ToolSpec(
        name="reject_memory",
        description="Reject a behavioural memory candidate or active item.",
        input_model=RejectMemoryInput,
        output_model=RejectMemoryOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=reject_memory_handler,
    ),
    ToolSpec(
        name="edit_memory_statement",
        description="Edit bounded statement fields for a behavioural memory item.",
        input_model=EditMemoryStatementInput,
        output_model=EditMemoryStatementOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=edit_memory_statement_handler,
    ),
    ToolSpec(
        name="forget_memory",
        description="Forget a memory item, clearing content while preserving a clean audit trail.",
        input_model=ForgetMemoryInput,
        output_model=ForgetMemoryOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=forget_memory_handler,
    ),

    ToolSpec(
        name="refresh_memories",
        description="Run observers across transactions and preferences to refresh memory store.",
        input_model=RefreshMemoriesInput,
        output_model=RefreshMemoriesOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=refresh_memories_handler,
    ),
    ToolSpec(
        name="record_contextual_exception",
        description="Record a contextual exception reason for a category and period.",
        input_model=RecordContextualExceptionInput,
        output_model=RecordContextualExceptionOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=record_contextual_exception_handler,
    ),
]



def register_memory_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register all behavioural memory tools."""
    for spec in MEMORY_SPECS:
        register_fn(spec)
