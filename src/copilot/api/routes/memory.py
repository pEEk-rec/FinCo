"""What FinCo remembers about you and what it has learned, each with a way to undo it."""

from typing import Any

from fastapi import FastAPI, Query

from copilot.api.contracts import (
    LearningResetIn,
    MemoryForgetIn,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import unwrap
from copilot.api.helpers import dump_data
from copilot.api.state import ApiState
from copilot.common.timeutil import now_utc
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- Memories ------------------------------------------------------------------------------
    @app.get("/api/memories", dependencies=auth)
    def memories_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_memory import list_memory_items

        items = list_memory_items(conn, user_id=state.user_id, status=status)
        return [dump_data(m) for m in items]

    @app.post("/api/memories/forget", dependencies=auth)
    def forget_memory_api(body: MemoryForgetIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "forget_memory",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    @app.get("/api/memories/audit", dependencies=auth)
    def memory_audit_api(conn: Conn, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM memory_audit_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (state.user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Learning ------------------------------------------------------------------------------
    @app.get("/api/learning", dependencies=auth)
    def learning_profile_api(conn: Conn) -> dict[str, Any]:
        from copilot.learning.feedback import list_tenant_learning_stats

        stats = list_tenant_learning_stats(conn, state.user_id)
        return {"user_id": state.user_id, "stats": stats}

    @app.post("/api/learning/reset", dependencies=auth)
    def reset_learning_api(body: LearningResetIn, conn: Conn) -> dict[str, Any]:
        from copilot.learning.feedback import reset_learning

        deleted = reset_learning(
            conn,
            state.user_id,
            subject_kind=body.subject_kind,
            subject_key=body.subject_key,
            clock=now_utc(state.clock),
        )
        conn.commit()
        return {"status": "ok", "reset_count": deleted}
