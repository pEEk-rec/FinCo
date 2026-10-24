"""
Scheduler and Schedule Parser for Agent Runtime (PLAN_PHASE3 Section 5.15).

Supports:
- "daily@HH:MM" (e.g., "daily@00:05", "daily@01:00")
- "every_N_minutes" (e.g., "every_60_minutes")
- "monthly@1st_HH:MM" (e.g., "monthly@1st_02:00")
- Seeding and initialization of scheduled_jobs rows for a tenant user
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from copilot.config.phase3 import RuntimeConfig, load_runtime_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import get_scheduled_job, upsert_scheduled_job
from copilot.models.phase3 import ScheduledJob


def compute_next_run_at(schedule: str, from_dt: datetime) -> datetime:
    """
    Calculate the next occurrence datetime based on schedule format.
    Always returns a timezone-aware UTC datetime.
    """
    if from_dt.tzinfo is None:
        from_dt = from_dt.replace(tzinfo=UTC)
    else:
        from_dt = from_dt.astimezone(UTC)

    # 1. daily@HH:MM
    m_daily = re.match(r"^daily@(\d{2}):(\d{2})$", schedule.strip())
    if m_daily:
        hour, minute = int(m_daily.group(1)), int(m_daily.group(2))
        candidate = from_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_dt:
            candidate += timedelta(days=1)
        return candidate

    # 2. every_N_minutes
    m_every = re.match(r"^every_(\d+)_minutes$", schedule.strip())
    if m_every:
        minutes = int(m_every.group(1))
        return from_dt + timedelta(minutes=minutes)

    # 3. monthly@1st_HH:MM
    m_monthly = re.match(r"^monthly@1st_(\d{2}):(\d{2})$", schedule.strip())
    if m_monthly:
        hour, minute = int(m_monthly.group(1)), int(m_monthly.group(2))
        # Candidate is 1st of current month at HH:MM
        candidate = from_dt.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_dt:
            # Advance to 1st of next month
            year = from_dt.year + (1 if from_dt.month == 12 else 0)
            month = 1 if from_dt.month == 12 else from_dt.month + 1
            candidate = candidate.replace(year=year, month=month, day=1)
        return candidate

    # Fallback default: 24 hours later
    return from_dt + timedelta(days=1)


def init_scheduled_jobs(
    conn: sqlite3.Connection,
    user_id: str,
    config: RuntimeConfig | None = None,
    as_of: datetime | None = None,
) -> list[ScheduledJob]:
    """
    Ensure all scheduled jobs configured in config/runtime.yaml exist in the database for user_id.
    """
    if config is None:
        config_path = PROJECT_ROOT / "config" / "runtime.yaml"
        config = load_runtime_config(config_path)

    ref_dt = as_of or now_utc()
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=UTC)
    now_iso = to_utc_iso(ref_dt)

    initialized: list[ScheduledJob] = []

    for job_kind, job_cfg in config.jobs.items():
        existing = get_scheduled_job(conn, user_id=user_id, job_kind=job_kind)
        if existing is None:
            next_run_dt = compute_next_run_at(job_cfg.schedule, ref_dt)
            new_job = ScheduledJob(
                id=f"job_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                job_kind=job_kind,
                schedule=job_cfg.schedule,
                next_run_at=to_utc_iso(next_run_dt),
                lease_owner=None,
                lease_until=None,
                last_status=None,
                consecutive_failures=0,
                enabled=job_cfg.enabled,
                updated_at=now_iso,
            )
            upsert_scheduled_job(conn, new_job)
            initialized.append(new_job)
        else:
            initialized.append(existing)

    return initialized
