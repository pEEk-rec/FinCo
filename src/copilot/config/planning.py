"""Config for reading questions and planning: intents, plan templates, the tool catalogue,
investigations and explanation wording.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from copilot.config.loading import load_yaml

ToolClass = Literal["read", "compute", "write_logical", "approval_required", "prohibited"]
ToolCost = Literal["cheap", "medium", "expensive"]


class ToolCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner_selectable: bool
    tool_class: ToolClass
    cost: ToolCost
    short_description: str
    intents: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capability_safety(self) -> "ToolCapability":
        # Rule 5.1: Only read and compute tools may have planner_selectable: true
        if self.planner_selectable and self.tool_class not in ("read", "compute"):
            raise ValueError(
                f"Safety invariant violated: tool with class '{self.tool_class}' "
                "cannot be planner_selectable. Only 'read' and 'compute' tools are selectable."
            )
        return self


class PlannerCapabilitiesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: dict[str, ToolCapability]


class IntentPatternsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refusal_classes: dict[str, list[str]]
    refusal_templates: dict[str, str]
    intent_keywords: dict[str, list[str]]
    labelled_examples: dict[str, list[str]] = Field(default_factory=dict)


class StepTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arg_bindings: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""


class PlanTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_type: str
    required_tools: list[str]
    allowed_tools: list[str]
    default_steps: list[StepTemplate]


class PlanTemplatesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templates: dict[str, PlanTemplate]


class InvestigationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_months: int = 3
    min_history_months: int = 2
    max_rounds: int = 2
    explained_share_threshold_bp: int = 6000  # 60%
    confidence_thresholds_bp: dict[str, int] = Field(
        default_factory=lambda: {"high": 7500, "medium": 5000, "low": 2500}
    )
    catalogue_hypotheses: list[str] = Field(default_factory=list)
    dev_seeds: list[int] = Field(default_factory=lambda: [42, 101, 202, 303, 404])
    held_out_seeds: list[int] = Field(default_factory=lambda: [777, 888, 999])


class ExplanationTemplatesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_templates: dict[str, str]
    fallback_templates: dict[str, str]
    hedged_sentences: dict[str, str]


CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"


def load_planner_capabilities(path: Path | None = None) -> PlannerCapabilitiesConfig:
    p = path or (CONFIG_DIR / "planner_capabilities.yaml")
    return PlannerCapabilitiesConfig.model_validate(load_yaml(p))


def load_intent_patterns(path: Path | None = None) -> IntentPatternsConfig:
    p = path or (CONFIG_DIR / "intent_patterns.yaml")
    return IntentPatternsConfig.model_validate(load_yaml(p))


def load_plan_templates(path: Path | None = None) -> PlanTemplatesConfig:
    p = path or (CONFIG_DIR / "plan_templates.yaml")
    return PlanTemplatesConfig.model_validate(load_yaml(p))


def load_investigation_config(path: Path | None = None) -> InvestigationConfig:
    p = path or (CONFIG_DIR / "investigation.yaml")
    return InvestigationConfig.model_validate(load_yaml(p))


def load_explanation_templates(path: Path | None = None) -> ExplanationTemplatesConfig:
    p = path or (CONFIG_DIR / "explanation_templates.yaml")
    return ExplanationTemplatesConfig.model_validate(load_yaml(p))
