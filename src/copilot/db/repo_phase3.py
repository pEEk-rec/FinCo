"""
Phase 3 SQLite repository functions (PLAN_PHASE3 Stage 3.1).
Every single user-scoped query filters by user_id. Parameterised queries throughout.
"""

import json
import sqlite3
import uuid
from typing import Any, Literal

from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.phase3 import (
    Bucket,
    BucketAllocation,
    Commitment,
    CommitmentMatch,
    ContextManifest,
    ContributionPlan,
    ContributionPlanStep,
    FeedbackStat,
    JobRun,
    MemoryEvidence,
    MemoryItem,
    Readiness,
    ReadinessCriterion,
    ReallocationDraft,
    Reflection,
    ScheduledJob,
    SkillRun,
    Span,
    SpecialistReport,
    TradeoffAlternative,
    TradeoffResult,
)


# ---------------------------------------------------------------------------------------------
# 1. Commitments & Matches
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 2. Goal Contributions
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 3. Virtual Buckets, Categories & Ledger
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 4. Behavioural Memory Store
# ---------------------------------------------------------------------------------------------
def insert_memory_item(conn: sqlite3.Connection, item: MemoryItem) -> MemoryItem:
    conn.execute(
        """
        INSERT INTO memory_items (
            id, user_id, kind, subject_key, statement_json, source, status,
            prior_bp, user_confirmed, created_at, last_evidence_at, last_confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.user_id,
            item.kind,
            item.subject_key,
            json.dumps(item.statement_json),
            item.source,
            item.status,
            item.prior_bp,
            1 if item.user_confirmed else 0,
            item.created_at,
            item.last_evidence_at,
            item.last_confirmed_at,
        ),
    )
    return item


def get_memory_item(conn: sqlite3.Connection, user_id: str, memory_id: str) -> MemoryItem | None:
    row = conn.execute(
        "SELECT * FROM memory_items WHERE user_id = ? AND id = ?",
        (user_id, memory_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["statement_json"] = json.loads(d["statement_json"])
    d["user_confirmed"] = bool(d["user_confirmed"])
    return MemoryItem.model_validate(d)


def list_memory_items(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
    kind: str | None = None,
    subject_key: str | None = None,
) -> list[MemoryItem]:
    query = "SELECT * FROM memory_items WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    if subject_key is not None:
        query += " AND subject_key = ?"
        params.append(subject_key)
    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["statement_json"] = json.loads(d["statement_json"])
        d["user_confirmed"] = bool(d["user_confirmed"])
        items.append(MemoryItem.model_validate(d))
    return items


def update_memory_status(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    status: str,
    last_confirmed_at: str | None = None,
    user_confirmed: bool | None = None,
) -> bool:
    updates = ["status = ?"]
    params: list[Any] = [status]
    if last_confirmed_at is not None:
        updates.append("last_confirmed_at = ?")
        params.append(last_confirmed_at)
    if user_confirmed is not None:
        updates.append("user_confirmed = ?")
        params.append(1 if user_confirmed else 0)
    params.extend([user_id, memory_id])

    cur = conn.execute(
        f"UPDATE memory_items SET {', '.join(updates)} WHERE user_id = ? AND id = ?",
        params,
    )
    return cur.rowcount > 0


def insert_memory_evidence(conn: sqlite3.Connection, e: MemoryEvidence) -> MemoryEvidence:
    conn.execute(
        """
        INSERT INTO memory_evidence (
            id, user_id, memory_id, polarity, ref_kind, ref_id, observed_at, weight_bp, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            e.id,
            e.user_id,
            e.memory_id,
            e.polarity,
            e.ref_kind,
            e.ref_id,
            e.observed_at,
            e.weight_bp,
            e.created_at,
        ),
    )
    # Update last_evidence_at on parent memory item
    conn.execute(
        "UPDATE memory_items SET last_evidence_at = ? WHERE user_id = ? AND id = ?",
        (e.observed_at, e.user_id, e.memory_id),
    )
    return e


def list_memory_evidence(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
) -> list[MemoryEvidence]:
    rows = conn.execute(
        "SELECT * FROM memory_evidence WHERE user_id = ? AND memory_id = ?"
        " ORDER BY observed_at ASC",
        (user_id, memory_id),
    ).fetchall()
    return [MemoryEvidence.model_validate(dict(r)) for r in rows]


def forget_memory_item(conn: sqlite3.Connection, user_id: str, memory_id: str) -> bool:
    """
    Clears statement_json and evidence rows' details, sets status = 'forgotten' (PLAN_PHASE3 5.8).
    """
    cur = conn.execute(
        "UPDATE memory_items SET status = 'forgotten', statement_json = '{}'"
        " WHERE user_id = ? AND id = ?",
        (user_id, memory_id),
    )
    if cur.rowcount > 0:
        conn.execute(
            "DELETE FROM memory_evidence WHERE user_id = ? AND memory_id = ?",
            (user_id, memory_id),
        )
        return True
    return False


def update_memory_statement(
    conn: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    statement_json: dict[str, Any],
) -> bool:
    cur = conn.execute(
        "UPDATE memory_items SET statement_json = ? WHERE user_id = ? AND id = ?",
        (json.dumps(statement_json), user_id, memory_id),
    )
    return cur.rowcount > 0


def get_memory_by_subject(
    conn: sqlite3.Connection,
    user_id: str,
    kind: str,
    subject_key: str,
) -> MemoryItem | None:
    query = (
        "SELECT * FROM memory_items "
        "WHERE user_id = ? AND kind = ? AND subject_key = ? AND status != 'forgotten' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = conn.execute(query, (user_id, kind, subject_key)).fetchone()

    if not row:
        return None
    d = dict(row)
    d["statement_json"] = json.loads(d["statement_json"])
    d["user_confirmed"] = bool(d["user_confirmed"])
    return MemoryItem.model_validate(d)



# ---------------------------------------------------------------------------------------------
# 5. User Preferences
# ---------------------------------------------------------------------------------------------
def set_user_preference(
    conn: sqlite3.Connection,
    user_id: str,
    key: str,
    value: Any,
    updated_at: str,
) -> None:
    pid = f"pref_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO user_preferences (id, user_id, key, value_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (pid, user_id, key, json.dumps(value), updated_at),
    )


def get_user_preference(conn: sqlite3.Connection, user_id: str, key: str) -> Any | None:
    row = conn.execute(
        "SELECT value_json FROM user_preferences WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def list_user_preferences(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT key, value_json FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {r[0]: json.loads(r[1]) for r in rows}


# ---------------------------------------------------------------------------------------------
# 5b. Readiness Assessments
# ---------------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------------
# 6. Explanations, Observability & Traces
# ---------------------------------------------------------------------------------------------
def insert_skill_run(conn: sqlite3.Connection, r: SkillRun) -> SkillRun:
    conn.execute(
        """
        INSERT INTO skill_runs (
            id, user_id, task_id, skill_name, skill_version,
            inputs_json, status, outputs_json, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.id,
            r.user_id,
            r.task_id,
            r.skill_name,
            r.skill_version,
            json.dumps(r.inputs_json),
            r.status,
            json.dumps(r.outputs_json),
            r.started_at,
            r.finished_at,
        ),
    )
    return r


def update_skill_run(
    conn: sqlite3.Connection,
    user_id: str,
    run_id: str,
    status: Literal["running", "ok", "failed", "cannot_run"],
    outputs_json: dict[str, Any],
    finished_at: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE skill_runs
        SET status = ?, outputs_json = ?, finished_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (status, json.dumps(outputs_json), finished_at, run_id, user_id),
    )


def get_skill_run(conn: sqlite3.Connection, user_id: str, run_id: str) -> SkillRun | None:
    row = conn.execute(
        "SELECT * FROM skill_runs WHERE id = ? AND user_id = ?",
        (run_id, user_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["inputs_json"] = json.loads(d["inputs_json"])
    d["outputs_json"] = json.loads(d["outputs_json"])
    return SkillRun.model_validate(d)


def list_skill_runs(
    conn: sqlite3.Connection, user_id: str, task_id: str | None = None
) -> list[SkillRun]:
    query = "SELECT * FROM skill_runs WHERE user_id = ?"
    params: list[Any] = [user_id]
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    query += " ORDER BY started_at ASC"
    rows = conn.execute(query, tuple(params)).fetchall()
    runs = []
    for r in rows:
        d = dict(r)
        d["inputs_json"] = json.loads(d["inputs_json"])
        d["outputs_json"] = json.loads(d["outputs_json"])
        runs.append(SkillRun.model_validate(d))
    return runs


def insert_specialist_report(conn: sqlite3.Connection, r: SpecialistReport) -> SpecialistReport:
    conn.execute(
        """
        INSERT INTO specialist_reports (
            id, user_id, task_id, agent_role, sub_question_json, status,
            findings_json, gaps_json, error_code, duration_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.id,
            r.user_id,
            r.task_id,
            r.agent_role,
            json.dumps(r.sub_question_json),
            r.status,
            json.dumps(r.findings_json),
            json.dumps(r.gaps_json),
            r.error_code,
            r.duration_ms,
            r.created_at,
        ),
    )
    return r


def list_specialist_reports(
    conn: sqlite3.Connection, user_id: str, task_id: str
) -> list[SpecialistReport]:
    rows = conn.execute(
        """
        SELECT * FROM specialist_reports
        WHERE user_id = ? AND task_id = ?
        ORDER BY created_at ASC
        """,
        (user_id, task_id),
    ).fetchall()
    reports = []
    for r in rows:
        d = dict(r)
        d["sub_question_json"] = json.loads(d["sub_question_json"])
        d["findings_json"] = json.loads(d["findings_json"])
        d["gaps_json"] = json.loads(d["gaps_json"])
        reports.append(SpecialistReport.model_validate(d))
    return reports


def insert_reflection(conn: sqlite3.Connection, r: Reflection) -> Reflection:
    conn.execute(
        """
        INSERT INTO reflections (
            id, user_id, task_id, round, critique_codes_json, source, revised, outcome, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.id,
            r.user_id,
            r.task_id,
            r.round,
            json.dumps(r.critique_codes),
            r.source,
            1 if r.revised else 0,
            r.outcome,
            r.created_at,
        ),
    )
    return r


def list_reflections(
    conn: sqlite3.Connection, user_id: str, task_id: str
) -> list[Reflection]:
    rows = conn.execute(
        """
        SELECT * FROM reflections
        WHERE user_id = ? AND task_id = ?
        ORDER BY round ASC, created_at ASC
        """,
        (user_id, task_id),
    ).fetchall()
    reflections = []
    for r in rows:
        d = dict(r)
        d["critique_codes"] = json.loads(d.pop("critique_codes_json"))
        d["revised"] = bool(d["revised"])
        reflections.append(Reflection.model_validate(d))
    return reflections


def insert_context_manifest(conn: sqlite3.Connection, m: ContextManifest) -> ContextManifest:

    conn.execute(
        """
        INSERT INTO context_manifests (
            id, user_id, call_id, task_id, purpose, budget_tokens, estimated_tokens,
            included_json, excluded_json, redactions_count, prompt_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            m.id,
            m.user_id,
            m.call_id,
            m.task_id,
            m.purpose,
            m.budget_tokens,
            m.estimated_tokens,
            json.dumps(m.included),
            json.dumps(m.excluded),
            m.redactions_count,
            m.prompt_version,
            m.created_at,
        ),
    )
    return m


def get_context_manifest(
    conn: sqlite3.Connection, user_id: str, manifest_id: str
) -> ContextManifest | None:
    row = conn.execute(
        "SELECT * FROM context_manifests WHERE user_id = ? AND id = ?",
        (user_id, manifest_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["included"] = json.loads(d.pop("included_json"))
    d["excluded"] = json.loads(d.pop("excluded_json"))
    return ContextManifest.model_validate(d)


def list_context_manifests(
    conn: sqlite3.Connection,
    user_id: str,
    task_id: str | None = None,
    purpose: str | None = None,
) -> list[ContextManifest]:
    query = "SELECT * FROM context_manifests WHERE user_id = ?"
    params: list[Any] = [user_id]
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    if purpose:
        query += " AND purpose = ?"
        params.append(purpose)
    query += " ORDER BY created_at ASC"

    rows = conn.execute(query, tuple(params)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["included"] = json.loads(d.pop("included_json"))
        d["excluded"] = json.loads(d.pop("excluded_json"))
        results.append(ContextManifest.model_validate(d))
    return results


def insert_trace_span(conn: sqlite3.Connection, s: Span) -> Span:
    conn.execute(
        """
        INSERT INTO trace_spans (
            id, user_id, trace_id, span_id, parent_span_id, kind, name,
            started_at, duration_ms, status, error_code, attrs_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            s.id,
            s.user_id,
            s.trace_id,
            s.span_id,
            s.parent_span_id,
            s.kind,
            s.name,
            s.started_at,
            s.duration_ms,
            s.status,
            s.error_code,
            json.dumps(s.attrs),
            s.created_at,
        ),
    )
    return s


def list_trace_spans(conn: sqlite3.Connection, user_id: str, trace_id: str) -> list[Span]:
    rows = conn.execute(
        "SELECT * FROM trace_spans WHERE user_id = ? AND trace_id = ? ORDER BY started_at ASC",
        (user_id, trace_id),
    ).fetchall()
    spans = []
    for r in rows:
        d = dict(r)
        d["attrs"] = json.loads(d["attrs_json"])
        del d["attrs_json"]
        spans.append(Span.model_validate(d))
    return spans


# ---------------------------------------------------------------------------------------------
# 7. Scheduled Jobs & Runtime
# ---------------------------------------------------------------------------------------------
def upsert_scheduled_job(conn: sqlite3.Connection, j: ScheduledJob) -> ScheduledJob:
    conn.execute(
        """
        INSERT INTO scheduled_jobs (
            id, user_id, job_kind, schedule, next_run_at, lease_owner, lease_until,
            last_status, consecutive_failures, enabled, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, job_kind) DO UPDATE SET
            schedule = excluded.schedule,
            next_run_at = excluded.next_run_at,
            lease_owner = excluded.lease_owner,
            lease_until = excluded.lease_until,
            last_status = excluded.last_status,
            consecutive_failures = excluded.consecutive_failures,
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (
            j.id,
            j.user_id,
            j.job_kind,
            j.schedule,
            j.next_run_at,
            j.lease_owner,
            j.lease_until,
            j.last_status,
            j.consecutive_failures,
            1 if j.enabled else 0,
            j.updated_at,
        ),
    )
    return j


def list_scheduled_jobs(
    conn: sqlite3.Connection, user_id: str, enabled_only: bool = True
) -> list[ScheduledJob]:
    query = "SELECT * FROM scheduled_jobs WHERE user_id = ?"
    params: list[Any] = [user_id]
    if enabled_only:
        query += " AND enabled = 1"
    query += " ORDER BY next_run_at ASC"

    rows = conn.execute(query, params).fetchall()
    jobs = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        jobs.append(ScheduledJob.model_validate(d))
    return jobs


def get_scheduled_job(
    conn: sqlite3.Connection, user_id: str, job_kind: str
) -> ScheduledJob | None:
    row = conn.execute(
        "SELECT * FROM scheduled_jobs WHERE user_id = ? AND job_kind = ?",
        (user_id, job_kind),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return ScheduledJob.model_validate(d)


def get_scheduled_job_by_id(
    conn: sqlite3.Connection, user_id: str, job_id: str
) -> ScheduledJob | None:
    row = conn.execute(
        "SELECT * FROM scheduled_jobs WHERE user_id = ? AND id = ?",
        (user_id, job_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return ScheduledJob.model_validate(d)


def list_due_jobs(
    conn: sqlite3.Connection, user_id: str, as_of: str
) -> list[ScheduledJob]:
    """List enabled jobs due to run at or before as_of whose lease is free."""
    rows = conn.execute(
        """
        SELECT * FROM scheduled_jobs
        WHERE user_id = ?
          AND enabled = 1
          AND next_run_at <= ?
          AND (lease_until IS NULL OR lease_until < ?)
        ORDER BY next_run_at ASC
        """,
        (user_id, as_of, as_of),
    ).fetchall()
    jobs = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        jobs.append(ScheduledJob.model_validate(d))
    return jobs


def acquire_job_lease(
    conn: sqlite3.Connection,
    user_id: str,
    job_id: str,
    lease_owner: str,
    lease_until: str,
    as_of: str,
) -> bool:
    """
    Atomically acquire a lease on a scheduled job.
    Returns True if acquired, False if already held by another active lease.
    """
    cur = conn.execute(
        """
        UPDATE scheduled_jobs
        SET lease_owner = ?, lease_until = ?, updated_at = ?
        WHERE id = ? AND user_id = ? AND enabled = 1
          AND (lease_until IS NULL OR lease_until < ?)
        """,
        (lease_owner, lease_until, as_of, job_id, user_id, as_of),
    )
    return cur.rowcount > 0


def release_job_lease(
    conn: sqlite3.Connection,
    user_id: str,
    job_id: str,
    lease_owner: str,
    next_run_at: str,
    last_status: str,
    consecutive_failures: int,
    updated_at: str,
) -> None:
    """Release a lease and update next_run_at, status, and failure count."""
    conn.execute(
        """
        UPDATE scheduled_jobs
        SET lease_owner = NULL,
            lease_until = NULL,
            next_run_at = ?,
            last_status = ?,
            consecutive_failures = ?,
            updated_at = ?
        WHERE id = ? AND user_id = ? AND lease_owner = ?
        """,
        (next_run_at, last_status, consecutive_failures, updated_at, job_id, user_id, lease_owner),
    )


def insert_job_run(conn: sqlite3.Connection, r: JobRun) -> JobRun:
    conn.execute(
        """
        INSERT INTO job_runs (
            id, user_id, job_id, started_at, finished_at, status,
            attempt, error_code, summary_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.id,
            r.user_id,
            r.job_id,
            r.started_at,
            r.finished_at,
            r.status,
            r.attempt,
            r.error_code,
            json.dumps(r.summary_json),
            r.created_at,
        ),
    )
    return r


def list_job_runs(
    conn: sqlite3.Connection,
    user_id: str,
    job_id: str | None = None,
    limit: int = 100,
) -> list[JobRun]:
    query = "SELECT * FROM job_runs WHERE user_id = ?"
    params: list[Any] = [user_id]
    if job_id is not None:
        query += " AND job_id = ?"
        params.append(job_id)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    runs = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("summary_json"), str):
            d["summary_json"] = json.loads(d["summary_json"])
        runs.append(JobRun.model_validate(d))
    return runs


def get_latest_job_run(
    conn: sqlite3.Connection, user_id: str, job_id: str
) -> JobRun | None:
    row = conn.execute(
        "SELECT * FROM job_runs WHERE user_id = ? AND job_id = ? ORDER BY started_at DESC LIMIT 1",
        (user_id, job_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("summary_json"), str):
        d["summary_json"] = json.loads(d["summary_json"])
    return JobRun.model_validate(d)


def update_job_run(
    conn: sqlite3.Connection,
    run_id: str,
    user_id: str,
    finished_at: str,
    status: str,
    error_code: str | None,
    summary_json: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE job_runs
        SET finished_at = ?, status = ?, error_code = ?, summary_json = ?
        WHERE id = ? AND user_id = ?
        """,
        (finished_at, status, error_code, json.dumps(summary_json), run_id, user_id),
    )


# ---------------------------------------------------------------------------------------------
# 7b. Observability Spans
# ---------------------------------------------------------------------------------------------
def insert_span(conn: sqlite3.Connection, s: Span) -> Span:
    conn.execute(
        """
        INSERT INTO trace_spans (
            id, user_id, trace_id, span_id, parent_span_id,
            kind, name, started_at, duration_ms, status,
            error_code, attrs_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            s.id,
            s.user_id,
            s.trace_id,
            s.span_id,
            s.parent_span_id,
            s.kind,
            s.name,
            s.started_at,
            s.duration_ms,
            s.status,
            s.error_code,
            json.dumps(s.attrs),
            s.created_at,
        ),
    )
    return s


def list_spans(
    conn: sqlite3.Connection,
    user_id: str,
    trace_id: str | None = None,
    limit: int = 1000,
) -> list[Span]:
    query = "SELECT * FROM trace_spans WHERE user_id = ?"
    params: list[Any] = [user_id]
    if trace_id is not None:
        query += " AND trace_id = ?"
        params.append(trace_id)
    query += " ORDER BY started_at ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    spans = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("attrs_json"), str):
            d["attrs"] = json.loads(d.pop("attrs_json"))
        else:
            d["attrs"] = d.pop("attrs_json", {})
        spans.append(Span.model_validate(d))
    return spans


def get_span(conn: sqlite3.Connection, user_id: str, span_id: str) -> Span | None:
    row = conn.execute(
        "SELECT * FROM trace_spans WHERE user_id = ? AND span_id = ?",
        (user_id, span_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("attrs_json"), str):
        d["attrs"] = json.loads(d.pop("attrs_json"))
    else:
        d["attrs"] = d.pop("attrs_json", {})
    return Span.model_validate(d)


# ---------------------------------------------------------------------------------------------
# 8. Feedback Stats (Learning)
# ---------------------------------------------------------------------------------------------
def upsert_feedback_stat(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str,
    subject_key: str,
    alpha_milli: int,
    beta_milli: int,
    updated_at: str,
) -> None:
    fid = f"fb_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO feedback_stats (
            id, user_id, subject_kind, subject_key, alpha_milli, beta_milli, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, subject_kind, subject_key) DO UPDATE SET
            alpha_milli = excluded.alpha_milli,
            beta_milli = excluded.beta_milli,
            updated_at = excluded.updated_at
        """,
        (fid, user_id, subject_kind, subject_key, alpha_milli, beta_milli, updated_at),
    )


def get_feedback_stat(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str,
    subject_key: str,
) -> FeedbackStat | None:
    row = conn.execute(
        "SELECT * FROM feedback_stats WHERE user_id = ? AND subject_kind = ? AND subject_key = ?",
        (user_id, subject_kind, subject_key),
    ).fetchone()
    return FeedbackStat.model_validate(dict(row)) if row else None


def list_feedback_stats(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str | None = None,
) -> list[FeedbackStat]:
    """List all feedback statistics for a tenant, optionally filtered by subject_kind."""
    if subject_kind is not None:
        rows = conn.execute(
            "SELECT * FROM feedback_stats WHERE user_id = ? AND subject_kind = ? ORDER BY subject_key ASC",
            (user_id, subject_kind),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM feedback_stats WHERE user_id = ? ORDER BY subject_kind, subject_key ASC",
            (user_id,),
        ).fetchall()
    return [FeedbackStat.model_validate(dict(r)) for r in rows]


def delete_feedback_stat(
    conn: sqlite3.Connection,
    user_id: str,
    subject_kind: str | None = None,
    subject_key: str | None = None,
) -> int:
    """Delete a specific feedback stat row or all stats for a subject_kind."""
    if subject_kind is not None and subject_key is not None:
        cur = conn.execute(
            "DELETE FROM feedback_stats WHERE user_id = ? AND subject_kind = ? AND subject_key = ?",
            (user_id, subject_kind, subject_key),
        )
    elif subject_key is not None:
        cur = conn.execute(
            "DELETE FROM feedback_stats WHERE user_id = ? AND subject_key = ?",
            (user_id, subject_key),
        )
    elif subject_kind is not None:
        cur = conn.execute(
            "DELETE FROM feedback_stats WHERE user_id = ? AND subject_kind = ?",
            (user_id, subject_kind),
        )
    else:
        cur = conn.execute(
            "DELETE FROM feedback_stats WHERE user_id = ?",
            (user_id,),
        )
    return cur.rowcount




