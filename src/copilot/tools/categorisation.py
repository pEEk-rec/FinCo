"""Batch categorization tools: `categorize_batch` and `undo_categorize_batch`."""

import json
from typing import Any

from pydantic import BaseModel, Field

from copilot.audit.events import record_event
from copilot.core.config import load_settings
from copilot.db.repo import get_transaction
from copilot.tools.contracts import ToolInput, ToolOutput

APPLY_EVENT = "transaction_categorized_batch"
UNDO_EVENT = "transaction_categorization_undone"
PROTECTED_SOURCES = ("user", "override")
SOURCES = ("override", "rule", "cache", "llm", "none")


class CategorizeUpdate(BaseModel):
    """One proposed category for one transaction."""

    transaction_id: str
    category_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    model: str | None = None
    prompt_version: str | None = None


class CategorizeBatchInput(ToolInput):
    updates: list[CategorizeUpdate]


class CategorizeBatchOutput(ToolOutput):
    updated_count: int
    review_queue_count: int
    skipped_count: int = 0


def _category_exists(ctx: Any, category_id: str) -> bool:
    row = ctx.conn.execute(
        "SELECT 1 FROM categories WHERE id = ? AND user_id = ?", (category_id, ctx.user_id)
    ).fetchone()
    return row is not None


def _state(category_id: str | None, source: str, confidence: float | None, review: bool) -> dict:
    return {
        "category_id": category_id,
        "category_source": source,
        "category_confidence": confidence,
        "needs_review": bool(review),
    }


def categorize_batch_handler(ctx: Any, updates: list[CategorizeUpdate]) -> CategorizeBatchOutput:
    """
    Apply category proposals under the agent's built-in constraints.

    - never touches transactions whose source is `user` or `override`
    - proposals below `auto_accept_min_confidence`, with no category, or naming an unknown
      category go to the review queue instead of being applied as accepted
    - LLM confidence is capped at `llm_confidence_cap`
    - one audit event per changed transaction, sharing the run id, so the batch is undoable
    """
    cfg = load_settings().categorization
    updated = queued = skipped = 0

    for up in updates:
        if up.source not in SOURCES:
            skipped += 1
            continue
        tx = get_transaction(ctx.conn, ctx.user_id, up.transaction_id)
        if tx is None or tx.category_source in PROTECTED_SOURCES:
            skipped += 1
            continue

        category_id = up.category_id
        confidence = (
            min(up.confidence, cfg.llm_confidence_cap) if up.source == "llm" else (up.confidence)
        )
        if category_id is not None and not _category_exists(ctx, category_id):
            category_id, confidence = None, 0.0
        if category_id is None:
            up_source = "none"
        else:
            up_source = up.source
        needs_review = category_id is None or confidence < cfg.auto_accept_min_confidence

        before = _state(tx.category_id, tx.category_source, tx.category_confidence, tx.needs_review)
        after = _state(category_id, up_source, confidence, needs_review)
        if before == after:
            skipped += 1
            continue

        ctx.conn.execute(
            """
            UPDATE transactions
            SET category_id = ?, category_source = ?, category_confidence = ?, needs_review = ?
            WHERE id = ? AND user_id = ?
            """,
            (category_id, up_source, confidence, int(needs_review), tx.id, ctx.user_id),
        )
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type=APPLY_EVENT,
            reason=f"Batch categorization via {up_source}",
            run_id=ctx.run_id,
            entity_type="transaction",
            entity_id=tx.id,
            before_data=before,
            after_data=after,
            metadata={"model": up.model, "prompt_version": up.prompt_version},
            clock=ctx.clock,
        )
        if needs_review:
            queued += 1
        else:
            updated += 1

    return CategorizeBatchOutput(
        updated_count=updated, review_queue_count=queued, skipped_count=skipped
    )


class UndoCategorizeBatchInput(ToolInput):
    target_run_id: str


class UndoCategorizeBatchOutput(ToolOutput):
    restored_count: int
    skipped_count: int = 0


def undo_categorize_batch_handler(ctx: Any, target_run_id: str) -> UndoCategorizeBatchOutput:
    """
    Restore every transaction changed by a batch to its exact before-state.

    A transaction is restored only if it still holds the state the batch gave it. If the user
    (or a later run) changed it since, it is left alone and counted as skipped. Running the
    undo twice is harmless: the second run finds nothing left to restore.
    """
    rows = ctx.conn.execute(
        """
        SELECT entity_id, before_json, after_json FROM audit_events
        WHERE user_id = ? AND run_id = ? AND event_type = ?
        ORDER BY occurred_at DESC, rowid DESC
        """,
        (ctx.user_id, target_run_id, APPLY_EVENT),
    ).fetchall()

    restored = skipped = 0
    for tx_id, before_json, after_json in rows:
        before, after = json.loads(before_json), json.loads(after_json)
        tx = get_transaction(ctx.conn, ctx.user_id, tx_id)
        current = (
            _state(tx.category_id, tx.category_source, tx.category_confidence, tx.needs_review)
            if tx is not None
            else None
        )
        if current != after or current == before:
            skipped += 1
            continue
        ctx.conn.execute(
            """
            UPDATE transactions
            SET category_id = ?, category_source = ?, category_confidence = ?, needs_review = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                before["category_id"],
                before["category_source"],
                before["category_confidence"],
                int(before["needs_review"]),
                tx_id,
                ctx.user_id,
            ),
        )
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type=UNDO_EVENT,
            reason=f"Undo categorization for run {target_run_id}",
            run_id=ctx.run_id,
            entity_type="transaction",
            entity_id=tx_id,
            before_data=current,
            after_data=before,
            metadata={"undid_run_id": target_run_id},
            clock=ctx.clock,
        )
        restored += 1

    return UndoCategorizeBatchOutput(restored_count=restored, skipped_count=skipped)
