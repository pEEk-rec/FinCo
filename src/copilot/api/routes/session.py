"""Health and the session token: the only routes a fresh page calls first."""

from fastapi import FastAPI

from copilot.api.contracts import (
    Health,
    Session,
)
from copilot.api.deps import auth
from copilot.api.state import ApiState
from copilot.common.timeutil import IST, now_utc, to_utc_iso


def register(app: FastAPI, state: ApiState) -> None:
    # -- health and session --------------------------------------------------------------------
    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    @app.get("/api/session", response_model=Session, dependencies=auth)
    def session() -> Session:
        now = now_utc(state.clock)
        ist = now.astimezone(IST)
        return Session(
            user_id=state.user_id,
            as_of=to_utc_iso(now),
            period=f"{ist.year:04d}-{ist.month:02d}",
            data_source=state.data_source,
            demo_clock=state.clock is not None,
            llm_available=state.get_llm() is not None,
        )
