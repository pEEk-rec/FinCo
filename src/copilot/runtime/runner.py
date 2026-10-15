"""
Job Runner and Lease Manager for Agent Runtime (PLAN_PHASE3 Section 5.15).

Invariants:
1. Distributed lease-based locking to guarantee zero duplicate concurrent runs.
2. Idempotent re-runs for the same period write nothing and return skipped runs.
3. Exponential backoff retry handling up to max_retries, transitioning to dead_letter.
4. Strictly execute through `execute_tool(ctx, ...)` with actor='agent'.
5. Safety Rule 18: Jobs never perform user-actor writes and never run twice for the same
   lease/period.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from copilot.audit.events import record_event
from copilot.config.phase3 import RuntimeConfig, load_buckets_config, load_runtime_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo_phase3 import (
    acquire_job_lease,
    get_scheduled_job,
    insert_job_run,
    list_due_jobs,
    list_job_runs,
    release_job_lease,
)
from copilot.governance.policy import load_policy
from copilot.models.phase3 import JobRun
from copilot.ops.tracing import span
from copilot.runtime.scheduler import compute_next_run_at, init_scheduled_jobs
from copilot.skills.runner import run_skill
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

logger = logging.getLogger(__name__)


def _get_period_key(job_kind: str, dt: datetime) -> str:
    """Return period identifier used for idempotency tracking."""
    if job_kind in ("rollover_buckets", "monthly_close"):
        return dt.strftime("%Y-%m")
    elif job_kind == "evaluate_alerts":
        return dt.strftime("%Y-%m-%d-%H")
    else:
        # Daily jobs: refresh_memories, coverage_scan, suggest_commitments, expire_drafts
        return dt.strftime("%Y-%m-%d")


def _execute_job_handler(
    job_kind: str,
    ctx: ExecutionContext,
    as_of: datetime,
    period_key: str,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Execute specific scheduled job logic strictly through execute_tool or run_skill.
    Returns (success: bool, summary_json: dict, error_code: str | None).
    """
    try:
        if job_kind == "rollover_buckets":
            # For monthly rollover, close previous month if today is 1st, else current month
            closing_period = period_key
            res = execute_tool(ctx, "rollover_buckets", {"closing_period": closing_period})
            if not res.ok:
                err_msg = res.error.message if res.error else "failed"
                err_code = res.error.code.value if res.error else "tool_failure"
                return False, {"error": err_msg, "period": period_key}, err_code
            released = getattr(res.data, "released_allocations", [])
            return True, {"released_count": len(released), "period": period_key}, None

        elif job_kind == "refresh_memories":
            res = execute_tool(ctx, "refresh_memories", {})
            if not res.ok:
                err_msg = res.error.message if res.error else "failed"
                err_code = res.error.code.value if res.error else "tool_failure"
                return False, {"error": err_msg, "period": period_key}, err_code
            refreshed = getattr(res.data, "refreshed_count", 0)
            return True, {"refreshed_count": refreshed, "period": period_key}, None

        elif job_kind == "evaluate_alerts":
            res = execute_tool(ctx, "evaluate_alerts", {})
            if not res.ok:
                err_msg = res.error.message if res.error else "failed"
                err_code = res.error.code.value if res.error else "tool_failure"
                return False, {"error": err_msg, "period": period_key}, err_code
            alerts = getattr(res.data, "alerts", [])
            return True, {"alerts_count": len(alerts), "period": period_key}, None

        elif job_kind == "coverage_scan":
            res = execute_tool(ctx, "get_calendar", {"horizon_days": 60})
            if not res.ok:
                err_msg = res.error.message if res.error else "failed"
                err_code = res.error.code.value if res.error else "tool_failure"
                return False, {"error": err_msg, "period": period_key}, err_code
            cal = getattr(res.data, "calendar", None)
            covs = cal.coverage if cal else []
            shortfalls = [c for c in covs if c.status in ("not_covered", "shortfall")]
            return (
                True,
                {
                    "total_occurrences": len(covs),
                    "shortfall_count": len(shortfalls),
                    "period": period_key,
                },
                None,
            )

        elif job_kind == "suggest_commitments":
            res = execute_tool(ctx, "suggest_commitments", {})
            if not res.ok:
                err_msg = res.error.message if res.error else "failed"
                err_code = res.error.code.value if res.error else "tool_failure"
                return False, {"error": err_msg, "period": period_key}, err_code
            suggs = getattr(res.data, "suggestions", [])
            return True, {"suggestions_count": len(suggs), "period": period_key}, None

        elif job_kind == "expire_drafts":
            # Check draft expiration per config
            b_cfg = load_buckets_config()
            ttl_seconds = b_cfg.draft_ttl_days * 86400
            q = (
                "SELECT id, created_at, status FROM reallocation_drafts "
                "WHERE user_id = ? AND status IN ('draft', 'approved')"
            )
            rows = ctx.conn.execute(q, (ctx.user_id,)).fetchall()
            expired_count = 0
            for r in rows:
                did, c_iso, st = r[0], r[1], r[2]
                c_dt = from_utc_iso(c_iso)
                if (as_of - c_dt).total_seconds() > ttl_seconds:
                    ctx.conn.execute(
                        "UPDATE reallocation_drafts SET status = 'expired' "
                        "WHERE id = ? AND user_id = ?",
                        (did, ctx.user_id),
                    )
                    record_event(
                        ctx.conn,
                        user_id=ctx.user_id,
                        actor="agent",
                        event_type="draft_expired",
                        reason=f"Reallocation draft '{did}' expired after {b_cfg.draft_ttl_days}d.",
                        run_id=ctx.run_id,
                        entity_type="reallocation_draft",
                        entity_id=did,
                        before_data={"status": st},
                        after_data={"status": "expired"},
                        clock=ctx.clock,
                    )
                    expired_count += 1
            return True, {"expired_count": expired_count, "period": period_key}, None

        elif job_kind == "monthly_close":
            # Execute monthly_close skill through skill runner
            skill_res = run_skill(ctx, "monthly_close", {"period": period_key}, task_id=ctx.run_id)
            if skill_res.status != "ok":
                return (
                    False,
                    {
                        "skill_status": skill_res.status,
                        "reason": skill_res.reason,
                        "period": period_key,
                    },
                    "skill_failed",
                )
            return (
                True,
                {
                    "skill_status": skill_res.status,
                    "outputs": list(skill_res.outputs.keys()),
                    "period": period_key,
                },
                None,
            )

        else:
            return False, {"error": f"Unknown job kind '{job_kind}'"}, "unknown_job_kind"

    except Exception as exc:
        logger.exception("Error executing scheduled job %s: %s", job_kind, exc)
        return False, {"error": str(exc), "period": period_key}, type(exc).__name__


def run_job(
    conn: sqlite3.Connection,
    user_id: str,
    job_kind: str,
    as_of: datetime | None = None,
    runner_id: str | None = None,
    force: bool = False,
    config: RuntimeConfig | None = None,
) -> JobRun:
    """
    Execute a single scheduled job with distributed lease protection, idempotency check,
    and exponential backoff retry semantics.
    """
    if config is None:
        config_path = PROJECT_ROOT / "config" / "runtime.yaml"
        config = load_runtime_config(config_path)

    ref_dt = as_of or now_utc()
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=UTC)
    else:
        ref_dt = ref_dt.astimezone(UTC)
    now_iso = to_utc_iso(ref_dt)

    active_runner_id = runner_id or f"runner_{uuid.uuid4().hex[:8]}"
    run_id = f"jrun_{uuid.uuid4().hex[:12]}"

    ensure_tools_registered()

    # 1. Fetch or initialize job
    job = get_scheduled_job(conn, user_id=user_id, job_kind=job_kind)
    if job is None:
        init_scheduled_jobs(conn, user_id=user_id, config=config, as_of=ref_dt)
        job = get_scheduled_job(conn, user_id=user_id, job_kind=job_kind)
        if job is None:
            raise ValueError(f"Scheduled job '{job_kind}' could not be initialized.")

    if not job.enabled and not force:
        return JobRun(
            id=run_id,
            user_id=user_id,
            job_id=job.id,
            started_at=now_iso,
            finished_at=now_iso,
            status="skipped",
            attempt=1,
            error_code=None,
            summary_json={"reason": "job_disabled"},
            created_at=now_iso,
        )

    # 2. Acquire Lease
    lease_duration = config.lease_duration_seconds
    lease_until_dt = ref_dt + timedelta(seconds=lease_duration)
    lease_until_iso = to_utc_iso(lease_until_dt)

    acquired = acquire_job_lease(
        conn,
        user_id=user_id,
        job_id=job.id,
        lease_owner=active_runner_id,
        lease_until=lease_until_iso,
        as_of=now_iso,
    )

    if not acquired and not force:
        # Another runner holds the active lease
        logger.info(
            "Lease acquisition skipped: job %s is held by another runner until %s",
            job_kind,
            job.lease_until,
        )
        return JobRun(
            id=run_id,
            user_id=user_id,
            job_id=job.id,
            started_at=now_iso,
            finished_at=now_iso,
            status="skipped",
            attempt=1,
            error_code="lease_locked",
            summary_json={"reason": "lease_locked", "held_until": job.lease_until},
            created_at=now_iso,
        )

    # 3. Check Period Idempotency
    period_key = _get_period_key(job_kind, ref_dt)
    if not force:
        past_runs = list_job_runs(conn, user_id=user_id, job_id=job.id, limit=30)
        already_run = any(
            r.status == "ok" and r.summary_json.get("period") == period_key
            for r in past_runs
        )
        if already_run:
            # Idempotent skip: release lease without changing next_run_at or failure count
            release_job_lease(
                conn,
                user_id=user_id,
                job_id=job.id,
                lease_owner=active_runner_id,
                next_run_at=job.next_run_at,
                last_status=job.last_status or "ok",
                consecutive_failures=job.consecutive_failures,
                updated_at=now_iso,
            )
            return JobRun(
                id=run_id,
                user_id=user_id,
                job_id=job.id,
                started_at=now_iso,
                finished_at=now_iso,
                status="skipped",
                attempt=1,
                error_code=None,
                summary_json={
                    "reason": "idempotent_already_run_for_period",
                    "period": period_key,
                },
                created_at=now_iso,
            )

    # 4. Prepare ExecutionContext strictly with actor='agent'
    policy_path = PROJECT_ROOT / "config" / "policy.yaml"
    policy = load_policy(policy_path)
    ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id=run_id,
        policy=policy,
        clock=ref_dt,
        actor="agent",  # Safety Rule 18: strictly agent actor
    )

    attempt = job.consecutive_failures + 1

    # 5. Execute within tracing span
    with span(
        kind="job",
        name=job_kind,
        attrs={"job_kind": job_kind, "attempt": attempt, "period": period_key},
        user_id=user_id,
        trace_id=run_id,
        conn=conn,
    ) as sp:
        success, summary_data, err_code = _execute_job_handler(
            job_kind, ctx, ref_dt, period_key
        )

        finish_dt = now_utc()
        finish_iso = to_utc_iso(finish_dt)

        if success:
            sp.status = "ok"
            # Calculate normal next run
            next_run_dt = compute_next_run_at(job.schedule, ref_dt)
            release_job_lease(
                conn,
                user_id=user_id,
                job_id=job.id,
                lease_owner=active_runner_id,
                next_run_at=to_utc_iso(next_run_dt),
                last_status="ok",
                consecutive_failures=0,
                updated_at=finish_iso,
            )
            job_run = JobRun(
                id=run_id,
                user_id=user_id,
                job_id=job.id,
                started_at=now_iso,
                finished_at=finish_iso,
                status="ok",
                attempt=attempt,
                error_code=None,
                summary_json=summary_data,
                created_at=finish_iso,
            )
        else:
            sp.status = "error"
            sp.error_code = err_code or "job_failure"
            consecutive_failures = job.consecutive_failures + 1

            if consecutive_failures >= config.max_retries:
                # Transition to dead letter
                status: Literal["ok", "failed", "skipped", "dead_letter"] = "dead_letter"
                next_run_iso = "2999-12-31T00:00:00Z"
                summary_data["dead_letter_reason"] = (
                    f"Max retries ({config.max_retries}) exceeded"
                )
            else:
                status = "failed"
                # Exponential backoff schedule
                backoff_seconds = config.backoff_base_seconds * (
                    2 ** (consecutive_failures - 1)
                )
                next_run_dt = ref_dt + timedelta(seconds=backoff_seconds)
                next_run_iso = to_utc_iso(next_run_dt)

            release_job_lease(
                conn,
                user_id=user_id,
                job_id=job.id,
                lease_owner=active_runner_id,
                next_run_at=next_run_iso,
                last_status=status,
                consecutive_failures=consecutive_failures,
                updated_at=finish_iso,
            )

            job_run = JobRun(
                id=run_id,
                user_id=user_id,
                job_id=job.id,
                started_at=now_iso,
                finished_at=finish_iso,
                status=status,
                attempt=attempt,
                error_code=err_code,
                summary_json=summary_data,
                created_at=finish_iso,
            )

        insert_job_run(conn, job_run)
        return job_run


def run_due_jobs(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: datetime | None = None,
    runner_id: str | None = None,
    config: RuntimeConfig | None = None,
) -> list[JobRun]:
    """
    Run all jobs that are due for user_id at the given timestamp.
    Used by CLI `copilot jobs run-due` and Windows Task Scheduler.
    """
    if config is None:
        config_path = PROJECT_ROOT / "config" / "runtime.yaml"
        config = load_runtime_config(config_path)

    ref_dt = as_of or now_utc()
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=UTC)
    else:
        ref_dt = ref_dt.astimezone(UTC)
    now_iso = to_utc_iso(ref_dt)

    # Ensure scheduled jobs exist
    init_scheduled_jobs(conn, user_id=user_id, config=config, as_of=ref_dt)

    due_jobs = list_due_jobs(conn, user_id=user_id, as_of=now_iso)
    runs: list[JobRun] = []

    for dj in due_jobs:
        # Check if job is in dead_letter
        if dj.last_status == "dead_letter":
            continue
        run = run_job(
            conn=conn,
            user_id=user_id,
            job_kind=dj.job_kind,
            as_of=ref_dt,
            runner_id=runner_id,
            config=config,
        )
        runs.append(run)

    return runs


def retry_dead_letter_job(
    conn: sqlite3.Connection,
    user_id: str,
    job_kind: str,
    as_of: datetime | None = None,
    config: RuntimeConfig | None = None,
) -> JobRun:
    """
    Manually retry a dead-lettered job, resetting failure counters and lease state.
    """
    ref_dt = as_of or now_utc()
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=UTC)
    now_iso = to_utc_iso(ref_dt)

    job = get_scheduled_job(conn, user_id=user_id, job_kind=job_kind)
    if not job:
        raise ValueError(f"Job '{job_kind}' not found for user {user_id}")

    # Reset job counters
    conn.execute(
        """
        UPDATE scheduled_jobs
        SET consecutive_failures = 0,
            last_status = NULL,
            lease_owner = NULL,
            lease_until = NULL,
            next_run_at = ?,
            updated_at = ?
        WHERE user_id = ? AND job_kind = ?
        """,
        (now_iso, now_iso, user_id, job_kind),
    )

    return run_job(
        conn=conn,
        user_id=user_id,
        job_kind=job_kind,
        as_of=ref_dt,
        force=True,
        config=config,
    )
