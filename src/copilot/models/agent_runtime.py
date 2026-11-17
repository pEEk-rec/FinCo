"""Typed records for the agent's machinery: memory, preferences, skills, specialists, reflections,
context, spans, jobs and feedback.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    subject_kind: Literal["alert_kind", "advice_kind", "challenge_template", "capture_signal"]
    subject_key: str
    alpha_milli: int = Field(default=2000, gt=0)
    beta_milli: int = Field(default=2000, gt=0)
    updated_at: str
