"""
Pydantic data models for the Phase 2 Agentic Intelligence Layer (PLAN_PHASE2 Section 4).
"""

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt

from copilot.core.timeutil import normalize_utc_iso

Id = Annotated[str, Field(min_length=1)]
UtcTimestamp = Annotated[str, AfterValidator(normalize_utc_iso)]


class AgenticModel(BaseModel):
    """Base model rejecting extra attributes to prevent silent schema drift."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------------
# 1. Intent & Input Gate
# ---------------------------------------------------------------------------------------------
IntentType = Literal[
    "summarize_period",
    "explain_change",
    "investigate_anomaly",
    "check_budget",
    "forecast",
    "whatif_add_spend",
    "whatif_reduce_spend",
    "goal_check",
    "list_recurring",
    "alerts_overview",
    "goal_progress",
    "commitment_check",
    "calendar_lookahead",
    "bucket_status",
    "investment_readiness",
    "contribution_check",
    "tradeoff_compare",
    "affordability",
    "trip_planning",
    "memory_query",
    "unknown",
]


class Intent(AgenticModel):
    type: IntentType
    period: str | None = None  # e.g., "2026-09"
    year: int | None = None
    month: int | None = None
    category_id: str | None = None
    merchant_normalized: str | None = None
    goal_id: str | None = None
    amount_paise: StrictInt | None = None
    horizon_months: int | None = None
    confidence_label: Literal["high", "medium", "low"] = "high"
    source: Literal["deterministic", "llm"] = "deterministic"
    clarification: str | None = None


# ---------------------------------------------------------------------------------------------
# 2. Plan, Steps & Observations
# ---------------------------------------------------------------------------------------------
StepStatus = Literal[
    "proposed", "rejected", "running", "done", "failed", "skipped_memoized"
]


class PlanStep(AgenticModel):
    id: Id
    task_id: Id
    user_id: Id
    seq: int = Field(ge=0)
    tool_name: str
    args: dict[str, Any]
    rationale: str
    proposed_by: Literal["deterministic", "llm"]
    status: StepStatus = "proposed"
    reject_reason: str | None = None
    started_at: UtcTimestamp | None = None
    finished_at: UtcTimestamp | None = None


class Plan(AgenticModel):
    task_id: Id
    steps: list[PlanStep] = Field(default_factory=list)


class Observation(AgenticModel):
    step_seq: int
    tool_name: str
    ok: bool
    data_summary: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------------------------
# 3. Agent Task
# ---------------------------------------------------------------------------------------------
TaskStatus = Literal[
    "understood",
    "needs_clarification",
    "refused",
    "planned",
    "running",
    "awaiting_approval",
    "done",
    "failed",
    "stopped",
]
StopReason = Literal[
    "completed",
    "step_budget",
    "llm_budget",
    "loop_detected",
    "tool_failure",
    "inconclusive",
]


class AgentTask(AgenticModel):
    id: Id
    user_id: Id
    run_id: str | None = None
    raw_text: str  # local only, never logged or leaked to prompts without redaction
    intent: Intent | None = None
    status: TaskStatus
    stop_reason: StopReason | None = None
    planner_mode: Literal["deterministic", "llm"] = "deterministic"
    model: str | None = None
    prompt_version: str | None = None
    created_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None


# ---------------------------------------------------------------------------------------------
# 4. Goals
# ---------------------------------------------------------------------------------------------
GoalKind = Literal["savings", "purchase", "emergency_fund", "other"]
GoalStatus = Literal["active", "paused", "done"]


class Goal(AgenticModel):
    id: Id
    user_id: Id
    name: str
    kind: GoalKind
    target_paise: StrictInt = Field(gt=0)
    current_paise: StrictInt = Field(ge=0)
    deadline: str | None = None  # YYYY-MM-DD
    priority: int = Field(ge=1, le=3)
    status: GoalStatus = "active"
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    progress_source: Literal["manual", "bucket", "account"] = "manual"
    linked_account_id: str | None = None
    start_date: str | None = None
    essential: bool | int = 0
    notes: str | None = None


# ---------------------------------------------------------------------------------------------
# 5. Investigations & Hypotheses
# ---------------------------------------------------------------------------------------------
InvestigationSubjectKind = Literal[
    "anomaly", "category_change", "merchant_change", "period_change"
]
InvestigationOutcome = Literal[
    "explained", "partially_explained", "inconclusive", "needs_clarification"
]
HypothesisStatus = Literal["supported", "contradicted", "untested", "neutral"]
EvidenceResult = Literal["supports", "contradicts", "neutral"]


class Hypothesis(AgenticModel):
    id: Id
    investigation_id: Id
    user_id: Id
    code: str
    status: HypothesisStatus = "untested"
    score_bp: int = Field(ge=0, le=10000)
    contribution_paise: StrictInt = Field(ge=0)


class EvidenceItem(AgenticModel):
    id: Id
    investigation_id: Id
    user_id: Id
    hypothesis_code: str
    test_code: str
    result: EvidenceResult
    strength_bp: int = Field(ge=0, le=10000)
    numbers: dict[str, Any]
    txn_ids: list[str] = Field(default_factory=list)


class Investigation(AgenticModel):
    id: Id
    task_id: str | None = None
    user_id: Id
    run_id: str | None = None
    subject_kind: InvestigationSubjectKind
    subject_ref: dict[str, Any]
    outcome: InvestigationOutcome
    confidence_label: Literal["high", "medium", "low"]
    explained_share_bp: int = Field(ge=0, le=10000)
    unexplained_paise: StrictInt = Field(ge=0)
    rounds: int = Field(ge=1)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    created_at: UtcTimestamp


# ---------------------------------------------------------------------------------------------
# 6. What-If Simulation
# ---------------------------------------------------------------------------------------------
ScenarioKind = Literal["add_spend", "reduce_spend", "change_contribution"]


class Scenario(AgenticModel):
    kind: ScenarioKind
    category_id: str | None = None
    amount_paise: StrictInt = Field(ge=0)
    start_month: str  # YYYY-MM
    recurring: bool = False
    months: int = Field(default=1, ge=1, le=12)
    goal_id: str | None = None


class Projection(AgenticModel):
    scenario: Scenario
    months_projected: int
    monthly_spend_paise: dict[str, int]
    monthly_surplus_paise: dict[str, int]
    budget_statuses: dict[str, str]
    goal_impacts: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    has_insufficient_data: bool = False


# ---------------------------------------------------------------------------------------------
# 7. Adaptive Alerts
# ---------------------------------------------------------------------------------------------
AlertSeverity = Literal["info", "notice", "warning", "critical"]
AlertStatus = Literal["open", "acknowledged", "dismissed", "snoozed"]


class Alert(AgenticModel):
    id: Id
    user_id: Id
    kind: str
    subject_key: str
    period: str
    score_bp: int = Field(ge=0, le=10000)
    severity: AlertSeverity
    components: dict[str, Any]
    why_text: str
    status: AlertStatus = "open"
    snoozed_until: UtcTimestamp | None = None
    dedup_key: str
    run_id: str | None = None
    created_at: UtcTimestamp
    decided_at: UtcTimestamp | None = None
    dismiss_reason: str | None = None


class AlertPreference(AgenticModel):
    id: Id
    user_id: Id
    category_id: str | None = None
    kind: str | None = None
    min_severity: AlertSeverity = "info"
    muted: bool = False
    max_open_alerts: int | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------------------------
# 8. Explainable Recommendations & Timeline
# ---------------------------------------------------------------------------------------------
RecommendationOrigin = Literal[
    "monthly_review", "investigation", "whatif", "alert", "goal"
]


class CalcStep(AgenticModel):
    label: str
    formula_id: str
    inputs: dict[str, Any]
    result: Any


class Recommendation(AgenticModel):
    id: Id
    user_id: Id
    task_id: str | None = None
    run_id: str | None = None
    origin: RecommendationOrigin = "monthly_review"
    text: str
    evidence: list[str] = Field(default_factory=list)
    calculations: list[CalcStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    tools_used: list[dict[str, Any]] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    confidence_label: Literal["high", "medium", "low"] | None = None
    simulation_id: str | None = None
    status: Literal["draft", "approved", "rejected", "superseded"] = "draft"
    created_at: UtcTimestamp


TimelineKind = Literal[
    "observation",
    "plan",
    "tool_call",
    "investigation",
    "simulation",
    "alert",
    "decision",
    "approval_pending",
    "refusal",
    "error",
    "commitment",
    "allocation",
    "readiness",
    "memory",
    "skill_run",
    "tradeoff",
    "contribution_plan",
]


class TimelineEntry(AgenticModel):
    ts: UtcTimestamp
    kind: TimelineKind
    title: str
    detail: str
    status: str
    ref: dict[str, Any] = Field(default_factory=dict)


class Timeline(AgenticModel):
    user_id: str
    entries: list[TimelineEntry] = Field(default_factory=list)
    pending_approvals: list[TimelineEntry] = Field(default_factory=list)
