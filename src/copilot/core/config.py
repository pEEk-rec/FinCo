"""
Load and validate config/settings.yaml.

Values that the code does not support are rejected at load time (for example a timezone other
than Asia/Kolkata), so config can never silently disagree with the implementation.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class CategorizationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    auto_accept_min_confidence: float = 0.85
    llm_confidence_cap: float = 0.85
    review_queue_below: float = 0.85
    llm_batch_size: int = Field(default=20, ge=1, le=100)


class Settings(BaseModel):
    """Validated application settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timezone: Literal["Asia/Kolkata"]
    currency: Literal["INR"]
    db_path: Path
    policy_path: Path
    default_warn_threshold_pct: int = Field(ge=0, le=100)
    forecast_method: Literal["run_rate"]
    llm_max_retries: int = Field(ge=0, le=5)
    transfer_window_hours: int = Field(ge=1, le=168, default=48)
    recurring_tolerance_pct: int = Field(ge=0, le=50, default=10)
    recurring_min_occurrences: int = Field(ge=2, le=12, default=3)

    # Phase 1 Config Paths
    categorization_rules_path: Path
    merchant_aliases_path: Path
    advice_templates_path: Path
    categorization: CategorizationSettings = CategorizationSettings()


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> Settings:
    """Read settings YAML, validate it, and resolve relative paths against the project root."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Settings file {path} must contain a mapping.")
    settings = Settings.model_validate(data)
    return settings.model_copy(
        update={
            "db_path": _resolve(settings.db_path),
            "policy_path": _resolve(settings.policy_path),
            "categorization_rules_path": _resolve(settings.categorization_rules_path),
            "merchant_aliases_path": _resolve(settings.merchant_aliases_path),
            "advice_templates_path": _resolve(settings.advice_templates_path),
        }
    )


def _resolve(path: Path) -> Path:
    """Absolute paths stay as they are; relative ones are taken from the project root."""
    return path if path.is_absolute() else PROJECT_ROOT / path
