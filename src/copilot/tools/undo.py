from typing import TYPE_CHECKING

from copilot.audit.events import get_event, record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.db.repo import get_transaction, update_transaction_category
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
    if event.event_type not in (
        "transaction_recategorized",
        "override_applied",
        "payment_labeled",
    ):
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Cannot undo event type {event.event_type}")

    # We must ensure we haven't already undone this by checking metadata.undone_event_id.
    already_undone = ctx.conn.execute(
        "SELECT 1 FROM audit_events WHERE user_id = ? AND event_type = 'undo' "
        "AND json_extract(metadata_json, '$.undone_event_id') = ?",
        (ctx.user_id, audit_event_id),
    ).fetchone()

    if already_undone:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, f"Event {audit_event_id} has already been undone"
        )

    if event.entity_type == "payment_event":
        from copilot.core.capture import undo_label

        if event.before is None or event.after is None or event.entity_id is None:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Missing state data for event")
        undo_label(
            ctx.conn,
            ctx.user_id,
            event.entity_id,
            event.before,
            event.after,
            event.metadata or {},
        )

    elif event.entity_type == "transaction":
        before = event.before
        after = event.after
        if before is None or after is None:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Missing state data for event")

        tx_id = event.entity_id
        tx = get_transaction(ctx.conn, ctx.user_id, tx_id)
        if not tx:
            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="undo_refused",
                reason=f"Undo refused: transaction {tx_id} not found",
                run_id=ctx.run_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                metadata={"undone_event_id": audit_event_id, "refusal_reason": "entity_not_found"},
                clock=ctx.clock,
            )
            raise ToolFailure(
                ErrorCode.NOT_FOUND,
                f"Undo refused: transaction {tx_id} not found",
                audit_event_type="undo_refused",
                audit_metadata={
                    "undone_event_id": audit_event_id,
                    "refusal_reason": "entity_not_found",
                },
            )

        current_state = {
            "category_id": tx.category_id,
            "category_source": tx.category_source,
            "category_confidence": tx.category_confidence,
        }

        # Check divergence against after_data
        diverged = False
        for k in ("category_id", "category_source", "category_confidence"):
            if k in after and current_state.get(k) != after.get(k):
                diverged = True
                break

        if diverged:
            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="undo_refused",
                reason=f"Current state differs from after_data for event {audit_event_id}",
                run_id=ctx.run_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                before_data=current_state,
                after_data=after,
                metadata={
                    "undone_event_id": audit_event_id,
                    "refusal_reason": "state_diverged",
                },
                clock=ctx.clock,
            )
            raise ToolFailure(
                ErrorCode.STALE_DATA,
                f"Undo refused: transaction {tx_id} state has diverged from event after_data",
                audit_event_type="undo_refused",
                audit_metadata={
                    "undone_event_id": audit_event_id,
                    "refusal_reason": "state_diverged",
                },
            )

        update_transaction_category(
            ctx.conn,
            ctx.user_id,
            tx_id,
            before["category_id"],
            before["category_source"],
            before.get("category_confidence"),
            needs_review=before.get("needs_review"),
        )

    elif event.entity_type == "transaction_batch":
        before = event.before
        after = event.after
        if before is None or after is None:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Missing state data for event")

        diverged_tx_id = None
        current_states = {}

        # All-or-nothing: check every transaction in batch before modifying any
        for tx_id, expected_after in after.items():
            tx = get_transaction(ctx.conn, ctx.user_id, tx_id)
            if not tx:
                diverged_tx_id = tx_id
                break
            curr_state = {
                "category_id": tx.category_id,
                "category_source": tx.category_source,
                "category_confidence": tx.category_confidence,
            }
            current_states[tx_id] = curr_state
            for k in ("category_id", "category_source", "category_confidence"):
                if k in expected_after and curr_state.get(k) != expected_after.get(k):
                    diverged_tx_id = tx_id
                    break
            if diverged_tx_id:
                break

        if diverged_tx_id:
            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="undo_refused",
                reason=(
                    f"Current state differs from after_data for transaction {diverged_tx_id} "
                    f"in batch event {audit_event_id}"
                ),
                run_id=ctx.run_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                before_data=current_states,
                after_data=after,
                metadata={
                    "undone_event_id": audit_event_id,
                    "refusal_reason": "batch_item_diverged",
                    "diverged_transaction_id": diverged_tx_id,
                },
                clock=ctx.clock,
            )
            raise ToolFailure(
                ErrorCode.STALE_DATA,
                f"Undo refused: batch item {diverged_tx_id} state has diverged from after_data",
                audit_event_type="undo_refused",
                audit_metadata={
                    "undone_event_id": audit_event_id,
                    "refusal_reason": "batch_item_diverged",
                    "diverged_transaction_id": diverged_tx_id,
                },
            )

        for tx_id, b_data in before.items():
            update_transaction_category(
                ctx.conn,
                ctx.user_id,
                tx_id,
                b_data["category_id"],
                b_data["category_source"],
                b_data.get("category_confidence"),
                needs_review=b_data.get("needs_review"),
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
