"""
Typed MonthlyReview data models (PLAN_PHASE1 Section 5.8).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BudgetState = Literal["ok", "warning", "exceeded", "projected_exceed"]


class CategoryTotal(BaseModel):
    """Spend in one category with change vs previous month."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category_id: str
    category_name: str
    current_spend_paise: int
    previous_spend_paise: int | None = None
    change_paise: int | None = None
    change_pct: float | None = None


class ReviewBudgetStatus(BaseModel):
    """Budget performance for one category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category_id: str
    category_name: str
    spent_paise: int
    limit_paise: int
    pct_used: int | None = None
    status: BudgetState


class ReviewRecurringItem(BaseModel):
    """A recurring subscription or recurring expense active this month."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant: str
    typical_amount_paise: int
    cadence_days: int | None = None
    confidence: float = 1.0


class ReviewAnomalyItem(BaseModel):
    """An outlier transaction flagged during the month."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str
    merchant: str
    amount_paise: int
    occurred_at: str
    reason: str


class ReviewForecast(BaseModel):
    """Month-end projection for the ongoing/next period."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spent_so_far_paise: int
    projected_total_paise: int
    projected_range_paise: tuple[int, int]
    insufficient_data: bool = False


class ReviewAdviceItem(BaseModel):
    """Approved or draft advice associated with this month's findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    text: str
    status: Literal["draft", "approved", "rejected"]
    assumptions: list[str] = Field(default_factory=list)


class DataQualityNotes(BaseModel):
    """Audit and data health indicators for the period."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_queue_size: int = 0
    duplicates_flagged: int = 0
    missing_days: int = 0
    days_recorded: int = 0
    days_in_month: int = 30
    is_partial_month: bool = False


class MonthlyReviewData(BaseModel):
    """
    The complete, structured monthly review document.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    user_id: str
    period: str  # YYYY-MM
    year: int
    month: int
    version: int = 1
    run_id: str
    generated_at: str

    income_paise: int
    spend_paise: int
    net_paise: int

    previous_period: str | None = None
    previous_income_paise: int | None = None
    previous_spend_paise: int | None = None
    previous_net_paise: int | None = None

    category_totals: list[CategoryTotal] = Field(default_factory=list)
    budget_statuses: list[ReviewBudgetStatus] = Field(default_factory=list)
    recurring_payments: list[ReviewRecurringItem] = Field(default_factory=list)
    anomalies: list[ReviewAnomalyItem] = Field(default_factory=list)
    forecast: ReviewForecast | None = None
    advice: list[ReviewAdviceItem] = Field(default_factory=list)
    data_quality: DataQualityNotes
