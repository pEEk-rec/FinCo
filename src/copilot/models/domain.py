"""
Core domain models for Finance Copilot.

Models are the validation gate in front of the database: they reject unknown fields, refuse
non-integer money (no silent 1000.0 -> 1000 coercion) and normalise timestamps to canonical UTC.
"""

from typing import Annotated, Literal, Optional

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

    category_id: Optional[Id] = None
    category_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    category_source: Literal["rule", "llm", "user", "none"] = "none"

    created_at: UtcTimestamp

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
