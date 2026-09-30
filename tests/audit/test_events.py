import sqlite3
from datetime import datetime

import pytest

from copilot.audit.events import list_events, record_event
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    for user in ("u1", "u2"):
        c.execute("INSERT INTO users (id, created_at) VALUES (?, '2023-01-01T00:00:00Z')", (user,))
    c.commit()
    return c


def test_record_and_list_events(conn):
    event_id1 = record_event(
        conn,
        user_id="u1",
        actor="agent",
        event_type="test_event",
        reason="testing",
        run_id="run1",
        entity_id="e1",
    )
    event_id2 = record_event(
        conn,
        user_id="u1",
        actor="user",
        event_type="another_event",
        reason="testing more",
        run_id="run2",
    )

    assert [e.id for e in list_events(conn, user_id="u1")] == [event_id1, event_id2]
    assert [e.id for e in list_events(conn, user_id="u1", run_id="run1")] == [event_id1]
    assert [e.id for e in list_events(conn, user_id="u1", entity_id="e1")] == [event_id1]
    assert [e.id for e in list_events(conn, user_id="u1", event_type="another_event")] == [
        event_id2
    ]


def test_events_filtered_by_user(conn):
    record_event(conn, user_id="u1", actor="system", event_type="t", reason="mine")
    record_event(conn, user_id="u2", actor="system", event_type="t", reason="theirs", run_id="r")
    assert [e.reason for e in list_events(conn, "u1")] == ["mine"]
    # Filtering by another user's run id still never leaks their rows
    assert list_events(conn, "u1", run_id="r") == []


def test_json_fields_round_trip(conn):
    record_event(
        conn,
        user_id="u1",
        actor="agent",
        event_type="recategorize",
        reason="r",
        before_data={"category_id": None},
        after_data={"category_id": "c1", "category_confidence": 1.0},
        metadata={"tool": "x"},
        policy_decision="allow",
    )
    event = list_events(conn, "u1")[0]
    assert event.before == {"category_id": None}
    assert event.after == {"category_confidence": 1.0, "category_id": "c1"}
    assert event.metadata == {"tool": "x"}
    assert event.policy_decision == "allow"


def test_clock_is_injectable(conn):
    record_event(
        conn,
        user_id="u1",
        actor="system",
        event_type="t",
        reason="r",
        clock=datetime(2024, 2, 1, 0, 30, tzinfo=IST),
    )
    assert list_events(conn, "u1")[0].occurred_at == "2024-01-31T19:00:00Z"


def test_same_second_events_keep_insertion_order(conn):
    clock = datetime(2024, 1, 1, tzinfo=IST)
    ids = [
        record_event(
            conn, user_id="u1", actor="system", event_type=f"e{i}", reason="r", clock=clock
        )
        for i in range(20)
    ]
    assert [e.id for e in list_events(conn, "u1")] == ids


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actor": "robot"},
        {"policy_decision": "maybe"},
        {"event_type": " "},
        {"reason": ""},
    ],
)
def test_invalid_event_rejected_before_write(conn, kwargs):
    args = {"user_id": "u1", "actor": "system", "event_type": "t", "reason": "r"} | kwargs
    with pytest.raises(ValueError):
        record_event(conn, **args)
    assert list_events(conn, "u1") == []


def test_non_json_data_rejected_before_write(conn):
    with pytest.raises(TypeError, match="after_data"):
        record_event(
            conn,
            user_id="u1",
            actor="system",
            event_type="t",
            reason="r",
            after_data={"x": object()},
        )
    assert list_events(conn, "u1") == []


def test_append_only_update_fails(conn):
    event_id = record_event(conn, user_id="u1", actor="system", event_type="test", reason="test")
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        conn.execute("UPDATE audit_events SET reason = 'hacked' WHERE id = ?", (event_id,))


def test_append_only_delete_fails(conn):
    event_id = record_event(conn, user_id="u1", actor="system", event_type="test", reason="test")
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        conn.execute("DELETE FROM audit_events WHERE id = ?", (event_id,))


def test_insert_or_replace_cannot_overwrite(conn):
    event_id = record_event(conn, user_id="u1", actor="system", event_type="t", reason="original")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "INSERT OR REPLACE INTO audit_events "
            "(id, user_id, occurred_at, actor, event_type, reason) "
            "VALUES (?, 'u1', '2000-01-01T00:00:00Z', 'system', 't', 'TAMPERED')",
            (event_id,),
        )
    assert list_events(conn, "u1")[0].reason == "original"


def test_record_event_does_not_commit(conn):
    record_event(conn, user_id="u1", actor="system", event_type="t", reason="r")
    conn.rollback()
    assert list_events(conn, "u1") == []
