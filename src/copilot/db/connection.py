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
    Apply all pending migrations in order. Safe to call again on an initialised database.
    """
    # Maintain Phase 0 PRAGMA user_version for baseline tests
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != 0 and version != SCHEMA_VERSION:
        raise RuntimeError(f"Unknown schema version {version}; expected {SCHEMA_VERSION}.")

    # 1. Ensure migrations table exists
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        ) STRICT;
        """
    )

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    migrations_dir = pathlib.Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        return

    migration_files = sorted(migrations_dir.glob("*.sql"))

    for mf in migration_files:
        version = mf.name
        if version not in applied:
            script = mf.read_text(encoding="utf-8")
            conn.execute("PRAGMA foreign_keys = OFF;")
            # executescript commits any pending transaction first, so we wrap the migration
            # and the record insertion in an explicit BEGIN..COMMIT block.
            wrapped_script = (
                "BEGIN;\n"
                f"{script}\n"
                f"INSERT INTO schema_migrations (version, applied_at) VALUES ('{version}', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));\n"  # noqa: E501
                "COMMIT;\n"
            )
            conn.executescript(wrapped_script)
            conn.execute("PRAGMA foreign_keys = ON;")


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
