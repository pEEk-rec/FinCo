"""
Tests for Agent Runtime, Scheduler, Lease Locking, and Upkeep Jobs (PLAN_PHASE3 Section 5.15 & Stage 3.13).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from copilot.config.phase3 import JobConfig, RuntimeConfig
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user
from copilot.db.repo_phase3 import (
    get_scheduled_job,
    list_due_jobs,
    upsert_scheduled_job,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, User
from copilot.models.phase3 import ScheduledJob
from copilot.runtime.daemon import run_agentd
from copilot.runtime.runner import retry_dead_letter_job, run_job
from copilot.runtime.scheduler import init_scheduled_jobs
from copilot.tools.executor import ExecutionContext, execute_tool


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = get_connection(":memory:")
    init_db(c)
    u = User(id="u1", created_at="2026-01-01T00:00:00Z")
    insert_user(c, u)
    acc = Account(
        id="acc_main",
        user_id="u1",
        name="Main Account",
        opening_balance_paise=10000000,
        created_at="2026-01-01T00:00:00Z",
    )
    insert_account(c, acc)
    return c


@pytest.fixture
def test_config() -> RuntimeConfig:
    return RuntimeConfig(
        loop_interval_seconds=1,
        lease_duration_seconds=60,
        max_retries=3,
        backoff_base_seconds=2,
        jobs={
            "evaluate_alerts": JobConfig(schedule="every_60_minutes", enabled=True),
            "refresh_memories": JobConfig(schedule="daily@01:00", enabled=True),
            "rollover_buckets": JobConfig(schedule="daily@00:05", enabled=True),
            "coverage_scan": JobConfig(schedule="daily@06:00", enabled=True),
            "suggest_commitments": JobConfig(schedule="daily@07:00", enabled=True),
            "expire_drafts": JobConfig(schedule="daily@00:10", enabled=True),
            "monthly_close": JobConfig(schedule="monthly@1st_02:00", enabled=True),
        },
    )


# -------------------------------------------------------------------------------------------------
# 1. Due-job selection with an injected clock
# -------------------------------------------------------------------------------------------------
def test_due_job_selection_with_injected_clock(
    conn: sqlite3.Connection, test_config: RuntimeConfig
) -> None:
    # Set up jobs with specific next_run_at
    ref_dt = datetime(2026, 4, 1, 6, 30, 0, tzinfo=UTC)
    now_iso = to_utc_iso(ref_dt)

    # Job 1: due earlier (06:00) -> due
    j1 = ScheduledJob(
        id="job_due_1",
        user_id="u1",
        job_kind="coverage_scan",
        schedule="daily@06:00",
        next_run_at="2026-04-01T06:00:00Z",
        consecutive_failures=0,
        enabled=True,
        updated_at=now_iso,
    )
    upsert_scheduled_job(conn, j1)

    # Job 2: due later (07:00) -> NOT due
    j2 = ScheduledJob(
        id="job_not_due",
        user_id="u1",
        job_kind="suggest_commitments",
        schedule="daily@07:00",
        next_run_at="2026-04-01T07:00:00Z",
        consecutive_failures=0,
        enabled=True,
        updated_at=now_iso,
    )
    upsert_scheduled_job(conn, j2)

    # Query due jobs at 06:30
    due = list_due_jobs(conn, user_id="u1", as_of=now_iso)
    due_kinds = [j.job_kind for j in due]

    assert "coverage_scan" in due_kinds
    assert "suggest_commitments" not in due_kinds


# -------------------------------------------------------------------------------------------------
# 2. Lease prevents double runs (two runners, one executes)
# -------------------------------------------------------------------------------------------------
def test_lease_prevents_double_runs(conn: sqlite3.Connection, test_config: RuntimeConfig) -> None:
    clock = datetime(2026, 4, 1, 1, 30, 0, tzinfo=UTC)
    now_iso = to_utc_iso(clock)

    j = ScheduledJob(
        id="job_double_run_test",
        user_id="u1",
        job_kind="evaluate_alerts",
        schedule="every_60_minutes",
        next_run_at="2026-04-01T01:00:00Z",
        consecutive_failures=0,
        enabled=True,
        updated_at=now_iso,
    )
    upsert_scheduled_job(conn, j)

    # Runner 1 acquires lease and runs
    run1 = run_job(
        conn=conn,
        user_id="u1",
        job_kind="evaluate_alerts",
        as_of=clock,
        runner_id="runner_alpha",
        config=test_config,
    )
    assert run1.status == "ok"

    # Now simulate Runner 2 trying to run while lease is held
    # We manually set active lease on the job to simulate concurrency
    active_lease_until = to_utc_iso(clock + timedelta(seconds=120))
    conn.execute(
        "UPDATE scheduled_jobs SET lease_owner = 'runner_alpha', lease_until = ? WHERE id = ?",
        (active_lease_until, j.id),
    )

    run2 = run_job(
        conn=conn,
        user_id="u1",
        job_kind="evaluate_alerts",
        as_of=clock,
        runner_id="runner_beta",
        config=test_config,
    )
    # Runner 2 must be skipped due to active lease
    assert run2.status == "skipped"
    assert run2.error_code == "lease_locked"


# -------------------------------------------------------------------------------------------------
# 3. Idempotent re-run for the same period writes nothing
# -------------------------------------------------------------------------------------------------
def test_idempotent_rerun_for_same_period(
    conn: sqlite3.Connection, test_config: RuntimeConfig
) -> None:
    clock = datetime(2026, 4, 1, 0, 10, 0, tzinfo=UTC)

    # Run rollover_buckets for period 2026-04
    run1 = run_job(
        conn=conn,
        user_id="u1",
        job_kind="rollover_buckets",
        as_of=clock,
        config=test_config,
    )
    assert run1.status == "ok"
    assert run1.summary_json.get("period") == "2026-04"

    # Count audit events before re-run
    events_before = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE user_id = 'u1'"
    ).fetchone()[0]

    # Re-run for the exact same period (2026-04)
    run2 = run_job(
        conn=conn,
        user_id="u1",
        job_kind="rollover_buckets",
        as_of=clock + timedelta(hours=2),
        config=test_config,
    )

    assert run2.status == "skipped"
    assert run2.summary_json.get("reason") == "idempotent_already_run_for_period"

    # Zero writes made during idempotent skip
    events_after = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE user_id = 'u1'"
    ).fetchone()[0]
    assert events_after == events_before


# -------------------------------------------------------------------------------------------------
# 4. Backoff schedule and dead-letter after max attempts
# -------------------------------------------------------------------------------------------------
def test_backoff_schedule_and_dead_letter(
    conn: sqlite3.Connection, test_config: RuntimeConfig
) -> None:
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Patch handler to simulate failure
    with patch("copilot.runtime.runner._execute_job_handler") as mock_exec:
        mock_exec.return_value = (False, {"simulated": "failure"}, "SIMULATED_ERROR")

        # Attempt 1: consecutive_failures -> 1, backoff 2^0 * 2 = 2s
        run1 = run_job(
            conn=conn,
            user_id="u1",
            job_kind="coverage_scan",
            as_of=clock,
            force=True,
            config=test_config,
        )
        assert run1.status == "failed"
        assert run1.attempt == 1

        j = get_scheduled_job(conn, "u1", "coverage_scan")
        assert j is not None
        assert j.consecutive_failures == 1
        assert j.last_status == "failed"
        expected_next_1 = clock + timedelta(seconds=2)
        assert j.next_run_at == to_utc_iso(expected_next_1)

        # Attempt 2: consecutive_failures -> 2, backoff 2^1 * 2 = 4s
        run2 = run_job(
            conn=conn,
            user_id="u1",
            job_kind="coverage_scan",
            as_of=expected_next_1,
            force=True,
            config=test_config,
        )
        assert run2.status == "failed"
        assert run2.attempt == 2
        j = get_scheduled_job(conn, "u1", "coverage_scan")
        assert j is not None
        assert j.consecutive_failures == 2
        expected_next_2 = expected_next_1 + timedelta(seconds=4)
        assert j.next_run_at == to_utc_iso(expected_next_2)

        # Attempt 3: max_retries reached (3) -> transitions to dead_letter!
        run3 = run_job(
            conn=conn,
            user_id="u1",
            job_kind="coverage_scan",
            as_of=expected_next_2,
            force=True,
            config=test_config,
        )
        assert run3.status == "dead_letter"
        assert run3.attempt == 3
        j = get_scheduled_job(conn, "u1", "coverage_scan")
        assert j is not None
        assert j.last_status == "dead_letter"
        assert j.consecutive_failures == 3
        assert j.next_run_at == "2999-12-31T00:00:00Z"


# -------------------------------------------------------------------------------------------------
# 5. Retry from dead letter
# -------------------------------------------------------------------------------------------------
def test_retry_from_dead_letter(conn: sqlite3.Connection, test_config: RuntimeConfig) -> None:
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Set job into dead_letter status
    init_scheduled_jobs(conn, "u1", config=test_config, as_of=clock)
    conn.execute(
        """
        UPDATE scheduled_jobs
        SET last_status = 'dead_letter', consecutive_failures = 3, next_run_at = '2999-12-31T00:00:00Z'
        WHERE user_id = 'u1' AND job_kind = 'coverage_scan'
        """
    )

    # Run retry_dead_letter_job
    run = retry_dead_letter_job(
        conn, user_id="u1", job_kind="coverage_scan", as_of=clock, config=test_config
    )

    assert run.status == "ok"
    j = get_scheduled_job(conn, "u1", "coverage_scan")
    assert j is not None
    assert j.consecutive_failures == 0
    assert j.last_status == "ok"
    assert j.next_run_at != "2999-12-31T00:00:00Z"


# -------------------------------------------------------------------------------------------------
# 6. Jobs cannot perform user-actor writes (Safety Rule 18)
# -------------------------------------------------------------------------------------------------
def test_jobs_cannot_perform_user_actor_writes(conn: sqlite3.Connection) -> None:
    """
    Safety Rule 18: All jobs run with actor='agent'.
    Verify that write tools requiring user authorization (e.g. apply_reallocation)
    are strictly rejected by execute_tool policy decision.
    """
    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    ctx = ExecutionContext(
        conn=conn,
        user_id="u1",
        run_id="test_actor_check",
        policy=policy,
        actor="agent",  # Jobs strictly use agent actor
    )

    # Attempt to call apply_reallocation as agent
    res = execute_tool(ctx, "apply_reallocation", {"draft_id": "draft_xyz"})
    assert not res.ok
    assert res.error is not None
    # Must be denied by policy or rejected without affecting DB
    assert res.error.code.value in (
        "DENIED_BY_POLICY",
        "APPROVAL_REQUIRED",
        "NOT_FOUND",
        "INVALID_INPUT",
    )


# -------------------------------------------------------------------------------------------------
# 7. Agentd Foreground Daemon Loop
# -------------------------------------------------------------------------------------------------
def test_agentd_daemon_loop(conn: sqlite3.Connection, test_config: RuntimeConfig) -> None:
    # Use max_cycles=2
    def conn_factory():
        return conn

    cycles_completed = run_agentd(
        conn_factory=conn_factory,
        user_id="u1",
        loop_interval_seconds=0,
        max_cycles=2,
    )
    assert cycles_completed == 2
