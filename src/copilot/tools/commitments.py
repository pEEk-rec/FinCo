"""
Tool specifications and handlers for financial commitments (PLAN_PHASE3 Section 5.1).

Governance rules:
- create_commitment, update_commitment, pause_commitment,
  end_commitment, accept_commitment, reject_commitment:
    SideEffect.WRITE_LOGICAL. Allowed for user, requires approval for agent.
    Never planner-selectable.
- list_commitments, get_commitment_status:
    SideEffect.READ. Allowed for all actors, planner-selectable.
- suggest_commitments:
    SideEffect.WRITE_LOGICAL. Allowed for agent and user (writes drafts only).
    Never planner-selectable.
"""

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import Field, StrictInt

from copilot.audit.events import record_event
from copilot.core.commitments import expand_occurrences, match_occurrences
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import (
    get_commitment,
    insert_commitment,
    list_recurring_series,
    update_commitment,
    update_commitment_status,
)
from copilot.db.repo_phase3 import (
    list_commitments as repo_list_commitments,
)
from copilot.models.phase3 import (
    Commitment,
    CommitmentCertainty,
    CommitmentDirection,
    CommitmentKind,
    CommitmentSource,
    CommitmentStatus,
    Occurrence,
    ScheduleKind,
)
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# ---------------------------------------------------------------------------------------------
# 1. create_commitment
# ---------------------------------------------------------------------------------------------
class CreateCommitmentInput(ToolInput):
    """Input parameters for creating a commitment."""

    name: str = Field(min_length=1)
    direction: CommitmentDirection = "outflow"
    kind: CommitmentKind = "bill"
    schedule_kind: ScheduleKind = "monthly"
    schedule_json: dict[str, Any]
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount_paise: StrictInt | None = Field(default=None, ge=0)
    amount_min_paise: StrictInt | None = Field(default=None, ge=0)
    amount_max_paise: StrictInt | None = Field(default=None, ge=0)
    certainty: CommitmentCertainty = "firm"
    category_id: str | None = None
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    recurring_series_id: str | None = None
    goal_id: str | None = None
    bucket_id: str | None = None
    source: CommitmentSource = "user"
    status: CommitmentStatus = "active"


class CreateCommitmentOutput(ToolOutput):
    """Result of creating a commitment."""

    commitment: Commitment


def create_commitment_handler(ctx: "ExecutionContext", **kwargs) -> CreateCommitmentOutput:
    params = CreateCommitmentInput.model_validate(kwargs)
    ts = to_utc_iso(now_utc(ctx.clock))
    comm_id = f"comm_{uuid.uuid4().hex[:8]}"

    comm = Commitment(
        id=comm_id,
        user_id=ctx.user_id,
        name=params.name,
        direction=params.direction,
        kind=params.kind,
        category_id=params.category_id,
        amount_paise=params.amount_paise,
        amount_min_paise=params.amount_min_paise,
        amount_max_paise=params.amount_max_paise,
        certainty=params.certainty,
        schedule_kind=params.schedule_kind,
        schedule_json=params.schedule_json,
        start_date=params.start_date,
        end_date=params.end_date,
        recurring_series_id=params.recurring_series_id,
        goal_id=params.goal_id,
        bucket_id=params.bucket_id,
        source=params.source,
        status=params.status,
        created_at=ts,
        updated_at=ts,
    )

    insert_commitment(ctx.conn, comm)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_created",
        reason=f"Commitment '{comm.name}' created by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=comm.id,
        after_data=comm.model_dump(mode="json"),
        metadata={
            "commitment_id": comm.id,
            "name": comm.name,
            "direction": comm.direction,
            "kind": comm.kind,
        },
        clock=ctx.clock,
    )

    return CreateCommitmentOutput(commitment=comm)


# ---------------------------------------------------------------------------------------------
# 2. update_commitment
# ---------------------------------------------------------------------------------------------
class UpdateCommitmentInput(ToolInput):
    """Input parameters for updating a commitment."""

    commitment_id: str
    name: str | None = None
    direction: CommitmentDirection | None = None
    kind: CommitmentKind | None = None
    category_id: str | None = None
    amount_paise: StrictInt | None = Field(default=None, ge=0)
    amount_min_paise: StrictInt | None = Field(default=None, ge=0)
    amount_max_paise: StrictInt | None = Field(default=None, ge=0)
    certainty: CommitmentCertainty | None = None
    schedule_kind: ScheduleKind | None = None
    schedule_json: dict[str, Any] | None = None
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    goal_id: str | None = None
    bucket_id: str | None = None
    status: CommitmentStatus | None = None


class UpdateCommitmentOutput(ToolOutput):
    """Result of updating a commitment."""

    commitment: Commitment


def update_commitment_handler(ctx: "ExecutionContext", **kwargs) -> UpdateCommitmentOutput:
    params = UpdateCommitmentInput.model_validate(kwargs)
    existing = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    upd_kwargs: dict[str, Any] = {"updated_at": ts}
    if params.name is not None:
        upd_kwargs["name"] = params.name
    if params.direction is not None:
        upd_kwargs["direction"] = params.direction
    if params.kind is not None:
        upd_kwargs["kind"] = params.kind
    if params.category_id is not None:
        upd_kwargs["category_id"] = params.category_id
    if params.amount_paise is not None:
        upd_kwargs["amount_paise"] = params.amount_paise
    if params.amount_min_paise is not None:
        upd_kwargs["amount_min_paise"] = params.amount_min_paise
    if params.amount_max_paise is not None:
        upd_kwargs["amount_max_paise"] = params.amount_max_paise
    if params.certainty is not None:
        upd_kwargs["certainty"] = params.certainty
    if params.schedule_kind is not None:
        upd_kwargs["schedule_kind"] = params.schedule_kind
    if params.schedule_json is not None:
        upd_kwargs["schedule_json"] = params.schedule_json
    if params.start_date is not None:
        upd_kwargs["start_date"] = params.start_date
    if params.end_date is not None:
        upd_kwargs["end_date"] = params.end_date
    if params.goal_id is not None:
        upd_kwargs["goal_id"] = params.goal_id
    if params.bucket_id is not None:
        upd_kwargs["bucket_id"] = params.bucket_id
    if params.status is not None:
        upd_kwargs["status"] = params.status

    update_commitment(ctx.conn, ctx.user_id, params.commitment_id, **upd_kwargs)
    updated = existing.model_copy(update=upd_kwargs)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_updated",
        reason=f"Commitment '{updated.name}' updated by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=updated.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    return UpdateCommitmentOutput(commitment=updated)


# ---------------------------------------------------------------------------------------------
# 3. pause_commitment
# ---------------------------------------------------------------------------------------------
class PauseCommitmentInput(ToolInput):
    """Input parameters for pausing a commitment."""

    commitment_id: str


class PauseCommitmentOutput(ToolOutput):
    """Result of pausing a commitment."""

    commitment: Commitment


def pause_commitment_handler(ctx: "ExecutionContext", **kwargs) -> PauseCommitmentOutput:
    params = PauseCommitmentInput.model_validate(kwargs)
    existing = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    update_commitment_status(ctx.conn, ctx.user_id, existing.id, "paused", ts)
    updated = existing.model_copy(update={"status": "paused", "updated_at": ts})

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_paused",
        reason=f"Commitment '{existing.name}' paused by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=existing.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    return PauseCommitmentOutput(commitment=updated)


# ---------------------------------------------------------------------------------------------
# 4. end_commitment
# ---------------------------------------------------------------------------------------------
class EndCommitmentInput(ToolInput):
    """Input parameters for ending a commitment."""

    commitment_id: str
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class EndCommitmentOutput(ToolOutput):
    """Result of ending a commitment."""

    commitment: Commitment


def end_commitment_handler(ctx: "ExecutionContext", **kwargs) -> EndCommitmentOutput:
    params = EndCommitmentInput.model_validate(kwargs)
    existing = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    end_date = params.end_date or ts[:10]
    update_commitment(
        ctx.conn, ctx.user_id, existing.id, status="ended", end_date=end_date, updated_at=ts
    )
    updated = existing.model_copy(
        update={"status": "ended", "end_date": end_date, "updated_at": ts}
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_ended",
        reason=f"Commitment '{existing.name}' ended by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=existing.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    return EndCommitmentOutput(commitment=updated)


# ---------------------------------------------------------------------------------------------
# 5. accept_commitment
# ---------------------------------------------------------------------------------------------
class AcceptCommitmentInput(ToolInput):
    """Input parameters for accepting a draft commitment."""

    commitment_id: str


class AcceptCommitmentOutput(ToolOutput):
    """Result of accepting a draft commitment."""

    commitment: Commitment


def accept_commitment_handler(ctx: "ExecutionContext", **kwargs) -> AcceptCommitmentOutput:
    params = AcceptCommitmentInput.model_validate(kwargs)
    existing = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )
    if existing.status != "draft":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Only draft commitments can be accepted. '{existing.id}' is '{existing.status}'.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    update_commitment_status(ctx.conn, ctx.user_id, existing.id, "active", ts)
    updated = existing.model_copy(update={"status": "active", "updated_at": ts})

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_accepted",
        reason=f"Draft commitment '{existing.name}' accepted by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=existing.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    return AcceptCommitmentOutput(commitment=updated)


# ---------------------------------------------------------------------------------------------
# 6. reject_commitment
# ---------------------------------------------------------------------------------------------
class RejectCommitmentInput(ToolInput):
    """Input parameters for rejecting a commitment."""

    commitment_id: str


class RejectCommitmentOutput(ToolOutput):
    """Result of rejecting a commitment."""

    commitment: Commitment


def reject_commitment_handler(ctx: "ExecutionContext", **kwargs) -> RejectCommitmentOutput:
    params = RejectCommitmentInput.model_validate(kwargs)
    existing = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    update_commitment_status(ctx.conn, ctx.user_id, existing.id, "rejected", ts)
    updated = existing.model_copy(update={"status": "rejected", "updated_at": ts})

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="commitment_rejected",
        reason=f"Commitment '{existing.name}' rejected by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="commitment",
        entity_id=existing.id,
        before_data=existing.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    return RejectCommitmentOutput(commitment=updated)


# ---------------------------------------------------------------------------------------------
# 7. list_commitments
# ---------------------------------------------------------------------------------------------
class ListCommitmentsInput(ToolInput):
    """Input parameters for listing commitments."""

    status: CommitmentStatus | None = None
    kind: CommitmentKind | None = None


class ListCommitmentsOutput(ToolOutput):
    """List of commitments."""

    commitments: list[Commitment]


def list_commitments_handler(ctx: "ExecutionContext", **kwargs) -> ListCommitmentsOutput:
    params = ListCommitmentsInput.model_validate(kwargs)
    comms = repo_list_commitments(ctx.conn, ctx.user_id, status=params.status, kind=params.kind)
    return ListCommitmentsOutput(commitments=comms)


# ---------------------------------------------------------------------------------------------
# 8. get_commitment_status
# ---------------------------------------------------------------------------------------------
class GetCommitmentStatusInput(ToolInput):
    """Input parameters for getting commitment status and matching against occurrences."""

    commitment_id: str
    window_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    window_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class GetCommitmentStatusOutput(ToolOutput):
    """Status summary and occurrence projection for a commitment."""

    commitment: Commitment
    occurrences: list[Occurrence]
    next_due: Occurrence | None
    status_summary: str
    matched_count: int
    overdue_count: int


def get_commitment_status_handler(ctx: "ExecutionContext", **kwargs) -> GetCommitmentStatusOutput:
    params = GetCommitmentStatusInput.model_validate(kwargs)
    c = get_commitment(ctx.conn, ctx.user_id, params.commitment_id)
    if c is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Commitment '{params.commitment_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    as_of = params.as_of_date or ts[:10]
    as_of_d = datetime.date.fromisoformat(as_of)

    # Window defaults: 30 days prior to 60 days ahead
    win_from = params.window_from or (as_of_d - datetime.timedelta(days=30)).isoformat()
    win_to = params.window_to or (as_of_d + datetime.timedelta(days=60)).isoformat()

    occs = expand_occurrences(c, win_from, win_to)

    d_from = datetime.date.fromisoformat(win_from)
    d_to = datetime.date.fromisoformat(win_to)
    tx_start = (d_from - datetime.timedelta(days=3)).isoformat() + "T00:00:00Z"
    tx_end = (d_to + datetime.timedelta(days=3)).isoformat() + "T23:59:59Z"

    tx_rows = ctx.conn.execute(
        """
        SELECT id, occurred_at, amount_paise, direction, category_id,
               merchant_normalized, excluded_from_spend
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at <= ? AND excluded_from_spend = 0
        ORDER BY occurred_at ASC
        """,
        (ctx.user_id, tx_start, tx_end),
    ).fetchall()

    txs = [dict(r) for r in tx_rows]
    matches = match_occurrences(occs, txs, as_of_date=as_of)

    overdue_count = sum(1 for o in occs if o.status == "overdue")
    matched_count = sum(1 for o, txn, m, conf in matches if txn is not None)

    upcoming_occs = [o for o in occs if o.due_date >= as_of and o.status == "upcoming"]
    next_due = upcoming_occs[0] if upcoming_occs else None

    if c.status == "paused":
        summary = "paused"
    elif c.status == "ended":
        summary = "ended"
    elif c.status == "draft":
        summary = "draft"
    elif overdue_count > 0:
        summary = "overdue"
    elif any(o.status == "partially_paid" for o in occs):
        summary = "partially_paid"
    else:
        summary = "on_track"

    return GetCommitmentStatusOutput(
        commitment=c,
        occurrences=occs,
        next_due=next_due,
        status_summary=summary,
        matched_count=matched_count,
        overdue_count=overdue_count,
    )


# ---------------------------------------------------------------------------------------------
# 9. suggest_commitments
# ---------------------------------------------------------------------------------------------
class SuggestCommitmentsInput(ToolInput):
    """Input parameters for suggesting commitments from detected recurring series."""

    tolerance_bp: int = Field(default=500, ge=0, le=5000)


class SuggestCommitmentsOutput(ToolOutput):
    """Result of suggesting commitments from recurring payment series."""

    drafts_created: int
    commitments: list[Commitment]


def suggest_commitments_handler(ctx: "ExecutionContext", **kwargs) -> SuggestCommitmentsOutput:
    params = SuggestCommitmentsInput.model_validate(kwargs)
    ts = to_utc_iso(now_utc(ctx.clock))

    series_list = list_recurring_series(ctx.conn, ctx.user_id)
    existing_commitments = repo_list_commitments(ctx.conn, ctx.user_id)
    linked_series_ids = {
        c.recurring_series_id for c in existing_commitments if c.recurring_series_id
    }

    drafts: list[Commitment] = []
    for s in series_list:
        if s["id"] in linked_series_ids:
            continue

        kind_str = s.get("kind", "other")
        if kind_str == "income":
            direction: CommitmentDirection = "inflow"
            comm_kind: CommitmentKind = "income"
        elif kind_str == "subscription":
            direction = "outflow"
            comm_kind = "subscription"
        elif kind_str == "bill":
            direction = "outflow"
            comm_kind = "bill"
        else:
            direction = "outflow"
            comm_kind = "other"

        cadence = s.get("cadence_days", 30)
        ne_str = s.get("next_expected", ts)[:10]
        ne_date = datetime.date.fromisoformat(ne_str)

        if cadence == 7:
            schedule_kind: ScheduleKind = "weekly"
            schedule_json = {"day_of_week": ne_date.weekday()}
        elif cadence in (28, 29, 30, 31):
            schedule_kind = "monthly"
            schedule_json = {"day": ne_date.day}
        elif cadence in (365, 366):
            schedule_kind = "yearly"
            schedule_json = {"month": ne_date.month, "day": ne_date.day}
        else:
            schedule_kind = "every_n_days"
            schedule_json = {"n": cadence, "anchor": ne_str}

        merchant_norm = s.get("merchant_normalized", "")
        tx_rows = ctx.conn.execute(
            """
            SELECT amount_paise, category_id FROM transactions
            WHERE user_id = ? AND merchant_normalized = ? AND excluded_from_spend = 0
            """,
            (ctx.user_id, merchant_norm),
        ).fetchall()

        typ_paise = s.get("typical_amount_paise", 0)
        category_id = None
        if tx_rows:
            amounts = [abs(r["amount_paise"]) for r in tx_rows]
            cat_candidates = [r["category_id"] for r in tx_rows if r["category_id"]]
            if cat_candidates:
                category_id = cat_candidates[0]
            min_amt = min(amounts)
            max_amt = max(amounts)
            tol_paise = (typ_paise * params.tolerance_bp) // 10000
            if (max_amt - min_amt) <= tol_paise:
                certainty: CommitmentCertainty = "firm"
                amt_paise: int | None = typ_paise
                amt_min: int | None = None
                amt_max: int | None = None
            else:
                certainty = "estimated"
                amt_paise = None
                amt_min = min_amt
                amt_max = max_amt
        else:
            certainty = "firm"
            amt_paise = typ_paise
            amt_min = None
            amt_max = None

        comm_id = f"comm_{uuid.uuid4().hex[:8]}"
        name = merchant_norm.title() if merchant_norm else f"{comm_kind.title()} {comm_id}"
        comm = Commitment(
            id=comm_id,
            user_id=ctx.user_id,
            name=name,
            direction=direction,
            kind=comm_kind,
            category_id=category_id,
            amount_paise=amt_paise,
            amount_min_paise=amt_min,
            amount_max_paise=amt_max,
            certainty=certainty,
            schedule_kind=schedule_kind,
            schedule_json=schedule_json,
            start_date=s.get("last_seen", ts)[:10],
            end_date=None,
            recurring_series_id=s["id"],
            goal_id=None,
            bucket_id=None,
            source="suggested",
            status="draft",
            created_at=ts,
            updated_at=ts,
        )
        insert_commitment(ctx.conn, comm)
        linked_series_ids.add(s["id"])
        drafts.append(comm)

    if drafts:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type="commitments_suggested",
            reason=f"Suggested {len(drafts)} commitments from recurring series",
            run_id=ctx.run_id,
            entity_type="commitment",
            entity_id=ctx.user_id,
            metadata={"draft_count": len(drafts), "commitment_ids": [c.id for c in drafts]},
            clock=ctx.clock,
        )

    return SuggestCommitmentsOutput(drafts_created=len(drafts), commitments=drafts)


# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------
COMMITMENT_TOOLS = (
    ToolSpec(
        name="create_commitment",
        description="Create a new financial commitment (outflow or inflow).",
        input_model=CreateCommitmentInput,
        output_model=CreateCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_commitment_handler,
    ),
    ToolSpec(
        name="update_commitment",
        description="Update an existing financial commitment.",
        input_model=UpdateCommitmentInput,
        output_model=UpdateCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=update_commitment_handler,
    ),
    ToolSpec(
        name="pause_commitment",
        description="Pause an active commitment.",
        input_model=PauseCommitmentInput,
        output_model=PauseCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=pause_commitment_handler,
    ),
    ToolSpec(
        name="end_commitment",
        description="End an active commitment with an end date.",
        input_model=EndCommitmentInput,
        output_model=EndCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=end_commitment_handler,
    ),
    ToolSpec(
        name="accept_commitment",
        description="Accept a suggested draft commitment to activate it.",
        input_model=AcceptCommitmentInput,
        output_model=AcceptCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=accept_commitment_handler,
    ),
    ToolSpec(
        name="reject_commitment",
        description="Reject a suggested commitment.",
        input_model=RejectCommitmentInput,
        output_model=RejectCommitmentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=reject_commitment_handler,
    ),
    ToolSpec(
        name="list_commitments",
        description="List commitments for the user, optionally filtered by status or kind.",
        input_model=ListCommitmentsInput,
        output_model=ListCommitmentsOutput,
        side_effect=SideEffect.READ,
        handler=list_commitments_handler,
    ),
    ToolSpec(
        name="get_commitment_status",
        description="Get status, occurrences, and transaction matches for a commitment.",
        input_model=GetCommitmentStatusInput,
        output_model=GetCommitmentStatusOutput,
        side_effect=SideEffect.READ,
        handler=get_commitment_status_handler,
    ),
    ToolSpec(
        name="suggest_commitments",
        description="Suggest draft commitments from detected recurring transaction series.",
        input_model=SuggestCommitmentsInput,
        output_model=SuggestCommitmentsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=suggest_commitments_handler,
    ),
)


def register_commitment_tools(register_fn=register) -> None:
    """Register all commitment-related tools into the global registry."""
    for spec in COMMITMENT_TOOLS:
        register_fn(spec)
