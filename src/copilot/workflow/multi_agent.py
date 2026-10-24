"""
Parallel specialist fan-out, fault tolerance, and deterministic merge (PLAN_PHASE3 Section 5.13).
"""

import concurrent.futures
import logging
import sqlite3
import time
import uuid
from typing import Any

from copilot.audit.events import record_event
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import insert_specialist_report
from copilot.models.phase3 import SpecialistReport, SubQuestion
from copilot.ops.tracing import span
from copilot.tools.executor import ExecutionContext
from copilot.workflow.specialists import DOMAIN_TO_ROLE, run_specialist

logger = logging.getLogger(__name__)


def _run_single_specialist(
    role: str,
    sq: SubQuestion,
    ctx: ExecutionContext,
    task_id: str,
    timeout_seconds: float,
    delay: float = 0.0,
) -> SpecialistReport:
    """Run one specialist with optional injected delay, capturing any unhandled error."""
    t0 = time.perf_counter()
    if delay > 0:
        time.sleep(delay)

    try:
        report = run_specialist(
            role=role,
            subquestion=sq,
            ctx=ctx,
            task_id=task_id,
        )
        return report
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return SpecialistReport(
            id=f"sr_{uuid.uuid4().hex[:12]}",
            user_id=ctx.user_id,
            task_id=task_id,
            agent_role=role,
            sub_question_json=sq.model_dump(),
            status="failed",
            findings_json=[],
            gaps_json=[f"Specialist '{role}' failed: {str(exc)}"],
            error_code="specialist_failed",
            duration_ms=duration_ms,
            created_at=to_utc_iso(now_utc(ctx.clock)),
        )


def run_specialists_fanout(
    subquestions: list[SubQuestion],
    ctx: ExecutionContext,
    task_id: str,
    timeout_seconds: float = 5.0,
    delays: dict[str, float] | None = None,
) -> list[SpecialistReport]:
    """
    Execute specialists concurrently in parallel threads.
    If a specialist branch times out or fails, captures a partial/failed report
    without failing the entire run.
    """
    if not subquestions:
        return []

    with span(
        kind="node",
        name="parallel_specialists_fanout",
        attrs={"subquestion_count": len(subquestions)},
        user_id=ctx.user_id,
        trace_id=task_id,
        conn=ctx.conn,
    ):
        delays = delays or {}
        reports: list[SpecialistReport] = []

        # Map each subquestion to a specialist role
        tasks_to_run = []
        for sq in subquestions:
            role = DOMAIN_TO_ROLE.get(sq.domain, "CashflowAgent")
            delay = delays.get(role, 0.0)
            tasks_to_run.append((role, sq, delay))

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks_to_run)) as executor:
            future_to_task = {
                executor.submit(
                    _run_single_specialist,
                    role,
                    sq,
                    ctx,
                    task_id,
                    timeout_seconds,
                    delay,
                ): (role, sq)
                for role, sq, delay in tasks_to_run
            }

            for future in future_to_task:
                role, sq = future_to_task[future]
                try:
                    report = future.result(timeout=timeout_seconds)
                    reports.append(report)
                except concurrent.futures.TimeoutError:
                    logger.warning(
                        "Specialist %s timed out after %s seconds", role, timeout_seconds
                    )
                    timeout_report = SpecialistReport(
                        id=f"sr_{uuid.uuid4().hex[:12]}",
                        user_id=ctx.user_id,
                        task_id=task_id,
                        agent_role=role,
                        sub_question_json=sq.model_dump(),
                        status="timeout",
                        findings_json=[],
                        gaps_json=[f"Specialist '{role}' timed out checking '{sq.question_kind}'"],
                        error_code="timeout",
                        duration_ms=int(timeout_seconds * 1000),
                        created_at=to_utc_iso(now_utc(ctx.clock)),
                    )
                    reports.append(timeout_report)
                except Exception as exc:
                    logger.exception("Specialist %s future raised: %s", role, exc)
                    failed_report = SpecialistReport(
                        id=f"sr_{uuid.uuid4().hex[:12]}",
                        user_id=ctx.user_id,
                        task_id=task_id,
                        agent_role=role,
                        sub_question_json=sq.model_dump(),
                        status="failed",
                        findings_json=[],
                        gaps_json=[f"Specialist '{role}' execution error: {str(exc)}"],
                        error_code="specialist_failed",
                        duration_ms=0,
                        created_at=to_utc_iso(now_utc(ctx.clock)),
                    )
                    reports.append(failed_report)

        # Persist reports if DB connection is active
        if ctx.conn:
            for r in reports:
                try:
                    insert_specialist_report(ctx.conn, r)
                except Exception as e:
                    logger.warning("Could not persist specialist report: %s", e)

        return reports


def merge_specialist_reports(
    reports: list[SpecialistReport],
    user_id: str,
    task_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """
    Deterministic Merge (PLAN_PHASE3 Section 5.13):
    1. Combines findings across specialist reports.
    2. Detects contradictions (different values reported for the same quantity/metric).
    3. Records audited `merge_conflict` error with both values.
    4. Excludes conflicting findings from the merged narration findings.
    5. Aggregates gaps and determines overall status ("ok", "partial", or "failed").
    """
    merged_findings: list[dict[str, Any]] = []
    merged_gaps: list[str] = []
    contradictions: list[dict[str, Any]] = []

    # Map of metric -> list of (role, value, finding_dict)
    metric_map: dict[str, list[tuple[str, Any, dict[str, Any]]]] = {}

    for report in reports:
        # Collect gaps
        merged_gaps.extend(report.gaps_json)

        # Index findings
        for f in report.findings_json:
            metric = f.get("metric")
            if metric:
                val = f.get("value")
                metric_map.setdefault(metric, []).append((report.agent_role, val, f))

    # Detect contradictions and filter
    conflicting_metrics: set[str] = set()

    for metric, occurrences in metric_map.items():
        if len(occurrences) > 1:
            first_val = occurrences[0][1]
            for _role, val, _finding in occurrences[1:]:
                if val != first_val:
                    conflicting_metrics.add(metric)
                    contradiction_data = {
                        "metric": metric,
                        "values": [{"role": r, "value": v} for r, v, _ in occurrences],
                    }
                    contradictions.append(contradiction_data)
                    logger.warning("Merge contradiction detected: %s", contradiction_data)

                    # Audited merge_conflict (PLAN_PHASE3 Section 5.13)
                    if conn:
                        record_event(
                            conn=conn,
                            user_id=user_id,
                            actor="agent",
                            event_type="merge_conflict",
                            reason=f"Contradictory findings reported for metric '{metric}'",
                            run_id=task_id,
                            metadata=contradiction_data,
                        )

                    merged_gaps.append(
                        f"Contradiction detected for metric '{metric}'; excluded from narration"
                    )
                    break

    # Add non-conflicting findings to merged_findings
    for metric, occurrences in metric_map.items():
        if metric not in conflicting_metrics:
            for _, _, f in occurrences:
                merged_findings.append(f)

    # Determine overall status
    has_failed = any(r.status in ("failed", "timeout") for r in reports)
    if not merged_findings and (has_failed or merged_gaps):
        overall_status = "failed"
    elif merged_gaps or has_failed or contradictions:
        overall_status = "partial"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "findings": merged_findings,
        "gaps": merged_gaps,
        "contradictions": contradictions,
        "reports_count": len(reports),
    }
