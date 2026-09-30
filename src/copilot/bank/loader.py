"""
Ingest raw bank records into the database via the repo layer.

No categorisation happens here: every row is stored with category_source = 'none'.
The whole batch and its audit event are written in one savepoint (all or nothing), and
re-running the same sync skips records that are already stored.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.money import rupees_to_paise
from copilot.db.connection import savepoint
from copilot.db.repo import get_account, get_transaction, insert_transaction
from copilot.models.domain import Transaction

RawRecord = dict[str, str]


class BankConnector(Protocol):
    """Anything that can return raw records for an account and time range."""

    def fetch_transactions(self, account_id: str, start: str, end: str) -> list[RawRecord]:
        """Raw records with start <= posted_at < end."""
        ...


@dataclass(frozen=True)
class IngestReport:
    """Outcome of one sync."""

    fetched: int
    inserted: int
    skipped_existing: int


def parse_record(record: RawRecord, user_id: str) -> Transaction:
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
    )


def ingest_transactions(
    conn: sqlite3.Connection,
    connector: BankConnector,
    user_id: str,
    account_id: str,
    start: str,
    end: str,
    clock: datetime | None = None,
) -> IngestReport:
    """
    Fetch records for one account and store the new ones, atomically.

    Connector failures propagate as ToolFailure and nothing is written. A malformed record
    fails the whole batch with INVALID_INPUT rather than loading a partial month.
    """
    if get_account(conn, user_id, account_id) is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Account '{account_id}' not found.")
    records = connector.fetch_transactions(account_id, start, end)
    try:
        parsed = [parse_record(r, user_id) for r in records]
    except (KeyError, ValueError, TypeError) as exc:
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Malformed bank record: {exc}") from exc

    inserted = 0
    with savepoint(conn):
        for tx in parsed:
            if get_transaction(conn, user_id, tx.id) is not None:
                continue
            insert_transaction(conn, tx)
            inserted += 1
        report = IngestReport(
            fetched=len(parsed), inserted=inserted, skipped_existing=len(parsed) - inserted
        )
        record_event(
            conn,
            user_id=user_id,
            actor="system",
            event_type="transactions_ingested",
            reason="Bank sync",
            entity_type="account",
            entity_id=account_id,
            metadata={"start": start, "end": end} | asdict(report),
            clock=clock,
        )
    return report
