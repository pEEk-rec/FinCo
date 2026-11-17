"""Experiments, challenges, offers, adjustments, progress and the goal gap."""

from typing import Any

from fastapi import FastAPI

from copilot.api.coach_view import CoachView, build_coach_view
from copilot.api.contracts import (
    AdjustmentRejectIn,
    ExperimentAbandonIn,
    ExperimentCheckinIn,
    ExperimentDesignIn,
    ExperimentStartIn,
    OfferDismissIn,
    OfferSuggestIn,
    ReviewFeedbackIn,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import ApiError, ApiException, not_found, unwrap
from copilot.api.helpers import dump_data
from copilot.api.state import ApiState
from copilot.common.timeutil import now_utc
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- Experiments ---------------------------------------------------------------------------
    @app.get("/api/experiments", dependencies=auth)
    def list_experiments_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_engagement import list_experiments as repo_list_experiments

        exps = repo_list_experiments(conn, user_id=state.user_id, status=status)
        return [dump_data(e) for e in exps]

    @app.get("/api/experiments/{id}", dependencies=auth)
    def get_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_experiment",
                {"experiment_id": id},
            )
        )
        return dump_data(out)

    @app.get("/api/experiments/{id}/progress", dependencies=auth)
    def experiment_progress_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "experiment_progress",
                {"experiment_id": id},
            )
        )
        return dump_data(out)

    @app.post("/api/experiments/design", dependencies=auth)
    def design_experiment_api(body: ExperimentDesignIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "design_experiment",
                body.model_dump(),
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/start", dependencies=auth)
    def start_experiment_api(body: ExperimentStartIn, conn: Conn) -> dict[str, Any]:
        if body.experiment_id:
            exp_id = body.experiment_id
        else:
            if not body.title or not body.metric_code:
                raise ApiException(
                    422,
                    ApiError(
                        code="INVALID_INPUT",
                        message="title and metric_code required when experiment_id is not provided",
                    ),
                )
            des_res = unwrap(
                execute_tool(
                    state.context(conn, "user"),
                    "design_experiment",
                    {
                        "title": body.title,
                        "metric_code": body.metric_code,
                        "template_code": body.template_code,
                        "categories": body.categories,
                        "merchants": body.merchants,
                        "duration_days": body.duration_days,
                        "difficulty": body.difficulty,
                        "target_value": body.target_value,
                        "baseline_median": body.baseline_median,
                        "start_date": body.start_date,
                        "goal_id": body.goal_id,
                        "rationale": body.rationale,
                        "origin": body.origin,
                    },
                )
            )
            exp_id = getattr(getattr(des_res, "experiment", des_res), "id", None)
            if not exp_id and isinstance(des_res, dict):
                exp_id = des_res.get("experiment", {}).get("id")

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "start_experiment",
                {"experiment_id": exp_id},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/{id}/pause", dependencies=auth)
    def pause_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "pause_experiment",
                {"experiment_id": id},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/{id}/resume", dependencies=auth)
    def resume_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "resume_experiment",
                {"experiment_id": id},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/{id}/abandon", dependencies=auth)
    def abandon_experiment_api(id: str, body: ExperimentAbandonIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "abandon_experiment",
                {"experiment_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/{id}/checkin", dependencies=auth)
    def checkin_experiment_api(id: str, body: ExperimentCheckinIn, conn: Conn) -> dict[str, Any]:
        import uuid

        from copilot.common.timeutil import IST, now_utc, to_utc_iso
        from copilot.db.repo_engagement import get_experiment, insert_experiment_checkin
        from copilot.db.repo_engagement import list_experiment_checkins as repo_list_checkins
        from copilot.engagement.experiments import calculate_pace
        from copilot.engagement.experiments import create_checkins as core_create_checkins
        from copilot.engagement.metrics import calculate_metric
        from copilot.models.engagement import ExperimentCheckin

        checkin_id = id if id.startswith("chk_") else None
        if not checkin_id:
            chks = repo_list_checkins(conn, user_id=state.user_id, experiment_id=id)
            if chks:
                checkin_id = chks[-1].id
            else:
                created = core_create_checkins(conn, user_id=state.user_id, clock=state.clock)
                matching = [c for c in created if c.experiment_id == id]
                if matching:
                    checkin_id = matching[0].id
                else:
                    exp = get_experiment(conn, state.user_id, id)
                    if exp is not None and exp.status == "active":
                        now_dt = state.clock or now_utc()
                        cur_date_str = now_dt.astimezone(IST).date().isoformat()
                        obs = calculate_metric(
                            conn,
                            state.user_id,
                            metric_code=exp.metric_def_json["metric_code"],
                            start_date=exp.window_start,
                            end_date=cur_date_str,
                            params=exp.params_json,
                        )
                        pace = calculate_pace(
                            observed_value=obs,
                            target_value=exp.target_value,
                            start_date=exp.window_start,
                            end_date=exp.window_end,
                            as_of_date=cur_date_str,
                            metric_code=exp.metric_def_json["metric_code"],
                        )
                        chk = ExperimentCheckin(
                            id=f"chk_{uuid.uuid4().hex[:12]}",
                            user_id=state.user_id,
                            experiment_id=exp.id,
                            checkin_date=cur_date_str,
                            observed_value=obs,
                            pace_status=pace,
                            created_at=to_utc_iso(now_dt),
                        )
                        insert_experiment_checkin(conn, chk)
                        checkin_id = chk.id
                    else:
                        raise not_found(f"Checkin for {id} not found")

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "answer_checkin",
                {"checkin_id": checkin_id, "response": body.user_response or "going_well"},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.get("/api/experiments/{id}/review", dependencies=auth)
    def get_review_api(id: str, conn: Conn) -> dict[str, Any]:
        from copilot.db.repo_engagement import get_experiment as repo_get_experiment
        from copilot.db.repo_engagement import get_experiment_review as repo_get_experiment_review
        from copilot.engagement.review_wording import describe_review

        rev = repo_get_experiment_review(conn, user_id=state.user_id, experiment_id=id)
        if not rev:
            raise not_found("Review", id)
        data = dump_data(rev)
        exp = repo_get_experiment(conn, state.user_id, id)
        if exp is not None:
            w = describe_review(exp, rev)
            data["wording"] = {
                "headline": w.headline,
                "details": w.details,
                "needs_confirmation": w.needs_confirmation,
                "confirmation_prompt": w.confirmation_prompt,
            }
        return data

    @app.post("/api/experiments/{id}/confirm-integrity", dependencies=auth)
    def confirm_integrity_api(id: str, conn: Conn) -> dict[str, Any]:
        """The user vouches that recategorised payments in the window were genuine."""
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "confirm_review_integrity", {"experiment_id": id}
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/experiments/{id}/feedback", dependencies=auth)
    def review_feedback_api(id: str, body: ReviewFeedbackIn, conn: Conn) -> dict[str, Any]:
        from copilot.db.repo_engagement import get_experiment_review as repo_get_experiment_review

        review_id = id if id.startswith("rev_") else None
        if not review_id:
            rev = repo_get_experiment_review(conn, user_id=state.user_id, experiment_id=id)
            if not rev:
                raise not_found(f"Review for experiment {id} not found")
            review_id = rev.id

        diff = (
            body.difficulty_rating if body.difficulty_rating is not None else body.user_difficulty
        )  # noqa: E501
        repeat = body.would_repeat if body.would_repeat is not None else body.user_would_repeat

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "submit_review_feedback",
                {
                    "review_id": review_id,
                    "difficulty_rating": diff,
                    "user_helpful": body.user_helpful,
                    "would_repeat": repeat,
                    "feedback_text": body.feedback_text,
                },
            )
        )
        conn.commit()
        return dump_data(out)

    # -- Challenges & Offers -------------------------------------------------------------------
    @app.get("/api/challenges/offers", dependencies=auth)
    def list_offers_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_offers",
                {"status": status},
            )
        )
        return dump_data(out.offers if hasattr(out, "offers") else out)

    @app.post("/api/challenges/offers/suggest", dependencies=auth)
    def suggest_offers_api(body: OfferSuggestIn, conn: Conn) -> dict[str, Any]:
        ctx = state.context(conn, "user")
        ctx.llm_client = state.get_llm()  # None when no model is configured: rules only
        out = unwrap(execute_tool(ctx, "suggest_challenges", body.model_dump()))
        conn.commit()
        return dump_data(out)

    @app.post("/api/challenges/offers/{id}/accept", dependencies=auth)
    def accept_offer_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "accept_offer",
                {"offer_id": id},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/challenges/offers/{id}/dismiss", dependencies=auth)
    def dismiss_offer_api(id: str, body: OfferDismissIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "dismiss_offer",
                {"offer_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return dump_data(out)

    # -- the screens' read model ---------------------------------------------------------------
    @app.get("/api/coach", response_model=CoachView, dependencies=auth)
    def coach_api(conn: Conn) -> CoachView:
        return build_coach_view(conn, state.user_id, clock=now_utc(state.clock))

    # -- Adjustments ---------------------------------------------------------------------------
    @app.get("/api/adjustments", dependencies=auth)
    def list_adjustments_api(conn: Conn, experiment_id: str | None = None) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_adjustments",
                {"experiment_id": experiment_id},
            )
        )
        return dump_data(out.proposals if hasattr(out, "proposals") else out)

    @app.post("/api/adjustments/{id}/accept", dependencies=auth)
    def accept_adjustment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "accept_adjustment",
                {"proposal_id": id},
            )
        )
        conn.commit()
        return dump_data(out)

    @app.post("/api/adjustments/{id}/reject", dependencies=auth)
    def reject_adjustment_api(id: str, body: AdjustmentRejectIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "reject_adjustment",
                {"proposal_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return dump_data(out)

    # -- Progress & Gamification ---------------------------------------------------------------
    @app.get("/api/progress", dependencies=auth)
    def progress_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_user_progress",
                {},
            )
        )
        return dump_data(out)

    @app.get("/api/progress/bests", dependencies=auth)
    def personal_bests_api(conn: Conn) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_personal_bests",
                {},
            )
        )
        return dump_data(out.personal_bests if hasattr(out, "personal_bests") else out)

    # -- Goal Gap Decomposition ----------------------------------------------------------------
    @app.post("/api/goals/{id}/decompose", dependencies=auth)
    def decompose_goal_api(id: str, conn: Conn) -> dict[str, Any]:
        from copilot.engagement.challenges import decompose_goal_gap

        decomp = decompose_goal_gap(conn, user_id=state.user_id, goal_id=id, clock=state.clock)
        return dump_data(decomp)
