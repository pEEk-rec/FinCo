"""Reads and writes for the agent's machinery: skill runs, specialist reports, reflections, context
manifests, spans, scheduled jobs and feedback stats.
"""

import json
import sqlite3
import uuid
from typing import Any, Literal

from copilot.models.agent_runtime import (
    ContextManifest,
    FeedbackStat,
    JobRun,
    Reflection,
    ScheduledJob,
    SkillRun,
    Span,
    SpecialistReport,
)


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


def list_reflections(conn: sqlite3.Connection, user_id: str, task_id: str) -> list[Reflection]:
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


def get_scheduled_job(conn: sqlite3.Connection, user_id: str, job_kind: str) -> ScheduledJob | None:
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


def list_due_jobs(conn: sqlite3.Connection, user_id: str, as_of: str) -> list[ScheduledJob]:
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


def get_latest_job_run(conn: sqlite3.Connection, user_id: str, job_id: str) -> JobRun | None:
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
            "SELECT * FROM feedback_stats WHERE user_id = ? AND subject_kind = ? ORDER BY subject_key ASC",  # noqa: E501
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
