"""
Pydantic schemas and strict loaders for Phase 2 YAML configurations (PLAN_PHASE2 Section 5).
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------------------------
# 1. Planner Capabilities (Section 5.1)
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 2. Intent Patterns (Section 5.2)
# ---------------------------------------------------------------------------------------------
class IntentPatternsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refusal_classes: dict[str, list[str]]
    refusal_templates: dict[str, str]
    intent_keywords: dict[str, list[str]]
    labelled_examples: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
# 3. Plan Templates (Section 5.3)
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 4. Investigation (Section 5.4)
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 5. Goals (Section 5.5)
# ---------------------------------------------------------------------------------------------
class GoalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_horizon_months: int = 60
    surplus_lookback_months: int = 3
    min_history_months_for_surplus: int = 2
    allowed_priorities: list[int] = Field(default_factory=lambda: [1, 2, 3])

    # Phase 3 extensions (PLAN_PHASE3 Section 0.7 merge)
    projection_months: int = 3
    allowed_progress_sources: list[str] = Field(
        default_factory=lambda: ["manual", "bucket", "account"]
    )
    default_progress_source: str = "manual"


# ---------------------------------------------------------------------------------------------
# 6. What-If Simulation (Section 5.6)
# ---------------------------------------------------------------------------------------------
class WhatIfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_horizon_months: int = 6
    max_scenarios_per_comparison: int = 3
    max_amount_paise: int = 100_000_000_00  # 1 crore


# ---------------------------------------------------------------------------------------------
# 7. Adaptive Alerts (Section 5.7)
# ---------------------------------------------------------------------------------------------
class AlertsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_weights_bp: dict[str, int]
    tier_thresholds_bp: dict[str, int]
    cooldown_days: int = 7
    default_max_open_alerts: int = 5
    quiet_mode: bool = True

    @model_validator(mode="after")
    def validate_weights(self) -> "AlertsConfig":
        total_weight = sum(self.signal_weights_bp.values())
        if total_weight != 10000:
            raise ValueError(
                f"Signal weights must sum to exactly 10,000 basis points (got {total_weight})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 8. Explanation Templates (Section 5.8)
# ---------------------------------------------------------------------------------------------
class ExplanationTemplatesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_templates: dict[str, str]
    fallback_templates: dict[str, str]
    hedged_sentences: dict[str, str]


# ---------------------------------------------------------------------------------------------
# Loader Helpers
# ---------------------------------------------------------------------------------------------
def load_yaml(path: Path) -> dict[str, Any]:
    """Load raw YAML document from path with UTF-8 encoding."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} must be a YAML mapping")
    return data


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


def load_goals_config(path: Path | None = None) -> GoalsConfig:
    p = path or (CONFIG_DIR / "goals.yaml")
    return GoalsConfig.model_validate(load_yaml(p))


def load_whatif_config(path: Path | None = None) -> WhatIfConfig:
    p = path or (CONFIG_DIR / "whatif.yaml")
    return WhatIfConfig.model_validate(load_yaml(p))


def load_alerts_config(path: Path | None = None) -> AlertsConfig:
    p = path or (CONFIG_DIR / "alerts.yaml")
    return AlertsConfig.model_validate(load_yaml(p))


def load_explanation_templates(path: Path | None = None) -> ExplanationTemplatesConfig:
    p = path or (CONFIG_DIR / "explanation_templates.yaml")
    return ExplanationTemplatesConfig.model_validate(load_yaml(p))

