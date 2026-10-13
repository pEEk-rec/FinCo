"""
Tools for transfer and recurring payment detection.
"""

import uuid
from typing import Any

from copilot.audit.events import record_event
from copilot.core.config import load_settings
from copilot.core.patterns import detect_recurring, detect_transfers
from copilot.db.connection import savepoint
from copilot.db.repo import list_transactions
from copilot.tools.contracts import ToolInput, ToolOutput


class DetectTransfersInput(ToolInput):
    pass


class DetectTransfersOutput(ToolOutput):
    links_created: int


def detect_transfers_handler(ctx: Any) -> DetectTransfersOutput:
    """Find and link own-account transfers, excluding them from spend."""
    settings = load_settings()
    window_hours = settings.transfer_window_hours

    # We fetch all transactions that are not excluded_from_spend
    # To keep it simple, fetch all and filter in python
    # For a real system we might limit to recent, but Phase 1 we scan all
    txs = list_transactions(ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")

    links = detect_transfers(txs, window_hours=window_hours)

    created = 0
    with savepoint(ctx.conn):
        for debit, credit in links:
            link_id = f"tl_{uuid.uuid4().hex[:8]}"

            # Double check they aren't already linked
            row = ctx.conn.execute(
                "SELECT 1 FROM transfer_links WHERE debit_txn_id = ? OR credit_txn_id = ?",
                (debit.id, credit.id),
            ).fetchone()
            if row:
                continue

            ctx.conn.execute(
                """
                INSERT INTO transfer_links (
                    id, user_id, debit_txn_id, credit_txn_id, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    link_id,
                    ctx.user_id,
                    debit.id,
                    credit.id,
                    0.9,
                    ctx.clock.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if ctx.clock
                    else "2024-01-01T00:00:00Z",
                ),
            )

            ctx.conn.execute(
                "UPDATE transactions SET excluded_from_spend = 1 "
                "WHERE id IN (?, ?) AND user_id = ?",
                (debit.id, credit.id, ctx.user_id),
            )

            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="transfer_detected",
                reason="Auto-detected transfer",
                run_id=ctx.run_id,
                entity_type="transfer_link",
                entity_id=link_id,
                metadata={"debit": debit.id, "credit": credit.id},
                clock=ctx.clock,
            )
            created += 1

    return DetectTransfersOutput(links_created=created)


class DetectRecurringInput(ToolInput):
    pass


class DetectRecurringOutput(ToolOutput):
    series_detected: int


def detect_recurring_handler(ctx: Any) -> DetectRecurringOutput:
    """Find recurring payment series."""
    settings = load_settings()

    txs = list_transactions(ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")

    series_list = detect_recurring(
        txs,
        tolerance_pct=settings.recurring_tolerance_pct,
        min_occurrences=settings.recurring_min_occurrences,
    )

    created = 0
    with savepoint(ctx.conn):
        # Clear existing ones and recreate for simplicity in Phase 1
        ctx.conn.execute("DELETE FROM recurring_series WHERE user_id = ?", (ctx.user_id,))

        for s in series_list:
            s_id = f"rs_{uuid.uuid4().hex[:8]}"
            ctx.conn.execute(
                """
                INSERT INTO recurring_series (
                    id, user_id, merchant_normalized, typical_amount_paise,
                    cadence_days, last_seen, next_expected, confidence, kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s_id,
                    ctx.user_id,
                    s["merchant_normalized"],
                    s["typical_amount_paise"],
                    s["cadence_days"],
                    s["last_seen"],
                    s["next_expected"],
                    s["confidence"],
                    s["kind"],
                ),
            )

            # Audit log summary is recorded after loop
            created += 1

        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type="recurring_detected",
            reason="Auto-detected recurring series",
            run_id=ctx.run_id,
            entity_type="system",
            entity_id=ctx.user_id,
            metadata={"count": created},
            clock=ctx.clock,
        )

    return DetectRecurringOutput(series_detected=created)
