"""
Experiments Engine for Phase 4 (PLAN_PHASE4 Section 5.3, Stage 4.3).

Implements experiment design, lifecycle transitions (offered -> active ->
paused/completed/abandoned -> reviewed), baseline/metric definition freezing,
check-in generation, review generation with deterministic outcomes, goal linking
without causal promises, and progress tracking.
"""

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from copilot.config.phase4 import load_baseline_config, load_experiments_config
from copilot.core.baseline import (
    calculate_baseline,
    calculate_integrity_notes,
    calculate_pace,
    evaluate_outcome,
)
from copilot.core.essentials import first_essential
from copilot.core.goals import goal_current_paise
from copilot.core.labels import format_metric, metric_label
from copilot.core.metrics import METRIC_DIRECTIONS, calculate_metric
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.repo import get_goal
from copilot.db.repo_phase4 import (
    get_experiment,
    get_experiment_checkin,
    get_experiment_review_by_id,
    insert_adjustment_proposal,
    insert_experiment,
    insert_experiment_checkin,
    insert_experiment_review,
    list_experiment_checkins,
    list_experiments,
    update_experiment_checkin_response,
    update_experiment_review_feedback,
    update_experiment_start,
    update_experiment_status,
)
from copilot.models.phase4 import (
    AdjustmentProposal,
    Baseline,
    Experiment,
    ExperimentCheckin,
    ExperimentProgress,
    ExperimentReview,
    Hypothesis,
)


def _round_paise(val: int, round_step: int) -> int:
    """Round integer paise to nearest step (e.g. 5000 paise = Rs 50)."""
    if round_step <= 0:
        return val
    half = round_step // 2
    return ((val + half) // round_step) * round_step


# ---------------------------------------------------------------------------------------------
# 1. Design Experiment
# ---------------------------------------------------------------------------------------------
#: Metrics whose value over a window is the sum of their values over its parts, so days that were
#: paused for a declared exception can simply be left out. Rates (tagging, check-in) are not.
_ADDITIVE_METRICS = {
    "category_spend",
    "merchant_group_spend",
    "txn_count",
    "no_spend_days",
    "bucket_adherence_days",
    "goal_allocation",
}


def paused_days(exp: Experiment) -> set[date]:
    """Days set aside by an exception pause (kept in the experiment's parameters)."""
    return {date.fromisoformat(d) for d in (exp.params_json or {}).get("paused_days", [])}


def comparison_days(exp: Experiment) -> int:
    """Length of the periods the baseline was built from: the experiment's original duration."""
    chosen = (exp.params_json or {}).get("duration_days")
    if chosen:
        return int(chosen)
    span = (date.fromisoformat(exp.window_end) - date.fromisoformat(exp.window_start)).days + 1
    extended = sum(int(e.get("days", 0)) for e in (exp.params_json or {}).get("extensions", []))
    return span - extended


def observed_value(conn: sqlite3.Connection, user_id: str, exp: Experiment, end_date: str) -> int:
    """
    The experiment's metric from its start to `end_date`, leaving out the days paused for a
    declared exception, so the measured days still add up to the comparison windows' length.
    """
    metric = exp.metric_def_json["metric_code"]
    skipped = paused_days(exp)
    start = date.fromisoformat(exp.window_start)
    end = date.fromisoformat(end_date)
    if not skipped or metric not in _ADDITIVE_METRICS:
        return calculate_metric(
            conn,
            user_id,
            metric_code=metric,
            start_date=exp.window_start,
            end_date=end_date,
            params=exp.params_json,
        )
    total = 0
    run_start: date | None = None
    day = start
    while day <= end + timedelta(days=1):
        counted = day <= end and day not in skipped
        if counted and run_start is None:
            run_start = day
        elif not counted and run_start is not None:
            total += calculate_metric(
                conn,
                user_id,
                metric_code=metric,
                start_date=run_start.isoformat(),
                end_date=(day - timedelta(days=1)).isoformat(),
                params=exp.params_json,
            )
            run_start = None
        day += timedelta(days=1)
    return total


def design_experiment(
    conn: sqlite3.Connection,
    user_id: str,
    template_code: str | None = None,
    params: dict[str, Any] | None = None,
    clock: datetime | None = None,
) -> Experiment:
    """
    Design a new financial experiment with deterministic baseline sizing and safety checks.
    Status starts in 'offered'.
    """
    p = params or {}
    cfg = load_experiments_config()

    metric_code = p.get("metric_code")
    if not metric_code or metric_code not in METRIC_DIRECTIONS:
        raise ValueError(f"Invalid or missing metric_code: {metric_code}")

    direction = METRIC_DIRECTIONS[metric_code]
    duration_days = int(p.get("duration_days", cfg.default_duration_days))
    if duration_days < cfg.duration_days_min or duration_days > cfg.duration_days_max:
        raise ValueError(
            f"Duration {duration_days} out of bounds "
            f"[{cfg.duration_days_min}, {cfg.duration_days_max}]"
        )

    categories = p.get("categories", [])
    # 1. Safety check: reduction targets only on non-essential categories
    if categories:
        # Any metric that targets categories is checked: "no-spend days" on groceries would
        # push the user to skip food just as a spend cap would.
        blocked = first_essential(conn, user_id, categories)
        if blocked is not None:
            raise ValueError(
                f"Reduction target cannot be placed on essential category: '{blocked}'"
            )

    # 2. Check conflict: at most one active experiment on the same category
    if categories:
        active_exps = list_experiments(conn, user_id, status="active")
        for active in active_exps:
            active_cats = active.metric_def_json.get("categories", [])
            for cat in categories:
                if cat in active_cats:
                    raise ValueError(
                        f"Active experiment already exists on category '{cat}' (id: {active.id})"
                    )

    now_dt = clock or now_utc()
    now_ist = now_dt.astimezone(IST)
    start_date_str = p.get("start_date") or now_ist.date().isoformat()
    start_date = date.fromisoformat(start_date_str)
    end_date = start_date + timedelta(days=duration_days - 1)
    end_date_str = end_date.isoformat()

    # 3. Baseline calculation
    base, _exclusions = calculate_baseline(
        conn,
        user_id,
        metric_code=metric_code,
        start_date=start_date_str,
        duration_days=duration_days,
        params=p,
        k=6,
    )

    # 4. Target sizing
    difficulty = str(p.get("difficulty", "medium"))
    target_val: int

    if "target_value" in p and p["target_value"] is not None:
        target_val = int(p["target_value"])
        if direction == "lower" and base is not None:
            min_target = (base.median * cfg.min_target_share_bp) // 10000
            if target_val < min_target:
                raise ValueError(
                    f"Target value ({target_val} paise) cannot be below 50% "
                    f"of baseline median ({min_target} paise)"
                )
    else:
        if base is not None:
            diff_cfg = cfg.difficulties.get(difficulty, cfg.difficulties["medium"])
            share_bp = diff_cfg.reduction_share_bp
            if direction == "lower":
                raw_target = base.median - ((base.median * share_bp) // 10000)
                min_target = (base.median * cfg.min_target_share_bp) // 10000
                target_val = max(raw_target, min_target)
                target_val = _round_paise(target_val, cfg.target_round_paise)
            else:
                raw_target = base.median + ((base.median * share_bp) // 10000)
                target_val = _round_paise(raw_target, cfg.target_round_paise)
        else:
            raise ValueError(
                "Baseline unavailable (fewer than 3 windows). Explicit target_value is required."
            )

    # 5. Hypothesis formulation
    metric_name = metric_label(metric_code)
    intervention = p.get("intervention") or "stick to this challenge"
    dir_word = "at or below" if direction == "lower" else "at or above"
    if base is not None:
        hypo_text = (
            f"If I {intervention}, then my {metric_name} over {duration_days} days will be "
            f"{dir_word} {format_metric(metric_code, target_val)}, compared with my usual "
            f"{format_metric(metric_code, base.median)} "
            f"(range {format_metric(metric_code, base.low)} to "
            f"{format_metric(metric_code, base.high)})."
        )
        hyp_model = Hypothesis(
            intervention=intervention,
            metric=metric_code,
            direction=direction,
            target=target_val,
        )
    else:
        hypo_text = (
            f"If I {intervention}, then my {metric_name} over {duration_days} days will be "
            f"{dir_word} {format_metric(metric_code, target_val)}."
        )
        hyp_model = Hypothesis(
            intervention=intervention,
            metric=metric_code,
            direction=direction,
            target=target_val,
        )

    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    exp = Experiment(
        id=exp_id,
        user_id=user_id,
        title=p.get("title") or f"Challenge: {metric_name}",
        template_code=template_code,
        hypothesis_json={"statement": hypo_text, "structured": hyp_model.model_dump()},
        metric_def_json={
            "metric_code": metric_code,
            "direction": direction,
            "categories": categories,
            "merchants": p.get("merchants") or [],
            "weekdays_only": bool(p.get("weekdays_only", False)),
            "goal_id": p.get("goal_id"),
            "bucket_id": p.get("bucket_id"),
        },
        params_json=p,
        difficulty=difficulty,
        window_start=start_date_str,
        window_end=end_date_str,
        baseline_json=base.model_dump() if base else {},
        target_value=target_val,
        status="offered",
        origin=p.get("origin") or "user",
        offer_id=p.get("offer_id"),
        goal_id=p.get("goal_id"),
        created_at=to_utc_iso(now_dt),
        started_at=None,
        ended_at=None,
    )
    insert_experiment(conn, exp)
    return exp


# ---------------------------------------------------------------------------------------------
# 2. Lifecycle: Start, Pause, Resume, Abandon
# ---------------------------------------------------------------------------------------------
def start_experiment(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> Experiment:
    """
    Transition an offered experiment to active.
    Freezes metric definition and baseline as of start date.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    if exp.status != "offered":
        raise ValueError(f"Cannot start experiment in status: {exp.status}")

    cfg = load_experiments_config()
    active_exps = list_experiments(conn, user_id, status="active")
    if len(active_exps) >= cfg.limits.max_active:
        raise ValueError(f"Maximum active experiments ({cfg.limits.max_active}) already reached.")

    categories = exp.metric_def_json.get("categories", [])
    if categories:
        for active in active_exps:
            active_cats = active.metric_def_json.get("categories", [])
            for cat in categories:
                if cat in active_cats:
                    raise ValueError(
                        f"Active experiment already exists on category '{cat}' (id: {active.id})"
                    )

    now_dt = clock or now_utc()
    now_ist = now_dt.astimezone(IST)
    w_start_date = now_ist.date()

    # Preserve duration days
    orig_start = date.fromisoformat(exp.window_start)
    orig_end = date.fromisoformat(exp.window_end)
    duration_days = (orig_end - orig_start).days + 1

    new_end_date = w_start_date + timedelta(days=duration_days - 1)
    new_start_str = w_start_date.isoformat()
    new_end_str = new_end_date.isoformat()

    # Re-calculate and freeze baseline as of actual start date
    base, _ = calculate_baseline(
        conn,
        user_id,
        metric_code=exp.metric_def_json["metric_code"],
        start_date=new_start_str,
        duration_days=duration_days,
        params=exp.params_json,
        k=6,
    )

    baseline_json = base.model_dump() if base else exp.baseline_json

    update_experiment_start(
        conn=conn,
        user_id=user_id,
        experiment_id=experiment_id,
        window_start=new_start_str,
        window_end=new_end_str,
        started_at=to_utc_iso(now_dt),
        baseline_json=baseline_json,
        metric_def_json=exp.metric_def_json,
    )

    updated = get_experiment(conn, user_id, experiment_id)
    assert updated is not None
    return updated


def pause_experiment(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    reason: str = "user_paused",
    clock: datetime | None = None,
) -> Experiment:
    """Transition active experiment to paused."""
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    if exp.status != "active":
        raise ValueError(f"Cannot pause experiment in status: {exp.status}")

    update_experiment_status(conn, user_id, experiment_id, "paused")
    updated = get_experiment(conn, user_id, experiment_id)
    assert updated is not None
    return updated


def resume_experiment(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> Experiment:
    """Transition paused experiment back to active."""
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    if exp.status != "paused":
        raise ValueError(f"Cannot resume experiment in status: {exp.status}")

    update_experiment_status(conn, user_id, experiment_id, "active")
    updated = get_experiment(conn, user_id, experiment_id)
    assert updated is not None
    return updated


def abandon_experiment(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    reason: str = "user_abandoned",
    clock: datetime | None = None,
) -> tuple[Experiment, ExperimentReview]:
    """
    Abandon an experiment at any point without penalty or negative wording.
    Immediately creates a learning review.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    if exp.status not in ("active", "paused"):
        raise ValueError(f"Cannot abandon experiment in status: {exp.status}")

    now_dt = clock or now_utc()
    now_ist = now_dt.astimezone(IST)
    update_experiment_status(conn, user_id, experiment_id, "abandoned", ended_at=to_utc_iso(now_dt))

    # Calculate observed metric up to current date
    cur_date_str = now_ist.date().isoformat()
    obs_val = observed_value(conn, user_id, exp, cur_date_str)

    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    rev = ExperimentReview(
        id=review_id,
        user_id=user_id,
        experiment_id=experiment_id,
        observed_value=obs_val,
        outcome="no_baseline",
        rank_p_bp=10000,
        effect_value=0,
        target_met=False,
        integrity_json={"notes": "Abandoned early by user; zero penalty."},
        data_quality_json={
            "narrative": (
                "Experiment was concluded early. "
                "Taking time to test and learn is valuable financial practice."
            ),
            "reason": reason,
            "abandoned": True,
        },
        user_difficulty=None,
        user_helpful=None,
        user_would_repeat=None,
        created_at=to_utc_iso(now_dt),
    )
    insert_experiment_review(conn, rev)

    updated_exp = get_experiment(conn, user_id, experiment_id)
    assert updated_exp is not None
    return updated_exp, rev


# ---------------------------------------------------------------------------------------------
# 3. Check-ins
# ---------------------------------------------------------------------------------------------
def create_checkins(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> list[ExperimentCheckin]:
    """
    Runtime job: create scheduled weekly check-ins for active experiments.
    """
    cfg = load_experiments_config()
    now_dt = clock or now_utc()
    now_d = now_dt.astimezone(IST).date()

    active_exps = list_experiments(conn, user_id, status="active")
    created: list[ExperimentCheckin] = []

    for exp in active_exps:
        w_start = date.fromisoformat(exp.window_start)
        w_end = date.fromisoformat(exp.window_end)

        existing_checkins = list_experiment_checkins(conn, user_id, exp.id)
        existing_dates = {c.checkin_date for c in existing_checkins}

        # Scheduled checkins every N days
        cur_checkin_d = w_start + timedelta(days=cfg.checkins.every_days)
        while cur_checkin_d <= w_end and cur_checkin_d <= now_d:
            d_str = cur_checkin_d.isoformat()
            if d_str not in existing_dates:
                obs = observed_value(conn, user_id, exp, d_str)
                pace = calculate_pace(
                    observed_value=obs,
                    target_value=exp.target_value,
                    start_date=exp.window_start,
                    end_date=exp.window_end,
                    as_of_date=d_str,
                    metric_code=exp.metric_def_json["metric_code"],
                )
                chk = ExperimentCheckin(
                    id=f"chk_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    experiment_id=exp.id,
                    checkin_date=d_str,
                    observed_value=obs,
                    pace_status=pace,
                    user_response=None,
                    created_at=to_utc_iso(now_dt),
                )
                insert_experiment_checkin(conn, chk)
                created.append(chk)
                existing_dates.add(d_str)

            cur_checkin_d += timedelta(days=cfg.checkins.every_days)

    return created


def answer_checkin(
    conn: sqlite3.Connection,
    user_id: str,
    checkin_id: str,
    response: str,
    note: str | None = None,
    clock: datetime | None = None,
) -> ExperimentCheckin:
    """
    Answer a scheduled check-in. Valid responses: 'going_well', 'hard', 'want_to_pause', 'skip'.
    If 'want_to_pause', generates an adjustment proposal.
    """
    valid_responses = {"going_well", "hard", "want_to_pause", "skip"}
    if response not in valid_responses:
        raise ValueError(
            f"Invalid response '{response}'. Must be one of: {sorted(valid_responses)}"
        )

    chk = get_experiment_checkin(conn, user_id, checkin_id)
    if chk is None:
        raise ValueError(f"Check-in not found: {checkin_id}")

    update_experiment_checkin_response(conn, user_id, checkin_id, response)

    now_dt = clock or now_utc()
    if response == "want_to_pause":
        prop = AdjustmentProposal(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            experiment_id=chk.experiment_id,
            kind="pause",
            reason_code="checkin_requested_pause",
            params_json={"note": note or ""},
            status="proposed",
            created_at=to_utc_iso(now_dt),
            decided_at=None,
        )
        insert_adjustment_proposal(conn, prop)

    updated = get_experiment_checkin(conn, user_id, checkin_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------------------------
# 4. Reviews & Goal Linking
# ---------------------------------------------------------------------------------------------
def create_due_reviews(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> list[ExperimentReview]:
    """
    Runtime job: creates reviews when window ends + delay_days has passed.
    Sets experiment status to 'completed'.
    Computes deterministic outcomes, integrity notes, and optional goal links.
    """
    cfg = load_experiments_config()
    now_dt = clock or now_utc()
    now_d = now_dt.astimezone(IST).date()

    active_exps = list_experiments(conn, user_id, status="active")
    reviews: list[ExperimentReview] = []

    for exp in active_exps:
        w_end = date.fromisoformat(exp.window_end)
        due_d = w_end + timedelta(days=cfg.review.delay_days)
        if now_d >= due_d:
            # 1. Complete experiment
            update_experiment_status(
                conn, user_id, exp.id, "completed", ended_at=to_utc_iso(now_dt)
            )

            # 2. Compute observed value across full window
            obs_val = observed_value(conn, user_id, exp, exp.window_end)

            # 3. Evaluate outcome
            base: Baseline | None = None
            if exp.baseline_json and exp.baseline_json.get("k", 0) >= 3:
                base = Baseline.model_validate(exp.baseline_json)

            baseline_cfg = load_baseline_config()
            outcome, rank_p, effect_val, target_met = evaluate_outcome(
                observed_value=obs_val,
                baseline=base,
                target_value=exp.target_value,
                metric_code=exp.metric_def_json["metric_code"],
                min_effect_share_bp=baseline_cfg.min_effect_share_bp,
                min_effect_paise=baseline_cfg.min_effect_paise,
            )

            # 4. Integrity notes
            integrity = calculate_integrity_notes(
                conn,
                user_id,
                start_date=exp.window_start,
                end_date=exp.window_end,
                target_value=exp.target_value,
                observed_value=obs_val,
                categories=exp.metric_def_json.get("categories", []),
                metric_code=exp.metric_def_json["metric_code"],
            )

            # 5. Review narrative (no causal claims)
            m_code = exp.metric_def_json["metric_code"]
            dir_str = "below" if effect_val > 0 else "above"
            if base is not None:
                narrative = (
                    f"Your {metric_label(m_code)} was {format_metric(m_code, obs_val)}, "
                    f"{format_metric(m_code, abs(effect_val))} {dir_str} your usual median "
                    f"of {format_metric(m_code, base.median)} "
                    f"(range {format_metric(m_code, base.low)} to "
                    f"{format_metric(m_code, base.high)})."
                )
            else:
                narrative = (
                    f"Your {metric_label(m_code)} was {format_metric(m_code, obs_val)} "
                    "(no baseline comparison)."
                )

            # 6. Goal linking using Phase 3 maths (never promises goal will be reached)
            goal_narrative: str | None = None
            if exp.goal_id:
                goal = get_goal(conn, user_id, exp.goal_id)
                if goal is not None:
                    curr_paise = goal_current_paise(conn, user_id, goal)
                    rem_gap = max(0, goal.target_paise - curr_paise)
                    if rem_gap > 0 and effect_val > 0:
                        share_pct = (effect_val * 100) // rem_gap
                        goal_narrative = (
                            f"₹{effect_val // 100} would cover {share_pct}% of the remaining "
                            f"gap for goal '{goal.name}'."
                        )

            span_days = (w_end - date.fromisoformat(exp.window_start)).days + 1
            measured = span_days - len(paused_days(exp))
            data_quality = {
                "narrative": narrative,
                "goal_link_narrative": goal_narrative,
                "days_measured": measured,
                "days_in_window": span_days,
                # Fewer days than the comparison windows is not a like-for-like comparison
                "not_like_for_like": base is not None and measured < comparison_days(exp),
            }

            rev = ExperimentReview(
                id=f"rev_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                experiment_id=exp.id,
                observed_value=obs_val,
                outcome=outcome,
                rank_p_bp=rank_p,
                effect_value=effect_val,
                target_met=target_met,
                integrity_json=integrity.model_dump(),
                data_quality_json=data_quality,
                user_difficulty=None,
                user_helpful=None,
                user_would_repeat=None,
                created_at=to_utc_iso(now_dt),
            )
            insert_experiment_review(conn, rev)
            reviews.append(rev)

    return reviews


def submit_review_feedback(
    conn: sqlite3.Connection,
    user_id: str,
    review_id: str,
    difficulty_rating: int | None = None,
    user_helpful: bool | None = None,
    would_repeat: bool | None = None,
    feedback_text: str | None = None,
    clock: datetime | None = None,
) -> ExperimentReview:
    """
    Submit optional review feedback for an experiment.
    Transitions experiment to 'reviewed'.
    """
    rev = get_experiment_review_by_id(conn, user_id, review_id)
    if rev is None:
        raise ValueError(f"Review not found: {review_id}")

    if difficulty_rating is not None and not (1 <= difficulty_rating <= 5):
        raise ValueError("difficulty_rating must be between 1 and 5")

    update_experiment_review_feedback(
        conn,
        user_id,
        review_id,
        user_difficulty=difficulty_rating,
        user_helpful=user_helpful,
        user_would_repeat=would_repeat,
    )
    update_experiment_status(conn, user_id, rev.experiment_id, "reviewed")

    updated = get_experiment_review_by_id(conn, user_id, review_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------------------------
# 5. Progress Tracking
# ---------------------------------------------------------------------------------------------
def get_experiment_progress(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> ExperimentProgress:
    """
    Compute real-time progress, expected value, and pace for an active or completed experiment.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment not found: {experiment_id}")

    now_dt = clock or now_utc()
    now_d = now_dt.astimezone(IST).date()
    w_start = date.fromisoformat(exp.window_start)
    w_end = date.fromisoformat(exp.window_end)

    as_of_date = min(max(w_start, now_d), w_end)
    as_of_str = as_of_date.isoformat()

    obs = observed_value(conn, user_id, exp, as_of_str)

    pace = calculate_pace(
        observed_value=obs,
        target_value=exp.target_value,
        start_date=exp.window_start,
        end_date=exp.window_end,
        as_of_date=as_of_str,
        metric_code=exp.metric_def_json["metric_code"],
    )

    total_days = (w_end - w_start).days + 1
    elapsed_days = max(1, min(total_days, (as_of_date - w_start).days + 1))
    checkins = list_experiment_checkins(conn, user_id, experiment_id)

    return ExperimentProgress(
        observed_value=obs,
        target_value=exp.target_value,
        pace_status=pace,
        elapsed_days=elapsed_days,
        total_days=total_days,
        checkins_count=len(checkins),
    )
