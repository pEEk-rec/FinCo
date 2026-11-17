"""Reads and writes for memories, their evidence, and user preferences."""

import json
import sqlite3
import uuid
from typing import Any

from copilot.models.agent_runtime import (
    MemoryEvidence,
    MemoryItem,
)


def insert_memory_item(conn: sqlite3.Connection, item: MemoryItem) -> MemoryItem:
    conn.execute(
        """
        INSERT INTO memory_items (
            id, user_id, kind, subject_key, statement_json, source, status,
            prior_bp, user_confirmed, created_at, last_evidence_at, last_confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.user_id,
            item.kind,
            item.subject_key,
            json.dumps(item.statement_json),
            item.source,
            item.status,
            item.prior_bp,
            1 if item.user_confirmed else 0,
            item.created_at,
            item.last_evidence_at,
            item.last_confirmed_at,
        ),
    )
    return item


def get_memory_item(conn: sqlite3.Connection, user_id: str, memory_id: str) -> MemoryItem | None:
    row = conn.execute(
        "SELECT * FROM memory_items WHERE user_id = ? AND id = ?",
        (user_id, memory_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["statement_json"] = json.loads(d["statement_json"])
    d["user_confirmed"] = bool(d["user_confirmed"])
    return MemoryItem.model_validate(d)


def list_memory_items(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
    kind: str | None = None,
    subject_key: str | None = None,
) -> list[MemoryItem]:
    query = "SELECT * FROM memory_items WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    if subject_key is not None:
        query += " AND subject_key = ?"
        params.append(subject_key)
    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["statement_json"] = json.loads(d["statement_json"])
        d["user_confirmed"] = bool(d["user_confirmed"])
        items.append(MemoryItem.model_validate(d))
    return items


def update_memory_status(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    status: str,
    last_confirmed_at: str | None = None,
    user_confirmed: bool | None = None,
) -> bool:
    updates = ["status = ?"]
    params: list[Any] = [status]
    if last_confirmed_at is not None:
        updates.append("last_confirmed_at = ?")
        params.append(last_confirmed_at)
    if user_confirmed is not None:
        updates.append("user_confirmed = ?")
        params.append(1 if user_confirmed else 0)
    params.extend([user_id, memory_id])

    cur = conn.execute(
        f"UPDATE memory_items SET {', '.join(updates)} WHERE user_id = ? AND id = ?",
        params,
    )
    return cur.rowcount > 0


def insert_memory_evidence(conn: sqlite3.Connection, e: MemoryEvidence) -> MemoryEvidence:
    conn.execute(
        """
        INSERT INTO memory_evidence (
            id, user_id, memory_id, polarity, ref_kind, ref_id, observed_at, weight_bp, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            e.id,
            e.user_id,
            e.memory_id,
            e.polarity,
            e.ref_kind,
            e.ref_id,
            e.observed_at,
            e.weight_bp,
            e.created_at,
        ),
    )
    # Update last_evidence_at on parent memory item
    conn.execute(
        "UPDATE memory_items SET last_evidence_at = ? WHERE user_id = ? AND id = ?",
        (e.observed_at, e.user_id, e.memory_id),
    )
    return e


def list_memory_evidence(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
) -> list[MemoryEvidence]:
    rows = conn.execute(
        "SELECT * FROM memory_evidence WHERE user_id = ? AND memory_id = ?"
        " ORDER BY observed_at ASC",
        (user_id, memory_id),
    ).fetchall()
    return [MemoryEvidence.model_validate(dict(r)) for r in rows]


def forget_memory_item(conn: sqlite3.Connection, user_id: str, memory_id: str) -> bool:
    """
    Clears statement_json and evidence rows' details, sets status = 'forgotten' (PLAN_PHASE3 5.8).
    """
    cur = conn.execute(
        "UPDATE memory_items SET status = 'forgotten', statement_json = '{}'"
        " WHERE user_id = ? AND id = ?",
        (user_id, memory_id),
    )
    if cur.rowcount > 0:
        conn.execute(
            "DELETE FROM memory_evidence WHERE user_id = ? AND memory_id = ?",
            (user_id, memory_id),
        )
        return True
    return False


def update_memory_statement(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    statement_json: dict[str, Any],
) -> bool:
    cur = conn.execute(
        "UPDATE memory_items SET statement_json = ? WHERE user_id = ? AND id = ?",
        (json.dumps(statement_json), user_id, memory_id),
    )
    return cur.rowcount > 0


def get_memory_by_subject(
    conn: sqlite3.Connection,
    user_id: str,
    kind: str,
    subject_key: str,
) -> MemoryItem | None:
    query = (
        "SELECT * FROM memory_items "
        "WHERE user_id = ? AND kind = ? AND subject_key = ? AND status != 'forgotten' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = conn.execute(query, (user_id, kind, subject_key)).fetchone()

    if not row:
        return None
    d = dict(row)
    d["statement_json"] = json.loads(d["statement_json"])
    d["user_confirmed"] = bool(d["user_confirmed"])
    return MemoryItem.model_validate(d)


def set_user_preference(
    conn: sqlite3.Connection,
    user_id: str,
    key: str,
    value: Any,
    updated_at: str,
) -> None:
    pid = f"pref_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO user_preferences (id, user_id, key, value_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (pid, user_id, key, json.dumps(value), updated_at),
    )


def get_user_preference(conn: sqlite3.Connection, user_id: str, key: str) -> Any | None:
    row = conn.execute(
        "SELECT value_json FROM user_preferences WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def list_user_preferences(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT key, value_json FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {r[0]: json.loads(r[1]) for r in rows}
