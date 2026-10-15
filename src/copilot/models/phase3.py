"""
Typed Pydantic domain models for Phase 3 Advanced Financial Copilot (PLAN_PHASE3 Stage 3.1).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------------------------
# 1. Commitments & Occurrences
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 2. Goals & Progress
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 3. Virtual Buckets & Ledger
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 4. Financial Calendar
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 5. Investment Readiness
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 6. Contributions & Trade-offs
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 7. Behavioural Memory
# ---------------------------------------------------------------------------------------------
class MemoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    kind: Literal[
        "recurring_pattern",
        "contextual_exception",
        "advice_feedback",
        "preference",
        "merchant_habit",
        "experiment_outcome",
    ]
    subject_key: str
    statement_json: dict[str, Any]
    source: Literal["observed", "user_stated", "feedback", "capture_label"]
    status: Literal["candidate", "active", "stale", "retired", "rejected", "forgotten"]
    prior_bp: int = Field(ge=0, le=10000)
    user_confirmed: bool = False
    confidence_bp: int = 0
    created_at: str
    last_evidence_at: str | None = None
    last_confirmed_at: str | None = None


class MemoryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    memory_id: str
    polarity: Literal["supports", "contradicts"]
    ref_kind: Literal[
        "txn",
        "advice",
        "audit_event",
        "anomaly",
        "investigation",
        "capture_label",
        "review",
        "experiment",
    ]
    ref_id: str
    observed_at: str
    weight_bp: int = Field(ge=0, le=10000)
    created_at: str


class UserPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    key: str
    value_json: Any
    updated_at: str


# ---------------------------------------------------------------------------------------------
# 8. Multi-Agent & Orchestration
# ---------------------------------------------------------------------------------------------
class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: int
    description: str
    inputs: dict[str, str] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    narration_template: str
    eval_cases: str


class SkillRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    task_id: str
    skill_name: str
    skill_version: int
    inputs_json: dict[str, Any]
    status: Literal["running", "ok", "failed", "cannot_run"]
    outputs_json: dict[str, Any]
    started_at: str
    finished_at: str | None = None


class SubQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["cashflow", "goals", "readiness", "behaviour", "coaching", "experiments"]
    question_kind: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    task_id: str
    agent_role: str
    sub_question_json: dict[str, Any]
    status: Literal["ok", "partial", "failed", "timeout"]
    findings_json: list[dict[str, Any]]
    gaps_json: list[str]
    error_code: str | None = None
    duration_ms: int = Field(ge=0)
    created_at: str


class Reflection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    task_id: str
    round: int = Field(ge=0)
    critique_codes: list[str]
    source: Literal["deterministic", "llm_critic"]
    revised: bool
    outcome: Literal["fixed", "unchanged", "gave_up"]
    created_at: str


# ---------------------------------------------------------------------------------------------
# 9. Context & Observability
# ---------------------------------------------------------------------------------------------
class ContextManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    call_id: str
    task_id: str
    purpose: str
    budget_tokens: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    included: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    redactions_count: int = Field(default=0, ge=0)
    prompt_version: str
    created_at: str


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    kind: Literal["node", "tool", "llm", "job", "skill", "specialist", "mcp"]
    name: str
    started_at: str
    duration_ms: int = Field(ge=0)
    status: Literal["ok", "error"]
    error_code: str | None = None
    attrs: dict[str, Any]
    created_at: str


class ScheduledJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    job_kind: str
    schedule: str
    next_run_at: str
    lease_owner: str | None = None
    lease_until: str | None = None
    last_status: str | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    enabled: bool = True
    updated_at: str


class JobRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    job_id: str
    started_at: str
    finished_at: str | None = None
    status: Literal["ok", "failed", "skipped", "dead_letter"]
    attempt: int = Field(ge=1)
    error_code: str | None = None
    summary_json: dict[str, Any]
    created_at: str


class FeedbackStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    subject_kind: Literal["alert_kind", "advice_kind", "challenge_template"]
    subject_key: str
    alpha_milli: int = Field(default=2000, gt=0)
    beta_milli: int = Field(default=2000, gt=0)
    updated_at: str
