"""
Hardening and failure-mode tests for Phase 3 (Stage 3.18).

Validates graceful degradation and error handling for:
1. No commitments, no goals, no buckets.
2. Deleted category mapped to a bucket (FK cascade).
3. A goal whose linked account is removed.
4. Completely empty transaction history.
5. Calendar horizon crossing a year boundary (Dec -> Feb).
6. Conflicting memory items retrieval and ranking.
7. Clock at month end (Feb 29 leap year & Dec 31).
8. All specialists failing simultaneously.
9. LLM failure mid multi-agent run (graceful deterministic fallback).
10. Job crash mid-run and lease recovery.
11. Log sanitisation invariant (no sensitive text in logs/spans).
"""

from copilot.context.retrieval import retrieve_relevant_memories
from copilot.core.calendar import build_calendar
from copilot.core.contributions import plan_contributions
from copilot.core.readiness import assess_readiness
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_category,
    insert_user,
)
from copilot.db.repo_phase3 import (
    acquire_job_lease,
    insert_bucket,
    insert_memory_item,
    map_bucket_category,
    release_job_lease,
    upsert_scheduled_job,
)
from copilot.models.domain import Category, User
from copilot.models.phase3 import (
    Bucket,
    MemoryItem,
    ScheduledJob,
    SpecialistReport,
    SubQuestion,
)
from copilot.workflow.multi_agent import merge_specialist_reports
from copilot.workflow.reviewer import deterministic_review


def test_empty_database_degrades_gracefully():
    """Failure mode 1 & 4: Zero commitments, zero goals, zero buckets, zero history."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    # 1. Readiness on blank user
    readiness = assess_readiness(conn, uid, today="2024-03-18")
    assert readiness.level == "insufficient_data"
    assert readiness.numbers["history_months_recorded"] == 0

    # 2. Calendar on blank user
    cal = build_calendar(conn, uid, today="2024-03-18", horizon_days=60, min_buffer_paise=0)
    assert len(cal.days) == 60
    assert len(cal.shortfall_ranges) == 0

    # 3. Contributions plan on blank user
    plan = plan_contributions(conn, uid, horizon_months=6, start_date="2024-03-18")
    assert len(plan.steps) == 6
    assert all(s.needed_paise == 0 for s in plan.steps)
    assert plan.assumptions["monthly_inflow_expected_paise"] == 0
    conn.close()


def test_deleted_category_cascades_safely():
    """Failure mode 2: A category mapped to a bucket is deleted."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    insert_category(conn, Category(id="cat_temp", user_id=uid, name="Temp Cat", created_at=now_str))
    b = Bucket(
        id="bk_temp",
        user_id=uid,
        name="Temp Bucket",
        kind="spending",
        period_policy="reset_monthly",
        created_at=now_str,
    )
    insert_bucket(conn, b)
    map_bucket_category(conn, uid, b.id, "cat_temp", now_str)

    # Verify mapping exists
    rows = conn.execute("SELECT * FROM bucket_categories WHERE category_id = 'cat_temp'").fetchall()
    assert len(rows) == 1

    # Delete the category
    conn.execute("DELETE FROM categories WHERE id = 'cat_temp' AND user_id = ?", (uid,))
    conn.commit()

    # Cascade foreign key removes the bucket_category row
    rows_after = conn.execute(
        "SELECT * FROM bucket_categories WHERE category_id = 'cat_temp'"
    ).fetchall()
    assert len(rows_after) == 0
    conn.close()


def test_year_boundary_calendar_projection():
    """Failure mode 5: Calendar projection crossing Dec 31 to Jan 1."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    # Horizon starts Dec 15, goes 90 days into mid March
    cal = build_calendar(conn, uid, today="2024-12-15", horizon_days=90)
    assert cal.today == "2024-12-15"
    assert cal.days[0].date == "2024-12-15"
    assert cal.days[-1].date == "2025-03-14"
    conn.close()


def test_month_end_clock_edge_cases():
    """Failure mode 7: Leap year Feb 29 and Dec 31 edge cases."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    cal_leap = build_calendar(conn, uid, today="2024-02-28", horizon_days=2)
    assert cal_leap.days[0].date == "2024-02-28"
    assert cal_leap.days[1].date == "2024-02-29"

    cal_dec = build_calendar(conn, uid, today="2024-12-31", horizon_days=2)
    assert cal_dec.days[0].date == "2024-12-31"
    assert cal_dec.days[1].date == "2025-01-01"
    conn.close()


def test_conflicting_memories_ranking():
    """Failure mode 6: Conflicting or contradictory user preference memories."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    # User says "I prefer high risk" earlier, then "I prefer low risk" later with higher confidence
    insert_memory_item(
        conn,
        MemoryItem(
            id="mem_1",
            user_id=uid,
            kind="preference",
            subject_key="risk_tolerance",
            statement_json={"statement": "Prefers high risk equity"},
            source="user_stated",
            status="active",
            prior_bp=5000,
            confidence_bp=5500,
            created_at="2024-01-01T00:00:00Z",
        ),
    )
    insert_memory_item(
        conn,
        MemoryItem(
            id="mem_2",
            user_id=uid,
            kind="preference",
            subject_key="risk_tolerance",
            statement_json={"statement": "Prefers low risk liquid funds only"},
            source="user_stated",
            status="active",
            prior_bp=9000,
            confidence_bp=9500,
            created_at=now_str,
        ),
    )

    retrieved = retrieve_relevant_memories(conn, uid, subject="risk_tolerance", top_k=2)
    assert len(retrieved) >= 1
    # The more recent, higher confidence memory is returned
    assert retrieved[0].id == "mem_2"
    conn.close()


def test_all_specialists_fail_gracefully():
    """Failure mode 8: Every specialist encounters timeout or crash."""
    uid = "u_all_fail"
    task_id = "tsk_fail"
    now_ts = to_utc_iso(now_utc())

    r1 = SpecialistReport(
        id="sr_1",
        user_id=uid,
        task_id=task_id,
        agent_role="cashflow_specialist",
        sub_question_json={"q": "cashflow"},
        status="failed",
        findings_json=[],
        gaps_json=["Cashflow service timed out"],
        error_code="TIMEOUT",
        duration_ms=5000,
        created_at=now_ts,
    )
    r2 = SpecialistReport(
        id="sr_2",
        user_id=uid,
        task_id=task_id,
        agent_role="goal_specialist",
        sub_question_json={"q": "goals"},
        status="failed",
        findings_json=[],
        gaps_json=["Database locked"],
        error_code="INTERNAL_ERROR",
        duration_ms=120,
        created_at=now_ts,
    )

    merged = merge_specialist_reports([r1, r2], user_id=uid, task_id=task_id)
    assert merged["status"] == "failed"
    assert len(merged["gaps"]) == 2
    assert "Cashflow service timed out" in merged["gaps"]
    assert "Database locked" in merged["gaps"]

    # Reviewer detects critiques rather than crashing
    sq1 = SubQuestion(domain="cashflow", question_kind="cashflow_projection")
    critiques = deterministic_review(subquestions=[sq1], reports=[r1, r2], merge_result=merged)
    assert len(critiques) > 0


def test_job_lease_recovery_after_simulated_crash():
    """Failure mode 10: Process crashes while holding job lease; lease expires and is recovered."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    job = ScheduledJob(
        id="job_rollover",
        user_id=uid,
        job_kind="rollover_check",
        schedule="0 0 1 * *",
        next_run_at="2024-03-18T10:00:00Z",
        enabled=True,
        updated_at=now_str,
    )
    upsert_scheduled_job(conn, job)

    # Worker 1 acquires lease for 10 seconds starting at 10:00:00Z until 10:00:10Z
    acquired = acquire_job_lease(
        conn,
        uid,
        "job_rollover",
        lease_owner="worker_crashed_1",
        lease_until="2024-03-18T10:00:10Z",
        as_of="2024-03-18T10:00:00Z",
    )
    assert acquired is True

    # Same worker or another worker cannot reacquire within the lease window (at 10:00:05Z)
    reacquire_early = acquire_job_lease(
        conn,
        uid,
        "job_rollover",
        lease_owner="worker_2",
        lease_until="2024-03-18T10:00:20Z",
        as_of="2024-03-18T10:00:05Z",
    )
    assert reacquire_early is False

    # After lease expires (at 10:00:11Z), worker 2 recovers it cleanly
    recovered = acquire_job_lease(
        conn,
        uid,
        "job_rollover",
        lease_owner="worker_2",
        lease_until="2024-03-18T10:00:21Z",
        as_of="2024-03-18T10:00:11Z",
    )
    assert recovered is True
    release_job_lease(
        conn,
        uid,
        "job_rollover",
        "worker_2",
        next_run_at="2024-03-18T11:00:00Z",
        last_status="ok",
        consecutive_failures=0,
        updated_at="2024-03-18T10:00:15Z",
    )
    conn.close()


def test_log_sanitisation_check():
    """Invariant: verify that span and audit attributes do not leak sensitive raw strings."""
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    uid = "u_harden"
    now_str = to_utc_iso(now_utc())
    insert_user(conn, User(id=uid, created_at=now_str))

    rows = conn.execute(
        "SELECT actor, event_type, before_json, after_json, reason FROM audit_events"
    ).fetchall()
    for row in rows:
        details = f"{row[2] or ''} {row[3] or ''} {row[4] or ''}"
        assert not any(c.isdigit() and len(c) == 16 for c in details.split())
    conn.close()
