"""
One typed read model for the Challenges and Progress screens.

The screens never compute, label or format-guess: every name, unit, sentence and percentage
here comes from the same code the CLI and the tests use. Reads only; every change goes through
the existing governed endpoints.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from copilot.config.phase4 import load_offers_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.experiments import get_experiment_progress
from copilot.core.labels import Unit, metric_label, metric_unit
from copilot.core.policy import is_in_dismissal_quiet_period, is_user_in_rest_weeks
from copilot.core.review_wording import describe_review
from copilot.core.rewards import get_user_progress
from copilot.core.timeutil import IST, now_utc
from copilot.db.repo_phase4 import (
    list_adjustment_proposals,
    list_experiment_checkins,
    list_experiment_reviews,
    list_experiments,
    list_offers,
)

Difficulty = Literal["easy", "medium", "hard"]


class OfferView(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    duration_days: int
    reason: str
    unit: Unit
    metric_label: str
    target: int
    usual: int
    expected_saving_paise: int


class ExperimentView(BaseModel):
    id: str
    title: str
    status: str
    difficulty: Difficulty
    direction: Literal["lower", "higher"]
    metric_label: str
    unit: Unit
    window_start: str
    window_end: str
    elapsed_days: int
    total_days: int
    target: int
    observed: int
    usual: int | None
    low: int | None
    high: int | None
    history: list[int]
    pace: str
    paused_days: list[str]
    extended_by_days: int
    hypothesis: str
    checkin_id: str | None = None


class ReviewView(BaseModel):
    experiment_id: str
    title: str
    outcome: str
    headline: str
    details: list[str]
    target_met: bool | None
    needs_confirmation: bool
    confirmation_prompt: str | None
    feedback_given: bool
    unit: Unit
    observed: int
    usual: int | None
    low: int | None
    high: int | None
    window_end: str


class AdjustmentView(BaseModel):
    id: str
    experiment_id: str
    experiment_title: str
    kind: str
    message: str
    status: str


class BadgeView(BaseModel):
    code: str
    name: str
    description: str
    awarded_at: str


class StreakView(BaseModel):
    code: str
    label: str
    days: int


class BestView(BaseModel):
    label: str
    scope: str
    unit: Unit
    window_days: int
    best: int
    achieved_at: str


class LevelView(BaseModel):
    number: int
    name: str
    total_xp: int
    xp_to_next: int | None
    progress_bp: int = Field(ge=0, le=10000)


class ProgressView(BaseModel):
    level: LevelView
    badges: list[BadgeView]
    locked_badges: list[BadgeView]
    streaks: list[StreakView]
    bests: list[BestView]


class CoachView(BaseModel):
    offers: list[OfferView]
    offers_note: str | None
    active: list[ExperimentView]
    reviews: list[ReviewView]
    adjustments: list[AdjustmentView]
    progress: ProgressView


_STREAK_LABELS = {
    "tagging_streak": "Everything categorised",
    "checkin_streak": "Weekly check-ins",
    "bucket_streak": "Within your bucket",
}


def _badge_catalogue() -> dict[str, dict[str, str]]:
    path = PROJECT_ROOT / "config" / "badges.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("badges", {})


def _band(exp_baseline: dict | None) -> tuple[int | None, int | None, int | None, list[int]]:
    b = exp_baseline or {}
    return b.get("median"), b.get("low"), b.get("high"), list(b.get("window_values") or [])


def build_coach_view(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> CoachView:
    now = clock or now_utc()
    today = now.astimezone(IST).date()
    titles: dict[str, str] = {}

    # ---- offers (and why there may be none) --------------------------------------------
    offers = []
    for o in list_offers(conn, user_id, status="shown"):
        p = o.params_json
        code = str(p.get("metric_code", ""))
        r = o.reason_json or {}
        offers.append(
            OfferView(
                id=o.id,
                title=str(p.get("title") or o.template_code),
                difficulty=o.difficulty,
                duration_days=int(p.get("duration_days", 7)),
                reason=str(r.get("statement") or r.get("text") or ""),
                unit=metric_unit(code),
                metric_label=metric_label(code),
                target=int(p.get("target_value", 0)),
                usual=int(r.get("baseline_median", 0)),
                expected_saving_paise=int(r.get("expected_effect_paise", 0)),
            )
        )
    note: str | None = None
    if not offers:
        cfg = load_offers_config()
        if is_user_in_rest_weeks(conn, user_id, as_of=today, config=cfg):
            note = "A short rest after two challenges that did not work out. No offers this week."
        elif is_in_dismissal_quiet_period(conn, user_id, as_of=today, config=cfg):
            note = "You passed on a few offers, so nothing new this week. They return soon."

    # ---- experiments ---------------------------------------------------------------------
    active: list[ExperimentView] = []
    experiments = list_experiments(conn, user_id)
    for e in experiments:
        titles[e.id] = e.title
        if e.status not in ("active", "paused"):
            continue
        code = str(e.metric_def_json.get("metric_code", ""))
        prog = get_experiment_progress(conn, user_id, e.id, clock=now)
        usual, low, high, history = _band(e.baseline_json)
        pending = [c for c in list_experiment_checkins(conn, user_id, e.id) if not c.user_response]
        params = e.params_json
        active.append(
            ExperimentView(
                id=e.id,
                title=e.title,
                status=e.status,
                difficulty=e.difficulty,
                direction=str(e.metric_def_json.get("direction", "lower")),  # type: ignore[arg-type]
                metric_label=metric_label(code),
                unit=metric_unit(code),
                window_start=e.window_start,
                window_end=e.window_end,
                elapsed_days=prog.elapsed_days,
                total_days=prog.total_days,
                target=e.target_value,
                observed=prog.observed_value,
                usual=usual,
                low=low,
                high=high,
                history=history,
                pace=prog.pace_status,
                paused_days=list(params.get("paused_days") or []),
                extended_by_days=sum(int(x.get("days", 0)) for x in params.get("extensions") or []),
                hypothesis=str((e.hypothesis_json or {}).get("statement", "")),
                checkin_id=pending[-1].id if pending else None,
            )
        )

    # ---- reviews --------------------------------------------------------------------------
    by_id = {e.id: e for e in experiments}
    reviews: list[ReviewView] = []
    for rev in list_experiment_reviews(conn, user_id):
        exp = by_id.get(rev.experiment_id)
        if exp is None:
            continue
        w = describe_review(exp, rev)
        code = str(exp.metric_def_json.get("metric_code", ""))
        usual, low, high, _ = _band(exp.baseline_json)
        reviews.append(
            ReviewView(
                experiment_id=exp.id,
                title=exp.title,
                outcome=rev.outcome,
                headline=w.headline,
                details=list(w.details),
                target_met=rev.target_met,
                needs_confirmation=w.needs_confirmation,
                confirmation_prompt=w.confirmation_prompt,
                feedback_given=any(
                    v is not None
                    for v in (rev.user_difficulty, rev.user_helpful, rev.user_would_repeat)
                ),
                unit=metric_unit(code),
                observed=rev.observed_value,
                usual=usual,
                low=low,
                high=high,
                window_end=exp.window_end,
            )
        )
    reviews.sort(key=lambda r: r.window_end, reverse=True)

    # ---- adjustments ---------------------------------------------------------------------
    adjustments = [
        AdjustmentView(
            id=a.id,
            experiment_id=a.experiment_id,
            experiment_title=titles.get(a.experiment_id, "Challenge"),
            kind=a.kind,
            message=str((a.params_json or {}).get("message", "")),
            status=a.status,
        )
        for a in list_adjustment_proposals(conn, user_id, status="proposed")
    ]

    # ---- progress ------------------------------------------------------------------------
    p = get_user_progress(conn, user_id, clock=now)
    catalogue = _badge_catalogue()
    earned = {b.badge_code: b for b in p.badges}
    start = p.total_xp - p.xp_in_level
    span = (p.xp_for_next_level - start) if p.xp_for_next_level is not None else 0
    level = LevelView(
        number=p.level_number,
        name=p.level_name,
        total_xp=p.total_xp,
        xp_to_next=(p.xp_for_next_level - p.total_xp) if p.xp_for_next_level is not None else None,
        progress_bp=10000 if span <= 0 else min(10000, p.xp_in_level * 10000 // span),
    )

    def badge(code: str, awarded_at: str) -> BadgeView:
        meta = catalogue.get(code, {})
        return BadgeView(
            code=code,
            name=str(meta.get("name", code.replace("_", " ").title())),
            description=str(meta.get("description", "")),
            awarded_at=awarded_at,
        )

    progress = ProgressView(
        level=level,
        badges=[badge(c, b.awarded_at) for c, b in earned.items()],
        locked_badges=[badge(c, "") for c in catalogue if c not in earned],
        streaks=[
            StreakView(code=k, label=_STREAK_LABELS.get(k, k.replace("_", " ").title()), days=v)
            for k, v in p.active_streaks.items()
        ],
        bests=[
            BestView(
                label=metric_label(b.metric_code),
                scope=b.scope,
                unit=metric_unit(b.metric_code),
                window_days=b.window_length_days,
                best=b.best_value,
                achieved_at=b.achieved_at,
            )
            for b in p.personal_bests
        ],
    )
    return CoachView(
        offers=offers,
        offers_note=note,
        active=active,
        reviews=reviews,
        adjustments=adjustments,
        progress=progress,
    )
