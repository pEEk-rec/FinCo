"""
The shapes the API accepts and returns. Every request body and response is a typed model here,
so FastAPI validates input before any route code runs and the OpenAPI schema stays exact.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from copilot.api import read_models as rm
from copilot.domain.whatif import ScenarioComparison
from copilot.models.agentic import Goal, Investigation, Projection
from copilot.models.capture import PromptView
from copilot.models.money import GoalProgress
from copilot.review.models import MonthlyReviewData


class Health(BaseModel):
    status: Literal["ok"]


class Session(BaseModel):
    user_id: str
    as_of: str
    period: str
    data_source: Literal["synthetic_demo", "connected"]
    demo_clock: bool
    llm_available: bool = False


class CategoryOut(BaseModel):
    id: str
    name: str


class RecategorizeIn(BaseModel):
    category_id: str | None
    remember: bool = False


class RecategorizeOut(BaseModel):
    transaction_id: str
    previous_category_id: str | None
    new_category_id: str | None
    audit_event_id: str
    detail: rm.TransactionDetail


class UndoIn(BaseModel):
    audit_event_id: str


class UndoOut(BaseModel):
    undone_event_id: str
    new_audit_event_id: str


class ConsentDecisionOut(BaseModel):
    consent_id: str
    status: Literal["pending", "active", "expired", "revoked"]
    audit_event_id: str


class ReviewVersion(BaseModel):
    version: int
    generated_at: str


class MonthlyReviewOut(BaseModel):
    period: str
    versions: list[ReviewVersion]
    review: MonthlyReviewData | None


class GenerateReviewIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class AdviceDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


class AdviceDecisionOut(BaseModel):
    advice_id: str
    status: Literal["approved", "rejected"]


class AdviceExplanation(BaseModel):
    id: str
    text: str
    status: str
    origin: str | None
    confidence_label: str | None
    evidence: list[Any]
    calculations: list[Any]
    assumptions: list[Any]
    tools_used: list[Any]
    memories: list[Any]
    simulation_id: str | None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    clarification: str | None = Field(default=None, max_length=300)
    use_llm: bool = True


class PlanStepOut(BaseModel):
    seq: int
    tool_name: str
    rationale: str
    proposed_by: str
    status: str


class TraceNodeOut(BaseModel):
    node: str
    status: str
    duration_ms: float
    counts: dict[str, int]


class AnswerOut(BaseModel):
    headline: str
    points: list[str] = []
    followups: list[str] = []
    confidence: str | None = None
    written_by: str = "rules"
    causal_ok: bool = False
    facts: list[Any] = []


class LlmUsedOut(BaseModel):
    available: bool
    model: str | None = None
    calls: int = 0
    failures: int = 0
    planner: str = "rules"
    #: which way this response was produced: llm, fallback (model asked but not usable), or rules
    path: str = "rules"
    path_reason: str = ""


class AskOut(BaseModel):
    answer: AnswerOut | None = None
    llm: LlmUsedOut | None = None
    task_id: str | None
    status: str
    stop_reason: str | None
    question: str | None
    refusal_reason: str | None
    intent: dict[str, Any] | None
    recommendations: list[dict[str, Any]]
    pending_recommendations: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    investigations: list[dict[str, Any]]
    plan: list[PlanStepOut]
    trace: list[TraceNodeOut]
    rounds: int
    planner_mode: str


class AnomalyOut(BaseModel):
    id: str
    transaction_id: str
    merchant: str
    amount_paise: int
    occurred_at: str
    kind: str
    status: str


class InvestigateAnomalyIn(BaseModel):
    anomaly_id: str


class InvestigateChangeIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    category_id: str | None = None
    baseline_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class InvestigationOut(BaseModel):
    investigation: Investigation
    decomposition: dict[str, int]


class AlertsOut(BaseModel):
    alerts: list[dict[str, Any]]


class AlertDecisionIn(BaseModel):
    action: Literal["acknowledge", "dismiss", "snooze"]
    reason: str | None = None
    snooze_days: int | None = Field(default=None, ge=1, le=90)


class AlertPreferenceIn(BaseModel):
    category_id: str | None = None
    kind: str | None = None
    min_severity: Literal["info", "notice", "warning", "critical"] = "info"
    muted: bool = False


class CaptureInboxOut(BaseModel):
    """Payments waiting to be tagged, plus what the simulator panel offers."""

    prompts: list[PromptView]
    pending_count: int
    banks: list[dict[str, str]]
    kinds: list[str]
    credit_kinds: list[str]


class CaptureSmsOut(BaseModel):
    """What the phone is told. Never echoes the message."""

    outcome: Literal["recorded", "duplicate", "dropped", "unparsed"]
    reason: str | None = None
    event_id: str | None = None
    decision: str | None = None


class BridgeBankOut(BaseModel):
    bank: str
    name: str
    enabled: bool
    last_received_at: str | None
    parsed: int
    unparsed: int
    failure_bp: int
    drifting: bool


class BridgeHealthOut(BaseModel):
    secret_configured: bool
    banks: list[BridgeBankOut]
    any_enabled: bool


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=6, max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=12, max_length=600)
    keys: PushKeysIn
    label: str = Field(default="This device", min_length=1, max_length=40)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=12, max_length=600)


class PushDeviceOut(BaseModel):
    id: str
    label: str


class PushStatusOut(BaseModel):
    enabled: bool
    public_key: str
    lock_screen_safe: bool
    max_actions: int
    devices: list[PushDeviceOut]


class PushActionIn(BaseModel):
    """A press on a notification button. Authorised by its single-use token, not a login."""

    prompt_id: str
    token: str = Field(min_length=10, max_length=100)
    label: str = Field(min_length=1, max_length=80)
    rank: int = Field(default=0, ge=0, le=5)
    credit: bool = False


class PushActionOut(BaseModel):
    outcome: Literal["tagged", "already_tagged"]


class CaptureSimulateIn(BaseModel):
    bank: Literal["hdfc", "sbi", "icici", "axis", "kotak"]
    kind: Literal["debit", "credit", "card", "atm", "autopay", "reversal"] = "debit"
    amount_paise: int = Field(gt=0, le=100_000_000)
    counterparty: str = Field(default="", max_length=80)
    vpa: str | None = Field(default=None, max_length=80)


class CaptureLabelIn(BaseModel):
    event_id: str
    category_id: str | None = None
    credit_kind: str | None = None
    note: str | None = Field(default=None, max_length=200)
    rank_picked: int | None = Field(default=None, ge=0, le=5)
    linked_event_id: str | None = None


class CapturePolicyIn(BaseModel):
    counterparty_key: str = Field(min_length=1)
    policy: Literal["learn", "always_ask", "always_category"]
    category_id: str | None = None


class GoalsOut(BaseModel):
    goals: list[Goal]
    progress: list[GoalProgress] = Field(default_factory=list)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["savings", "purchase", "emergency_fund", "other"] = "savings"
    target_paise: int = Field(gt=0)
    current_paise: int = Field(default=0, ge=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: int = Field(default=2, ge=1, le=3)


class GoalUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_paise: int | None = Field(default=None, gt=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: int | None = Field(default=None, ge=1, le=3)
    status: Literal["active", "paused", "done"] | None = None


class GoalContributionIn(BaseModel):
    amount_paise: int = Field(ge=1)


class WhatIfIn(BaseModel):
    kind: Literal["add_spend", "reduce_spend", "change_contribution"]
    category_id: str | None = None
    amount_paise: int = Field(ge=1)
    recurring: bool = True
    months: int = Field(default=3, ge=1, le=12)
    goal_id: str | None = None


class WhatIfOut(BaseModel):
    projection: Projection
    simulation_id: str


class CompareIn(BaseModel):
    scenarios: list[WhatIfIn] = Field(min_length=1, max_length=4)


class CompareOut(BaseModel):
    comparison: ScenarioComparison
    simulation_id: str


class CommitmentIn(BaseModel):
    name: str = Field(min_length=1)
    amount_paise: int = Field(ge=1)
    start_date: str = Field(default="2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    category_id: str | None = None
    schedule_kind: Literal["monthly", "weekly", "yearly", "custom"] = "monthly"
    schedule_json: dict[str, Any] = Field(default_factory=lambda: {"day": 1})
    direction: Literal["outflow", "inflow"] = "outflow"
    kind: Literal["bill", "subscription", "emi", "sip", "rent", "tax", "income", "other"] = "bill"
    certainty: Literal["firm", "variable", "discretionary"] = "firm"
    goal_id: str | None = None
    bucket_id: str | None = None


class BucketIn(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["spending", "goal", "commitment", "flexible"] = "spending"
    period_policy: Literal["reset_monthly", "accumulate"] | None = None
    goal_id: str | None = None
    commitment_id: str | None = None
    sort_order: int = 0


class BucketAllocateIn(BaseModel):
    bucket_id: str
    amount_paise: int = Field(ge=1)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class BucketReallocateIn(BaseModel):
    from_bucket_id: str
    to_bucket_id: str
    amount_paise: int = Field(ge=1)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class MemoryForgetIn(BaseModel):
    memory_id: str
    reason: str = "user_request"


class LearningResetIn(BaseModel):
    subject_kind: str | None = None
    subject_key: str | None = None


class ExperimentDesignIn(BaseModel):
    template_code: str | None = None
    metric_code: str | None = None
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    duration_days: int = 14
    difficulty: str = "medium"
    target_value: int | None = None
    baseline_median: int | None = None
    start_date: str | None = None
    goal_id: str | None = None
    rationale: str | None = None


class ExperimentStartIn(BaseModel):
    experiment_id: str | None = None
    title: str | None = None
    metric_code: str | None = None
    template_code: str | None = None
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    duration_days: int = 14
    difficulty: str = "medium"
    target_value: int | None = None
    baseline_median: int | None = None
    start_date: str | None = None
    goal_id: str | None = None
    rationale: str | None = None
    origin: Literal["user", "offer", "goal_decomposition"] = "user"


class ExperimentAbandonIn(BaseModel):
    reason: str | None = None


class ExperimentCheckinIn(BaseModel):
    user_response: Literal["going_well", "hard", "want_to_pause", "skip"] | None = None


class ReviewFeedbackIn(BaseModel):
    difficulty_rating: int | None = Field(None, ge=1, le=5)
    user_difficulty: int | None = Field(None, ge=1, le=5)
    user_helpful: bool | None = None
    would_repeat: bool | None = None
    user_would_repeat: bool | None = None
    feedback_text: str | None = None


class OfferSuggestIn(BaseModel):
    week_start: str | None = None


class OfferDismissIn(BaseModel):
    reason: str | None = None


class AdjustmentRejectIn(BaseModel):
    reason: str | None = None


class UnderstandAnswerIn(BaseModel):
    category_id: str
    entity_id: str | None = None
    transaction_id: str | None = None


class CheckinResponseIn(BaseModel):
    response: Literal["acted", "dismissed", "not_useful"]


class ProfileValueIn(BaseModel):
    value: Any


class BudgetMoveIn(BaseModel):
    from_category: str
    to_category: str
    amount_paise: int = Field(gt=0)


class SubscriptionNoteIn(BaseModel):
    note: Literal["unused", "keep"]


class SplitGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    others: list[str] = Field(min_length=1, max_length=20)


class SplitExpenseIn(BaseModel):
    paid_by: str
    amount_paise: int = Field(gt=0)
    note: str = Field(default="", max_length=80)
    weights: dict[str, int] | None = None
    transaction_id: str | None = None


class SplitSettleIn(BaseModel):
    from_member: str
    to_member: str
    amount_paise: int = Field(gt=0)
    transaction_id: str | None = None
