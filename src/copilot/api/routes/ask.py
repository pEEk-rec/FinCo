"""Asking FinCo: the agent, its timeline, investigations, anomalies, alerts, goals and what-ifs."""

import sqlite3
from datetime import timedelta
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from copilot.api.contracts import (
    AlertDecisionIn,
    AlertPreferenceIn,
    AlertsOut,
    AnomalyOut,
    AskIn,
    AskOut,
    CompareIn,
    CompareOut,
    GoalContributionIn,
    GoalIn,
    GoalsOut,
    GoalUpdateIn,
    InvestigateAnomalyIn,
    InvestigateChangeIn,
    InvestigationOut,
    WhatIfIn,
    WhatIfOut,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import not_found, unwrap
from copilot.api.state import ApiState
from copilot.common.timeutil import IST, now_utc
from copilot.db.repo import list_goals
from copilot.models.agentic import Timeline
from copilot.ops.timeline import build_timeline
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- agent surfaces ------------------------------------------------------------------------
    @app.post("/api/ask", response_model=AskOut, dependencies=auth)
    def ask(body: AskIn, conn: Conn) -> AskOut:
        from copilot.api.agent import run_ask

        text = body.text if not body.clarification else f"{body.text} ({body.clarification})"
        return AskOut.model_validate(run_ask(state, conn, text, use_llm=body.use_llm))

    @app.post("/api/ask/stream", dependencies=auth)
    async def ask_stream_route(body: AskIn) -> StreamingResponse:
        """The same ask, as server-sent events: each step arrives as the agent takes it."""
        from copilot.api.ask_stream import ask_stream

        text = body.text if not body.clarification else f"{body.text} ({body.clarification})"
        return StreamingResponse(
            ask_stream(state, text, use_llm=body.use_llm),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/llm/status", dependencies=auth)
    def llm_status() -> dict[str, Any]:
        llm = state.get_llm()
        status = getattr(llm, "status", lambda: None)() if llm is not None else None
        return {"available": llm is not None, "router": status}

    @app.get("/api/timeline", response_model=Timeline, dependencies=auth)
    def timeline(conn: Conn, task_id: str | None = None, run_id: str | None = None) -> Timeline:
        return build_timeline(conn, state.user_id, task_id=task_id, run_id=run_id)

    @app.get("/api/investigations/{investigation_id}", dependencies=auth)
    def investigation(investigation_id: str, conn: Conn) -> dict[str, Any]:
        from copilot.db.repo import get_investigation

        inv = get_investigation(conn, state.user_id, investigation_id)
        if inv is None:
            raise not_found("Investigation not found.")
        return inv.model_dump(mode="json")

    @app.get("/api/anomalies", response_model=list[AnomalyOut], dependencies=auth)
    def anomalies(conn: Conn) -> list[AnomalyOut]:
        """Unusual transactions from the deterministic detector (a read; nothing is stored)."""
        from copilot.db.repo import list_transactions
        from copilot.domain.anomalies import detect_anomalies

        txs = list_transactions(conn, state.user_id, "1970-01-01T00:00:00Z", "2100-01-01T00:00:00Z")
        by_id = {t.id: t for t in txs}
        found: dict[str, AnomalyOut] = {}
        for item in detect_anomalies(txs):
            tx = by_id.get(item["transaction_ids"][-1])
            if tx is None or tx.id in found:
                continue
            found[tx.id] = AnomalyOut(
                id=tx.id,
                transaction_id=tx.id,
                kind=item["kind"],
                status="open",
                merchant=(tx.merchant_normalized or tx.merchant_raw).strip(),
                amount_paise=abs(tx.amount_paise),
                occurred_at=tx.occurred_at,
            )
        order = {"large_transaction": 0, "duplicate_charge": 1, "new_merchant": 2}
        ranked = sorted(found.values(), key=lambda a: (order.get(a.kind, 9), -a.amount_paise))
        return ranked[:8]

    @app.post("/api/investigate/anomaly", response_model=InvestigationOut, dependencies=auth)
    def investigate_anomaly(body: InvestigateAnomalyIn, conn: Conn) -> InvestigationOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "investigate_anomaly", {"anomaly_id": body.anomaly_id}
            )
        )
        conn.commit()
        return InvestigationOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.post("/api/investigate/change", response_model=InvestigationOut, dependencies=auth)
    def investigate_change(body: InvestigateChangeIn, conn: Conn) -> InvestigationOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "explain_change",
                {
                    "period": body.period,
                    "category_id": body.category_id,
                    "merchant": None,
                    "baseline_period": body.baseline_period,
                },
            )
        )
        conn.commit()
        return InvestigationOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.get("/api/alerts", response_model=AlertsOut, dependencies=auth)
    def alerts(
        conn: Conn, status: Literal["open", "acknowledged", "dismissed", "snoozed"] | None = None
    ) -> AlertsOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "list_alerts", {"status": status, "limit": 50}
            )
        )
        conn.commit()
        return AlertsOut(alerts=[a.model_dump(mode="json") for a in out.alerts])  # type: ignore[attr-defined]

    @app.post("/api/alerts/{alert_id}/decision", dependencies=auth)
    def decide_alert(alert_id: str, body: AlertDecisionIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "decide_alert",
                {
                    "alert_id": alert_id,
                    "action": body.action,
                    "reason": body.reason,
                    "snooze_days": body.snooze_days,
                },
            )
        )
        conn.commit()
        return out.model_dump(mode="json")  # type: ignore[attr-defined]

    @app.post("/api/alert-preferences", dependencies=auth)
    def alert_preference(body: AlertPreferenceIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "set_alert_preference",
                {
                    **body.model_dump(),
                    "max_open_alerts": None,
                },
            )
        )
        conn.commit()
        return out.model_dump(mode="json")  # type: ignore[attr-defined]

    @app.get("/api/goals", response_model=GoalsOut, dependencies=auth)
    def goals(conn: Conn) -> GoalsOut:
        return _goals_out(conn)

    def _goals_out(conn: sqlite3.Connection) -> GoalsOut:
        from copilot.domain.goals import goal_progress

        items = list_goals(conn, state.user_id)
        today = now_utc(state.clock).astimezone(IST).date()
        progress = [goal_progress(conn, state.user_id, g, today) for g in items]
        return GoalsOut(goals=items, progress=progress)

    @app.post("/api/goals", response_model=GoalsOut, dependencies=auth)
    def create_goal_api(body: GoalIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_goal",
                body.model_dump(exclude_none=True),
            )
        )
        conn.commit()
        return _goals_out(conn)

    @app.post("/api/goals/{goal_id}/update", response_model=GoalsOut, dependencies=auth)
    def update_goal_api(goal_id: str, body: GoalUpdateIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "update_goal",
                {"goal_id": goal_id, **body.model_dump(exclude_none=True)},
            )
        )
        conn.commit()
        return _goals_out(conn)

    @app.post("/api/goals/{goal_id}/contributions", response_model=GoalsOut, dependencies=auth)
    def goal_contribution_api(goal_id: str, body: GoalContributionIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "record_goal_contribution",
                {"goal_id": goal_id, "amount_paise": body.amount_paise},
            )
        )
        conn.commit()
        return _goals_out(conn)

    def _scenario(s: WhatIfIn) -> dict[str, Any]:
        now = now_utc(state.clock).astimezone(IST)
        nxt = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        return {**s.model_dump(), "start_month": f"{nxt.year:04d}-{nxt.month:02d}"}

    @app.post("/api/whatif", response_model=WhatIfOut, dependencies=auth)
    def whatif(body: WhatIfIn, conn: Conn) -> WhatIfOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "run_whatif",
                {"scenario": _scenario(body), "horizon_months": body.months},
            )
        )
        conn.commit()
        return WhatIfOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.post("/api/whatif/compare", response_model=CompareOut, dependencies=auth)
    def compare(body: CompareIn, conn: Conn) -> CompareOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "compare_options",
                {
                    "scenarios": [_scenario(s) for s in body.scenarios],
                    "horizon_months": max(s.months for s in body.scenarios),
                },
            )
        )
        conn.commit()
        return CompareOut.model_validate(out.model_dump())  # type: ignore[attr-defined]
