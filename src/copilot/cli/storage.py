"""
Storage and connector management for the CLI.
Persists mock bank connector state and workflow traces across separate CLI process invocations.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copilot.bank.ingest import set_connector
from copilot.bank.mock_bank import MockAAConnector
from copilot.bank.synth import generate_transactions
from copilot.core.config import PROJECT_ROOT, load_settings
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import PolicySettings, load_policy
from copilot.models.domain import Transaction
from copilot.tools.executor import ExecutionContext

DATA_DIR = PROJECT_ROOT / "data"


def get_db_path(db_arg: str | None) -> str:
    """Resolve database path from CLI argument or settings."""
    if db_arg:
        return db_arg
    settings = load_settings()
    return str(settings.db_path)


def open_db(db_path: str) -> sqlite3.Connection:
    """Open SQLite connection and ensure migrations are applied."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    init_db(conn)
    return conn


def get_mock_bank_path(user_id: str) -> Path:
    """Path to the persisted mock bank state for a user."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"mock_bank_{user_id}.json"


def get_trace_path(run_id: str) -> Path:
    """Path to persisted execution trace."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"trace_{run_id}.json"


def save_mock_bank_data(user_id: str, seed: int, months: int, account_id: str) -> int:
    """
    Generate synthetic transactions, persist them to disk, and return count.
    """
    synth = generate_transactions(
        seed=seed, months=months, user_id=user_id, account_ids=[account_id]
    )
    raw_txs = [t.model_dump() for t in synth.transactions]
    file_path = get_mock_bank_path(user_id)
    file_path.write_text(
        json.dumps(
            {
                "seed": seed,
                "months": months,
                "account_id": account_id,
                "user_id": user_id,
                "transactions": raw_txs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(raw_txs)


def load_and_register_connector(
    user_id: str,
    account_id: str = "a1",
    conn: sqlite3.Connection | None = None,
) -> MockAAConnector:
    """
    Load persisted mock bank transactions and register connector in ingest module.
    Falls back to generating seed 42 transactions if no state file exists.
    """
    file_path = get_mock_bank_path(user_id)
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            txs = [Transaction.model_validate(t) for t in data["transactions"]]
            connector = MockAAConnector(txs)
        except Exception:
            connector = MockAAConnector.from_seed(
                seed=42, months=3, user_id=user_id, account_id=account_id
            )
    else:
        connector = MockAAConnector.from_seed(
            seed=42, months=3, user_id=user_id, account_id=account_id
        )

    # Sync consents from database into mock connector
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT id, account_ids, date_range_from, date_range_to, status, expires_at "
                "FROM consents WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            for r in rows:
                acc_ids = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or [account_id])
                connector._consents[r[0]] = {
                    "user_id": user_id,
                    "account_ids": acc_ids,
                    "range_from": r[2],
                    "range_to": r[3],
                    "status": r[4],
                    "expires_at": r[5],
                }
        except Exception:
            pass

    set_connector(connector)
    return connector


def save_trace(run_id: str, trace_entries: list[dict[str, Any]]) -> None:
    """Save workflow execution trace entries to disk."""
    get_trace_path(run_id).write_text(
        json.dumps(trace_entries, indent=2, default=str), encoding="utf-8"
    )


def load_trace(run_id: str) -> list[dict[str, Any]] | None:
    """Load workflow execution trace entries from disk."""
    path = get_trace_path(run_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def make_exec_ctx(
    conn: sqlite3.Connection,
    user_id: str,
    run_id: str | None = None,
    actor: str = "user",
    policy: PolicySettings | None = None,
) -> ExecutionContext:
    """Create ExecutionContext for CLI tool execution."""
    if policy is None:
        settings = load_settings()
        policy = load_policy(settings.policy_path)
    rid = run_id or f"cli_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"
    return ExecutionContext(
        conn=conn,
        user_id=user_id,
        policy=policy,
        actor=actor,  # type: ignore[arg-type]
        run_id=rid,
    )
