"""Config for the agent's machinery: memory, skills, decomposition, context budgets, runtime jobs,
learning, ops and MCP.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from copilot.config.loading import _load_yaml


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


class SubQuestionTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["cashflow", "goals", "readiness", "behaviour", "coaching", "experiments"]
    question_kind: str


class DecompositionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_subquestions_per_task: int = Field(ge=1, le=10)
    decomposition_templates: dict[str, list[SubQuestionTemplate]]
    registered_question_kinds: dict[str, str] = Field(default_factory=dict)


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_budgets: dict[str, int]
    top_k_memories: int = Field(ge=1, le=50)
    character_token_ratio: int = Field(ge=1, le=10)


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


class OpsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_per_1k_tokens: float = Field(ge=0.0)
    currency: str
    retention_days: int = Field(ge=1, le=365)
    latency_percentiles: list[int]


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_name: str
    protocol_version: str
    transport: Literal["stdio", "sse"]
    exposed_tools: list[str] = Field(default_factory=list)
    allow_transaction_detail: bool = False


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
        from copilot.common.settings import PROJECT_ROOT

        path = PROJECT_ROOT / "config" / "learning.yaml"
    return LearningConfig.model_validate(_load_yaml(path))


def load_ops_config(path: Path) -> OpsConfig:
    return OpsConfig.model_validate(_load_yaml(path))


def load_mcp_config(path: Path | None = None) -> MCPConfig:
    if path is None:
        from copilot.common.settings import PROJECT_ROOT

        path = PROJECT_ROOT / "config" / "mcp.yaml"
    return MCPConfig.model_validate(_load_yaml(path))
