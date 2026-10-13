"""Deterministic merchant normalization and rule matching (no LLM, no database)."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# Compiled regexes for normalization
_STRIP_PREFIXES = re.compile(
    r"^(?:(?:upi|imps|neft|rtgs|ach|pos|ecom|atm|cdm|card|inb|cr|dr)[\s\-_/]+)+", re.IGNORECASE
)
_STRIP_DATES_REFS = re.compile(
    r"(?:\d{2,4}[-/]\d{2}[-/]\d{2,4}|\b\d{4,}\b|@\w+|ref\.?\s*\d+|/txn\b|/rev\b)", re.IGNORECASE
)
_CLEANUP = re.compile(r"[^a-zA-Z0-9 ]")
_MULTISPACE = re.compile(r"\s{2,}")


def normalize_merchant(raw: str, aliases: dict[str, str] | None = None) -> str:
    """
    Clean up messy Indian bank narrations.
    Strips UPI/IMPS prefixes, reference numbers, handles, dates and noise.
    """
    s = str(raw).strip()
    # 1. Strip common prefixes
    s = _STRIP_PREFIXES.sub("", s)
    # 2. Strip dates, long reference numbers, and @UPI handles
    s = _STRIP_DATES_REFS.sub(" ", s)
    # 3. Keep only alphanumeric and space
    s = _CLEANUP.sub(" ", s)
    # 4. Remove extra spaces and lowercase
    s = _MULTISPACE.sub(" ", s).strip().lower()

    if aliases and s in aliases:
        return aliases[s]
    return s


@dataclass(frozen=True)
class CategorizationRule:
    match: str
    is_regex: bool
    category_id: str
    confidence: float
    direction: str | None = None
    min_amount_paise: int | None = None
    max_amount_paise: int | None = None

    def evaluate(self, normalized: str, amount_paise: int, direction: str) -> bool:
        if self.direction and self.direction != direction:
            return False
        if self.min_amount_paise is not None and abs(amount_paise) < self.min_amount_paise:
            return False
        if self.max_amount_paise is not None and abs(amount_paise) > self.max_amount_paise:
            return False

        if self.is_regex:
            return bool(re.search(self.match, normalized, re.IGNORECASE))
        return self.match == normalized


def evaluate_rules(
    normalized: str,
    amount_paise: int,
    direction: str,
    rules: list[CategorizationRule],
) -> tuple[str, float] | None:
    """Return the (category_id, confidence) of the first matching rule, or None."""
    for rule in rules:
        if rule.evaluate(normalized, amount_paise, direction):
            return rule.category_id, rule.confidence
    return None


class RuleModel(BaseModel):
    """One validated entry of config/categorization_rules.yaml."""

    model_config = ConfigDict(extra="forbid")
    match: str = Field(min_length=1)
    is_regex: bool = False
    category_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    direction: Literal["debit", "credit"] | None = None
    min_amount_paise: int | None = Field(default=None, ge=0)
    max_amount_paise: int | None = Field(default=None, ge=0)


def load_rules(path: str | Path) -> list[CategorizationRule]:
    """Load and validate categorization rules. Raises ValueError on a bad file or bad regex."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"Rules file {path} must contain a list.")
    rules = []
    for index, entry in enumerate(data):
        model = RuleModel.model_validate(entry)
        if model.is_regex:
            try:
                re.compile(model.match)
            except re.error as exc:
                raise ValueError(
                    f"Rule #{index} has an invalid regex {model.match!r}: {exc}"
                ) from exc  # noqa: E501
        rules.append(CategorizationRule(**model.model_dump()))
    return rules


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load merchant aliases (normalized text -> canonical merchant). Keys are lowercased."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Aliases file {path} must contain a mapping.")
    return {str(k).lower(): str(v).lower() for k, v in data.items()}
