"""Planning ahead: commitments, the cash-flow calendar, buckets and readiness."""

from typing import Any

from fastapi import FastAPI, Query

from copilot.api.contracts import (
    BucketAllocateIn,
    BucketIn,
    BucketReallocateIn,
    CommitmentIn,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import unwrap
from copilot.api.helpers import dump_data
from copilot.api.state import ApiState
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- Commitments ---------------------------------------------------------------------------
    @app.get("/api/commitments", dependencies=auth)
    def list_commitments_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_money import list_commitments

        items = list_commitments(conn, user_id=state.user_id, status=status)
        return [dump_data(c) for c in items]

    @app.post("/api/commitments", dependencies=auth)
    def create_commitment_api(body: CommitmentIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_commitment",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/commitments/suggest", dependencies=auth)
    def suggest_commitments_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "suggest_commitments",
                {},
            )
        )
        conn.commit()
        return dump_data(out)

    # -- Calendar ------------------------------------------------------------------------------
    @app.get("/api/calendar", dependencies=auth)
    def calendar_forecast_api(
        conn: Conn, horizon_days: int = Query(60, ge=1, le=180)
    ) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_calendar",
                {"horizon_days": horizon_days},
            )
        )
        conn.commit()
        return dump_data(out)

    # -- Buckets -------------------------------------------------------------------------------
    @app.get("/api/buckets", dependencies=auth)
    def buckets_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_buckets",
                {},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/buckets", dependencies=auth)
    def create_bucket_api(body: BucketIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_bucket",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/buckets/allocate", dependencies=auth)
    def allocate_bucket_api(body: BucketAllocateIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "allocate_to_bucket",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/buckets/reallocate", dependencies=auth)
    def reallocate_bucket_api(body: BucketReallocateIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "reassign_between_buckets",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    # -- Readiness -----------------------------------------------------------------------------
    @app.get("/api/readiness", dependencies=auth)
    def readiness_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "assess_investment_readiness",
                {},
            )
        )
        conn.commit()
        return dump_data(out)
