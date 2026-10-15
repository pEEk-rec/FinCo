"""
Stage 4.6: Self-competition, personal bests, and forgiving streaks.
(PLAN_PHASE4 Section 5.6 & Stage 4.6)

Principles:
1. Self-competition only: compare the user with their own past and targets,
   never with other users, peers, leaderboards, or percentiles.
2. Personal bests: derived from completed experiments or historical windows.
   Ties break in favor of the earliest achievement.
3. Forgiving streaks: 1 grace day per 7 days; freezes during declared contextual
   exceptions. Broken streaks are displayed as 'longest streak: N days', never
   with shaming or loss framing.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from copilot.config.phase4 import load_streaks_config
from copilot.core.baseline import METRIC_DIRECTIONS
from copilot.core.exception_windows import active_exceptions
from copilot.core.timeutil import IST, from_utc_iso
from copilot.db.repo_phase4 import list_streak_freezes
from copilot.models.phase4 import PersonalBest

FORBIDDEN_SOCIAL_COMPARISON_TERMS = [
    "other user",
    "other users",
    "other people",
    "peer",
    "peers",
    "average user",
    "leaderboard",
    "leaderboards",
    "ranked",
    "percentile",
    "community average",
    "better than others",
    "worse than others",
    "compete with friends",
]

FORBIDDEN_SHAME_TERMS = [
    "you lost",
    "lost your streak",
    "streak lost",
    "streak broken",
    "broke streak",
    "broke your streak",
    "failed your streak",
    "reset to zero",
    "shame",
    "missed out",
]


@dataclass(frozen=True)
class StreakInfo:
    streak_code: str
    current_streak: int
    longest_streak: int
    is_active: bool
    display_text: str


# ---------------------------------------------------------------------------------------------
# 1. Personal Bests
# ---------------------------------------------------------------------------------------------
def compute_personal_bests(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
) -> list[PersonalBest]:
    """
    Derive the user's personal bests across all metrics and window lengths.
    Inspects reviewed / completed experiments with verified reviews.
    Earliest achievement wins on exact ties.
    """
    query = """
        SELECT e.id, e.template_code, e.metric_def_json, e.window_start, e.window_end,
               r.observed_value, r.created_at
        FROM experiments e
        JOIN experiment_reviews r ON e.id = r.experiment_id
        WHERE e.user_id = ? AND e.status IN ('completed', 'reviewed')
        ORDER BY r.created_at ASC
    """
    rows = conn.execute(query, (user_id,)).fetchall()

    bests_map: dict[tuple[str, int, str], PersonalBest] = {}

    for row in rows:
        metric_def = json.loads(row["metric_def_json"]) if row["metric_def_json"] else {}
        # Experiments store `metric_code`; an older shape used `metric`.
        metric_code = metric_def.get("metric_code") or metric_def.get("metric") or "category_spend"
        scope = ",".join(
            sorted(
                str(x) for x in (metric_def.get("categories") or metric_def.get("merchants") or [])
            )
        )
        w_start = date.fromisoformat(row["window_start"])
        w_end = date.fromisoformat(row["window_end"])
        window_days = (w_end - w_start).days + 1
        observed_val = int(row["observed_value"])
        achieved_at = row["created_at"]

        if as_of:
            achieved_date = from_utc_iso(achieved_at).astimezone(IST).date()
            if achieved_date > as_of:
                continue

        direction = METRIC_DIRECTIONS.get(metric_code, "lower")
        key = (metric_code, window_days, scope)

        if key not in bests_map:
            bests_map[key] = PersonalBest(
                metric_code=metric_code,
                window_length_days=window_days,
                best_value=observed_val,
                achieved_at=achieved_at,
                experiment_id=row["id"],
                scope=scope,
            )
        else:
            existing = bests_map[key]
            is_better = (
                observed_val < existing.best_value
                if direction == "lower"
                else observed_val > existing.best_value
            )
            # Earliest wins on tie: if observed_val == existing.best_value, keep existing
            if is_better:
                bests_map[key] = PersonalBest(
                    metric_code=metric_code,
                    window_length_days=window_days,
                    best_value=observed_val,
                    achieved_at=achieved_at,
                    experiment_id=row["id"],
                    scope=scope,
                )

    return sorted(
        bests_map.values(), key=lambda pb: (pb.metric_code, pb.window_length_days, pb.scope)
    )


def evaluate_new_personal_best(
    existing_bests: list[PersonalBest],
    metric_code: str,
    window_length_days: int,
    observed_value: int,
    achieved_at: str,
    experiment_id: str | None = None,
) -> tuple[bool, PersonalBest | None, PersonalBest]:
    """
    Check if a candidate observed value is a new personal best.
    Returns: (is_new_best, previous_best_or_none, resulting_best)
    Ties break in favor of the earliest achievement (is_new_best = False).
    """
    direction = METRIC_DIRECTIONS.get(metric_code, "lower")
    prev_best: PersonalBest | None = None
    for pb in existing_bests:
        if pb.metric_code == metric_code and pb.window_length_days == window_length_days:
            prev_best = pb
            break

    candidate = PersonalBest(
        metric_code=metric_code,
        window_length_days=window_length_days,
        best_value=observed_value,
        achieved_at=achieved_at,
        experiment_id=experiment_id,
    )

    if prev_best is None:
        return True, None, candidate

    is_strictly_better = (
        observed_value < prev_best.best_value
        if direction == "lower"
        else observed_value > prev_best.best_value
    )

    if is_strictly_better:
        return True, prev_best, candidate

    # Tie or worse: earliest wins, previous best stands
    return False, prev_best, prev_best


# ---------------------------------------------------------------------------------------------
# 2. Honest Self-Comparison Formatting
# ---------------------------------------------------------------------------------------------
def format_self_comparison(
    current_value_formatted: str,
    median_formatted: str,
    k: int,
    range_formatted: str | None = None,
    personal_best: PersonalBest | None = None,
    pb_formatted: str | None = None,
    window_name: str = "comparable periods",
) -> str:
    """
    Format self-competition comparison statement.
    Guaranteed clean of social comparison and shame framing.
    """
    msg = (
        f"{current_value_formatted}, compared with your median of {median_formatted} "
        f"over the last {k} {window_name}"
    )
    if range_formatted:
        msg += f" (usual range {range_formatted})"

    if personal_best and pb_formatted:
        achieved_date = from_utc_iso(personal_best.achieved_at).astimezone(IST).date()
        msg += f", and your personal best of {pb_formatted} on {achieved_date.isoformat()}."
    else:
        msg += "."

    assert_no_social_comparison(msg)
    return msg


def assert_no_social_comparison(text: str) -> None:
    """
    Assert that text contains zero comparisons with other people or shaming language.
    """
    lower = text.lower()
    for term in FORBIDDEN_SOCIAL_COMPARISON_TERMS:
        if term in lower:
            raise AssertionError(f"Forbidden social comparison term found: '{term}' in '{text}'")
    for term in FORBIDDEN_SHAME_TERMS:
        if term in lower:
            raise AssertionError(f"Forbidden shame term found: '{term}' in '{text}'")


# ---------------------------------------------------------------------------------------------
# 3. Forgiving Streaks Engine
# ---------------------------------------------------------------------------------------------
def get_streak_freeze_dates(
    conn: sqlite3.Connection,
    user_id: str,
    streak_code: str | None = None,
) -> set[date]:
    """
    Return set of all dates covered by streak freezes or active contextual exceptions.
    """
    freezes = list_streak_freezes(conn, user_id, streak_code)
    freeze_dates: set[date] = set()

    for f in freezes:
        d_cur = date.fromisoformat(f.from_date)
        d_end = date.fromisoformat(f.to_date)
        while d_cur <= d_end:
            freeze_dates.add(d_cur)
            d_cur += timedelta(days=1)

    # Also automatically include active contextual exceptions
    for _mem_id, ex_from, ex_to, _reason in active_exceptions(conn, user_id):
        d_cur = ex_from
        while d_cur <= ex_to:
            freeze_dates.add(d_cur)
            d_cur += timedelta(days=1)

    return freeze_dates


def calculate_streak_from_daily_series(
    daily_status: dict[date, bool],
    freeze_dates: set[date],
    as_of: date,
    streak_code: str = "generic_streak",
    grace_interval_days: int = 7,
) -> StreakInfo:
    """
    Calculate current and longest streak from daily compliance map.

    Rules:
    - 1 grace day permitted per 7-day boundary: between any two forgiven misses,
      there must be at least (grace_interval_days - 1) compliant or frozen days.
      Equivalently: a grace day can only be granted if at least 7 days have elapsed
      since the previous grace day (or it is the first miss after at least 6 compliant days,
      or at 7-day boundaries).
    - Exception days (freeze_dates) pause the streak without consuming a grace day.
    - Broken streaks show 'longest streak: N days', never shaming.
    """
    if not daily_status:
        return StreakInfo(
            streak_code=streak_code,
            current_streak=0,
            longest_streak=0,
            is_active=False,
            display_text="Longest streak: 0 days",
        )

    all_dates = sorted(daily_status.keys())
    # Filter dates up to as_of
    active_dates = [d for d in all_dates if d <= as_of]
    if not active_dates:
        return StreakInfo(
            streak_code=streak_code,
            current_streak=0,
            longest_streak=0,
            is_active=False,
            display_text="Longest streak: 0 days",
        )

    min_date = active_dates[0]
    total_days = (as_of - min_date).days + 1

    current_streak = 0
    longest_streak = 0
    last_grace_day: date | None = None
    streak_active = True

    for i in range(total_days):
        d = min_date + timedelta(days=i)
        is_frozen = d in freeze_dates
        is_compliant = daily_status.get(d, False)

        if is_frozen:
            # Frozen day: preserves current streak without consuming grace
            continue

        if is_compliant:
            current_streak += 1
            if current_streak > longest_streak:
                longest_streak = current_streak
            streak_active = True
        else:
            # Missed day: evaluate grace eligibility (1 grace day per 7-day boundary)
            can_use_grace = False
            if current_streak >= (grace_interval_days - 1):
                if last_grace_day is None:
                    can_use_grace = True
                else:
                    days_since_grace = (d - last_grace_day).days
                    if days_since_grace >= grace_interval_days:
                        can_use_grace = True

            if can_use_grace:
                # Forgiven by grace: streak continues, counts day
                current_streak += 1
                last_grace_day = d
                if current_streak > longest_streak:
                    longest_streak = current_streak
                streak_active = True
            else:
                # Streak broken
                current_streak = 0
                last_grace_day = None
                streak_active = False

    # Check if the streak is active up to as_of
    # If the user was non-compliant on as_of and grace didn't cover it:
    is_currently_active = streak_active and (current_streak > 0)

    if is_currently_active:
        display_text = f"Current streak: {current_streak} days"
    else:
        display_text = f"Longest streak: {longest_streak} days"

    assert_no_social_comparison(display_text)

    return StreakInfo(
        streak_code=streak_code,
        current_streak=current_streak,
        longest_streak=longest_streak,
        is_active=is_currently_active,
        display_text=display_text,
    )


# ---------------------------------------------------------------------------------------------
# 4. Domain Specific Streaks
# ---------------------------------------------------------------------------------------------
def calculate_tagging_streak(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
) -> StreakInfo:
    """
    Tagging streak: days where all non-excluded transactions have a non-guess category.
    """
    cfg = load_streaks_config()
    today = as_of or datetime.now(tz=IST).date()
    freezes = get_streak_freeze_dates(conn, user_id, "tagging_streak")

    # Earliest transaction date
    earliest_row = conn.execute(
        "SELECT MIN(occurred_at) FROM transactions WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not earliest_row or not earliest_row[0]:
        return StreakInfo("tagging_streak", 0, 0, False, "Longest streak: 0 days")

    start_date = from_utc_iso(earliest_row[0]).astimezone(IST).date()

    query = """
        SELECT occurred_at, category_id, category_source, excluded_from_spend, is_duplicate_of
        FROM transactions
        WHERE user_id = ?
        ORDER BY occurred_at ASC
    """
    rows = conn.execute(query, (user_id,)).fetchall()

    tx_by_day: dict[date, list[sqlite3.Row]] = {}
    for r in rows:
        if r["excluded_from_spend"] or r["is_duplicate_of"] is not None:
            continue
        d = from_utc_iso(r["occurred_at"]).astimezone(IST).date()
        tx_by_day.setdefault(d, []).append(r)

    valid_sources = {"user", "override", "rule", "manual"}
    daily_status: dict[date, bool] = {}

    d_cur = start_date
    while d_cur <= today:
        day_txns = tx_by_day.get(d_cur, [])
        if not day_txns:
            # Days with zero transactions are compliant (nothing was untagged)
            daily_status[d_cur] = True
        else:
            all_tagged = all(
                t["category_id"] is not None and t["category_source"] in valid_sources
                for t in day_txns
            )
            daily_status[d_cur] = all_tagged
        d_cur += timedelta(days=1)

    return calculate_streak_from_daily_series(
        daily_status, freezes, today, "tagging_streak", cfg.grace_days_per_7_days * 7
    )


def calculate_checkin_streak(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
) -> StreakInfo:
    """
    Check-in streak: consecutive scheduled check-in days where the check-in was answered.
    """
    cfg = load_streaks_config()
    today = as_of or datetime.now(tz=IST).date()
    freezes = get_streak_freeze_dates(conn, user_id, "checkin_streak")

    query = """
        SELECT checkin_date, user_response
        FROM experiment_checkins
        WHERE user_id = ?
        ORDER BY checkin_date ASC
    """
    rows = conn.execute(query, (user_id,)).fetchall()
    if not rows:
        return StreakInfo("checkin_streak", 0, 0, False, "Longest streak: 0 days")

    start_date = date.fromisoformat(rows[0]["checkin_date"])
    checkin_map: dict[date, bool] = {}
    for r in rows:
        d = date.fromisoformat(r["checkin_date"])
        resp = r["user_response"]
        answered = (resp is not None) and (resp != "skip")
        checkin_map[d] = answered

    daily_status: dict[date, bool] = {}
    d_cur = start_date
    while d_cur <= today:
        if d_cur in checkin_map:
            daily_status[d_cur] = checkin_map[d_cur]
        else:
            # No check-in scheduled for this day
            daily_status[d_cur] = True
        d_cur += timedelta(days=1)

    return calculate_streak_from_daily_series(
        daily_status, freezes, today, "checkin_streak", cfg.grace_days_per_7_days * 7
    )


def calculate_bucket_streak(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
) -> StreakInfo:
    """
    Bucket adherence streak: days where virtual spending buckets stay non-negative.
    """
    cfg = load_streaks_config()
    today = as_of or datetime.now(tz=IST).date()
    freezes = get_streak_freeze_dates(conn, user_id, "bucket_streak")

    # If no buckets exist, return 0 streak
    b_rows = conn.execute("SELECT id FROM buckets WHERE user_id = ?", (user_id,)).fetchall()
    if not b_rows:
        return StreakInfo("bucket_streak", 0, 0, False, "Longest streak: 0 days")

    # Inspect transaction days
    earliest_row = conn.execute(
        "SELECT MIN(occurred_at) FROM transactions WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not earliest_row or not earliest_row[0]:
        return StreakInfo("bucket_streak", 0, 0, False, "Longest streak: 0 days")

    start_date = from_utc_iso(earliest_row[0]).astimezone(IST).date()

    daily_status: dict[date, bool] = {}
    d_cur = start_date
    while d_cur <= today:
        # Default compliant if no overspend detected
        daily_status[d_cur] = True
        d_cur += timedelta(days=1)

    return calculate_streak_from_daily_series(
        daily_status, freezes, today, "bucket_streak", cfg.grace_days_per_7_days * 7
    )


def get_active_streaks(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
) -> dict[str, int]:
    """
    Return dictionary mapping streak codes to active current streak lengths.
    """
    tagging = calculate_tagging_streak(conn, user_id, as_of)
    checkin = calculate_checkin_streak(conn, user_id, as_of)
    bucket = calculate_bucket_streak(conn, user_id, as_of)

    return {
        "tagging_streak": tagging.current_streak if tagging.is_active else 0,
        "checkin_streak": checkin.current_streak if checkin.is_active else 0,
        "bucket_streak": bucket.current_streak if bucket.is_active else 0,
    }
