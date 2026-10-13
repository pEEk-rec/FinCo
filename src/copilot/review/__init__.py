"""
Monthly financial review generation and report rendering module (PLAN_PHASE1 Section 5.8).
"""

from copilot.review.builder import build_monthly_review
from copilot.review.models import (
    CategoryTotal,
    DataQualityNotes,
    MonthlyReviewData,
    ReviewAdviceItem,
    ReviewAnomalyItem,
    ReviewBudgetStatus,
    ReviewForecast,
    ReviewRecurringItem,
)
from copilot.review.renderers import (
    extract_all_review_numbers,
    extract_numbers_from_rendered_text,
    render_html,
    render_markdown,
)

__all__ = [
    "MonthlyReviewData",
    "CategoryTotal",
    "ReviewBudgetStatus",
    "ReviewRecurringItem",
    "ReviewAnomalyItem",
    "ReviewForecast",
    "ReviewAdviceItem",
    "DataQualityNotes",
    "build_monthly_review",
    "render_markdown",
    "render_html",
    "extract_numbers_from_rendered_text",
    "extract_all_review_numbers",
]
