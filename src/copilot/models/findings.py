"""
Typed findings and LLM advice drafts (PLAN_PHASE1 section 5.6).

A `Finding` is a deterministic fact produced by analysis. It is the *only* source of numbers
the LLM may narrate: every number carries an explicit unit so the advice validator can compare
"₹1,234" in text against 123400 paise without guessing.

`domain.Finding` / `domain.AdviceItem` are the database row models; the models here are the
analysis-level and LLM-level shapes.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FindingKind = Literal[
    "category_spend",
    "budget_status",
    "forecast",
    "recurring",
    "anomaly",
    "income_spend",
]
NumberUnit = Literal["paise", "percent", "count", "days"]

_DIGIT = re.compile(r"\d")


class FindingNumber(BaseModel):
    """One labelled number. Percentages are whole percent; money is always integer paise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: int
    unit: NumberUnit


class Finding(BaseModel):
    """A structured, deterministic fact that advice may reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: FindingKind
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # IST calendar month, YYYY-MM
    subject: str | None = None  # display name: category, merchant, ...
    numbers: list[FindingNumber] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)  # transactions, budgets, series
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "Finding":
        """Labels are unique, and the description carries no numbers of its own."""
        labels = [n.label for n in self.numbers]
        if len(labels) != len(set(labels)):
            raise ValueError("finding number labels must be unique")
        if _DIGIT.search(self.description):
            # Numbers belong in `numbers`, where the validator can see their unit.
            raise ValueError("finding description must not contain digits")
        return self

    def number(self, label: str) -> FindingNumber | None:
        """The number with this label, or None."""
        return next((n for n in self.numbers if n.label == label), None)


class AdviceDraft(BaseModel):
    """One advice item proposed by the LLM. Never trusted until validated."""

    model_config = ConfigDict(extra="forbid")

    finding_ids: list[str] = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1, max_length=600)


class AdviceDraftBatch(BaseModel):
    """Structured LLM output for `draft_advice`."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdviceDraft] = Field(max_length=50)
