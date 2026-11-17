"""Operations: the scheduled jobs and their runs."""

from typing import Any

from fastapi import FastAPI

from copilot.api.deps import Conn, auth
from copilot.api.helpers import dump_data
from copilot.api.state import ApiState


def register(app: FastAPI, state: ApiState) -> None:
    # -- Ops & Jobs ----------------------------------------------------------------------------
    @app.get("/api/ops", dependencies=auth)
    def ops_dashboard_api(conn: Conn) -> dict[str, Any]:
        import dataclasses

        from copilot.db.repo_agent_runtime import list_scheduled_jobs
        from copilot.ops.telemetry import compute_ops_telemetry

        telemetry = compute_ops_telemetry(conn, user_id=state.user_id)
        jobs = list_scheduled_jobs(conn, user_id=state.user_id, enabled_only=False)
        return {
            "status": "healthy",
            "telemetry": dataclasses.asdict(telemetry),
            "background_jobs": [dump_data(j) for j in jobs],
        }

    @app.post("/api/jobs/run", dependencies=auth)
    def run_due_jobs_api(conn: Conn) -> dict[str, Any]:
        from copilot.runtime.runner import run_due_jobs

        runs = run_due_jobs(conn, user_id=state.user_id)
        conn.commit()
        return {"status": "ok", "jobs_executed": len(runs), "runs": [dump_data(r) for r in runs]}
