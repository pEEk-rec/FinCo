"""The monthly review and its advice: generate, explain, approve or reject."""

from fastapi import FastAPI, Query

from copilot.api.contracts import (
    AdviceDecisionIn,
    AdviceDecisionOut,
    AdviceExplanation,
    GenerateReviewIn,
    MonthlyReviewOut,
    ReviewVersion,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import not_found, unwrap
from copilot.api.helpers import (
    json_list,
    parse_period,
    refresh_advice_status,
)
from copilot.api.services import draft_month_advice
from copilot.api.state import ApiState
from copilot.db.repo import (
    get_monthly_review,
    list_monthly_reviews,
)
from copilot.review.models import MonthlyReviewData
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- monthly review and advice -------------------------------------------------------------
    @app.get("/api/monthly-reviews/{period}", response_model=MonthlyReviewOut, dependencies=auth)
    def monthly_review(
        conn: Conn, period: str, version: int | None = Query(None, ge=1)
    ) -> MonthlyReviewOut:
        year, month = parse_period(period)
        versions = [
            ReviewVersion(version=r.version, generated_at=r.created_at)
            for r in list_monthly_reviews(conn, state.user_id, year, month)
        ]
        row = get_monthly_review(conn, state.user_id, year, month, version)
        review = None
        if row is not None:
            raw = row.review_json
            review = (
                MonthlyReviewData.model_validate_json(raw)
                if isinstance(raw, str)
                else MonthlyReviewData.model_validate(raw)
            )
            review = refresh_advice_status(conn, review)
        return MonthlyReviewOut(period=period, versions=versions, review=review)

    @app.post("/api/monthly-reviews", response_model=MonthlyReviewOut, dependencies=auth)
    def generate_review(body: GenerateReviewIn, conn: Conn) -> MonthlyReviewOut:
        year, month = parse_period(body.period)
        draft_month_advice(state, conn, year, month)
        unwrap(
            execute_tool(
                state.context(conn, "user"), "build_monthly_review", {"year": year, "month": month}
            )
        )
        conn.commit()
        return monthly_review(conn, body.period, None)

    @app.get("/api/advice/{advice_id}", response_model=AdviceExplanation, dependencies=auth)
    def advice_explanation(advice_id: str, conn: Conn) -> AdviceExplanation:
        r = conn.execute(
            "SELECT * FROM advice_items WHERE id = ? AND user_id = ?", (advice_id, state.user_id)
        ).fetchone()
        if r is None:
            raise not_found("Advice not found.")
        return AdviceExplanation(
            id=r["id"],
            text=r["text"],
            status=r["status"],
            origin=r["origin"],
            confidence_label=r["confidence_label"],
            evidence=json_list(r["evidence_json"]),
            calculations=json_list(r["calculations_json"]),
            assumptions=json_list(r["assumptions_json"]),
            tools_used=json_list(r["tools_used_json"]),
            memories=json_list(r["memories_json"]),
            simulation_id=r["simulation_id"],
        )

    @app.post(
        "/api/advice/{advice_id}/decision", response_model=AdviceDecisionOut, dependencies=auth
    )
    def decide_advice(advice_id: str, body: AdviceDecisionIn, conn: Conn) -> AdviceDecisionOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "decide_advice",
                {"advice_id": advice_id, "decision": body.decision},
            )
        )
        conn.commit()
        return AdviceDecisionOut.model_validate(out.model_dump())  # type: ignore[attr-defined]
