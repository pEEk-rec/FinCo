"""
Database repository functions for Phase 4 (PLAN_PHASE4 Section 4, Section 5).
All queries enforce strict multi-tenant isolation via `user_id = ?`.
"""

import json
import sqlite3
from typing import Any

from copilot.models.phase4 import (
    AdjustmentProposal,
    BadgeAward,
    Experiment,
    ExperimentCheckin,
    ExperimentReview,
    Offer,
    ProposalStatus,
    StreakFreeze,
    XpEvent,
)


# ---------------------------------------------------------------------------------------------
# 1. Experiments Repo
# ---------------------------------------------------------------------------------------------
def insert_experiment(conn: sqlite3.Connection, exp: Experiment) -> None:
    query = """
        INSERT INTO experiments (
            id, user_id, title, template_code, hypothesis_json, metric_def_json,
            params_json, difficulty, window_start, window_end, baseline_json,
            target_value, status, origin, offer_id, goal_id, created_at, started_at, ended_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            exp.id,
            exp.user_id,
            exp.title,
            exp.template_code,
            json.dumps(exp.hypothesis_json),
            json.dumps(exp.metric_def_json),
            json.dumps(exp.params_json),
            exp.difficulty,
            exp.window_start,
            exp.window_end,
            json.dumps(exp.baseline_json),
            exp.target_value,
            exp.status,
            exp.origin,
            exp.offer_id,
            exp.goal_id,
            exp.created_at,
            exp.started_at,
            exp.ended_at,
        ),
    )


def _row_to_experiment(row: sqlite3.Row) -> Experiment:
    return Experiment(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        template_code=row["template_code"],
        hypothesis_json=json.loads(row["hypothesis_json"]),
        metric_def_json=json.loads(row["metric_def_json"]),
        params_json=json.loads(row["params_json"]),
        difficulty=row["difficulty"],
        window_start=row["window_start"],
        window_end=row["window_end"],
        baseline_json=json.loads(row["baseline_json"]),
        target_value=row["target_value"],
        status=row["status"],
        origin=row["origin"],
        offer_id=row["offer_id"],
        goal_id=row["goal_id"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


def get_experiment(
    conn: sqlite3.Connection, user_id: str, experiment_id: str
) -> Experiment | None:
    query = "SELECT * FROM experiments WHERE user_id = ? AND id = ?"
    row = conn.execute(query, (user_id, experiment_id)).fetchone()
    if row is None:
        return None
    return _row_to_experiment(row)


def list_experiments(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
) -> list[Experiment]:
    if status:
        query = (
            "SELECT * FROM experiments WHERE user_id = ? AND status = ? "
            "ORDER BY window_start DESC"
        )
        rows = conn.execute(query, (user_id, status)).fetchall()
    else:
        query = "SELECT * FROM experiments WHERE user_id = ? ORDER BY window_start DESC"
        rows = conn.execute(query, (user_id,)).fetchall()
    return [_row_to_experiment(r) for r in rows]


def update_experiment_status(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    status: str,
    ended_at: str | None = None,
    started_at: str | None = None,
) -> None:
    if started_at and ended_at:
        query = (
            "UPDATE experiments SET status = ?, started_at = ?, ended_at = ? "
            "WHERE user_id = ? AND id = ?"
        )
        conn.execute(query, (status, started_at, ended_at, user_id, experiment_id))
    elif started_at:
        query = "UPDATE experiments SET status = ?, started_at = ? WHERE user_id = ? AND id = ?"
        conn.execute(query, (status, started_at, user_id, experiment_id))
    elif ended_at:
        query = "UPDATE experiments SET status = ?, ended_at = ? WHERE user_id = ? AND id = ?"
        conn.execute(query, (status, ended_at, user_id, experiment_id))
    else:
        query = "UPDATE experiments SET status = ? WHERE user_id = ? AND id = ?"
        conn.execute(query, (status, user_id, experiment_id))


def update_experiment_window(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    window_end: str,
    target_value: int | None = None,
) -> None:
    if target_value is not None:
        query = (
            "UPDATE experiments SET window_end = ?, target_value = ? "
            "WHERE user_id = ? AND id = ?"
        )
        conn.execute(query, (window_end, target_value, user_id, experiment_id))
    else:
        query = "UPDATE experiments SET window_end = ? WHERE user_id = ? AND id = ?"
        conn.execute(query, (window_end, user_id, experiment_id))


def update_experiment_params(
    conn: sqlite3.Connection, user_id: str, experiment_id: str, params_json: dict[str, Any]
) -> None:
    conn.execute(
        "UPDATE experiments SET params_json = ? WHERE user_id = ? AND id = ?",
        (json.dumps(params_json), user_id, experiment_id),
    )


def update_experiment_start(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    window_start: str,
    window_end: str,
    started_at: str,
    baseline_json: dict[str, Any] | None = None,
    metric_def_json: dict[str, Any] | None = None,
) -> None:
    query = """
        UPDATE experiments
        SET status = 'active', window_start = ?, window_end = ?, started_at = ?,
            baseline_json = COALESCE(?, baseline_json),
            metric_def_json = COALESCE(?, metric_def_json)
        WHERE user_id = ? AND id = ?
    """
    conn.execute(
        query,
        (
            window_start,
            window_end,
            started_at,
            json.dumps(baseline_json) if baseline_json is not None else None,
            json.dumps(metric_def_json) if metric_def_json is not None else None,
            user_id,
            experiment_id,
        ),
    )


# ---------------------------------------------------------------------------------------------
# 2. Check-ins Repo
# ---------------------------------------------------------------------------------------------
def insert_experiment_checkin(conn: sqlite3.Connection, checkin: ExperimentCheckin) -> None:
    query = """
        INSERT INTO experiment_checkins (
            id, user_id, experiment_id, checkin_date, observed_value, pace_status,
            user_response, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            checkin.id,
            checkin.user_id,
            checkin.experiment_id,
            checkin.checkin_date,
            checkin.observed_value,
            checkin.pace_status,
            checkin.user_response,
            checkin.created_at,
        ),
    )


def list_experiment_checkins(
    conn: sqlite3.Connection, user_id: str, experiment_id: str | None = None
) -> list[ExperimentCheckin]:
    if experiment_id is not None:
        query = """
            SELECT * FROM experiment_checkins
            WHERE user_id = ? AND experiment_id = ?
            ORDER BY checkin_date ASC
        """
        rows = conn.execute(query, (user_id, experiment_id)).fetchall()
    else:
        query = """
            SELECT * FROM experiment_checkins
            WHERE user_id = ?
            ORDER BY checkin_date ASC
        """
        rows = conn.execute(query, (user_id,)).fetchall()
    return [
        ExperimentCheckin(
            id=r["id"],
            user_id=r["user_id"],
            experiment_id=r["experiment_id"],
            checkin_date=r["checkin_date"],
            observed_value=r["observed_value"],
            pace_status=r["pace_status"],
            user_response=r["user_response"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_experiment_checkin(
    conn: sqlite3.Connection, user_id: str, checkin_id: str
) -> ExperimentCheckin | None:
    query = "SELECT * FROM experiment_checkins WHERE user_id = ? AND id = ?"
    row = conn.execute(query, (user_id, checkin_id)).fetchone()
    if row is None:
        return None
    return ExperimentCheckin(
        id=row["id"],
        user_id=row["user_id"],
        experiment_id=row["experiment_id"],
        checkin_date=row["checkin_date"],
        observed_value=row["observed_value"],
        pace_status=row["pace_status"],
        user_response=row["user_response"],
        created_at=row["created_at"],
    )


def update_experiment_checkin_response(
    conn: sqlite3.Connection,
    user_id: str,
    checkin_id: str,
    user_response: str,
) -> None:
    query = """
        UPDATE experiment_checkins
        SET user_response = ?
        WHERE user_id = ? AND id = ?
    """
    conn.execute(query, (user_response, user_id, checkin_id))


# ---------------------------------------------------------------------------------------------
# 3. Reviews Repo
# ---------------------------------------------------------------------------------------------
def insert_experiment_review(conn: sqlite3.Connection, review: ExperimentReview) -> None:
    query = """
        INSERT INTO experiment_reviews (
            id, user_id, experiment_id, observed_value, outcome, rank_p_bp,
            effect_value, target_met, integrity_json, data_quality_json,
            user_difficulty, user_helpful, user_would_repeat, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            review.id,
            review.user_id,
            review.experiment_id,
            review.observed_value,
            review.outcome,
            review.rank_p_bp,
            review.effect_value,
            1 if review.target_met else 0,
            json.dumps(review.integrity_json),
            json.dumps(review.data_quality_json),
            review.user_difficulty,
            1 if review.user_helpful is True else (
                0 if review.user_helpful is False else None
            ),
            1 if review.user_would_repeat is True else (
                0 if review.user_would_repeat is False else None
            ),
            review.created_at,
        ),
    )


def get_experiment_review(
    conn: sqlite3.Connection, user_id: str, experiment_id: str
) -> ExperimentReview | None:
    query = "SELECT * FROM experiment_reviews WHERE user_id = ? AND experiment_id = ?"
    row = conn.execute(query, (user_id, experiment_id)).fetchone()
    if row is None:
        return None
    return ExperimentReview(
        id=row["id"],
        user_id=row["user_id"],
        experiment_id=row["experiment_id"],
        observed_value=row["observed_value"],
        outcome=row["outcome"],
        rank_p_bp=row["rank_p_bp"],
        effect_value=row["effect_value"],
        target_met=bool(row["target_met"]),
        integrity_json=json.loads(row["integrity_json"]),
        data_quality_json=json.loads(row["data_quality_json"]),
        user_difficulty=row["user_difficulty"],
        user_helpful=(
            bool(row["user_helpful"]) if row["user_helpful"] is not None else None
        ),
        user_would_repeat=(
            bool(row["user_would_repeat"]) if row["user_would_repeat"] is not None else None
        ),
        created_at=row["created_at"],
    )


def list_experiment_reviews(conn: sqlite3.Connection, user_id: str) -> list[ExperimentReview]:
    query = "SELECT * FROM experiment_reviews WHERE user_id = ? ORDER BY created_at DESC"
    rows = conn.execute(query, (user_id,)).fetchall()
    return [
        ExperimentReview(
            id=r["id"],
            user_id=r["user_id"],
            experiment_id=r["experiment_id"],
            observed_value=r["observed_value"],
            outcome=r["outcome"],
            rank_p_bp=r["rank_p_bp"],
            effect_value=r["effect_value"],
            target_met=bool(r["target_met"]),
            integrity_json=json.loads(r["integrity_json"]),
            data_quality_json=json.loads(r["data_quality_json"]),
            user_difficulty=r["user_difficulty"],
            user_helpful=(
                bool(r["user_helpful"]) if r["user_helpful"] is not None else None
            ),
            user_would_repeat=(
                bool(r["user_would_repeat"]) if r["user_would_repeat"] is not None else None
            ),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_experiment_review_by_id(
    conn: sqlite3.Connection, user_id: str, review_id: str
) -> ExperimentReview | None:
    query = "SELECT * FROM experiment_reviews WHERE user_id = ? AND id = ?"
    row = conn.execute(query, (user_id, review_id)).fetchone()
    if row is None:
        return None
    return ExperimentReview(
        id=row["id"],
        user_id=row["user_id"],
        experiment_id=row["experiment_id"],
        observed_value=row["observed_value"],
        outcome=row["outcome"],
        rank_p_bp=row["rank_p_bp"],
        effect_value=row["effect_value"],
        target_met=bool(row["target_met"]),
        integrity_json=json.loads(row["integrity_json"]),
        data_quality_json=json.loads(row["data_quality_json"]),
        user_difficulty=row["user_difficulty"],
        user_helpful=(
            bool(row["user_helpful"]) if row["user_helpful"] is not None else None
        ),
        user_would_repeat=(
            bool(row["user_would_repeat"]) if row["user_would_repeat"] is not None else None
        ),
        created_at=row["created_at"],
    )


def update_experiment_review_feedback(
    conn: sqlite3.Connection,
    user_id: str,
    review_id: str,
    user_difficulty: int | None = None,
    user_helpful: bool | None = None,
    user_would_repeat: bool | None = None,
) -> None:
    helpful_val = 1 if user_helpful is True else (0 if user_helpful is False else None)
    repeat_val = 1 if user_would_repeat is True else (0 if user_would_repeat is False else None)
    # An answer that is not given now must not erase one given earlier.
    query = """
        UPDATE experiment_reviews
        SET user_difficulty = COALESCE(?, user_difficulty),
            user_helpful = COALESCE(?, user_helpful),
            user_would_repeat = COALESCE(?, user_would_repeat)
        WHERE user_id = ? AND id = ?
    """
    conn.execute(query, (user_difficulty, helpful_val, repeat_val, user_id, review_id))


def update_experiment_review_integrity(
    conn: sqlite3.Connection, user_id: str, review_id: str, integrity: dict
) -> None:
    conn.execute(
        "UPDATE experiment_reviews SET integrity_json = ? WHERE user_id = ? AND id = ?",
        (json.dumps(integrity), user_id, review_id),
    )


# ---------------------------------------------------------------------------------------------
# 4. Adjustment Proposals Repo
# ---------------------------------------------------------------------------------------------
def insert_adjustment_proposal(conn: sqlite3.Connection, prop: AdjustmentProposal) -> None:
    query = """
        INSERT INTO adjustment_proposals (
            id, user_id, experiment_id, kind, reason_code, params_json, status,
            created_at, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            prop.id,
            prop.user_id,
            prop.experiment_id,
            prop.kind,
            prop.reason_code,
            json.dumps(prop.params_json),
            prop.status,
            prop.created_at,
            prop.decided_at,
        ),
    )


def get_adjustment_proposal(
    conn: sqlite3.Connection, user_id: str, proposal_id: str
) -> AdjustmentProposal | None:
    query = "SELECT * FROM adjustment_proposals WHERE user_id = ? AND id = ?"
    row = conn.execute(query, (user_id, proposal_id)).fetchone()
    if row is None:
        return None
    return AdjustmentProposal(
        id=row["id"],
        user_id=row["user_id"],
        experiment_id=row["experiment_id"],
        kind=row["kind"],
        reason_code=row["reason_code"],
        params_json=json.loads(row["params_json"]),
        status=row["status"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


def list_adjustment_proposals(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str | None = None,
    status: str | None = None,
) -> list[AdjustmentProposal]:
    params: list[Any] = [user_id]
    clauses = ["user_id = ?"]
    if experiment_id:
        clauses.append("experiment_id = ?")
        params.append(experiment_id)
    where_sql = " AND ".join(clauses)
    query = f"SELECT * FROM adjustment_proposals WHERE {where_sql} ORDER BY created_at DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [
        AdjustmentProposal(
            id=r["id"],
            user_id=r["user_id"],
            experiment_id=r["experiment_id"],
            kind=r["kind"],
            reason_code=r["reason_code"],
            params_json=json.loads(r["params_json"]),
            status=r["status"],
            created_at=r["created_at"],
            decided_at=r["decided_at"],
        )
        for r in rows
    ]


def update_adjustment_status(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_id: str,
    status: ProposalStatus,
    decided_at: str,
) -> None:
    query = (
        "UPDATE adjustment_proposals SET status = ?, decided_at = ? "
        "WHERE user_id = ? AND id = ?"
    )
    conn.execute(query, (status, decided_at, user_id, proposal_id))


# ---------------------------------------------------------------------------------------------
# 5. Offers Repo
# ---------------------------------------------------------------------------------------------
def insert_offer(conn: sqlite3.Connection, offer: Offer) -> None:
    query = """
        INSERT INTO offers (
            id, user_id, week_start, template_code, difficulty, params_json, rank,
            propensity_bp, policy_version, rng_seed, reason_json, status, created_at, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            offer.id,
            offer.user_id,
            offer.week_start,
            offer.template_code,
            offer.difficulty,
            json.dumps(offer.params_json),
            offer.rank,
            offer.propensity_bp,
            offer.policy_version,
            offer.rng_seed,
            json.dumps(offer.reason_json),
            offer.status,
            offer.created_at,
            offer.decided_at,
        ),
    )


def get_offer(conn: sqlite3.Connection, user_id: str, offer_id: str) -> Offer | None:
    query = "SELECT * FROM offers WHERE user_id = ? AND id = ?"
    row = conn.execute(query, (user_id, offer_id)).fetchone()
    if row is None:
        return None
    return Offer(
        id=row["id"],
        user_id=row["user_id"],
        week_start=row["week_start"],
        template_code=row["template_code"],
        difficulty=row["difficulty"],
        params_json=json.loads(row["params_json"]),
        rank=row["rank"],
        propensity_bp=row["propensity_bp"],
        policy_version=row["policy_version"],
        rng_seed=row["rng_seed"],
        reason_json=json.loads(row["reason_json"]),
        status=row["status"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


def list_offers(
    conn: sqlite3.Connection,
    user_id: str,
    week_start: str | None = None,
    status: str | None = None,
) -> list[Offer]:
    params: list[Any] = [user_id]
    clauses = ["user_id = ?"]
    if week_start:
        clauses.append("week_start = ?")
        params.append(week_start)
    if status:
        clauses.append("status = ?")
        params.append(status)
    query = f"SELECT * FROM offers WHERE {' AND '.join(clauses)} ORDER BY rank ASC"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [
        Offer(
            id=r["id"],
            user_id=r["user_id"],
            week_start=r["week_start"],
            template_code=r["template_code"],
            difficulty=r["difficulty"],
            params_json=json.loads(r["params_json"]),
            rank=r["rank"],
            propensity_bp=r["propensity_bp"],
            policy_version=r["policy_version"],
            rng_seed=r["rng_seed"],
            reason_json=json.loads(r["reason_json"]),
            status=r["status"],
            created_at=r["created_at"],
            decided_at=r["decided_at"],
        )
        for r in rows
    ]


def update_offer_status(
    conn: sqlite3.Connection,
    user_id: str,
    offer_id: str,
    status: str,
    decided_at: str,
) -> None:
    query = "UPDATE offers SET status = ?, decided_at = ? WHERE user_id = ? AND id = ?"
    conn.execute(query, (status, decided_at, user_id, offer_id))


def update_offer(conn: sqlite3.Connection, offer: Offer) -> None:
    query = "UPDATE offers SET status = ?, decided_at = ? WHERE user_id = ? AND id = ?"
    conn.execute(query, (offer.status, offer.decided_at, offer.user_id, offer.id))


# ---------------------------------------------------------------------------------------------
# 6. XP Events Repo
# ---------------------------------------------------------------------------------------------
def insert_xp_event(conn: sqlite3.Connection, event: XpEvent) -> bool:
    """
    Insert an XP event. Returns True if inserted, False if duplicate (idempotent).
    """
    query = """
        INSERT OR IGNORE INTO xp_events (
            id, user_id, rule_code, points, ref_kind, ref_id, period_day, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    cur = conn.execute(
        query,
        (
            event.id,
            event.user_id,
            event.rule_code,
            event.points,
            event.ref_kind,
            event.ref_id,
            event.period_day,
            event.created_at,
        ),
    )
    return cur.rowcount > 0


def list_xp_events(conn: sqlite3.Connection, user_id: str) -> list[XpEvent]:
    query = "SELECT * FROM xp_events WHERE user_id = ? ORDER BY created_at DESC"
    rows = conn.execute(query, (user_id,)).fetchall()
    return [
        XpEvent(
            id=r["id"],
            user_id=r["user_id"],
            rule_code=r["rule_code"],
            points=r["points"],
            ref_kind=r["ref_kind"],
            ref_id=r["ref_id"],
            period_day=r["period_day"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_user_xp_total(conn: sqlite3.Connection, user_id: str) -> int:
    query = "SELECT COALESCE(SUM(points), 0) FROM xp_events WHERE user_id = ?"
    row = conn.execute(query, (user_id,)).fetchone()
    return int(row[0]) if row else 0


def get_user_xp_for_day(conn: sqlite3.Connection, user_id: str, period_day: str) -> int:
    query = "SELECT COALESCE(SUM(points), 0) FROM xp_events WHERE user_id = ? AND period_day = ?"
    row = conn.execute(query, (user_id, period_day)).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------------------------
# 7. Badge Awards Repo
# ---------------------------------------------------------------------------------------------
def insert_badge_award(conn: sqlite3.Connection, award: BadgeAward) -> bool:
    """
    Insert a one-time badge award. Returns True if awarded, False if already exists.
    """
    query = """
        INSERT OR IGNORE INTO badge_awards (id, user_id, badge_code, awarded_at, evidence_json)
        VALUES (?, ?, ?, ?, ?)
    """
    cur = conn.execute(
        query,
        (
            award.id,
            award.user_id,
            award.badge_code,
            award.awarded_at,
            json.dumps(award.evidence_json),
        ),
    )
    return cur.rowcount > 0


def list_badge_awards(conn: sqlite3.Connection, user_id: str) -> list[BadgeAward]:
    query = "SELECT * FROM badge_awards WHERE user_id = ? ORDER BY awarded_at ASC"
    rows = conn.execute(query, (user_id,)).fetchall()
    return [
        BadgeAward(
            id=r["id"],
            user_id=r["user_id"],
            badge_code=r["badge_code"],
            awarded_at=r["awarded_at"],
            evidence_json=json.loads(r["evidence_json"]),
        )
        for r in rows
    ]


def has_badge(conn: sqlite3.Connection, user_id: str, badge_code: str) -> bool:
    query = "SELECT 1 FROM badge_awards WHERE user_id = ? AND badge_code = ?"
    return conn.execute(query, (user_id, badge_code)).fetchone() is not None


# ---------------------------------------------------------------------------------------------
# 8. Streak Freezes Repo
# ---------------------------------------------------------------------------------------------
def insert_streak_freeze(conn: sqlite3.Connection, freeze: StreakFreeze) -> None:
    query = """
        INSERT INTO streak_freezes (
            id, user_id, streak_code, from_date, to_date, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    conn.execute(
        query,
        (
            freeze.id,
            freeze.user_id,
            freeze.streak_code,
            freeze.from_date,
            freeze.to_date,
            freeze.reason,
            freeze.created_at,
        ),
    )


def list_streak_freezes(
    conn: sqlite3.Connection, user_id: str, streak_code: str | None = None
) -> list[StreakFreeze]:
    if streak_code:
        query = (
            "SELECT * FROM streak_freezes WHERE user_id = ? AND streak_code = ? "
            "ORDER BY from_date ASC"
        )
        rows = conn.execute(query, (user_id, streak_code)).fetchall()
    else:
        query = "SELECT * FROM streak_freezes WHERE user_id = ? ORDER BY from_date ASC"
        rows = conn.execute(query, (user_id,)).fetchall()
    return [
        StreakFreeze(
            id=r["id"],
            user_id=r["user_id"],
            streak_code=r["streak_code"],
            from_date=r["from_date"],
            to_date=r["to_date"],
            reason=r["reason"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
