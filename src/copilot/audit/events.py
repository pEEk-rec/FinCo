"""
Audit log implementation enforcing append-only semantics.
"""

import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from copilot.core.timeutil import now_utc, to_utc_iso


def record_event(
    conn: sqlite3.Connection,
    user_id: str,
    actor: str,
    event_type: str,
    reason: str,
    run_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    before_data: Optional[Dict[str, Any]] = None,
    after_data: Optional[Dict[str, Any]] = None,
    policy_decision: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Record a new audit event. Returns the generated event ID.
    """
    event_id = str(uuid.uuid4())
    occurred_at = to_utc_iso(now_utc())

    before_json = json.dumps(before_data) if before_data is not None else None
    after_json = json.dumps(after_data) if after_data is not None else None
    metadata_json = json.dumps(metadata) if metadata is not None else None

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
            occurred_at,
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


def list_events(
    conn: sqlite3.Connection,
    user_id: str,
    run_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[sqlite3.Row]:
    """
    List audit events for a user, optionally filtering by run, entity, or type.
    """
    query = "SELECT * FROM audit_events WHERE user_id = ?"
    params = [user_id]

    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)

    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(entity_id)

    if event_type is not None:
        query += " AND event_type = ?"
        params.append(event_type)

    query += " ORDER BY occurred_at ASC"

    return conn.execute(query, params).fetchall()
