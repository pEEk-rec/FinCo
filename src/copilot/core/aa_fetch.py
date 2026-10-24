"""
Fetching under a consent (PLAN_CAPTURE Stage C7, safety rule 6).

A fetch runs only under an active, in-scope consent. The consent is checked before the source is
called and again before anything is saved, so a revoke that lands mid-fetch discards the result.
Rows outside the consented date range are dropped. What was fetched becomes ledger transactions
(deduplicated by fingerprint) and then goes through reconciliation with the captured events.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel

from copilot.audit.events import Actor, record_event
from copilot.core import aa_consent
from copilot.core.aa_source import AASource, MockAASource, bank_side_feed, sandbox_source
from copilot.core.capture_reconcile import reconcile_events
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.live.service import import_rows

_UNIT_HOURS = {"HOUR": 1, "DAY": 24, "MONTH": 24 * 30}


class FetchReport(BaseModel):
    consent_id: str
    skipped: str | None = None  # why nothing was fetched, if so
    fetched: int = 0
    out_of_range: int = 0
    inserted: int = 0
    already_known: int = 0
    matched: int = 0
    ambiguous: int = 0


def _due(row: sqlite3.Row, now: datetime) -> bool:
    if not row["last_fetch_at"]:
        return True
    freq = json.loads(row["frequency_json"])
    gap = timedelta(hours=freq["value"] * _UNIT_HOURS[freq["unit"]])
    return now - from_utc_iso(row["last_fetch_at"]) >= gap


def fetch_now(
    conn: sqlite3.Connection,
    user_id: str,
    consent_id: str,
    source: AASource,
    *,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
    force: bool = False,
) -> FetchReport:
    now = now_utc(clock)
    row = aa_consent.require_active(conn, user_id, consent_id, now)
    if not force and not _due(row, now):
        return FetchReport(consent_id=consent_id, skipped="not due yet")
    window_from = from_utc_iso(row["range_from"])
    window_to = min(now, from_utc_iso(row["range_to"]))
    result = source.fetch(window_from, window_to)
    # The permission may have been withdrawn while the source was answering.
    aa_consent.require_active(conn, user_id, consent_id, now)

    rows = [r for r in result.rows if window_from <= from_utc_iso(r.occurred_at) <= window_to]
    out_of_range = len(result.rows) - len(rows)
    if result.payload is not None:
        life = timedelta(days=row["data_life_days"])
        conn.execute(
            "INSERT INTO aa_raw (id, user_id, consent_id, fetched_at, delete_after, txn_count,"
            " payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"aar_{uuid.uuid4().hex[:12]}", user_id, consent_id, to_utc_iso(now),
                to_utc_iso(now + life), len(rows), json.dumps(result.payload),
            ),
        )  # fmt: skip
    account = conn.execute(
        "SELECT id FROM accounts WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,)
    ).fetchone()
    if account is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "There is no account to add the transactions to.")
    summary = import_rows(conn, user_id, rows, "aa", now, account=account["id"])
    rec = reconcile_events(conn, user_id, actor="system", run_id=run_id, clock=now)
    conn.execute(
        "UPDATE aa_consents SET last_fetch_at = ? WHERE id = ?", (to_utc_iso(now), consent_id)
    )
    report = FetchReport(
        consent_id=consent_id,
        fetched=len(result.rows),
        out_of_range=out_of_range,
        inserted=summary.inserted,
        already_known=summary.skipped_existing,
        matched=rec.matched,
        ambiguous=rec.ambiguous,
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="aa_fetched",
        reason="Fetched transactions under the bank link", run_id=run_id,
        entity_type="aa_consent", entity_id=consent_id,
        metadata=report.model_dump(exclude={"consent_id", "skipped"}), clock=now,
    )  # fmt: skip
    return report


def default_source(
    conn: sqlite3.Connection, user_id: str, row: sqlite3.Row, clock: datetime | None
) -> AASource | None:
    """The source a consent was made for: the mock bank, or the sandbox if the owner set it up."""
    if row["connector"] == "mock":
        return MockAASource(bank_side_feed(conn, user_id, clock))
    if row["connector"] == "sandbox":
        return sandbox_source(row["external_ref"])
    return None


class CycleReport(BaseModel):
    expired: int
    raw_deleted: int
    fetches: list[FetchReport]
    skipped_no_source: int = 0


def run_cycle(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> CycleReport:
    """The daily job: end what has ended, delete what is past its life, fetch what is due."""
    now = now_utc(clock)
    expired, deleted = aa_consent.expire_due(conn, user_id, actor=actor, run_id=run_id, clock=now)
    fetches: list[FetchReport] = []
    no_source = 0
    for row in conn.execute(
        "SELECT * FROM aa_consents WHERE user_id = ? AND status = 'active' ORDER BY created_at",
        (user_id,),
    ).fetchall():
        source = default_source(conn, user_id, row, now)
        if source is None:
            no_source += 1
            continue
        fetches.append(
            fetch_now(conn, user_id, row["id"], source, actor=actor, run_id=run_id, clock=now)
        )
    return CycleReport(
        expired=expired, raw_deleted=deleted, fetches=fetches, skipped_no_source=no_source
    )
