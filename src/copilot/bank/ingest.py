"""
Idempotent ingestion of raw bank records via a mock bank connector.
"""

import hashlib
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.money import rupees_to_paise
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.db.connection import savepoint
from copilot.db.repo import get_account, get_transaction, insert_transaction, list_transactions
from copilot.models.domain import Transaction

RawRecord = dict[str, str]


class BankConnector(Protocol):
    """Anything that can return raw records for a consent."""

    def fetch_session(self, consent_id: str) -> list[RawRecord]:
        """Fetch transactions for an active consent."""
        ...


@dataclass(frozen=True)
class IngestReport:
    """Outcome of one sync."""

    fetched: int
    inserted: int
    skipped_existing: int
    duplicates_flagged: int


def generate_fingerprint(record: RawRecord) -> str:
    """Deterministic fingerprint for exact repeats."""
    # account, timestamp, amount, normalized narration, reference
    content = f"{record['account_no']}|{record['posted_at']}|{record['amount']}|{record.get('narration', '')}|{record['txn_ref']}"  # noqa: E501
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_record(record: RawRecord, user_id: str, fingerprint: str) -> Transaction:
    """Convert one raw record into a Transaction. Raises ValueError on malformed input."""
    if record.get("type") not in ("DR", "CR"):
        raise ValueError(f"Unknown record type {record.get('type')!r}")
    paise = rupees_to_paise(record["amount"])
    if paise <= 0:
        raise ValueError(f"Record amount must be positive, got {record['amount']!r}")
    signed = paise if record["type"] == "DR" else -paise
    return Transaction(
        id=record["txn_ref"],
        user_id=user_id,
        account_id=record["account_no"],
        occurred_at=record["posted_at"],
        amount_paise=signed,
        direction="debit" if signed > 0 else "credit",
        merchant_raw=record["narration"],
        description=record.get("remarks", ""),
        category_id=None,
        category_source="none",
        created_at=record["posted_at"],
        fingerprint=fingerprint,
    )


def ingest_statements(
    conn: sqlite3.Connection,
    connector: BankConnector,
    user_id: str,
    account_id: str,
    consent_id: str,
    clock: datetime | None = None,
    duplicate_window_hours: int = 24,
) -> IngestReport:
    """
    Fetch records for one account and store the new ones, atomically.
    Flags duplicate charges and skips exact repeats.
    """
    if get_account(conn, user_id, account_id) is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Account '{account_id}' not found.")

    batch_id = str(uuid.uuid4())
    started_at = to_utc_iso(clock or now_utc())
    dummy_range = "1970-01-01T00:00:00Z"

    try:
        records = connector.fetch_session(consent_id)
    except ToolFailure as exc:
        conn.execute(
            """
            INSERT INTO ingestion_batches (
                id, user_id, consent_id, account_id, range_from, range_to, 
                fetched_count, inserted_count, duplicate_count, status, error_code, 
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                user_id,
                consent_id,
                account_id,
                dummy_range,
                dummy_range,
                0,
                0,
                0,
                "failed",
                exc.error.code.value,
                started_at,
                to_utc_iso(clock or now_utc()),
            ),  # noqa: E501
        )
        raise

    try:
        parsed = []
        for r in records:
            fp = generate_fingerprint(r)
            parsed.append((fp, parse_record(r, user_id, fp)))
    except (KeyError, ValueError, TypeError) as exc:
        conn.execute(
            """
            INSERT INTO ingestion_batches (
                id, user_id, consent_id, account_id, range_from, range_to, 
                fetched_count, inserted_count, duplicate_count, status, error_code, 
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                user_id,
                consent_id,
                account_id,
                dummy_range,
                dummy_range,
                len(records),
                0,
                0,
                "failed",
                ErrorCode.INVALID_INPUT.value,
                started_at,
                to_utc_iso(clock or now_utc()),
            ),  # noqa: E501
        )
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Malformed bank record: {exc}") from exc

    inserted = 0
    skipped = 0
    duplicates_flagged = 0
    window = timedelta(hours=duplicate_window_hours)

    # Pre-fetch existing transactions (padded by the window) for duplicate detection
    if records:
        range_from = min(r["posted_at"] for r in records)
        range_to = max(r["posted_at"] for r in records)
        lookup_from = to_utc_iso(from_utc_iso(range_from) - window)
        lookup_to = to_utc_iso(from_utc_iso(range_to) + window + timedelta(seconds=1))
        existing_txs = list_transactions(
            conn, user_id, lookup_from, lookup_to, account_id=account_id
        )
    else:
        range_from = dummy_range
        range_to = dummy_range
        existing_txs = []

    fingerprints = {t.fingerprint for t in existing_txs if t.fingerprint}
    # Deterministic processing order: the same set of records always gives the same flags.
    parsed.sort(key=lambda item: (item[1].occurred_at, item[1].id))

    with savepoint(conn):
        # Insert batch first so foreign keys pass
        conn.execute(
            """
            INSERT INTO ingestion_batches (
                id, user_id, consent_id, account_id, range_from, range_to,
                fetched_count, inserted_count, duplicate_count, status, error_code,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                user_id,
                consent_id,
                account_id,
                range_from,
                range_to,
                len(parsed),
                0,
                0,
                "pending",
                None,
                started_at,
                None,
            ),
        )

        for fp, tx in parsed:
            tx.batch_id = batch_id

            # Exact repeat
            if get_transaction(conn, user_id, tx.id) is not None or fp in fingerprints:
                skipped += 1
                continue

            # Likely duplicate charge: same merchant and amount close in time. The later of the
            # pair is flagged; both stay stored.
            when = from_utc_iso(tx.occurred_at)
            twins = [
                t
                for t in existing_txs
                if t.merchant_raw == tx.merchant_raw
                and t.amount_paise == tx.amount_paise
                and abs(from_utc_iso(t.occurred_at) - when) <= window
            ]
            later_twin = None
            if twins:
                earlier = [t for t in twins if (t.occurred_at, t.id) < (tx.occurred_at, tx.id)]
                if earlier:
                    tx.is_duplicate_of = min(earlier, key=lambda t: (t.occurred_at, t.id)).id
                    duplicates_flagged += 1
                else:
                    candidate = min(twins, key=lambda t: (t.occurred_at, t.id))
                    if candidate.is_duplicate_of is None:
                        later_twin = candidate

            insert_transaction(conn, tx)
            if later_twin is not None:
                conn.execute(
                    "UPDATE transactions SET is_duplicate_of = ? WHERE id = ? AND user_id = ?",
                    (tx.id, later_twin.id, user_id),
                )
                later_twin.is_duplicate_of = tx.id
                duplicates_flagged += 1
            existing_txs.append(tx)
            fingerprints.add(fp)
            inserted += 1

        report = IngestReport(
            fetched=len(parsed),
            inserted=inserted,
            skipped_existing=skipped,
            duplicates_flagged=duplicates_flagged,  # noqa: E501
        )

        conn.execute(
            """
            UPDATE ingestion_batches SET
                inserted_count = ?, duplicate_count = ?, status = 'completed', finished_at = ?
            WHERE id = ?
            """,
            (inserted, duplicates_flagged, to_utc_iso(clock or now_utc()), batch_id),
        )

        record_event(
            conn,
            user_id=user_id,
            actor="system",
            event_type="transactions_ingested",
            reason="Bank sync",
            entity_type="account",
            entity_id=account_id,
            metadata={"consent_id": consent_id} | asdict(report),
            clock=clock,
        )
    return report


_CONNECTOR: BankConnector | None = None


def set_connector(connector: BankConnector) -> None:
    global _CONNECTOR
    _CONNECTOR = connector


def ingest_statements_handler(ctx, account_id: str, consent_id: str) -> dict:
    if _CONNECTOR is None:
        raise ToolFailure(ErrorCode.TOOL_FAILURE, "Bank connector not configured.")
    report = ingest_statements(ctx.conn, _CONNECTOR, ctx.user_id, account_id, consent_id, ctx.clock)
    return asdict(report)
