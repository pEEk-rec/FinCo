# ruff: noqa: E501  (long SQL and prose lines)
"""Validated loaders for the understanding config (PLAN_AGENTIC_V2). Strict: a typo fails at load."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


# ---- narration formats -----------------------------------------------------------------------
class NarrationFormat(_Strict):
    name: str
    rail: Literal["upi", "card", "imps", "neft", "mandate", "atm", "bank"]
    pattern: str

    @field_validator("pattern")
    @classmethod
    def compiles(cls, v: str) -> str:
        try:
            re.compile(v, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"pattern does not compile: {exc}") from exc
        return v


class NarrationConfig(_Strict):
    formats: list[NarrationFormat] = Field(min_length=1)
    business_words: list[str]
    person_rails: list[str]


# ---- thresholds ------------------------------------------------------------------------------
class Levels(_Strict):
    more_questions: int = Field(ge=0, le=10000)
    balanced: int = Field(ge=0, le=10000)
    fewer_questions: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def ordered(self) -> Levels:
        if not self.fewer_questions <= self.balanced <= self.more_questions:
            raise ValueError("levels must run fewer_questions <= balanced <= more_questions")
        return self


class Neighbours(_Strict):
    k: int = Field(ge=1, le=10)
    min_similarity_bp: int = Field(ge=0, le=10000)
    examples: int = Field(ge=0, le=10)


class EntityCfg(_Strict):
    exact_vpa_bp: int = Field(ge=0, le=10000)
    exact_name_bp: int = Field(ge=0, le=10000)
    squash_equal_bp: int = Field(ge=0, le=10000)
    prefix_bp: int = Field(ge=0, le=10000)
    merge_at_bp: int = Field(ge=0, le=10000)
    min_prefix_chars: int = Field(ge=4, le=40)


class ModelCfg(_Strict):
    confidence_cap_bp: int = Field(ge=0, le=10000)
    max_calls_per_run: int = Field(ge=0, le=1000)


class CalibrationCfg(_Strict):
    bins: Literal[10]
    prior_strength: int = Field(ge=0, le=100)


class AuditCfg(_Strict):
    every: int = Field(ge=0, le=1000)  # 0 switches spot checks off


class LearningCfg(_Strict):
    rule_after: int = Field(ge=2, le=20)
    unsteady_bp: int = Field(ge=0, le=10000)
    mcc_map: dict[str, str]


class UnderstandConfig(_Strict):
    engine: Literal["cascade", "legacy"]
    ask_level: Literal["more_questions", "balanced", "fewer_questions"]
    levels: Levels
    neighbours: Neighbours
    entities: EntityCfg
    model: ModelCfg
    calibration: CalibrationCfg
    audit: AuditCfg
    learning: LearningCfg

    @property
    def threshold_bp(self) -> int:
        return getattr(self.levels, self.ask_level)

    def with_level(self, level: str) -> UnderstandConfig:
        return self.model_copy(update={"ask_level": level})


# ---- dictionary ------------------------------------------------------------------------------
class Brand(_Strict):
    name: str
    category: str
    names: list[str] = Field(min_length=1)
    handles: list[str] = []


class Dictionary(_Strict):
    brands: list[Brand]


@lru_cache(maxsize=2)
def load_narration_config(path: Path | None = None) -> NarrationConfig:
    return NarrationConfig.model_validate(_read(path or CONFIG_DIR / "narration_formats.yaml"))


@lru_cache(maxsize=2)
def load_understand_config(path: Path | None = None) -> UnderstandConfig:
    return UnderstandConfig.model_validate(_read(path or CONFIG_DIR / "understand.yaml"))


@lru_cache(maxsize=2)
def load_dictionary(path: Path | None = None) -> Dictionary:
    return Dictionary.model_validate(_read(path or CONFIG_DIR / "merchant_dictionary.yaml"))
