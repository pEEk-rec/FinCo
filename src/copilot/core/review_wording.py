"""
Plain-language wording for an experiment review (PLAN_PHASE4 section 5.2).

The numbers come from the review and the baseline frozen when the experiment started; this
module only phrases them. It states where the result sits against the user's own previous
comparable periods, never that the challenge caused it, and never in a tone of praise or blame.
A model may reword this text, but the figures and the claim are fixed here.
"""

from dataclasses import dataclass, field
from datetime import date

from copilot.core.advice import format_inr
from copilot.core.metrics import METRIC_DIRECTIONS
from copilot.models.phase4 import Experiment, ExperimentReview

_MONEY = {"category_spend", "merchant_group_spend", "goal_allocation"}
_COUNT = {"txn_count"}
_DAYS = {"no_spend_days", "bucket_adherence_days"}
_RATE = {"tagging_completeness", "checkin_rate"}


@dataclass
class ReviewWording:
    headline: str
    details: list[str] = field(default_factory=list)
    needs_confirmation: bool = False
    confirmation_prompt: str | None = None

    def text(self) -> str:
        lines = [self.headline, *self.details]
        if self.confirmation_prompt:
            lines.append(self.confirmation_prompt)
        return "\n".join(lines)


def _fmt(metric: str, value: int) -> str:
    if metric in _MONEY:
        return format_inr(value)
    if metric in _COUNT:
        return f"{value} payment{'s' if value != 1 else ''}"
    if metric in _DAYS:
        return f"{value} day{'s' if value != 1 else ''}"
    if metric in _RATE:
        return f"{value // 100}%"
    return str(value)


def _unit(exp: Experiment) -> str:
    days = (date.fromisoformat(exp.window_end) - date.fromisoformat(exp.window_start)).days + 1
    return {7: "weeks", 14: "fortnights"}.get(days, f"{days}-day periods")


def describe_review(exp: Experiment, review: ExperimentReview) -> ReviewWording:
    """The review in plain words. Deterministic: the same review always reads the same."""
    metric = str(exp.metric_def_json.get("metric_code") or "")
    direction = METRIC_DIRECTIONS.get(metric, "lower")
    seen = _fmt(metric, review.observed_value)
    base = exp.baseline_json or {}
    k = int(base.get("k") or 0)
    low, high = base.get("low"), base.get("high")
    unit = _unit(exp)
    abandoned = bool((review.data_quality_json or {}).get("abandoned"))
    target = _fmt(metric, exp.target_value)

    if abandoned:
        headline = f"You stopped this early, which is fine. Up to that point the figure was {seen}."
        details = ["Trying something and learning that it does not suit you is a useful result."]
    elif review.outcome == "no_baseline" or not k or low is None or high is None:
        headline = f"The figure for this period was {seen}."
        details = [
            "There was not enough earlier history to compare it with your usual pattern, "
            "so it can only be measured against the target you set."
        ]
    else:
        usual = f"usual range {_fmt(metric, int(low))} to {_fmt(metric, int(high))}"
        better = "lower" if direction == "lower" else "higher"
        worse = "higher" if direction == "lower" else "lower"
        if review.outcome == "beyond_usual_range":
            headline = (
                f"{seen}, {better} than all {k} of your previous comparable {unit} ({usual})."
            )
        elif review.outcome == "above_usual_range":
            headline = (
                f"{seen}, {worse} than your usual range across your previous {k} comparable "
                f"{unit} ({usual})."
            )
            details = ["This period ran differently from your usual pattern."]
        else:
            headline = (
                f"{seen}, within your usual range across your previous {k} comparable {unit} "
                f"({usual})."
            )
        if review.outcome != "above_usual_range":
            details = []
        details.append(
            "This compares you with your own earlier periods only; it says nothing about the "
            "reason for the difference."
        )
    details.append(
        f"Your target was {target}: "
        + ("reached." if review.target_met else "not reached this time.")
    )
    narrative = (review.data_quality_json or {}).get("goal_link_narrative")
    if isinstance(narrative, str) and narrative:
        details.append(narrative)

    integrity = review.integrity_json or {}
    needs = integrity.get("confirmation_required") is True and not integrity.get("user_confirmed")
    prompt = None
    if needs:
        amount = int(integrity.get("recategorized_amount_paise") or 0)
        prompt = (
            f"Payments worth {format_inr(amount)} in this category were moved to another category "
            "during the window. If those were genuine corrections, confirm it so the target "
            "can count toward rewards."
        )
    return ReviewWording(
        headline=headline, details=details, needs_confirmation=needs, confirmation_prompt=prompt
    )
