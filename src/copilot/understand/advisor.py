# ruff: noqa: E501  (long lines)
"""
The model's seat in the cascade (PLAN_AGENTIC_V2, S4).

The cascade asks an `Advisor` about cleaned merchant names, many at once (one request for a whole
batch, like the old pipeline). What may be sent is fixed here: the cleaned names, the user's
category ids and names, and a few of the user's own labelled shops as examples. Never a person, a
raw narration, an amount, a date, an account number or a reference. Each answer is validated
against the user's categories and capped, so a confident model can never outrank a rule or the user.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import AliasChoices, BaseModel, Field

from copilot.common.errors import ToolFailure
from copilot.llm.client import LLMClient, structured_call
from copilot.llm.redactor import redact

Request = tuple[str, list[tuple[str, str]]]  # (cleaned name, similar shops the user labelled)


class Suggestion(BaseModel):
    # earlier replies and recorded cassettes call this field merchant_normalized
    merchant: str = Field(validation_alias=AliasChoices("merchant", "merchant_normalized"))
    category_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)


class SuggestionBatch(BaseModel):
    decisions: list[Suggestion]


class Advisor(Protocol):
    calls: int  # requests made, not names asked about

    def suggest_many(
        self, requests: list[Request], categories: dict[str, str]
    ) -> list[tuple[str | None, int]]:
        """One answer per request, in order: (category id or None, confidence in basis points)."""
        ...


def build_prompt(requests: list[Request], categories: dict[str, str]) -> str:
    cats = "\n".join(f"- {cid}: {label}" for cid, label in sorted(categories.items()))
    shots = sorted({f"- {n} -> {c}" for _name, ex in requests for n, c in ex})
    names = sorted(name for name, _ex in requests)
    prompt = (
        "Decide which one category each merchant belongs to, using only the allowed ids.\n"
        "Answer null for any you are not sure about. Do not guess. Copy merchant exactly.\n"
        f"Allowed categories:\n{cats}\n"
        "Shops this person has already labelled (for style):\n"
        + ("\n".join(shots) or "- (none yet)")
        + f"\nMerchants: {names}"
    )
    return redact(prompt)


class RouterAdvisor:
    """The production advisor: structured calls through the existing model router."""

    def __init__(self, llm: LLMClient, max_retries: int = 1, batch_size: int = 20) -> None:
        self.llm = llm
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.calls = 0
        self.failures = 0

    def suggest_many(
        self, requests: list[Request], categories: dict[str, str]
    ) -> list[tuple[str | None, int]]:
        answers: dict[str, tuple[str | None, int]] = {}
        for start in range(0, len(requests), self.batch_size):
            chunk = requests[start : start + self.batch_size]
            self.calls += 1
            try:
                out = structured_call(
                    client=self.llm,
                    prompt=build_prompt(chunk, categories),
                    output_model=SuggestionBatch,
                    max_retries=self.max_retries,
                    temperature=0,
                    purpose="categorization",
                )
            except ToolFailure:
                self.failures += 1
                continue
            asked = {name for name, _ex in chunk}
            for d in out.decisions:
                if d.merchant not in asked or d.merchant in answers:
                    continue
                ok = d.category_id is not None and d.category_id in categories
                answers[d.merchant] = (
                    (d.category_id, round(d.confidence * 10000)) if ok else (None, 0)
                )
        return [answers.get(name, (None, 0)) for name, _ex in requests]


class NoAdvisor:
    """No model available: the cascade simply goes from the dictionary to asking."""

    calls = 0

    def suggest_many(
        self, requests: list[Request], categories: dict[str, str]
    ) -> list[tuple[str | None, int]]:
        return [(None, 0) for _ in requests]
