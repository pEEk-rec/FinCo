"""
Tool specifications and handlers for financial experiments (PLAN_PHASE4 Section 5.3).

Governance rules:
- design_experiment, start_experiment, pause_experiment,
  resume_experiment, abandon_experiment, answer_checkin,
  submit_review_feedback:
    SideEffect.WRITE_LOGICAL. Allowed for user, denied or requires approval for agent.
    Never planner-selectable.
- get_experiment, list_experiments, experiment_progress:
    SideEffect.READ. Allowed for all actors, planner-selectable.
- create_checkins, create_due_reviews:
    SideEffect.WRITE_LOGICAL. Allowed for agent and user (runtime maintenance jobs).
    Never planner-selectable.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from copilot.audit.events import record_event
from copilot.core.experiments import (
    abandon_experiment as core_abandon,
)
from copilot.core.experiments import (
    answer_checkin as core_answer_checkin,
)
from copilot.core.experiments import (
    create_checkins as core_create_checkins,
)
from copilot.core.experiments import (
    create_due_reviews as core_create_due_reviews,
)
from copilot.core.experiments import (
    design_experiment as core_design,
)
from copilot.core.experiments import (
    get_experiment_progress as core_get_progress,
)
from copilot.core.experiments import (
    pause_experiment as core_pause,
)
from copilot.core.experiments import (
    resume_experiment as core_resume,
)
from copilot.core.experiments import (
    start_experiment as core_start,
)
from copilot.core.experiments import (
    submit_review_feedback as core_submit_feedback,
)
from copilot.core.learning_loop import process_post_review_learning, update_template_posterior
from copilot.core.rewards import confirm_review_integrity as core_confirm_integrity
from copilot.db.repo_phase4 import (
    get_experiment as repo_get_experiment,
)
from copilot.db.repo_phase4 import (
    get_experiment_review as repo_get_experiment_review,
)
from copilot.db.repo_phase4 import (
    get_experiment_review_by_id as repo_get_review_by_id,
)
from copilot.db.repo_phase4 import (
    list_experiments as repo_list_experiments,
)
from copilot.models.phase4 import (
    CheckinUserResponse,
    Experiment,
    ExperimentCheckin,
    ExperimentProgress,
    ExperimentReview,
)
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# ---------------------------------------------------------------------------------------------
# 1. design_experiment
# ---------------------------------------------------------------------------------------------
class DesignExperimentInput(ToolInput):
    """Input for designing a financial experiment."""

    metric_code: str
    template_code: str | None = None
    target_value: int | None = None
    baseline_median: int | None = None
    rationale: str | None = None
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    duration_days: int = Field(default=14, ge=7, le=56)
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    intervention: str | None = None
    goal_id: str | None = None
    title: str | None = None
    start_date: str | None = None
    origin: Literal["template", "llm", "user"] = "user"


class DesignExperimentOutput(ToolOutput):
    experiment: Experiment


def design_experiment_handler(ctx: "ExecutionContext", **kwargs) -> DesignExperimentOutput:
    params = DesignExperimentInput.model_validate(kwargs)
    exp = core_design(
        conn=ctx.conn,
        user_id=ctx.user_id,
        template_code=params.template_code,
        params=params.model_dump(),
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="experiment_designed",
        reason=f"Experiment '{exp.id}' designed by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="experiment",
        entity_id=exp.id,
        after_data=exp.model_dump(mode="json"),
        metadata={"metric_code": params.metric_code, "difficulty": params.difficulty},
    )
    return DesignExperimentOutput(experiment=exp)


# ---------------------------------------------------------------------------------------------
# 2. start_experiment
# ---------------------------------------------------------------------------------------------
class StartExperimentInput(ToolInput):
    experiment_id: str


class StartExperimentOutput(ToolOutput):
    experiment: Experiment


def start_experiment_handler(ctx: "ExecutionContext", **kwargs) -> StartExperimentOutput:
    params = StartExperimentInput.model_validate(kwargs)
    exp = core_start(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=params.experiment_id,
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="experiment_started",
        reason=f"Experiment '{exp.id}' started by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="experiment",
        entity_id=exp.id,
        after_data=exp.model_dump(mode="json"),
        metadata={"window_start": exp.window_start, "window_end": exp.window_end},
    )
    return StartExperimentOutput(experiment=exp)


# ---------------------------------------------------------------------------------------------
# 3. pause_experiment
# ---------------------------------------------------------------------------------------------
class PauseExperimentInput(ToolInput):
    experiment_id: str
    reason: str = "user_paused"


class PauseExperimentOutput(ToolOutput):
    experiment: Experiment


def pause_experiment_handler(ctx: "ExecutionContext", **kwargs) -> PauseExperimentOutput:
    params = PauseExperimentInput.model_validate(kwargs)
    exp = core_pause(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=params.experiment_id,
        reason=params.reason,
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="experiment_paused",
        reason=f"Experiment '{exp.id}' paused: {params.reason}",
        run_id=ctx.run_id,
        entity_type="experiment",
        entity_id=exp.id,
        after_data=exp.model_dump(mode="json"),
        metadata={"reason": params.reason},
    )
    return PauseExperimentOutput(experiment=exp)


# ---------------------------------------------------------------------------------------------
# 4. resume_experiment
# ---------------------------------------------------------------------------------------------
class ResumeExperimentInput(ToolInput):
    experiment_id: str


class ResumeExperimentOutput(ToolOutput):
    experiment: Experiment


def resume_experiment_handler(ctx: "ExecutionContext", **kwargs) -> ResumeExperimentOutput:
    params = ResumeExperimentInput.model_validate(kwargs)
    exp = core_resume(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=params.experiment_id,
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="experiment_resumed",
        reason=f"Experiment '{exp.id}' resumed by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="experiment",
        entity_id=exp.id,
        after_data=exp.model_dump(mode="json"),
    )
    return ResumeExperimentOutput(experiment=exp)


# ---------------------------------------------------------------------------------------------
# 5. abandon_experiment
# ---------------------------------------------------------------------------------------------
class AbandonExperimentInput(ToolInput):
    experiment_id: str
    reason: str = "user_abandoned"


class AbandonExperimentOutput(ToolOutput):
    experiment: Experiment
    review: ExperimentReview


def abandon_experiment_handler(ctx: "ExecutionContext", **kwargs) -> AbandonExperimentOutput:
    params = AbandonExperimentInput.model_validate(kwargs)
    exp, rev = core_abandon(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=params.experiment_id,
        reason=params.reason,
        clock=ctx.clock,
    )
    update_template_posterior(
        ctx.conn,
        ctx.user_id,
        exp.template_code or "custom",
        "abandoned",
        clock=ctx.clock if isinstance(ctx.clock, datetime) else None,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="experiment_abandoned",
        reason=f"Experiment '{exp.id}' concluded early: {params.reason}",
        run_id=ctx.run_id,
        entity_type="experiment",
        entity_id=exp.id,
        after_data=exp.model_dump(mode="json"),
        metadata={"review_id": rev.id, "reason": params.reason},
    )
    return AbandonExperimentOutput(experiment=exp, review=rev)


# ---------------------------------------------------------------------------------------------
# 6. answer_checkin
# ---------------------------------------------------------------------------------------------
class AnswerCheckinInput(ToolInput):
    checkin_id: str
    response: CheckinUserResponse
    note: str | None = None


class AnswerCheckinOutput(ToolOutput):
    checkin: ExperimentCheckin


def answer_checkin_handler(ctx: "ExecutionContext", **kwargs) -> AnswerCheckinOutput:
    params = AnswerCheckinInput.model_validate(kwargs)
    chk = core_answer_checkin(
        conn=ctx.conn,
        user_id=ctx.user_id,
        checkin_id=params.checkin_id,
        response=params.response,
        note=params.note,
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="checkin_answered",
        reason=f"Checkin '{chk.id}' answered with '{params.response}'",
        run_id=ctx.run_id,
        entity_type="experiment_checkin",
        entity_id=chk.id,
        after_data=chk.model_dump(mode="json"),
        metadata={"response": params.response},
    )
    return AnswerCheckinOutput(checkin=chk)


# ---------------------------------------------------------------------------------------------
# 7. submit_review_feedback
# ---------------------------------------------------------------------------------------------
class SubmitReviewFeedbackInput(ToolInput):
    review_id: str | None = None
    experiment_id: str | None = None
    difficulty_rating: int | None = Field(default=None, ge=1, le=5)
    user_difficulty: int | None = Field(default=None, ge=1, le=5)
    user_helpful: bool | None = None
    would_repeat: bool | None = None
    user_would_repeat: bool | None = None
    feedback_text: str | None = None


class SubmitReviewFeedbackOutput(ToolOutput):
    review: ExperimentReview


def submit_review_feedback_handler(ctx: "ExecutionContext", **kwargs) -> SubmitReviewFeedbackOutput:
    params = SubmitReviewFeedbackInput.model_validate(kwargs)
    r_id = params.review_id
    if not r_id and params.experiment_id:
        rev_row = repo_get_experiment_review(
            ctx.conn, user_id=ctx.user_id, experiment_id=params.experiment_id
        )
        if not rev_row:
            raise ValueError(f"No review found for experiment: {params.experiment_id}")
        r_id = rev_row.id
    if not r_id:
        raise ValueError("Either review_id or experiment_id must be provided")

    diff = (
        params.difficulty_rating if params.difficulty_rating is not None else params.user_difficulty
    )
    rep = params.would_repeat if params.would_repeat is not None else params.user_would_repeat

    first_feedback = repo_get_review_by_id(ctx.conn, ctx.user_id, r_id)
    is_first = first_feedback is not None and (
        first_feedback.user_difficulty is None
        and first_feedback.user_helpful is None
        and first_feedback.user_would_repeat is None
    )
    rev = core_submit_feedback(
        conn=ctx.conn,
        user_id=ctx.user_id,
        review_id=r_id,
        difficulty_rating=diff,
        user_helpful=params.user_helpful,
        would_repeat=rep,
        feedback_text=params.feedback_text,
        clock=ctx.clock,
    )
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="review_feedback_submitted",
        reason=f"Feedback submitted for review '{rev.id}'",
        run_id=ctx.run_id,
        entity_type="experiment_review",
        entity_id=rev.id,
        after_data=rev.model_dump(mode="json"),
        metadata={
            "user_difficulty": params.difficulty_rating,
            "user_helpful": params.user_helpful,
            "would_repeat": params.would_repeat,
        },
    )
    if is_first:
        # The learning loop hears about an experiment once: the template's Beta posterior moves
        # and an experiment_outcome memory is written (PLAN_PHASE4 section 7).
        process_post_review_learning(
            ctx.conn,
            ctx.user_id,
            rev.experiment_id,
            clock=ctx.clock if isinstance(ctx.clock, datetime) else None,
        )
    return SubmitReviewFeedbackOutput(review=rev)


# ---------------------------------------------------------------------------------------------
# 7b. confirm_review_integrity
# ---------------------------------------------------------------------------------------------
class ConfirmReviewIntegrityInput(ToolInput):
    review_id: str | None = None
    experiment_id: str | None = None


class ConfirmReviewIntegrityOutput(ToolOutput):
    review: ExperimentReview


def confirm_review_integrity_handler(
    ctx: "ExecutionContext", **kwargs
) -> ConfirmReviewIntegrityOutput:
    """The user vouches that payments recategorised during the window were genuine corrections."""
    params = ConfirmReviewIntegrityInput.model_validate(kwargs)
    review_id = params.review_id
    if not review_id and params.experiment_id:
        found = repo_get_experiment_review(ctx.conn, ctx.user_id, params.experiment_id)
        review_id = found.id if found else None
    if not review_id:
        raise ValueError("Either review_id or experiment_id must identify a review")
    review = core_confirm_integrity(ctx.conn, ctx.user_id, review_id, clock=ctx.clock)
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="review_integrity_confirmed",
        reason="User confirmed that recategorised payments in the window were genuine.",
        run_id=ctx.run_id,
        entity_type="experiment_review",
        entity_id=review.id,
        after_data={"integrity": review.integrity_json},
        clock=ctx.clock,
    )
    return ConfirmReviewIntegrityOutput(review=review)


# ---------------------------------------------------------------------------------------------
# 8. get_experiment
# ---------------------------------------------------------------------------------------------
class GetExperimentInput(ToolInput):
    experiment_id: str


class GetExperimentOutput(ToolOutput):
    experiment: Experiment | None


def get_experiment_handler(ctx: "ExecutionContext", **kwargs) -> GetExperimentOutput:
    params = GetExperimentInput.model_validate(kwargs)
    exp = repo_get_experiment(ctx.conn, ctx.user_id, params.experiment_id)
    return GetExperimentOutput(experiment=exp)


# ---------------------------------------------------------------------------------------------
# 9. list_experiments
# ---------------------------------------------------------------------------------------------
class ListExperimentsInput(ToolInput):
    status: str | None = None


class ListExperimentsOutput(ToolOutput):
    experiments: list[Experiment]


def list_experiments_handler(ctx: "ExecutionContext", **kwargs) -> ListExperimentsOutput:
    params = ListExperimentsInput.model_validate(kwargs)
    exps = repo_list_experiments(ctx.conn, ctx.user_id, status=params.status)
    return ListExperimentsOutput(experiments=exps)


# ---------------------------------------------------------------------------------------------
# 10. experiment_progress
# ---------------------------------------------------------------------------------------------
class ExperimentProgressInput(ToolInput):
    experiment_id: str


class ExperimentProgressOutput(ToolOutput):
    progress: ExperimentProgress


def experiment_progress_handler(ctx: "ExecutionContext", **kwargs) -> ExperimentProgressOutput:
    params = ExperimentProgressInput.model_validate(kwargs)
    prog = core_get_progress(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=params.experiment_id,
        clock=ctx.clock,
    )
    return ExperimentProgressOutput(progress=prog)


# ---------------------------------------------------------------------------------------------
# 11. create_checkins (Runtime Job)
# ---------------------------------------------------------------------------------------------
class CreateCheckinsInput(ToolInput):
    pass


class CreateCheckinsOutput(ToolOutput):
    checkins: list[ExperimentCheckin]


def create_checkins_handler(ctx: "ExecutionContext", **kwargs) -> CreateCheckinsOutput:
    CreateCheckinsInput.model_validate(kwargs)
    chks = core_create_checkins(ctx.conn, ctx.user_id, clock=ctx.clock)
    if chks:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type="checkins_created",
            reason=f"Created {len(chks)} scheduled check-ins",
            run_id=ctx.run_id,
            entity_type="experiment_checkin",
            metadata={"count": len(chks), "checkin_ids": [c.id for c in chks]},
        )
    return CreateCheckinsOutput(checkins=chks)


# ---------------------------------------------------------------------------------------------
# 12. create_due_reviews (Runtime Job)
# ---------------------------------------------------------------------------------------------
class CreateDueReviewsInput(ToolInput):
    pass


class CreateDueReviewsOutput(ToolOutput):
    reviews: list[ExperimentReview]


def create_due_reviews_handler(ctx: "ExecutionContext", **kwargs) -> CreateDueReviewsOutput:
    CreateDueReviewsInput.model_validate(kwargs)
    revs = core_create_due_reviews(ctx.conn, ctx.user_id, clock=ctx.clock)
    if revs:
        record_event(
            ctx.conn,
            user_id=ctx.user_id,
            actor=ctx.actor,
            event_type="reviews_created",
            reason=f"Created {len(revs)} due experiment reviews",
            run_id=ctx.run_id,
            entity_type="experiment_review",
            metadata={"count": len(revs), "review_ids": [r.id for r in revs]},
        )
    return CreateDueReviewsOutput(reviews=revs)


# ---------------------------------------------------------------------------------------------
# Tool Specifications
# ---------------------------------------------------------------------------------------------
EXPERIMENT_TOOLS = (
    ToolSpec(
        name="design_experiment",
        description="Design a new financial experiment with deterministic baseline sizing.",
        input_model=DesignExperimentInput,
        output_model=DesignExperimentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=design_experiment_handler,
    ),
    ToolSpec(
        name="start_experiment",
        description="Start an offered financial experiment, freezing metric and baseline.",
        input_model=StartExperimentInput,
        output_model=StartExperimentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=start_experiment_handler,
    ),
    ToolSpec(
        name="pause_experiment",
        description="Pause an active financial experiment.",
        input_model=PauseExperimentInput,
        output_model=PauseExperimentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=pause_experiment_handler,
    ),
    ToolSpec(
        name="resume_experiment",
        description="Resume a paused financial experiment.",
        input_model=ResumeExperimentInput,
        output_model=ResumeExperimentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=resume_experiment_handler,
    ),
    ToolSpec(
        name="abandon_experiment",
        description="Abandon an experiment at any time without penalty or shame.",
        input_model=AbandonExperimentInput,
        output_model=AbandonExperimentOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=abandon_experiment_handler,
    ),
    ToolSpec(
        name="answer_checkin",
        description="Answer a scheduled weekly check-in for an active experiment.",
        input_model=AnswerCheckinInput,
        output_model=AnswerCheckinOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=answer_checkin_handler,
    ),
    ToolSpec(
        name="submit_review_feedback",
        description="Submit user feedback on difficulty and helpfulness for an experiment review.",
        input_model=SubmitReviewFeedbackInput,
        output_model=SubmitReviewFeedbackOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=submit_review_feedback_handler,
    ),
    ToolSpec(
        name="confirm_review_integrity",
        description="Confirm that transactions recategorised during the window were genuine.",
        input_model=ConfirmReviewIntegrityInput,
        output_model=ConfirmReviewIntegrityOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=confirm_review_integrity_handler,
    ),
    ToolSpec(
        name="get_experiment",
        description="Get financial experiment details by id.",
        input_model=GetExperimentInput,
        output_model=GetExperimentOutput,
        side_effect=SideEffect.READ,
        handler=get_experiment_handler,
    ),
    ToolSpec(
        name="list_experiments",
        description="List financial experiments for user with optional status filter.",
        input_model=ListExperimentsInput,
        output_model=ListExperimentsOutput,
        side_effect=SideEffect.READ,
        handler=list_experiments_handler,
    ),
    ToolSpec(
        name="experiment_progress",
        description="Get progress, current observed spend/metric, and pace for an experiment.",
        input_model=ExperimentProgressInput,
        output_model=ExperimentProgressOutput,
        side_effect=SideEffect.READ,
        handler=experiment_progress_handler,
    ),
    ToolSpec(
        name="create_checkins",
        description="Runtime maintenance job: generate due weekly check-ins.",
        input_model=CreateCheckinsInput,
        output_model=CreateCheckinsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_checkins_handler,
    ),
    ToolSpec(
        name="create_due_reviews",
        description="Runtime maintenance job: generate due reviews for finished experiments.",
        input_model=CreateDueReviewsInput,
        output_model=CreateDueReviewsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_due_reviews_handler,
    ),
)


def register_experiment_tools(register_fn=register) -> None:
    """Register all experiment tools into the global registry."""
    for spec in EXPERIMENT_TOOLS:
        register_fn(spec)
