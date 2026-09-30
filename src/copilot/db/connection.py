"""
Database connection, initialization and transaction boundaries.

Transaction rule: repo and audit functions never commit. The caller owns the unit of work and
wraps it in `savepoint(conn)`, so a state change and its audit event commit or roll back together.
"""

import pathlib
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

SCHEMA_VERSION = 1
# STRICT tables need SQLite 3.37 or newer.
MIN_SQLITE_VERSION = (3, 37, 0)


def get_connection(path: str = ":memory:") -> sqlite3.Connection:
    """Open a SQLite connection with Row results and foreign keys enabled."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} is too old; need "
            f"{'.'.join(map(str, MIN_SQLITE_VERSION))}+ for STRICT tables."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    Create the schema on a fresh database. Safe to call again on an initialised one.

    Raises RuntimeError if the database has a schema version this code does not know.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise RuntimeError(f"Unknown schema version {version}; expected {SCHEMA_VERSION}.")

    schema_path = pathlib.Path(__file__).parent / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    # executescript commits any pending transaction first; the script itself is BEGIN..COMMIT.
    try:
        conn.executescript(schema)
    except sqlite3.Error:
        if conn.in_transaction:
            conn.rollback()
        raise


@contextmanager
def savepoint(conn: sqlite3.Connection) -> Iterator[None]:
    """
    Run a block atomically. On exception everything since entry is undone, then re-raised.

    Outside any transaction the block is committed on exit. Inside a caller's transaction it
    nests: the caller's own commit or rollback decides the final outcome.
    """
    name = f"sp_{uuid.uuid4().hex}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")
