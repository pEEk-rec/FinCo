"""
Pydantic schemas and strict loaders for Phase 3 YAML configurations (PLAN_PHASE3 Section 5, 1.3).
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------------------------
# 1. Commitments Configuration (Section 5.1)
# ---------------------------------------------------------------------------------------------
class CommitmentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_tolerance_bp: int = Field(ge=0, le=10000)
    date_tolerance_days: int = Field(ge=0, le=30)
    suggestion_min_occurrences: int = Field(ge=1, le=10)
    allowed_certainties: list[str]
    allowed_directions: list[str]
    allowed_kinds: list[str]
    allowed_schedule_kinds: list[str]


# ---------------------------------------------------------------------------------------------
# 2. Goals Configuration (Section 5.2 - Merged with Phase 2)
# ---------------------------------------------------------------------------------------------
class Phase3GoalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_horizon_months: int = Field(ge=1, le=120)
    surplus_lookback_months: int = Field(ge=1, le=12)
    min_history_months_for_surplus: int = Field(ge=1, le=12)
    allowed_priorities: list[int]
    projection_months: int = Field(default=3, ge=1, le=12)
    allowed_progress_sources: list[Literal["manual", "bucket", "account"]]
    default_progress_source: Literal["manual", "bucket", "account"]


# ---------------------------------------------------------------------------------------------
# 3. Virtual Buckets Configuration (Section 5.3)
# ---------------------------------------------------------------------------------------------
class BucketsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_threshold_bp: int = Field(ge=0, le=10000)
    draft_ttl_days: int = Field(ge=1, le=365)
    allowed_kinds: list[str]
    allowed_period_policies: list[str]
    default_period_policy: dict[str, str]


# ---------------------------------------------------------------------------------------------
# 4. Financial Calendar Configuration (Section 5.4)
# ---------------------------------------------------------------------------------------------
class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_horizon_days: int = Field(ge=1, le=180)
    max_horizon_days: int = Field(ge=1, le=180)
    min_buffer_paise: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_horizons(self) -> "CalendarConfig":
        if self.default_horizon_days > self.max_horizon_days:
            raise ValueError(
                f"default_horizon_days ({self.default_horizon_days}) cannot exceed "
                f"max_horizon_days ({self.max_horizon_days})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 5. Investment Readiness Configuration (Section 5.6)
# ---------------------------------------------------------------------------------------------
class ReadinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_history_months: int = Field(ge=1, le=12)
    positive_months_required: int = Field(ge=1, le=12)
    max_cv_bp: int = Field(ge=0, le=10000)
    emergency_months_target: int = Field(ge=1, le=12)
    emergency_min_months: int = Field(ge=1, le=12)
    obligation_window_days: int = Field(ge=1, le=365)
    essential_categories: list[str]

    @model_validator(mode="after")
    def validate_emergency_months(self) -> "ReadinessConfig":
        if self.emergency_min_months > self.emergency_months_target:
            raise ValueError(
                f"emergency_min_months ({self.emergency_min_months}) cannot exceed "
                f"emergency_months_target ({self.emergency_months_target})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 6. Contribution Planning & Trade-offs Configuration (Section 5.7)
# ---------------------------------------------------------------------------------------------
class ContributionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_horizon_months: int = Field(ge=1, le=24)
    max_horizon_months: int = Field(ge=1, le=24)
    max_tradeoff_alternatives: int = Field(ge=1, le=5)
    waterfall_order: list[str]

    @model_validator(mode="after")
    def validate_horizons(self) -> "ContributionsConfig":
        if self.default_horizon_months > self.max_horizon_months:
            raise ValueError("default_horizon_months cannot exceed max_horizon_months")
        return self


# ---------------------------------------------------------------------------------------------
# 7. Behavioural Memory Configuration (Section 5.8, 5.9)
# ---------------------------------------------------------------------------------------------
class MemoryThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use: int = Field(ge=0, le=10000)
    stale: int = Field(ge=0, le=10000)
    retire: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def validate_ordering(self) -> "MemoryThresholds":
        if not (self.use > self.stale >= self.retire):
            raise ValueError("Memory thresholds must satisfy: use > stale >= retire")
        return self


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advice_cooldown_days: int = Field(ge=1, le=365)
    thresholds_bp: MemoryThresholds
    half_lives_days: dict[str, int]
    support_cap_bp: int = Field(ge=1000, le=20000)
    min_contradictions_to_retire: int = Field(ge=1, le=10)
    k_s: float = Field(ge=0.1, le=5.0)
    k_c: float = Field(ge=0.1, le=5.0)
    allowed_exception_reasons: list[str]
    exception_damping_bp: int = Field(default=5000, ge=0, le=10000)
    observers: dict[str, Any] = Field(default_factory=dict)



# ---------------------------------------------------------------------------------------------
# 8. Skill Manifest (Section 5.12)
# ---------------------------------------------------------------------------------------------
class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: int = Field(ge=1)
    description: str
    inputs: dict[str, str]
    preconditions: list[str]
    steps: list[dict[str, Any]]
    outputs: list[str]
    narration_template: str
    eval_cases: str


# ---------------------------------------------------------------------------------------------
# 9. Multi-Agent Decomposition Configuration (Section 5.13)
# ---------------------------------------------------------------------------------------------
class SubQuestionTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["cashflow", "goals", "readiness", "behaviour", "coaching", "experiments"]
    question_kind: str


class DecompositionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_subquestions_per_task: int = Field(ge=1, le=10)
    decomposition_templates: dict[str, list[SubQuestionTemplate]]
    registered_question_kinds: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
# 10. Context Engineering Configuration (Section 5.14)
# ---------------------------------------------------------------------------------------------
class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_budgets: dict[str, int]
    top_k_memories: int = Field(ge=1, le=50)
    character_token_ratio: int = Field(ge=1, le=10)


# ---------------------------------------------------------------------------------------------
# 11. Agent Runtime Configuration (Section 5.15)
# ---------------------------------------------------------------------------------------------
class JobConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule: str
    enabled: bool = True


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loop_interval_seconds: int = Field(ge=1, le=3600)
    lease_duration_seconds: int = Field(ge=10, le=3600)
    max_retries: int = Field(ge=0, le=10)
    backoff_base_seconds: int = Field(ge=1, le=60)
    jobs: dict[str, JobConfig]


# ---------------------------------------------------------------------------------------------
# 12. Bounded Feedback Learning Configuration (Section 5.16)
# ---------------------------------------------------------------------------------------------
class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prior_alpha: int = Field(ge=1, le=100)
    prior_beta: int = Field(ge=1, le=100)
    eta: float = Field(ge=0.0, le=1.0)
    m_min: float = Field(ge=0.1, le=1.0)
    m_max: float = Field(ge=1.0, le=3.0)
    hard_floor_severities: list[str]

    @model_validator(mode="after")
    def validate_multipliers(self) -> "LearningConfig":
        if self.m_min >= self.m_max:
            raise ValueError(
                f"m_min ({self.m_min}) must be strictly less than m_max ({self.m_max})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 13. Observability & Ops Configuration (Section 5.15)
# ---------------------------------------------------------------------------------------------
class OpsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_per_1k_tokens: float = Field(ge=0.0)
    currency: str
    retention_days: int = Field(ge=1, le=365)
    latency_percentiles: list[int]


# ---------------------------------------------------------------------------------------------
# 14. MCP Server Configuration (Section 5.17)
# ---------------------------------------------------------------------------------------------
class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_name: str
    protocol_version: str
    transport: Literal["stdio", "sse"]
    exposed_tools: list[str] = Field(default_factory=list)
    allow_transaction_detail: bool = False


# ---------------------------------------------------------------------------------------------
# Strict Loaders
# ---------------------------------------------------------------------------------------------
def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration in {path} must be a YAML mapping")
    return data


def load_commitments_config(path: Path) -> CommitmentsConfig:
    return CommitmentsConfig.model_validate(_load_yaml(path))


def load_phase3_goals_config(path: Path) -> Phase3GoalsConfig:
    return Phase3GoalsConfig.model_validate(_load_yaml(path))


def load_buckets_config(path: Path) -> BucketsConfig:
    return BucketsConfig.model_validate(_load_yaml(path))


def load_calendar_config(path: Path) -> CalendarConfig:
    return CalendarConfig.model_validate(_load_yaml(path))


def load_readiness_config(path: Path) -> ReadinessConfig:
    return ReadinessConfig.model_validate(_load_yaml(path))


def load_contributions_config(path: Path) -> ContributionsConfig:
    return ContributionsConfig.model_validate(_load_yaml(path))


def load_memory_config(path: Path) -> MemoryConfig:
    return MemoryConfig.model_validate(_load_yaml(path))


def load_skill_manifest(path: Path) -> SkillManifest:
    return SkillManifest.model_validate(_load_yaml(path))


def load_decomposition_config(path: Path) -> DecompositionConfig:
    return DecompositionConfig.model_validate(_load_yaml(path))


def load_context_config(path: Path) -> ContextConfig:
    return ContextConfig.model_validate(_load_yaml(path))


def load_runtime_config(path: Path) -> RuntimeConfig:
    return RuntimeConfig.model_validate(_load_yaml(path))


def load_learning_config(path: Path | None = None) -> LearningConfig:
    if path is None:
        from copilot.core.config import PROJECT_ROOT

        path = PROJECT_ROOT / "config" / "learning.yaml"
    return LearningConfig.model_validate(_load_yaml(path))


def load_ops_config(path: Path) -> OpsConfig:
    return OpsConfig.model_validate(_load_yaml(path))


def load_mcp_config(path: Path | None = None) -> MCPConfig:
    if path is None:
        from copilot.core.config import PROJECT_ROOT

        path = PROJECT_ROOT / "config" / "mcp.yaml"
    return MCPConfig.model_validate(_load_yaml(path))
