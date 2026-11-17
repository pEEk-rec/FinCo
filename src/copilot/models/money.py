"""Typed records for commitments, goals progress, buckets, the cash calendar, readiness and
contribution plans.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CommitmentDirection = Literal["outflow", "inflow"]
CommitmentKind = Literal[
    "fee",
    "bill",
    "rent",
    "travel",
    "allowance",
    "income",
    "subscription",
    "emi",
    "investment_contribution",
    "goal_contribution",
    "other",
]
CommitmentCertainty = Literal["firm", "estimated"]
ScheduleKind = Literal["once", "weekly", "monthly", "yearly", "every_n_days"]
CommitmentSource = Literal["user", "suggested"]
CommitmentStatus = Literal["draft", "active", "paused", "ended", "rejected"]


class Commitment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    name: str
    direction: CommitmentDirection
    kind: CommitmentKind
    category_id: str | None = None
    amount_paise: int | None = None
    amount_min_paise: int | None = None
    amount_max_paise: int | None = None
    certainty: CommitmentCertainty
    schedule_kind: ScheduleKind
    schedule_json: dict[str, Any]
    start_date: str
    end_date: str | None = None
    recurring_series_id: str | None = None
    goal_id: str | None = None
    bucket_id: str | None = None
    source: CommitmentSource = "user"
    status: CommitmentStatus
    created_at: str
    updated_at: str


class Occurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commitment_id: str
    due_date: str
    amount_low_paise: int
    amount_expected_paise: int
    amount_high_paise: int
    direction: Literal["outflow", "inflow"]
    name: str
    category_id: str | None = None
    status: Literal["upcoming", "paid", "partially_paid", "overdue"] = "upcoming"


class CommitmentMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    commitment_id: str
    due_date: str
    txn_id: str
    match_method: Literal["series", "amount_date", "manual"]
    confidence_bp: int = Field(ge=0, le=10000)
    created_at: str


class GoalProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    user_id: str
    name: str
    target_paise: int
    current_paise: int
    remaining_paise: int
    percent_bp: int = Field(ge=0, le=10000)
    progress_source: Literal["manual", "bucket", "account"]
    linked_account_id: str | None = None
    required_monthly_paise: int
    months_remaining: int
    projected_completion_date: str | None = None
    projection_range: dict[str, str | None] = Field(default_factory=dict)
    status: Literal["on_track", "at_risk", "off_track", "completed", "unknown"]


class Bucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    name: str
    kind: Literal["spending", "goal", "commitment", "flexible"]
    period_policy: Literal["reset_monthly", "accumulate"]
    goal_id: str | None = None
    commitment_id: str | None = None
    status: Literal["active", "archived"] = "active"
    sort_order: int = 0
    created_at: str


class BucketAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    bucket_id: str
    amount_paise: int
    kind: Literal["allocate", "release", "reassign_in", "reassign_out", "rollover", "adjust"]
    period: str
    pair_id: str | None = None
    source: Literal["user", "approved_draft", "system_rollover"]
    draft_id: str | None = None
    created_at: str


class BucketBalance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_id: str
    name: str
    kind: str
    period: str
    allocated_paise: int
    spent_paise: int
    balance_paise: int
    status: Literal["ok", "low", "depleted"]


class AllocationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    liquid_balance_paise: int
    reserved_total_paise: int
    available_unallocated_paise: int
    over_allocated_by_paise: int
    buckets: list[BucketBalance]


class ReallocationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    from_bucket_id: str
    to_bucket_id: str
    amount_paise: int = Field(gt=0)
    reason_json: dict[str, Any]
    simulation_id: str | None = None
    status: Literal["draft", "approved", "rejected", "applied", "expired"]
    created_at: str
    decided_at: str | None = None
    applied_at: str | None = None


class CalendarDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    running_balance_expected_paise: int
    running_balance_low_paise: int
    running_balance_high_paise: int
    known_inflows_paise: int = 0
    known_outflows_paise: int = 0
    variable_spend_paise: int = 0
    variable_spend_status: Literal["forecast", "unknown"] = "forecast"
    occurrences: list[Occurrence] = Field(default_factory=list)
    below_buffer: bool = False


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence: Occurrence
    coverage_status: Literal["covered", "at_risk", "not_covered", "unknown"]
    balance_after_low_paise: int
    balance_after_expected_paise: int
    buffer_paise: int


class Calendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    today: str
    horizon_days: int
    start_balance_paise: int
    min_buffer_paise: int
    days: list[CalendarDay]
    coverage: list[Coverage]
    shortfall_ranges: list[dict[str, Any]]


class ReadinessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pass", "fail", "unknown"]
    value_text: str
    threshold_text: str
    what_would_change_it: str


class Readiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    assessed_on: str
    level: Literal["not_ready", "building", "ready_with_conditions", "ready", "insufficient_data"]
    criteria: list[ReadinessCriterion]
    numbers: dict[str, Any]
    config_version: str


class ContributionPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_name: str
    needed_paise: int
    funded_expected_paise: int
    funded_low_paise: int
    shortfall_paise: int
    verdict: Literal["fits", "fits_expected_only", "does_not_fit"]


class ContributionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    period_from: str
    horizon_months: int
    waterfall_order: list[str]
    steps: list[ContributionPlanStep]
    options: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class TradeoffAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    scenarios: list[dict[str, Any]]
    metrics: dict[str, Any]
    satisfies_all_constraints: bool


class TradeoffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    alternatives: list[TradeoffAlternative]
    best_alternative_name: str | None = None
    assumptions: dict[str, Any] = Field(default_factory=dict)
