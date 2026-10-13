"""
Append-only audit log.

There are deliberately no update or delete functions, and database triggers reject UPDATE,
DELETE and re-INSERT of an existing id (which is how `INSERT OR REPLACE` would overwrite a row).
`record_event` does not commit: it joins the caller's unit of work so a state change and its
audit event are saved together.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from copilot.core.timeutil import now_utc, to_utc_iso

Actor = Literal["user", "agent", "system"]
PolicyDecision = Literal["allow", "deny", "needs_approval"]
_ACTORS = ("user", "agent", "system")
_DECISIONS = ("allow", "deny", "needs_approval")


class AuditEvent(BaseModel):
    """One audit row, with the JSON columns decoded back into Python values."""

    id: str
    user_id: str
    run_id: str | None
    occurred_at: str
    actor: Actor
    event_type: str
    entity_type: str | None
    entity_id: str | None
    before: Any | None
    after: Any | None
    reason: str
    policy_decision: PolicyDecision | None
    metadata: Any | None


def _to_json(value: Any | None, field: str) -> str | None:
    """Serialise a JSON-compatible value (stable key order); raise TypeError otherwise."""
    if value is None:
        return None
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"Audit field '{field}' is not JSON-serialisable: {exc}") from exc


def record_event(
    conn: sqlite3.Connection,
    user_id: str,
    actor: Actor,
    event_type: str,
    reason: str,
    run_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before_data: Any | None = None,
    after_data: Any | None = None,
    policy_decision: PolicyDecision | None = None,
    metadata: Any | None = None,
    clock: datetime | None = None,
) -> str:
    """
    Append an audit event and return its id. Does not commit.

    Everything is validated before the INSERT, so a bad call writes nothing.
    `clock` pins the event time (tests, or the executor's context clock).
    """
    if actor not in _ACTORS:
        raise ValueError(f"actor must be one of {_ACTORS}, got {actor!r}")
    if policy_decision is not None and policy_decision not in _DECISIONS:
        raise ValueError(f"policy_decision must be one of {_DECISIONS}, got {policy_decision!r}")
    if not event_type.strip():
        raise ValueError("event_type must not be empty")
    if not reason.strip():
        raise ValueError("reason must not be empty")

    before_json = _to_json(before_data, "before_data")
    after_json = _to_json(after_data, "after_data")
    metadata_json = _to_json(metadata, "metadata")

    event_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO audit_events (
            id, user_id, run_id, occurred_at, actor, event_type,
            entity_type, entity_id, before_json, after_json,
            reason, policy_decision, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            user_id,
            run_id,
            to_utc_iso(now_utc(clock)),
            actor,
            event_type,
            entity_type,
            entity_id,
            before_json,
            after_json,
            reason,
            policy_decision,
            metadata_json,
        ),
    )
    return event_id


def _row_to_event(row: sqlite3.Row) -> AuditEvent:
    """Decode a raw audit row into an AuditEvent."""
    data = dict(row)
    for column, field in (
        ("before_json", "before"),
        ("after_json", "after"),
        ("metadata_json", "metadata"),
    ):
        raw = data.pop(column)
        data[field] = json.loads(raw) if raw is not None else None
    return AuditEvent(**data)


def get_event(conn: sqlite3.Connection, event_id: str) -> AuditEvent | None:
    row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        return None
    return _row_to_event(row)


def list_events(
    conn: sqlite3.Connection,
    user_id: str,
    run_id: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
) -> list[AuditEvent]:
    """
    List a user's audit events, optionally filtered by run, entity or type.

    Ordered by time, then insertion order (rowid) so same-second events keep their sequence.
    """
    query = "SELECT * FROM audit_events WHERE user_id = ?"
    params: list[str] = [user_id]
    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(entity_id)
    if event_type is not None:
        query += " AND event_type = ?"
        params.append(event_type)
    query += " ORDER BY occurred_at ASC, rowid ASC"
    return [_row_to_event(row) for row in conn.execute(query, params).fetchall()]
