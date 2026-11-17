"""Understanding, the personal model, budgets, subscriptions, splits and check-ins."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from copilot.api.contracts import (
    BudgetMoveIn,
    CheckinResponseIn,
    ProfileValueIn,
    SplitExpenseIn,
    SplitGroupIn,
    SplitSettleIn,
    SubscriptionNoteIn,
    UnderstandAnswerIn,
)
from copilot.api.deps import Conn, auth
from copilot.api.helpers import call_tool
from copilot.api.state import ApiState


def register(app: FastAPI, state: ApiState) -> None:
    # -- Understanding, the personal model and check-ins ---------------------------------------
    @app.post("/api/understand/run", dependencies=auth)
    def understand_run(conn: Conn) -> Any:
        """Categorise what is not yet answered (the same cascade the agent runs)."""
        return call_tool(state, conn, "run_cascade", {}, actor="agent")

    @app.get("/api/understand/why/{transaction_id}", dependencies=auth)
    def understand_why(transaction_id: str, conn: Conn) -> Any:
        """Why a payment has the category it has: stage, confidence, what was considered."""
        return call_tool(state, conn, "explain_decision", {"transaction_id": transaction_id})

    @app.get("/api/understand/questions", dependencies=auth)
    def understand_questions(conn: Conn) -> Any:
        return call_tool(state, conn, "entity_questions", {})

    @app.post("/api/understand/answer", dependencies=auth)
    def understand_answer(body: UnderstandAnswerIn, conn: Conn) -> Any:
        return call_tool(state, conn, "answer_shop", body.model_dump(exclude_none=True))

    @app.get("/api/checkins", dependencies=auth)
    def checkins_list(conn: Conn) -> Any:
        return call_tool(state, conn, "list_checkins", {})

    @app.post("/api/checkins/run", dependencies=auth)
    def checkins_run(conn: Conn) -> Any:
        """Ask the agent now: it may well say there is nothing worth saying."""
        return call_tool(state, conn, "run_checkin", {"ignore_timing": True})

    @app.post("/api/checkins/{checkin_id}/respond", dependencies=auth)
    def checkins_respond(checkin_id: str, body: CheckinResponseIn, conn: Conn) -> Any:
        return call_tool(
            state, conn, "respond_checkin", {"checkin_id": checkin_id, "response": body.response}
        )

    @app.get("/api/profile", dependencies=auth)
    def profile_read(conn: Conn) -> Any:
        return call_tool(state, conn, "profile_get", {})

    # before /api/profile/{field}, which would otherwise take "suggest" as a field name
    @app.post("/api/profile/suggest", dependencies=auth)
    def profile_suggest(conn: Conn) -> Any:
        return call_tool(state, conn, "profile_infer", {}, actor="agent")

    @app.post("/api/profile/{field}", dependencies=auth)
    def profile_write(field: str, body: ProfileValueIn, conn: Conn) -> Any:
        return call_tool(state, conn, "profile_set", {"field": field, "value": body.value})

    @app.post("/api/profile/{field}/confirm", dependencies=auth)
    def profile_confirm_route(field: str, conn: Conn) -> Any:
        return call_tool(state, conn, "profile_confirm", {"field": field})

    @app.post("/api/profile/{field}/forget", dependencies=auth)
    def profile_forget(field: str, conn: Conn) -> Any:
        return call_tool(state, conn, "profile_delete", {"field": field})

    @app.get("/api/budget/proposal", dependencies=auth)
    def budget_proposal(conn: Conn) -> Any:
        return call_tool(state, conn, "budget_propose", {})

    @app.post("/api/budget/apply", dependencies=auth)
    def budget_apply_route(conn: Conn) -> Any:
        return call_tool(state, conn, "budget_apply", {})

    @app.get("/api/budget/replan", dependencies=auth)
    def budget_replan_route(conn: Conn) -> Any:
        return call_tool(state, conn, "budget_replan", {})

    @app.post("/api/budget/move", dependencies=auth)
    def budget_move_route(body: BudgetMoveIn, conn: Conn) -> Any:
        return call_tool(state, conn, "budget_move", body.model_dump())

    @app.get("/api/subscriptions", dependencies=auth)
    def subscriptions_read(conn: Conn) -> Any:
        return call_tool(state, conn, "list_subscriptions", {})

    @app.post("/api/subscriptions/{series_id}/mark", dependencies=auth)
    def subscriptions_mark(series_id: str, body: SubscriptionNoteIn, conn: Conn) -> Any:
        return call_tool(
            state, conn, "mark_subscription", {"series_id": series_id, "note": body.note}
        )

    @app.post("/api/splits", dependencies=auth)
    def splits_create(body: SplitGroupIn, conn: Conn) -> Any:
        return call_tool(state, conn, "create_split_group", body.model_dump())

    @app.get("/api/splits/{group_id}", dependencies=auth)
    def splits_view(group_id: str, conn: Conn) -> Any:
        return call_tool(state, conn, "split_balances", {"group_id": group_id})

    @app.post("/api/splits/{group_id}/expenses", dependencies=auth)
    def splits_add(group_id: str, body: SplitExpenseIn, conn: Conn) -> Any:
        return call_tool(
            state,
            conn,
            "add_split_expense",
            {"group_id": group_id, **body.model_dump(exclude_none=True)},
        )

    @app.post("/api/splits/{group_id}/settlements", dependencies=auth)
    def splits_settle(group_id: str, body: SplitSettleIn, conn: Conn) -> Any:
        return call_tool(
            state,
            conn,
            "record_split_settlement",
            {"group_id": group_id, **body.model_dump(exclude_none=True)},
        )

    @app.get("/api/capture/stream", dependencies=auth)
    async def capture_stream(request: Request, once: bool = False) -> StreamingResponse:
        """Server-sent events: a prompt appears the moment the ask policy says ask."""
        from copilot.api.capture_stream import capture_events

        return StreamingResponse(
            capture_events(state, request, once=once),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
