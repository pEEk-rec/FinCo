"""Config for the money logic: goals, what-if, alerts, commitments, buckets, calendar, readiness
and contributions.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from copilot.config.loading import _load_yaml, load_yaml
from copilot.config.planning import CONFIG_DIR


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


class WhatIfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_horizon_months: int = 6
    max_scenarios_per_comparison: int = 3
    max_amount_paise: int = 100_000_000_00  # 1 crore


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


def load_goals_config(path: Path | None = None) -> GoalsConfig:
    p = path or (CONFIG_DIR / "goals.yaml")
    return GoalsConfig.model_validate(load_yaml(p))


def load_whatif_config(path: Path | None = None) -> WhatIfConfig:
    p = path or (CONFIG_DIR / "whatif.yaml")
    return WhatIfConfig.model_validate(load_yaml(p))


def load_alerts_config(path: Path | None = None) -> AlertsConfig:
    p = path or (CONFIG_DIR / "alerts.yaml")
    return AlertsConfig.model_validate(load_yaml(p))


class CommitmentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_tolerance_bp: int = Field(ge=0, le=10000)
    date_tolerance_days: int = Field(ge=0, le=30)
    suggestion_min_occurrences: int = Field(ge=1, le=10)
    allowed_certainties: list[str]
    allowed_directions: list[str]
    allowed_kinds: list[str]
    allowed_schedule_kinds: list[str]


class Phase3GoalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_horizon_months: int = Field(ge=1, le=120)
    surplus_lookback_months: int = Field(ge=1, le=12)
    min_history_months_for_surplus: int = Field(ge=1, le=12)
    allowed_priorities: list[int]
    projection_months: int = Field(default=3, ge=1, le=12)
    allowed_progress_sources: list[Literal["manual", "bucket", "account"]]
    default_progress_source: Literal["manual", "bucket", "account"]


class BucketsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_threshold_bp: int = Field(ge=0, le=10000)
    draft_ttl_days: int = Field(ge=1, le=365)
    allowed_kinds: list[str]
    allowed_period_policies: list[str]
    default_period_policy: dict[str, str]


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
