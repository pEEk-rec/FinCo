"""Database connection and initialization."""
import pathlib
import sqlite3


def get_connection(path: str = ":memory:") -> sqlite3.Connection:
    """
    Get a configured SQLite connection.
    Enables foreign keys.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema from schema.sql."""
    schema_path = pathlib.Path(__file__).parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()
    
    conn.executescript(schema)
    conn.commit()
