from typing import TYPE_CHECKING

from copilot.audit.events import get_event, record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.db.repo import update_transaction_category
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


class UndoInput(ToolInput):
    audit_event_id: str


class UndoOutput(ToolOutput):
    undone_event_id: str
    new_audit_event_id: str


def undo_handler(ctx: "ExecutionContext", audit_event_id: str) -> UndoOutput:
    event = get_event(ctx.conn, audit_event_id)
    if not event:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Audit event {audit_event_id} not found")

    if event.user_id != ctx.user_id:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Audit event {audit_event_id} not found")

    # We only support undoing certain event types right now
    if event.event_type not in ("transaction_recategorized", "override_applied"):
        raise ToolFailure(ErrorCode.VALIDATION_ERROR, f"Cannot undo event type {event.event_type}")

    # We must ensure we haven't already undone this by checking metadata.undone_event_id.
    already_undone = ctx.conn.execute(
        "SELECT 1 FROM audit_events WHERE user_id = ? AND event_type = 'undo' "
        "AND json_extract(metadata_json, '$.undone_event_id') = ?",
        (ctx.user_id, audit_event_id),
    ).fetchone()

    if already_undone:
        raise ToolFailure(
            ErrorCode.VALIDATION_ERROR, f"Event {audit_event_id} has already been undone"
        )

    if event.entity_type == "transaction":
        before = event.before
        if before is None:
            raise ToolFailure(ErrorCode.VALIDATION_ERROR, "No before data to restore")

        # For a robust undo, restore prior category state
        tx_id = event.entity_id
        update_transaction_category(
            ctx.conn,
            ctx.user_id,
            tx_id,
            before["category_id"],
            before["category_source"],
            before["category_confidence"],
        )

    elif event.entity_type == "transaction_batch":
        before = event.before
        if before is None:
            raise ToolFailure(ErrorCode.VALIDATION_ERROR, "No before data to restore")

        for tx_id, b_data in before.items():
            update_transaction_category(
                ctx.conn,
                ctx.user_id,
                tx_id,
                b_data["category_id"],
                b_data["category_source"],
                b_data["category_confidence"],
            )

    # Record the undo
    new_event_id = record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="undo",
        reason=f"Undo event {audit_event_id}",
        run_id=ctx.run_id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        before_data=event.after,
        after_data=event.before,
        metadata={"undone_event_id": audit_event_id},
        clock=ctx.clock,
    )

    return UndoOutput(undone_event_id=audit_event_id, new_audit_event_id=new_event_id)


UNDO_TOOL = ToolSpec(
    name="undo",
    description="Undo a previous reversible action.",
    input_model=UndoInput,
    output_model=UndoOutput,
    side_effect=SideEffect.WRITE_LOGICAL,
    handler=undo_handler,
)
