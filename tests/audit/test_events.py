import sqlite3

import pytest

from copilot.audit.events import list_events, record_event
from copilot.db.connection import get_connection, init_db


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    c.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")
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
        entity_id="e1"
    )
    
    event_id2 = record_event(
        conn,
        user_id="u1",
        actor="user",
        event_type="another_event",
        reason="testing more",
        run_id="run2"
    )
    
    events = list_events(conn, user_id="u1")
    assert len(events) == 2
    
    # Filter by run
    run1_events = list_events(conn, user_id="u1", run_id="run1")
    assert len(run1_events) == 1
    assert run1_events[0]["id"] == event_id1
    
    # Filter by entity
    entity_events = list_events(conn, user_id="u1", entity_id="e1")
    assert len(entity_events) == 1
    assert entity_events[0]["id"] == event_id1
    
    # Filter by type
    type_events = list_events(conn, user_id="u1", event_type="another_event")
    assert len(type_events) == 1
    assert type_events[0]["id"] == event_id2

def test_append_only_update_fails(conn):
    event_id = record_event(
        conn, user_id="u1", actor="system", event_type="test", reason="test"
    )
    
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        conn.execute("UPDATE audit_events SET reason = 'hacked' WHERE id = ?", (event_id,))

def test_append_only_delete_fails(conn):
    event_id = record_event(
        conn, user_id="u1", actor="system", event_type="test", reason="test"
    )
    
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        conn.execute("DELETE FROM audit_events WHERE id = ?", (event_id,))
