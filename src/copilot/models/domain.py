"""
Core domain models for Finance Copilot.

Models are the validation gate in front of the database: they reject unknown fields, refuse
non-integer money (no silent 1000.0 -> 1000 coercion) and normalise timestamps to canonical UTC.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, model_validator

from copilot.core.timeutil import normalize_utc_iso

# Non-empty identifier (UUID4 strings in practice).
Id = Annotated[str, Field(min_length=1)]
# Any offset-aware ISO-8601 string, stored as canonical 'YYYY-MM-DDTHH:MM:SSZ'.
UtcTimestamp = Annotated[str, AfterValidator(normalize_utc_iso)]


class DomainModel(BaseModel):
    """Base for persistent entities: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class User(DomainModel):
    """The owner of all other rows. Phase 0 seeds a single user."""

    id: Id
    created_at: UtcTimestamp


class Account(DomainModel):
    """A bank account. The balance is derived from the opening balance plus transactions."""

    id: Id
    user_id: Id
    name: str
    opening_balance_paise: StrictInt = 0
    created_at: UtcTimestamp


class Category(DomainModel):
    """A spending category, unique by name per user."""

    id: Id
    user_id: Id
    name: str
    created_at: UtcTimestamp


class Transaction(DomainModel):
    """A single bank transaction."""

    id: Id
    user_id: Id
    account_id: Id
    occurred_at: UtcTimestamp

    # Sign convention: positive = spend (direction 'debit'),
    # negative = credit (refund, income; direction 'credit'). Zero is rejected.
    amount_paise: StrictInt
    direction: Literal["debit", "credit"]

    merchant_raw: str
    description: str

    category_id: Id | None = None
    category_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    category_source: Literal["rule", "llm", "user", "none", "override", "cache"] = "none"

    created_at: UtcTimestamp

    fingerprint: str | None = None
    batch_id: Id | None = None
    merchant_normalized: str | None = None
    mode: Literal["upi", "card", "atm", "neft", "imps", "other"] | None = None
    is_duplicate_of: Id | None = None
    needs_review: bool = False
    excluded_from_spend: bool = False

    @model_validator(mode="after")
    def _sign_matches_direction(self) -> "Transaction":
        """Reject amounts whose sign disagrees with `direction`."""
        if self.direction == "debit" and self.amount_paise <= 0:
            raise ValueError("debit transactions must have amount_paise > 0")
        if self.direction == "credit" and self.amount_paise >= 0:
            raise ValueError("credit transactions must have amount_paise < 0")
        return self


class Budget(DomainModel):
    """A monthly spending limit for one category (at most one per category)."""

    id: Id
    user_id: Id
    category_id: Id
    period: Literal["monthly"] = "monthly"
    limit_paise: StrictInt = Field(ge=0)
    warn_threshold_pct: StrictInt = Field(ge=0, le=100)
    forecast_warn: bool = False


# -----------------------------------------------------------------------------
# Phase 1 Models
# -----------------------------------------------------------------------------


class Consent(DomainModel):
    id: Id
    user_id: Id
    purpose: str
    fi_types: str
    account_ids: str
    date_range_from: UtcTimestamp
    date_range_to: UtcTimestamp
    status: Literal["pending", "active", "revoked", "expired"]
    expires_at: UtcTimestamp
    created_at: UtcTimestamp


class IngestionBatch(DomainModel):
    id: Id
    user_id: Id
    consent_id: Id
    account_id: Id
    range_from: UtcTimestamp
    range_to: UtcTimestamp
    fetched_count: StrictInt = 0
    inserted_count: StrictInt = 0
    duplicate_count: StrictInt = 0
    status: Literal["pending", "completed", "failed"]
    error_code: str | None = None
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None


class MerchantOverride(DomainModel):
    id: Id
    user_id: Id
    merchant_normalized: str
    category_id: Id
    created_by: Literal["user"]
    created_at: UtcTimestamp


class LLMCategoryCache(DomainModel):
    id: Id
    user_id: Id
    merchant_normalized: str
    category_id: Id
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    created_at: UtcTimestamp


class RecurringSeries(DomainModel):
    id: Id
    user_id: Id
    merchant_normalized: str
    typical_amount_paise: StrictInt
    cadence_days: StrictInt = Field(gt=0)
    last_seen: UtcTimestamp
    next_expected: UtcTimestamp
    confidence: float = Field(ge=0.0, le=1.0)
    kind: Literal["subscription", "bill", "income", "other"]


class TransferLink(DomainModel):
    id: Id
    user_id: Id
    debit_txn_id: Id
    credit_txn_id: Id
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: UtcTimestamp


class Anomaly(DomainModel):
    id: Id
    user_id: Id
    txn_id: Id | None = None
    kind: str
    score: float
    details_json: str
    run_id: str
    status: Literal["open", "dismissed"]
    created_at: UtcTimestamp


class Finding(DomainModel):
    id: Id
    user_id: Id
    run_id: str
    kind: str
    data_json: str
    created_at: UtcTimestamp


class AdviceItem(DomainModel):
    id: Id
    user_id: Id
    run_id: str
    finding_ids_json: str
    text: str
    evidence_json: str
    assumptions_json: str
    status: Literal["draft", "approved", "rejected", "superseded"]
    decided_at: UtcTimestamp | None = None
    decided_by: Literal["user"] | None = None
    created_at: UtcTimestamp


class MonthlyReview(DomainModel):
    id: Id
    user_id: Id
    year: StrictInt
    month: StrictInt = Field(ge=1, le=12)
    version: StrictInt = Field(ge=1)
    run_id: str
    review_json: str
    created_at: UtcTimestamp
