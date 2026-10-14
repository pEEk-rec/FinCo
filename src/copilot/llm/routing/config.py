"""Router configuration: providers' limits and each agentic task's candidate models."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["groq", "gemini"]
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "llm_router.yaml"


class ProviderLimits(BaseModel):
    """Per-key quota for one provider. The router uses `safety` of each limit."""

    model_config = ConfigDict(extra="forbid")

    rpm: int = Field(gt=0)
    tpm: int | None = Field(default=None, gt=0)
    rpd: int | None = Field(default=None, gt=0)
    timeout_s: float = Field(default=12.0, gt=0)
    safety: float = Field(default=0.85, gt=0, le=1)

    @property
    def usable_rpm(self) -> int:
        return max(1, int(self.rpm * self.safety))

    @property
    def usable_tpm(self) -> int | None:
        return None if self.tpm is None else max(1, int(self.tpm * self.safety))

    @property
    def usable_rpd(self) -> int | None:
        return None if self.rpd is None else max(1, int(self.rpd * self.safety))


class Candidate(BaseModel):
    """One (provider, model) the task may use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    model: str


class TaskPolicy(BaseModel):
    """How one agentic task should be served."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate] = Field(min_length=1)
    json_mode: bool = True
    max_tokens: int = Field(default=800, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=1)
    deadline_s: float = Field(default=15.0, gt=0)
    #: longest the task will wait for a busy key before giving up (interactive: short)
    max_wait_s: float = Field(default=8.0, ge=0)


class RouterConfig(BaseModel):
    """Everything the router needs except secrets."""

    model_config = ConfigDict(extra="forbid")

    providers: dict[ProviderName, ProviderLimits]
    tasks: dict[str, TaskPolicy]

    def policy(self, task: str) -> TaskPolicy:
        """The policy for `task`, falling back to `general`."""
        return self.tasks.get(task) or self.tasks["general"]


def load_router_config(path: str | Path = DEFAULT_CONFIG) -> RouterConfig:
    """Read and validate the router YAML."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    config = RouterConfig.model_validate(data)
    if "general" not in config.tasks:
        raise ValueError("llm_router.yaml must define a 'general' task")
    for name, task in config.tasks.items():
        for c in task.candidates:
            if c.provider not in config.providers:
                raise ValueError(f"task '{name}' uses provider '{c.provider}' with no limits")
    return config
