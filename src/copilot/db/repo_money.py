"""Reads and writes for commitments, goal contributions, buckets, readiness, contribution plans and
trade-offs.
"""

import json
import sqlite3
import uuid
from typing import Any

from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.models.money import (
    Bucket,
    BucketAllocation,
    Commitment,
    CommitmentMatch,
    ContributionPlan,
    ContributionPlanStep,
    Readiness,
    ReadinessCriterion,
    ReallocationDraft,
    TradeoffAlternative,
    TradeoffResult,
)


def insert_commitment(conn: sqlite3.Connection, c: Commitment) -> Commitment:
    conn.execute(
        """
        INSERT INTO commitments (
            id, user_id, name, direction, kind, category_id,
            amount_paise, amount_min_paise, amount_max_paise,
            certainty, schedule_kind, schedule_json,
            start_date, end_date, recurring_series_id,
            goal_id, bucket_id, source, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            c.id,
            c.user_id,
            c.name,
            c.direction,
            c.kind,
            c.category_id,
            c.amount_paise,
            c.amount_min_paise,
            c.amount_max_paise,
            c.certainty,
            c.schedule_kind,
            json.dumps(c.schedule_json),
            c.start_date,
            c.end_date,
            c.recurring_series_id,
            c.goal_id,
            c.bucket_id,
            c.source,
            c.status,
            c.created_at,
            c.updated_at,
        ),
    )
    return c


def get_commitment(conn: sqlite3.Connection, user_id: str, commitment_id: str) -> Commitment | None:
    row = conn.execute(
        "SELECT * FROM commitments WHERE user_id = ? AND id = ?",
        (user_id, commitment_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["schedule_json"] = json.loads(d["schedule_json"])
    return Commitment.model_validate(d)


def list_commitments(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
    kind: str | None = None,
) -> list[Commitment]:
    query = "SELECT * FROM commitments WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY start_date ASC, name ASC"

    rows = conn.execute(query, params).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["schedule_json"] = json.loads(d["schedule_json"])
        results.append(Commitment.model_validate(d))
    return results


def update_commitment_status(
    conn: sqlite3.Connection,
    user_id: str,
    commitment_id: str,
    status: str,
    updated_at: str,
) -> bool:
    cur = conn.execute(
        "UPDATE commitments SET status = ?, updated_at = ? WHERE user_id = ? AND id = ?",
        (status, updated_at, user_id, commitment_id),
    )
    return cur.rowcount > 0


def update_commitment(
    conn: sqlite3.Connection,
    user_id: str,
    commitment_id: str,
    *,
    name: str | None = None,
    direction: str | None = None,
    kind: str | None = None,
    category_id: str | None = None,
    amount_paise: int | None = None,
    amount_min_paise: int | None = None,
    amount_max_paise: int | None = None,
    certainty: str | None = None,
    schedule_kind: str | None = None,
    schedule_json: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    goal_id: str | None = None,
    bucket_id: str | None = None,
    status: str | None = None,
    updated_at: str,
) -> bool:
    sets = ["updated_at = ?"]
    params: list[Any] = [updated_at]
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if direction is not None:
        sets.append("direction = ?")
        params.append(direction)
    if kind is not None:
        sets.append("kind = ?")
        params.append(kind)
    if category_id is not None:
        sets.append("category_id = ?")
        params.append(category_id)
    if amount_paise is not None:
        sets.append("amount_paise = ?")
        params.append(amount_paise)
    if amount_min_paise is not None:
        sets.append("amount_min_paise = ?")
        params.append(amount_min_paise)
    if amount_max_paise is not None:
        sets.append("amount_max_paise = ?")
        params.append(amount_max_paise)
    if certainty is not None:
        sets.append("certainty = ?")
        params.append(certainty)
    if schedule_kind is not None:
        sets.append("schedule_kind = ?")
        params.append(schedule_kind)
    if schedule_json is not None:
        sets.append("schedule_json = ?")
        params.append(json.dumps(schedule_json))
    if start_date is not None:
        sets.append("start_date = ?")
        params.append(start_date)
    if end_date is not None:
        sets.append("end_date = ?")
        params.append(end_date)
    if goal_id is not None:
        sets.append("goal_id = ?")
        params.append(goal_id)
    if bucket_id is not None:
        sets.append("bucket_id = ?")
        params.append(bucket_id)
    if status is not None:
        sets.append("status = ?")
        params.append(status)

    params.extend([user_id, commitment_id])
    sql = f"UPDATE commitments SET {', '.join(sets)} WHERE user_id = ? AND id = ?"
    cur = conn.execute(sql, params)
    return cur.rowcount > 0


def list_recurring_series(
    conn: sqlite3.Connection,
    user_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM recurring_series WHERE user_id = ? ORDER BY next_expected ASC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_commitment_match(conn: sqlite3.Connection, m: CommitmentMatch) -> CommitmentMatch:
    conn.execute(
        """
        INSERT INTO commitment_matches (
            id, user_id, commitment_id, due_date, txn_id, match_method, confidence_bp, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            m.id,
            m.user_id,
            m.commitment_id,
            m.due_date,
            m.txn_id,
            m.match_method,
            m.confidence_bp,
            m.created_at,
        ),
    )
    return m


def list_commitment_matches(
    conn: sqlite3.Connection,
    user_id: str,
    commitment_id: str | None = None,
) -> list[CommitmentMatch]:
    query = "SELECT * FROM commitment_matches WHERE user_id = ?"
    params: list[Any] = [user_id]
    if commitment_id is not None:
        query += " AND commitment_id = ?"
        params.append(commitment_id)
    query += " ORDER BY due_date ASC"

    rows = conn.execute(query, params).fetchall()
    return [CommitmentMatch.model_validate(dict(r)) for r in rows]


def insert_goal_contribution(
    conn: sqlite3.Connection,
    user_id: str,
    goal_id: str,
    amount_paise: int,
    occurred_on: str,
    source: str,
    ref_id: str | None,
    created_at: str,
    contribution_id: str | None = None,
) -> str:
    cid = contribution_id or f"gc_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO goal_contributions (
            id, user_id, goal_id, amount_paise, occurred_on, source, ref_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cid, user_id, goal_id, amount_paise, occurred_on, source, ref_id, created_at),
    )
    return cid


def list_goal_contributions(
    conn: sqlite3.Connection,
    user_id: str,
    goal_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM goal_contributions WHERE user_id = ? AND goal_id = ?"
        " ORDER BY occurred_on ASC",
        (user_id, goal_id),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_bucket(conn: sqlite3.Connection, b: Bucket) -> Bucket:
    conn.execute(
        """
        INSERT INTO buckets (
            id, user_id, name, kind, period_policy, goal_id,
            commitment_id, status, sort_order, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            b.id,
            b.user_id,
            b.name,
            b.kind,
            b.period_policy,
            b.goal_id,
            b.commitment_id,
            b.status,
            b.sort_order,
            b.created_at,
        ),
    )
    return b


def get_bucket(conn: sqlite3.Connection, user_id: str, bucket_id: str) -> Bucket | None:
    row = conn.execute(
        "SELECT * FROM buckets WHERE user_id = ? AND id = ?",
        (user_id, bucket_id),
    ).fetchone()
    return Bucket.model_validate(dict(row)) if row else None


def list_buckets(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = "active",
) -> list[Bucket]:
    query = "SELECT * FROM buckets WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY sort_order ASC, name ASC"

    rows = conn.execute(query, params).fetchall()
    return [Bucket.model_validate(dict(r)) for r in rows]


def update_bucket(
    conn: sqlite3.Connection,
    user_id: str,
    bucket_id: str,
    *,
    name: str | None = None,
    kind: str | None = None,
    period_policy: str | None = None,
    goal_id: str | None = None,
    commitment_id: str | None = None,
    status: str | None = None,
    sort_order: int | None = None,
) -> bool:
    sets = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if kind is not None:
        sets.append("kind = ?")
        params.append(kind)
    if period_policy is not None:
        sets.append("period_policy = ?")
        params.append(period_policy)
    if goal_id is not None:
        sets.append("goal_id = ?")
        params.append(goal_id)
    if commitment_id is not None:
        sets.append("commitment_id = ?")
        params.append(commitment_id)
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if sort_order is not None:
        sets.append("sort_order = ?")
        params.append(sort_order)
    if not sets:
        return False
    params.extend([user_id, bucket_id])
    sql = f"UPDATE buckets SET {', '.join(sets)} WHERE user_id = ? AND id = ?"
    cur = conn.execute(sql, params)
    return cur.rowcount > 0


def map_bucket_category(
    conn: sqlite3.Connection,
    user_id: str,
    bucket_id: str,
    category_id: str,
    created_at: str,
) -> None:
    mapping_id = f"bc_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO bucket_categories (id, user_id, bucket_id, category_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, category_id) DO UPDATE SET
            bucket_id = excluded.bucket_id,
            created_at = excluded.created_at
        """,
        (mapping_id, user_id, bucket_id, category_id, created_at),
    )


def get_bucket_for_category(conn: sqlite3.Connection, user_id: str, category_id: str) -> str | None:
    row = conn.execute(
        "SELECT bucket_id FROM bucket_categories WHERE user_id = ? AND category_id = ?",
        (user_id, category_id),
    ).fetchone()
    return row[0] if row else None


def list_bucket_categories(
    conn: sqlite3.Connection,
    user_id: str,
    bucket_id: str | None = None,
) -> list[dict[str, str]]:
    query = "SELECT bucket_id, category_id FROM bucket_categories WHERE user_id = ?"
    params: list[Any] = [user_id]
    if bucket_id is not None:
        query += " AND bucket_id = ?"
        params.append(bucket_id)

    rows = conn.execute(query, params).fetchall()
    return [{"bucket_id": r[0], "category_id": r[1]} for r in rows]


def insert_bucket_allocation(conn: sqlite3.Connection, a: BucketAllocation) -> BucketAllocation:
    conn.execute(
        """
        INSERT INTO bucket_allocations (
            id, user_id, bucket_id, amount_paise, kind,
            period, pair_id, source, draft_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            a.id,
            a.user_id,
            a.bucket_id,
            a.amount_paise,
            a.kind,
            a.period,
            a.pair_id,
            a.source,
            a.draft_id,
            a.created_at,
        ),
    )
    return a


def list_bucket_allocations(
    conn: sqlite3.Connection,
    user_id: str,
    bucket_id: str | None = None,
    period: str | None = None,
) -> list[BucketAllocation]:
    query = "SELECT * FROM bucket_allocations WHERE user_id = ?"
    params: list[Any] = [user_id]
    if bucket_id is not None:
        query += " AND bucket_id = ?"
        params.append(bucket_id)
    if period is not None:
        query += " AND period = ?"
        params.append(period)
    query += " ORDER BY created_at ASC"

    rows = conn.execute(query, params).fetchall()
    return [BucketAllocation.model_validate(dict(r)) for r in rows]


def insert_reallocation_draft(conn: sqlite3.Connection, d: ReallocationDraft) -> ReallocationDraft:
    conn.execute(
        """
        INSERT INTO reallocation_drafts (
            id, user_id, from_bucket_id, to_bucket_id, amount_paise, reason_json,
            simulation_id, status, created_at, decided_at, applied_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d.id,
            d.user_id,
            d.from_bucket_id,
            d.to_bucket_id,
            d.amount_paise,
            json.dumps(d.reason_json),
            d.simulation_id,
            d.status,
            d.created_at,
            d.decided_at,
            d.applied_at,
        ),
    )
    return d


def get_reallocation_draft(
    conn: sqlite3.Connection, user_id: str, draft_id: str
) -> ReallocationDraft | None:
    row = conn.execute(
        "SELECT * FROM reallocation_drafts WHERE user_id = ? AND id = ?",
        (user_id, draft_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["reason_json"] = json.loads(d["reason_json"])
    return ReallocationDraft.model_validate(d)


def update_reallocation_draft_status(
    conn: sqlite3.Connection,
    user_id: str,
    draft_id: str,
    status: str,
    decided_at: str | None = None,
    applied_at: str | None = None,
) -> bool:
    cur = conn.execute(
        """
        UPDATE reallocation_drafts
        SET status = ?, decided_at = COALESCE(?, decided_at), applied_at = COALESCE(?, applied_at)
        WHERE user_id = ? AND id = ?
        """,
        (status, decided_at, applied_at, user_id, draft_id),
    )
    return cur.rowcount > 0


def insert_readiness_assessment(
    conn: sqlite3.Connection,
    user_id: str,
    r: Readiness,
    assessment_id: str | None = None,
) -> str:
    aid = assessment_id or f"ra_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO readiness_assessments (
            id, user_id, run_id, assessed_on, level,
            criteria_json, numbers_json, config_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid,
            user_id,
            r.run_id,
            r.assessed_on,
            r.level,
            json.dumps([c.model_dump() for c in r.criteria]),
            json.dumps(r.numbers),
            r.config_version,
            to_utc_iso(now_utc()),
        ),
    )
    return aid


def get_latest_readiness_assessment(
    conn: sqlite3.Connection,
    user_id: str,
) -> Readiness | None:
    row = conn.execute(
        """
        SELECT run_id, assessed_on, level, criteria_json, numbers_json, config_version
        FROM readiness_assessments
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return Readiness(
        run_id=row[0],
        assessed_on=row[1],
        level=row[2],
        criteria=[ReadinessCriterion.model_validate(c) for c in json.loads(row[3])],
        numbers=json.loads(row[4]),
        config_version=row[5],
    )


def list_readiness_assessments(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 10,
) -> list[Readiness]:
    rows = conn.execute(
        """
        SELECT run_id, assessed_on, level, criteria_json, numbers_json, config_version
        FROM readiness_assessments
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [
        Readiness(
            run_id=r[0],
            assessed_on=r[1],
            level=r[2],
            criteria=[ReadinessCriterion.model_validate(c) for c in json.loads(r[3])],
            numbers=json.loads(r[4]),
            config_version=r[5],
        )
        for r in rows
    ]


def insert_contribution_plan(
    conn: sqlite3.Connection,
    user_id: str,
    plan: ContributionPlan,
    plan_id: str | None = None,
) -> str:
    pid = plan_id or f"cp_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO contribution_plans (
            id, user_id, run_id, period_from, horizon_months,
            waterfall_json, result_json, assumptions_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pid,
            user_id,
            plan.run_id,
            plan.period_from,
            plan.horizon_months,
            json.dumps(plan.waterfall_order),
            json.dumps(
                {
                    "steps": [s.model_dump() for s in plan.steps],
                    "options": plan.options,
                }
            ),
            json.dumps(plan.assumptions),
            to_utc_iso(now_utc()),
        ),
    )
    return pid


def get_latest_contribution_plan(
    conn: sqlite3.Connection,
    user_id: str,
) -> ContributionPlan | None:
    row = conn.execute(
        """
        SELECT run_id, period_from, horizon_months, waterfall_json, result_json, assumptions_json
        FROM contribution_plans
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    res = json.loads(row[4])
    return ContributionPlan(
        run_id=row[0],
        period_from=row[1],
        horizon_months=row[2],
        waterfall_order=json.loads(row[3]),
        steps=[ContributionPlanStep.model_validate(s) for s in res.get("steps", [])],
        options=res.get("options", []),
        assumptions=json.loads(row[5]),
    )


def list_contribution_plans(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 10,
) -> list[ContributionPlan]:
    rows = conn.execute(
        """
        SELECT run_id, period_from, horizon_months, waterfall_json, result_json, assumptions_json
        FROM contribution_plans
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    plans = []
    for r in rows:
        res = json.loads(r[4])
        plans.append(
            ContributionPlan(
                run_id=r[0],
                period_from=r[1],
                horizon_months=r[2],
                waterfall_order=json.loads(r[3]),
                steps=[ContributionPlanStep.model_validate(s) for s in res.get("steps", [])],
                options=res.get("options", []),
                assumptions=json.loads(r[5]),
            )
        )
    return plans


def insert_tradeoff_analysis(
    conn: sqlite3.Connection,
    user_id: str,
    result: TradeoffResult,
    analysis_id: str | None = None,
) -> str:
    tid = analysis_id or f"ta_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO tradeoff_analyses (
            id, user_id, run_id, alternatives_json, results_json,
            assumptions_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tid,
            user_id,
            result.run_id,
            json.dumps([a.model_dump() for a in result.alternatives]),
            json.dumps({"best_alternative_name": result.best_alternative_name}),
            json.dumps(result.assumptions),
            to_utc_iso(now_utc()),
        ),
    )
    return tid


def get_latest_tradeoff_analysis(
    conn: sqlite3.Connection,
    user_id: str,
) -> TradeoffResult | None:
    row = conn.execute(
        """
        SELECT run_id, alternatives_json, results_json, assumptions_json
        FROM tradeoff_analyses
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    res = json.loads(row[2])
    return TradeoffResult(
        run_id=row[0],
        alternatives=[TradeoffAlternative.model_validate(a) for a in json.loads(row[1])],
        best_alternative_name=res.get("best_alternative_name"),
        assumptions=json.loads(row[3]),
    )


def list_tradeoff_analyses(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 10,
) -> list[TradeoffResult]:
    rows = conn.execute(
        """
        SELECT run_id, alternatives_json, results_json, assumptions_json
        FROM tradeoff_analyses
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    analyses = []
    for r in rows:
        res = json.loads(r[2])
        analyses.append(
            TradeoffResult(
                run_id=r[0],
                alternatives=[TradeoffAlternative.model_validate(a) for a in json.loads(r[1])],
                best_alternative_name=res.get("best_alternative_name"),
                assumptions=json.loads(r[3]),
            )
        )
    return analyses
