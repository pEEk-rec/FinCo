"""
Runtime state for the HTTP API: database location, session token, demo clock, data source.

One local user (on-device principle). Each request opens its own SQLite connection, so
request handlers never share a connection across threads.
"""

import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from copilot.api.llm import GuardedLLM, build_llm
from copilot.core.config import load_settings
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import PolicySettings, load_policy
from copilot.llm.client import LLMClient
from copilot.tools.executor import ExecutionContext

DataSource = Literal["synthetic_demo", "connected"]


@dataclass
class ApiState:
    """Everything the API needs at runtime. Built once by `create_app`."""

    db_path: Path
    user_id: str = "u1"
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    clock: datetime | None = None
    data_source: DataSource = "synthetic_demo"
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    policy: PolicySettings | None = None
    #: "auto" resolves from .env on first use; None disables the model; tests pass a fake client.
    llm: "LLMClient | GuardedLLM | None | Literal['auto']" = "auto"

    def get_llm(self) -> "LLMClient | GuardedLLM | None":
        """The optional language-model client (built once, lazily)."""
        if self.llm == "auto":
            self.llm = build_llm()
        return self.llm  # type: ignore[return-value]

    def get_policy(self) -> PolicySettings:
        """The governance policy from config/policy.yaml (loaded once)."""
        if self.policy is None:
            self.policy = load_policy(load_settings().policy_path)
        return self.policy

    def connect(self) -> sqlite3.Connection:
        """Open a connection with migrations applied."""
        conn = get_connection(str(self.db_path), check_same_thread=False)
        init_db(conn)
        return conn

    def context(
        self, conn: sqlite3.Connection, actor: Literal["user", "agent"] = "user"
    ) -> ExecutionContext:
        """Execution context for one request. User actions run as actor 'user'."""
        return ExecutionContext(
            conn=conn,
            user_id=self.user_id,
            run_id=f"api_{uuid.uuid4().hex[:12]}",
            policy=self.get_policy(),
            clock=self.clock,
            actor=actor,
        )


def connection_scope(state: ApiState) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency body: one connection per request, always closed."""
    conn = state.connect()
    try:
        yield conn
    finally:
        conn.close()
