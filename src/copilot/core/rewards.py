"""
Stage 4.7: Progress, XP rules, allowlist enforcement, badges, and copy safety.
(PLAN_PHASE4 Section 5.7, 5.8 & Stage 4.7)

Key rules:
1. XP allowlist: rewards attach only to healthy financial behaviours on an allowlist.
   Never reward: reductions in essential categories, skipping commitments,
   contribution amounts, transaction volume, or borrowing.
2. Idempotent awarding: xp_events unique constraint ensures no event is awarded twice.
3. Daily cap: XP is capped at daily_cap (default 100); XP never decreases.
4. Learning rewarded: finishing an abandoned-and-reviewed experiment earns learning XP.
5. Integrity check: if confirmation_required is True on a review, target_met XP
   is blocked until user confirmation is confirmed.
6. Badges: catalogue with deterministic predicates, awarded once with evidence.
7. Anti-addiction & Copy safety: zero pressure phrases, zero shame framing, zero social comparison.
"""

import sqlite3
import uuid
from datetime import datetime
from typing import Any

from copilot.config.phase4 import (
    RewardsConfig,
    load_phase4_safety_config,
    load_rewards_config,
)
from copilot.core.self_competition import (
    assert_no_social_comparison,
    calculate_checkin_streak,
    calculate_tagging_streak,
    compute_personal_bests,
    get_active_streaks,
)
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.repo_phase4 import (
    get_experiment,
    get_experiment_review,
    get_experiment_review_by_id,
    get_user_xp_for_day,
    get_user_xp_total,
    has_badge,
    insert_badge_award,
    insert_xp_event,
    list_badge_awards,
    list_experiment_reviews,
    update_experiment_review_integrity,
)
from copilot.models.phase4 import BadgeAward, ExperimentReview, Progress, XpEvent


# ---------------------------------------------------------------------------------------------
# 1. Static Rule Validation
# ---------------------------------------------------------------------------------------------
def validate_reward_rules(cfg: RewardsConfig | None = None) -> None:
    """
    Statically verify that no reward rule references forbidden metrics or categories.
    Fails if a rule references essential categories, skipping commitments, borrowing,
    or investment/contribution amounts.
    """
    c = cfg or load_rewards_config()
    forbidden_terms = set(c.forbidden_metrics_and_categories.metrics) | set(
        c.forbidden_metrics_and_categories.categories
    )

    for rule_name, rule in c.rules.items():
        rule_lower = rule_name.lower()
        desc_lower = rule.description.lower()
        for term in forbidden_terms:
            stems = [term, term.rstrip("s")] if term.endswith("s") else [term, f"{term}s"]
            for s in stems:
                if s in rule_lower:
                    raise ValueError(f"XP rule '{rule_name}' references forbidden term '{term}'")
                if (
                    f"skip {s}" in desc_lower
                    or f"reduce {s}" in desc_lower
                    or f"cutting {s}" in desc_lower
                    or f"delay {s}" in desc_lower
                    or "borrowing" in desc_lower
                    or "trading" in desc_lower
                ):
                    raise ValueError(
                        f"XP rule '{rule_name}' description encourages risky behaviour '{term}'"
                    )


# ---------------------------------------------------------------------------------------------
# 2. XP Awarding Engine
# ---------------------------------------------------------------------------------------------
def award_xp(
    conn: sqlite3.Connection,
    user_id: str,
    rule_code: str,
    ref_kind: str,
    ref_id: str,
    period_day: str | None = None,
    clock: datetime | None = None,
) -> XpEvent | None:
    """
    Award XP according to allowlisted rules with daily cap and idempotency protection.

    Returns the created XpEvent if awarded, or None if:
    - Rule is not in the allowlist
    - Event was already awarded (idempotency key: user_id, rule_code, ref_kind, ref_id)
    - Daily cap reached for period_day
    """
    cfg = load_rewards_config()
    if rule_code not in cfg.rules:
        raise ValueError(f"Rule code '{rule_code}' is not in the approved XP allowlist.")

    rule = cfg.rules[rule_code]
    now_dt = clock or datetime.now(tz=IST)
    now_iso = to_utc_iso(now_dt)
    day_str = period_day or now_dt.astimezone(IST).date().isoformat()

    daily_cap = cfg.xp.daily_cap
    daily_current = get_user_xp_for_day(conn, user_id, day_str)
    remaining_cap = max(0, daily_cap - daily_current)

    if remaining_cap <= 0:
        return None

    # Award points floored by remaining daily cap and max_daily_share
    points_to_award = min(rule.points, remaining_cap)
    if points_to_award <= 0:
        return None

    event = XpEvent(
        id=f"xp_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        rule_code=rule_code,
        points=points_to_award,
        ref_kind=ref_kind,
        ref_id=ref_id,
        period_day=day_str,
        created_at=now_iso,
    )

    inserted = insert_xp_event(conn, event)
    if not inserted:
        # Already awarded (idempotent duplicate)
        return None

    return event


def can_award_target_met_xp(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
) -> bool:
    """
    Check if target_met XP can be awarded.
    If integrity check flagged confirmation_required, user confirmation is required.
    """
    rev = get_experiment_review(conn, user_id, experiment_id)
    if rev is None or not rev.target_met:
        return False

    integ = rev.integrity_json or {}
    if integ.get("confirmation_required") is True:
        # User confirmation must be explicitly recorded
        if not integ.get("user_confirmed"):
            return False

    return True


def confirm_review_integrity(
    conn: sqlite3.Connection,
    user_id: str,
    review_id: str,
    clock: datetime | None = None,
) -> ExperimentReview:
    """
    The user confirms that payments recategorised during the window were genuine corrections.

    Only a review the integrity check flagged can be confirmed. Confirming lets the
    `target_met` XP be awarded (PLAN_PHASE4 section 5.2); it never changes the measurement.
    """
    review = get_experiment_review_by_id(conn, user_id, review_id)
    if review is None:
        raise ValueError(f"Review not found: {review_id}")
    integrity = dict(review.integrity_json or {})
    if integrity.get("confirmation_required") is not True:
        raise ValueError("This review has nothing to confirm.")
    integrity["user_confirmed"] = True
    integrity["confirmed_at"] = to_utc_iso(clock or datetime.now(tz=IST))
    update_experiment_review_integrity(conn, user_id, review_id, integrity)
    updated = get_experiment_review_by_id(conn, user_id, review_id)
    assert updated is not None
    return updated


def award_experiment_outcome_xp(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[XpEvent]:
    """
    Award completion and outcome XP for an experiment.
    - Completed experiment: earns 'experiment_completed' (40 pts)
    - Abandoned + reviewed: earns 'experiment_reviewed_abandoned' (20 pts, learning)
    - Target met (passing integrity): earns 'target_met' (30 pts)

    Whether an experiment was abandoned is read from its review, because the status moves on to
    'reviewed' once the user gives feedback and no longer says how it ended.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None:
        return []
    review = get_experiment_review(conn, user_id, experiment_id)
    was_abandoned = exp.status == "abandoned" or bool(
        review is not None and (review.data_quality_json or {}).get("abandoned") is True
    )

    now_dt = clock or datetime.now(tz=IST)
    period_day = now_dt.astimezone(IST).date().isoformat()
    awarded: list[XpEvent] = []

    # 1. Completion / Learning Review XP
    if exp.status in ("completed", "reviewed") and not was_abandoned:
        ev = award_xp(
            conn,
            user_id,
            rule_code="experiment_completed",
            ref_kind="experiment",
            ref_id=experiment_id,
            period_day=period_day,
            clock=clock,
        )
        if ev:
            awarded.append(ev)
    elif was_abandoned:
        # Finishing an abandoned-and-reviewed experiment earns learning XP
        rev = review
        if rev is not None:
            ev = award_xp(
                conn,
                user_id,
                rule_code="experiment_reviewed_abandoned",
                ref_kind="experiment",
                ref_id=experiment_id,
                period_day=period_day,
                clock=clock,
            )
            if ev:
                awarded.append(ev)

    # 2. Target Met XP (requires integrity confirmation if flagged)
    if can_award_target_met_xp(conn, user_id, experiment_id):
        ev = award_xp(
            conn,
            user_id,
            rule_code="target_met",
            ref_kind="experiment",
            ref_id=experiment_id,
            period_day=period_day,
            clock=clock,
        )
        if ev:
            awarded.append(ev)

    return awarded


# ---------------------------------------------------------------------------------------------
# 3. Neutral Levels Engine
# ---------------------------------------------------------------------------------------------
def calculate_user_level(total_xp: int) -> tuple[int, str, int, int | None]:
    """
    Determine level number, neutral name, XP in current level, and XP for next level.
    Names are neutral (no 'rich' or 'wealthy').
    """
    cfg = load_rewards_config()
    thresholds = cfg.levels.thresholds
    names = cfg.levels.names

    level_idx = 0
    for idx, t in enumerate(thresholds):
        if total_xp >= t:
            level_idx = idx
        else:
            break

    level_number = level_idx + 1
    level_name = names[level_idx]
    current_threshold = thresholds[level_idx]
    xp_in_level = total_xp - current_threshold

    if level_idx + 1 < len(thresholds):
        next_threshold = thresholds[level_idx + 1]
        xp_for_next = next_threshold - current_threshold
    else:
        xp_for_next = None  # Max level reached

    return level_number, level_name, xp_in_level, xp_for_next


# ---------------------------------------------------------------------------------------------
# 4. Badges Catalogue with Deterministic Predicates
# ---------------------------------------------------------------------------------------------
def check_and_award_badges(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> list[BadgeAward]:
    """
    Evaluate deterministic predicates for all badges in config/badges.yaml.
    Awarded once with evidence. Idempotent.
    """
    now_dt = clock or datetime.now(tz=IST)
    now_iso = to_utc_iso(now_dt)
    newly_awarded: list[BadgeAward] = []

    def _try_award(badge_code: str, evidence: dict[str, Any]) -> None:
        if has_badge(conn, user_id, badge_code):
            return
        award = BadgeAward(
            id=f"bdg_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            badge_code=badge_code,
            awarded_at=now_iso,
            evidence_json=evidence,
        )
        if insert_badge_award(conn, award):
            newly_awarded.append(award)

    # 1. first_experiment_reviewed
    reviews = list_experiment_reviews(conn, user_id)
    if len(reviews) >= 1:
        _try_award(
            "first_experiment_reviewed",
            {"first_review_id": reviews[0].id, "experiment_id": reviews[0].experiment_id},
        )

    # 2. four_checkins_streak
    chk_streak = calculate_checkin_streak(conn, user_id, now_dt.astimezone(IST).date())
    if chk_streak.longest_streak >= 4 or chk_streak.current_streak >= 4:
        _try_award(
            "four_checkins_streak",
            {
                "current_streak": chk_streak.current_streak,
                "longest_streak": chk_streak.longest_streak,
            },
        )

    # 3. tag_master_week
    tag_streak = calculate_tagging_streak(conn, user_id, now_dt.astimezone(IST).date())
    if tag_streak.longest_streak >= 7 or tag_streak.current_streak >= 7:
        _try_award(
            "tag_master_week",
            {"tagging_streak_days": max(tag_streak.current_streak, tag_streak.longest_streak)},
        )

    # 4. first_personal_best
    bests = compute_personal_bests(conn, user_id)
    if len(bests) >= 1:
        _try_award(
            "first_personal_best",
            {
                "metric_code": bests[0].metric_code,
                "best_value": bests[0].best_value,
                "achieved_at": bests[0].achieved_at,
            },
        )

    # 5. emergency_anchor
    # Checked if user maintained emergency fund target
    try:
        ef_row = conn.execute(
            """
            SELECT id FROM goals
            WHERE user_id = ? AND kind = 'emergency_fund' AND current_paise >= target_paise
            """,
            (user_id,),
        ).fetchone()
        if ef_row:
            _try_award("emergency_anchor", {"goal_id": ef_row[0]})
    except Exception:
        pass

    # 6. goal_finisher
    try:
        goal_row = conn.execute(
            """
            SELECT id, name FROM goals
            WHERE user_id = ? AND kind != 'emergency_fund' AND current_paise >= target_paise
            """,
            (user_id,),
        ).fetchone()
        if goal_row:
            _try_award("goal_finisher", {"goal_id": goal_row[0], "goal_name": goal_row[1]})
    except Exception:
        pass

    # 7. thoughtful_reflector
    feedback_reviews = [
        r for r in reviews if r.user_difficulty is not None or r.user_helpful is not None
    ]
    if len(feedback_reviews) >= 3:
        _try_award(
            "thoughtful_reflector",
            {"count": len(feedback_reviews), "review_ids": [r.id for r in feedback_reviews[:3]]},
        )

    return newly_awarded


# ---------------------------------------------------------------------------------------------
# 5. Progress Summary Model
# ---------------------------------------------------------------------------------------------
def get_user_progress(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> Progress:
    """
    Derive the user's full progress representation:
    total XP, level info, badges, personal bests, active streaks.
    """
    now_dt = clock or datetime.now(tz=IST)
    today = now_dt.astimezone(IST).date()

    total_xp = get_user_xp_total(conn, user_id)
    lvl_num, lvl_name, xp_in_lvl, xp_next = calculate_user_level(total_xp)

    # Award any newly qualified badges
    check_and_award_badges(conn, user_id, clock)

    badges = list_badge_awards(conn, user_id)
    bests = compute_personal_bests(conn, user_id, today)
    streaks = get_active_streaks(conn, user_id, today)

    return Progress(
        total_xp=total_xp,
        level_number=lvl_num,
        level_name=lvl_name,
        xp_in_level=xp_in_lvl,
        xp_for_next_level=xp_next,
        badges=badges,
        personal_bests=bests,
        active_streaks=streaks,
    )


# ---------------------------------------------------------------------------------------------
# 6. Copy and Safety Scans
# ---------------------------------------------------------------------------------------------
def scan_copy_safety(text: str) -> None:
    """
    Verify that copy text is completely clean of pressure phrases, forbidden encouragements,
    shame terms, and social comparisons.
    """
    safety_cfg = load_phase4_safety_config()
    lower = text.lower()

    # 1. Pressure phrases (e.g., hurry, limited time, last chance)
    for phrase in safety_cfg.pressure_phrases:
        if phrase.lower() in lower:
            raise ValueError(f"Forbidden pressure phrase found: '{phrase}' in '{text}'")

    # 2. Forbidden encouragements (e.g., skip essentials, cut debt payments)
    for enc in safety_cfg.forbidden_encouragements:
        if enc.lower() in lower:
            raise ValueError(f"Forbidden encouragement phrase found: '{enc}' in '{text}'")

    # 3. Social comparisons and shame terms
    try:
        assert_no_social_comparison(text)
    except AssertionError as e:
        raise ValueError(str(e)) from e
