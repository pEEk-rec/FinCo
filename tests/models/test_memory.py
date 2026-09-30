import sqlite3

import pytest
from pydantic import ValidationError

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_memory_entry, insert_user, list_memory_entries
from copilot.models.domain import User
from copilot.models.memory import MemoryEntry

T0 = "2024-01-01T00:00:00Z"


def entry(**overrides) -> MemoryEntry:
    data = {
        "id": "m1",
        "user_id": "u1",
        "kind": "preference",
        "content": "Prefers weekly summaries",
        "source": "user_stated",
        "confidence": 1.0,
        "created_at": T0,
        "last_confirmed_at": T0,
        "provenance": "chat message on 2024-01-01",
    }
    data.update(overrides)
    return MemoryEntry(**data)


@pytest.mark.parametrize("missing", ["provenance", "source", "confidence", "kind"])
def test_required_fields(missing):
    data = entry().model_dump()
    del data[missing]
    with pytest.raises(ValidationError):
        MemoryEntry(**data)


@pytest.mark.parametrize(
    "change",
    [
        {"provenance": "  "},
        {"content": ""},
        {"source": "guessed"},
        {"kind": "secret"},
        {"confidence": 1.01},
        {"last_confirmed_at": "2023-12-31T23:59:59Z"},
    ],
)
def test_invalid_entries_rejected(change):
    with pytest.raises(ValidationError):
        entry(**change)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    for u in ("u1", "u2"):
        insert_user(c, User(id=u, created_at=T0))
    return c


def test_insert_and_list(conn):
    insert_memory_entry(conn, entry())
    insert_memory_entry(conn, entry(id="m2", kind="pattern", source="observed", confidence=0.6))
    insert_memory_entry(conn, entry(id="m3", user_id="u2"))
    assert [m.id for m in list_memory_entries(conn, "u1")] == ["m1", "m2"]
    assert [m.id for m in list_memory_entries(conn, "u1", kind="pattern")] == ["m2"]
    assert list_memory_entries(conn, "u1")[0] == entry()


def test_database_rejects_blank_provenance(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_entries VALUES ('m9', 'u1', 'preference', 'x', 'observed', 0.5, "
            "?, ?, '   ')",
            (T0, T0),
        )
