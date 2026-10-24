"""Models for the Capture track (PLAN_CAPTURE Stage C1). No raw message text lives here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["debit", "credit"]
CounterpartyKind = Literal["merchant", "person", "self", "cash", "unknown"]
EventSource = Literal["sms", "notification", "manual", "simulator"]
EventState = Literal["detected", "posted", "reversed", "reconciled", "orphaned"]
LabelSource = Literal["user", "auto", "guess"]
PromptDecision = Literal["ask", "inbox", "auto_label", "guess_only", "no_ask"]
PromptStatus = Literal["pending", "answered", "expired", "dismissed", "not_needed"]
CounterpartyPolicy = Literal["learn", "always_ask", "always_category"]


class PaymentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    source: EventSource
    simulated: bool
    amount_paise: int = Field(gt=0)
    direction: Direction
    account_last4: str | None = None
    utr: str | None = None
    counterparty_key: str
    counterparty_kind: CounterpartyKind
    display_name: str
    bank: str | None = None
    channel: str
    occurred_at: str
    state: EventState
    category_id: str | None = None
    credit_kind: str | None = None
    category_source: LabelSource | None = None
    needs_review: bool = False
    created_at: str


class GuessView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str  # a category id (debits) or a credit kind (credits)
    name: str  # what to show
    score_bp: int
    reasons: list[str] = Field(default_factory=list)


class PromptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    event: PaymentEvent
    decision: PromptDecision
    reason: str
    guesses: list[GuessView]
    status: PromptStatus
    created_at: str
    expires_at: str | None = None


class CounterpartyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterparty_key: str
    kind: CounterpartyKind
    display_name: str
    policy: CounterpartyPolicy
    policy_category_id: str | None = None
    recent_categories: list[str] = Field(default_factory=list)
    seen_count: int = 0
