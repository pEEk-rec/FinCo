"""The bank link (Account Aggregator) and its consent."""

from typing import Literal

from fastapi import FastAPI

from copilot.api.deps import Conn, auth
from copilot.api.errors import unwrap
from copilot.api.state import ApiState
from copilot.tools.aa import ConsentOut, FetchOut
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- Account Aggregator: the bank link and its consent -------------------------------------
    @app.get("/api/aa/consent", response_model=ConsentOut, dependencies=auth)
    def aa_consent_get(conn: Conn) -> ConsentOut:
        return unwrap(execute_tool(state.context(conn, "user"), "aa_status", {}))  # type: ignore[return-value]

    @app.post("/api/aa/consent", response_model=ConsentOut, dependencies=auth)
    def aa_consent_create(conn: Conn) -> ConsentOut:
        out = unwrap(execute_tool(state.context(conn, "user"), "create_aa_consent", {}))
        conn.commit()
        return out  # type: ignore[return-value]

    @app.post("/api/aa/consent/{consent_id}/{action}", response_model=ConsentOut, dependencies=auth)
    def aa_consent_action(
        consent_id: str,
        action: Literal["approve", "pause", "resume", "revoke"],
        conn: Conn,
    ) -> ConsentOut:
        args = {"consent_id": consent_id, "action": action}
        out = unwrap(execute_tool(state.context(conn, "user"), "set_aa_consent_state", args))
        conn.commit()
        return out  # type: ignore[return-value]

    @app.post("/api/aa/fetch", response_model=FetchOut, dependencies=auth)
    def aa_fetch_now(conn: Conn) -> FetchOut:
        out = unwrap(execute_tool(state.context(conn, "user"), "fetch_aa_data", {"force": True}))
        conn.commit()
        return out  # type: ignore[return-value]
