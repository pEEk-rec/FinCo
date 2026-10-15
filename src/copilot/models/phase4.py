"""
Domain and data models for Phase 4 (PLAN_PHASE4 Section 4, Section 5).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------------------------
# Structured Sub-models
# ---------------------------------------------------------------------------------------------
class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervention: str
    metric: str
    direction: Literal["lower", "higher"]
    target: int


class MetricDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    weekdays_only: bool = False


class Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int
    window_values: list[int]
    median: int
    low: int
    high: int
    excluded_windows: list[dict[str, Any]] = Field(default_factory=list)


class IntegrityNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recategorized_count: int = 0
    recategorized_amount_paise: int = 0
    late_txns_count: int = 0
    late_txns_amount_paise: int = 0
    exceptions_count: int = 0
    confirmation_required: bool = False


# ---------------------------------------------------------------------------------------------
# Core Table Models
# ---------------------------------------------------------------------------------------------
ExperimentStatus = Literal[
    "offered", "active", "paused", "completed", "abandoned", "expired", "reviewed"
]
ExperimentOrigin = Literal["user", "offer", "goal_decomposition"]


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    title: str
    template_code: str | None = None
    hypothesis_json: dict[str, Any]
    metric_def_json: dict[str, Any]
    params_json: dict[str, Any]
    difficulty: str
    window_start: str
    window_end: str
    baseline_json: dict[str, Any]
    target_value: int
    status: ExperimentStatus
    origin: ExperimentOrigin
    offer_id: str | None = None
    goal_id: str | None = None
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None


PaceStatus = Literal["ahead", "on_pace", "behind", "insufficient"]
CheckinUserResponse = Literal["going_well", "hard", "want_to_pause", "skip"]


class ExperimentCheckin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    experiment_id: str
    checkin_date: str
    observed_value: int
    pace_status: PaceStatus
    user_response: CheckinUserResponse | None = None
    created_at: str


ReviewOutcome = Literal[
    "beyond_usual_range", "within_usual_range", "above_usual_range", "no_baseline"
]


class ExperimentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    experiment_id: str
    observed_value: int
    outcome: ReviewOutcome
    rank_p_bp: int
    effect_value: int
    target_met: bool
    integrity_json: dict[str, Any]
    data_quality_json: dict[str, Any]
    user_difficulty: int | None = None
    user_helpful: bool | None = None
    user_would_repeat: bool | None = None
    created_at: str


ProposalKind = Literal[
    "ease_target", "extend", "pause", "resume", "raise_target_optional", "end_early"
]
ProposalStatus = Literal["proposed", "accepted", "rejected", "expired", "auto_applied_pause"]


class AdjustmentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    experiment_id: str
    kind: ProposalKind
    reason_code: str
    params_json: dict[str, Any]
    status: ProposalStatus
    created_at: str
    decided_at: str | None = None


OfferStatus = Literal["shown", "accepted", "dismissed", "expired"]


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    week_start: str
    template_code: str
    difficulty: Literal["easy", "medium", "hard"]
    params_json: dict[str, Any]
    rank: int
    propensity_bp: int
    policy_version: str
    rng_seed: int
    reason_json: dict[str, Any]
    status: OfferStatus
    created_at: str
    decided_at: str | None = None


class XpEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    rule_code: str
    points: int
    ref_kind: str
    ref_id: str
    period_day: str
    created_at: str


class BadgeAward(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    badge_code: str
    awarded_at: str
    evidence_json: dict[str, Any]


class StreakFreeze(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    streak_code: str
    from_date: str
    to_date: str
    reason: Literal["grace", "exception"]
    created_at: str


# ---------------------------------------------------------------------------------------------
# Derived Models (Progress, Personal Bests)
# ---------------------------------------------------------------------------------------------
class PersonalBest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_code: str
    window_length_days: int
    best_value: int
    achieved_at: str
    experiment_id: str | None = None
    #: What the best is about (the categories or merchants), so a dining best is never set
    #: against a shopping one. Empty when the metric has no categories.
    scope: str = ""


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_xp: int
    level_number: int
    level_name: str
    xp_in_level: int
    xp_for_next_level: int | None
    badges: list[BadgeAward]
    personal_bests: list[PersonalBest]
    active_streaks: dict[str, int]


class ExperimentProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_value: int
    target_value: int
    pace_status: PaceStatus
    elapsed_days: int
    total_days: int
    checkins_count: int


# ---------------------------------------------------------------------------------------------
# Goal Decomposition Models
# ---------------------------------------------------------------------------------------------
class DecomposedExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_code: str
    title: str
    metric_code: str
    categories: list[str]
    duration_days: int
    difficulty: Literal["easy", "medium", "hard"]
    target_value: int
    expected_effect_paise: int
    gap_share_pct: int
    statement: str


class GoalDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    goal_name: str
    target_paise: int
    current_paise: int
    deficit_paise: int
    required_monthly_paise: int | None
    candidate_experiments: list[DecomposedExperiment]
