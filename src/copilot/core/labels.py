"""
Plain-language names and units for challenge metrics.

Challenge metrics are not all money: some count payments, days or percentages. Every place that
shows a metric value (offers, hypotheses, reviews, the web app) takes its label and unit from
here, so a raw code like "merchant_group_spend" never reaches a person and a count is never
shown as rupees.
"""

from __future__ import annotations

from typing import Literal

from copilot.core.advice import format_inr

Unit = Literal["money", "count", "days", "percent_bp"]

# code -> (label, unit)
METRICS: dict[str, tuple[str, Unit]] = {
    "category_spend": ("spending", "money"),
    "merchant_group_spend": ("spending on these merchants", "money"),
    "txn_count": ("number of payments", "count"),
    "no_spend_days": ("no-spend days", "days"),
    "bucket_adherence_days": ("days within your bucket", "days"),
    "goal_allocation": ("money set aside for your goal", "money"),
    "checkin_rate": ("check-ins answered", "percent_bp"),
    "tagging_completeness": ("payments with a category", "percent_bp"),
}


def metric_label(code: str) -> str:
    """A readable name for a metric code (falls back to the code with spaces)."""
    return METRICS.get(code, (code.replace("_", " "), "count"))[0]


def metric_unit(code: str) -> Unit:
    return METRICS.get(code, ("", "count"))[1]


def format_metric(code: str, value: int) -> str:
    """A value with its unit: rupees, a count, days or a whole percentage."""
    unit = metric_unit(code)
    if unit == "money":
        return format_inr(value)
    if unit == "percent_bp":
        return f"{value // 100}%"
    if unit == "days":
        return f"{value} day" if value == 1 else f"{value} days"
    return str(value)
