import pytest

from copilot.db.connection import get_connection, init_db, savepoint

T = "2024-01-01T00:00:00Z"


@pytest.fixture
def db_path(tmp_path):
    # A file DB so a second connection can observe what was really committed.
    path = str(tmp_path / "sp.db")
    c = get_connection(path)
    init_db(c)
    c.close()
    return path


@pytest.fixture
def conn(db_path):
    c = get_connection(db_path)
    yield c
    c.close()


def committed_users(db_path: str) -> list[str]:
    """Read users through a second connection, so only committed rows are visible."""
    other = get_connection(db_path)
    try:
        return [r[0] for r in other.execute("SELECT id FROM users ORDER BY id")]
    finally:
        other.close()


def test_savepoint_commits_at_top_level(conn, db_path):
    with savepoint(conn):
        conn.execute("INSERT INTO users VALUES ('u1', ?)", (T,))
    assert not conn.in_transaction
    assert committed_users(db_path) == ["u1"]


def test_savepoint_rolls_back_everything_on_error(conn, db_path):
    with pytest.raises(RuntimeError), savepoint(conn):
        conn.execute("INSERT INTO users VALUES ('u1', ?)", (T,))
        raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert committed_users(db_path) == []


def test_nested_savepoint_only_undoes_inner_block(conn, db_path):
    with savepoint(conn):
        conn.execute("INSERT INTO users VALUES ('outer', ?)", (T,))
        with pytest.raises(RuntimeError), savepoint(conn):
            conn.execute("INSERT INTO users VALUES ('inner', ?)", (T,))
            raise RuntimeError("boom")
    assert committed_users(db_path) == ["outer"]


def test_savepoint_inside_caller_transaction_does_not_commit(conn, db_path):
    conn.execute("INSERT INTO users VALUES ('pending', ?)", (T,))  # implicit BEGIN
    with savepoint(conn):
        conn.execute("INSERT INTO users VALUES ('inner', ?)", (T,))
    assert conn.in_transaction
    assert committed_users(db_path) == []
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
