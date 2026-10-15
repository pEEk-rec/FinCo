"""
Pydantic schemas and strict loaders for Phase 4 YAML configurations.
(PLAN_PHASE4 Section 1.3, Section 5)
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------------------------
# 1. Experiments Configuration
# ---------------------------------------------------------------------------------------------
class DifficultyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reduction_share_bp: int = Field(ge=0, le=10000)


class ExperimentLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_active: int = Field(ge=1, le=10)
    max_per_category: int = Field(ge=1, le=5)


class ExperimentCheckinsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every_days: int = Field(ge=1, le=30)


class ExperimentReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delay_days: int = Field(ge=0, le=14)


class ExperimentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_days_min: int = Field(ge=7, le=56)
    duration_days_max: int = Field(ge=7, le=56)
    default_duration_days: int = Field(ge=7, le=56)
    default_start_weekday: int = Field(ge=0, le=6)
    limits: ExperimentLimitsConfig
    checkins: ExperimentCheckinsConfig
    review: ExperimentReviewConfig
    difficulties: dict[str, DifficultyConfig]
    min_target_share_bp: int = Field(ge=1000, le=10000)
    target_round_paise: int = Field(ge=100)

    @model_validator(mode="after")
    def validate_durations(self) -> "ExperimentsConfig":
        if self.duration_days_min > self.duration_days_max:
            raise ValueError(
                f"duration_days_min ({self.duration_days_min}) cannot exceed "
                f"duration_days_max ({self.duration_days_max})"
            )
        if not (self.duration_days_min <= self.default_duration_days <= self.duration_days_max):
            raise ValueError(
                f"default_duration_days ({self.default_duration_days}) must be between "
                f"min ({self.duration_days_min}) and max ({self.duration_days_max})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 2. Baseline Configuration
# ---------------------------------------------------------------------------------------------
class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_k: int = Field(ge=3, le=52)
    min_windows: int = Field(ge=3, le=52)
    max_lookback_weeks: int = Field(ge=4, le=52)
    max_missing_days: int = Field(ge=0, le=7)
    min_effect_share_bp: int = Field(ge=0, le=5000)
    min_effect_paise: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_windows(self) -> "BaselineConfig":
        if self.min_windows > self.default_k:
            raise ValueError(
                f"min_windows ({self.min_windows}) cannot exceed default_k ({self.default_k})"
            )
        return self


# ---------------------------------------------------------------------------------------------
# 3. Challenge Templates Configuration
# ---------------------------------------------------------------------------------------------
class ChallengeTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    family: str
    metric: str
    eligible_categories: list[str]
    allowed_durations: list[int]
    allowed_difficulties: list[str]
    trigger_class: str
    weekdays_only: bool = False
    title: str
    rationale_template: str
    safety_tags: list[str]
    merchant_group: str | None = None  # key in config/category_hints.yaml

    @model_validator(mode="after")
    def validate_durations_and_difficulties(self) -> "ChallengeTemplate":
        for d in self.allowed_durations:
            if d < 7 or d > 56:
                raise ValueError(f"Challenge duration {d} out of range [7, 56]")
        allowed_diffs = {"easy", "medium", "hard"}
        for diff in self.allowed_difficulties:
            if diff not in allowed_diffs:
                raise ValueError(f"Unknown difficulty {diff}; must be one of {allowed_diffs}")
        return self


# ---------------------------------------------------------------------------------------------
# 4. Weekly Offers Configuration
# ---------------------------------------------------------------------------------------------
class OffersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_days: int = Field(ge=1, le=30)
    max_per_week: int = Field(ge=1, le=10)
    cooldown_days: int = Field(ge=1, le=180)
    rest_weeks: int = Field(ge=1, le=10)
    dismissed_in_a_row: int = Field(default=6, ge=2, le=30)
    quiet_weeks: int = Field(default=1, ge=1, le=10)
    dismiss_weight: float = Field(ge=0.0, le=1.0)
    propensity_draws: int = Field(ge=100, le=10000)
    llm_candidates: int = Field(ge=1, le=20)
    policy: Literal["thompson", "greedy", "random"]
    beta_prior_alpha: int = Field(ge=1)
    beta_prior_beta: int = Field(ge=1)


# ---------------------------------------------------------------------------------------------
# 5. Rewards & XP Configuration
# ---------------------------------------------------------------------------------------------
class XpRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: int = Field(ge=1, le=500)
    max_daily_share: int = Field(ge=1, le=100)
    description: str


class RewardsXpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_cap: int = Field(ge=10, le=1000)


class ForbiddenRulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[str]
    categories: list[str]


class LevelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: list[int]
    names: list[str]

    @model_validator(mode="after")
    def validate_levels(self) -> "LevelsConfig":
        if len(self.thresholds) != len(self.names):
            raise ValueError(
                f"Levels thresholds ({len(self.thresholds)}) must match names ({len(self.names)})"
            )
        if sorted(self.thresholds) != self.thresholds:
            raise ValueError("Level thresholds must be strictly monotonically increasing")
        return self


class RewardsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    xp: RewardsXpConfig
    rules: dict[str, XpRuleConfig]
    forbidden_metrics_and_categories: ForbiddenRulesConfig
    levels: LevelsConfig

    @model_validator(mode="after")
    def validate_rules_against_forbidden(self) -> "RewardsConfig":
        forbidden_terms = set(self.forbidden_metrics_and_categories.metrics) | set(
            self.forbidden_metrics_and_categories.categories
        )
        for rule_name, rule in self.rules.items():
            rule_lower = rule_name.lower()
            desc_lower = rule.description.lower()
            for term in forbidden_terms:
                stems = [term, term.rstrip("s")] if term.endswith("s") else [term, f"{term}s"]
                for s in stems:
                    if s in rule_lower:
                        raise ValueError(
                            f"XP rule '{rule_name}' contains forbidden term '{term}'"
                        )
                    if (
                        f"skip {s}" in desc_lower
                        or f"reduce {s}" in desc_lower
                        or f"cutting {s}" in desc_lower
                        or f"delay {s}" in desc_lower
                    ):
                        raise ValueError(
                            f"XP rule '{rule_name}' description encourages skipping '{term}'"
                        )
        return self


# ---------------------------------------------------------------------------------------------
# 6. Badges Configuration
# ---------------------------------------------------------------------------------------------
class BadgeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    category: str


class BadgesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    badges: dict[str, BadgeDefinition]


# ---------------------------------------------------------------------------------------------
# 7. Streaks Configuration
# ---------------------------------------------------------------------------------------------
class StreaksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grace_days_per_7_days: int = Field(ge=0, le=3)
    freeze_reasons: list[str]
    streak_types: list[str]


# ---------------------------------------------------------------------------------------------
# 8. Pace Configuration
# ---------------------------------------------------------------------------------------------
class PaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tolerance_bp: int = Field(ge=0, le=5000)
    consecutive_behind_for_adaptation: int = Field(ge=1, le=5)
    ahead_margin_bp: int = Field(ge=0, le=10000)


# ---------------------------------------------------------------------------------------------
# 9. Integrity Configuration
# ---------------------------------------------------------------------------------------------
class IntegrityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_of_margin_bp: int = Field(ge=0, le=10000)
    late_days_threshold: int = Field(ge=0, le=14)


# ---------------------------------------------------------------------------------------------
# 10. Safety Configuration
# ---------------------------------------------------------------------------------------------
class Phase4SafetyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pressure_phrases: list[str]
    forbidden_encouragements: list[str]
    essential_categories: list[str]
    essential_keywords: list[str] = []


# ---------------------------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------------------------
def load_experiments_config(path: Path | None = None) -> ExperimentsConfig:
    p = path or (Path(__file__).parents[3] / "config" / "experiments.yaml")
    with open(p, encoding="utf-8") as f:
        return ExperimentsConfig.model_validate(yaml.safe_load(f))


def load_baseline_config(path: Path | None = None) -> BaselineConfig:
    p = path or (Path(__file__).parents[3] / "config" / "baseline.yaml")
    with open(p, encoding="utf-8") as f:
        return BaselineConfig.model_validate(yaml.safe_load(f))


def load_challenge_templates(directory: Path | None = None) -> dict[str, ChallengeTemplate]:
    d = directory or (Path(__file__).parents[3] / "config" / "challenges")
    templates = {}
    for p in d.glob("*.yaml"):
        with open(p, encoding="utf-8") as f:
            tmpl = ChallengeTemplate.model_validate(yaml.safe_load(f))
            templates[tmpl.code] = tmpl
    return templates


def load_offers_config(path: Path | None = None) -> OffersConfig:
    p = path or (Path(__file__).parents[3] / "config" / "offers.yaml")
    with open(p, encoding="utf-8") as f:
        return OffersConfig.model_validate(yaml.safe_load(f))


def load_rewards_config(path: Path | None = None) -> RewardsConfig:
    p = path or (Path(__file__).parents[3] / "config" / "rewards.yaml")
    with open(p, encoding="utf-8") as f:
        return RewardsConfig.model_validate(yaml.safe_load(f))


def load_badges_config(path: Path | None = None) -> BadgesConfig:
    p = path or (Path(__file__).parents[3] / "config" / "badges.yaml")
    with open(p, encoding="utf-8") as f:
        return BadgesConfig.model_validate(yaml.safe_load(f))


def load_streaks_config(path: Path | None = None) -> StreaksConfig:
    p = path or (Path(__file__).parents[3] / "config" / "streaks.yaml")
    with open(p, encoding="utf-8") as f:
        return StreaksConfig.model_validate(yaml.safe_load(f))


def load_pace_config(path: Path | None = None) -> PaceConfig:
    p = path or (Path(__file__).parents[3] / "config" / "pace.yaml")
    with open(p, encoding="utf-8") as f:
        return PaceConfig.model_validate(yaml.safe_load(f))


def load_integrity_config(path: Path | None = None) -> IntegrityConfig:
    p = path or (Path(__file__).parents[3] / "config" / "integrity.yaml")
    with open(p, encoding="utf-8") as f:
        return IntegrityConfig.model_validate(yaml.safe_load(f))


def load_phase4_safety_config(path: Path | None = None) -> Phase4SafetyConfig:
    p = path or (Path(__file__).parents[3] / "config" / "phase4_safety.yaml")
    with open(p, encoding="utf-8") as f:
        return Phase4SafetyConfig.model_validate(yaml.safe_load(f))
