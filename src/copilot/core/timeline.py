"""
Activity Timeline read model (PLAN_PHASE2 Section 5.9 & Stage 2.9).

Derives an immutable, chronologically ordered activity timeline across:
- agent_tasks
- plan_steps
- investigations
- simulations
- alerts
- advice_items (pending recommendations and decisions)
- audit_events

Guarantees:
- Stable ordering (timestamp ASC, then deterministic secondary keys).
- Pinned "needs your decision" section for pending approvals.
- Privacy: No raw user query text in entries (intent type and entities only).
- Redaction rules applied.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any

from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.agentic import Timeline, TimelineEntry


def build_timeline(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    since: str | datetime | None = None,
) -> Timeline:
    """
    Build a unified chronological timeline for a user.
    Pure read model without creating new database records.
    """
    since_iso: str | None = None
    if since is not None:
        since_iso = to_utc_iso(now_utc(since))

    raw_entries: list[TimelineEntry] = []
    pending_approvals: list[TimelineEntry] = []

    # 1. Agent Tasks
    task_query = (
        "SELECT id, run_id, intent_json, status, stop_reason, created_at, finished_at "
        "FROM agent_tasks WHERE user_id = ?"
    )
    task_params: list[Any] = [user_id]
    if task_id:
        task_query += " AND id = ?"
        task_params.append(task_id)
    if run_id:
        task_query += " AND run_id = ?"
        task_params.append(run_id)
    task_query += " ORDER BY created_at ASC"

    for r in conn.execute(task_query, tuple(task_params)).fetchall():
        row = dict(r)
        intent_info = json.loads(row["intent_json"]) if row.get("intent_json") else {}
        intent_type = intent_info.get("type", "unknown")
        period = intent_info.get("period")
        amount_paise = intent_info.get("amount_paise")

        detail_parts = [f"Intent: {intent_type}"]
        if period:
            detail_parts.append(f"period: {period}")
        if amount_paise:
            detail_parts.append(f"amount: ₹{amount_paise / 100:.2f}")
        detail = ", ".join(detail_parts)

        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="observation",
                title=f"User Request ({intent_type})",
                detail=detail,
                status=row["status"],
                ref={"task_id": row["id"]},
            )
        )

    # 2. Plan Steps
    step_query = (
        "SELECT id, task_id, seq, tool_name, args_json, rationale, status, "
        "started_at, finished_at FROM plan_steps WHERE user_id = ?"
    )
    step_params: list[Any] = [user_id]
    if task_id:
        step_query += " AND task_id = ?"
        step_params.append(task_id)
    step_query += " ORDER BY started_at ASC, seq ASC"

    for r in conn.execute(step_query, tuple(step_params)).fetchall():
        row = dict(r)
        ts = row.get("started_at") or row.get("finished_at") or to_utc_iso(now_utc())
        raw_entries.append(
            TimelineEntry(
                ts=ts,
                kind="plan",
                title=f"Plan Step {row['seq'] + 1}: {row['tool_name']}",
                detail=row["rationale"] or f"Execute {row['tool_name']}",
                status=row["status"],
                ref={"step_id": row["id"], "tool_name": row["tool_name"]},
            )
        )

    # 3. Investigations
    inv_query = (
        "SELECT id, task_id, run_id, subject_kind, outcome, confidence_label, "
        "explained_share_bp, unexplained_paise, created_at "
        "FROM investigations WHERE user_id = ?"
    )
    inv_params: list[Any] = [user_id]
    if task_id:
        inv_query += " AND task_id = ?"
        inv_params.append(task_id)
    if run_id:
        inv_query += " AND run_id = ?"
        inv_params.append(run_id)
    inv_query += " ORDER BY created_at ASC"

    for r in conn.execute(inv_query, tuple(inv_params)).fetchall():
        row = dict(r)
        share_pct = (row.get("explained_share_bp") or 0) / 100.0
        unexp_paise = row.get("unexplained_paise") or 0
        detail = (
            f"Outcome: {row['outcome']} ({share_pct:.1f}% explained), "
            f"confidence: {row['confidence_label']}, "
            f"unexplained: ₹{unexp_paise / 100:.2f}"
        )
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="investigation",
                title=f"Investigation: {row['subject_kind']}",
                detail=detail,
                status=row["outcome"],
                ref={"investigation_id": row["id"]},
            )
        )

    # 4. Simulations
    sim_query = (
        "SELECT id, task_id, scenario_json, baseline_json, result_json, "
        "assumptions_json, created_at FROM simulations WHERE user_id = ?"
    )
    sim_params: list[Any] = [user_id]
    if task_id:
        sim_query += " AND task_id = ?"
        sim_params.append(task_id)
    sim_query += " ORDER BY created_at ASC"

    for r in conn.execute(sim_query, tuple(sim_params)).fetchall():
        row = dict(r)
        scenario = json.loads(row["scenario_json"]) if row.get("scenario_json") else {}
        kind = scenario.get("kind", "whatif")
        amt_paise = scenario.get("amount_paise", 0)
        detail = f"Scenario: {kind}, amount: ₹{amt_paise / 100:.2f}"
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="simulation",
                title=f"Simulation ({kind})",
                detail=detail,
                status="completed",
                ref={"simulation_id": row["id"]},
            )
        )

    # 5. Alerts
    alert_query = (
        "SELECT id, kind, subject_key, period, score_bp, severity, "
        "why_text, status, created_at, decided_at, dismiss_reason "
        "FROM alerts WHERE user_id = ?"
    )
    alert_params: list[Any] = [user_id]
    if run_id:
        alert_query += " AND run_id = ?"
        alert_params.append(run_id)
    alert_query += " ORDER BY created_at ASC"

    for r in conn.execute(alert_query, tuple(alert_params)).fetchall():
        row = dict(r)
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="alert",
                title=f"Alert: {row['kind']} [{row['severity'].upper()}]",
                detail=row["why_text"],
                status=row["status"],
                ref={"alert_id": row["id"]},
            )
        )

    # 6. Recommendations & Approvals
    rec_query = (
        "SELECT id, task_id, run_id, text, status, origin, created_at, decided_at "
        "FROM advice_items WHERE user_id = ?"
    )
    rec_params: list[Any] = [user_id]
    if task_id:
        rec_query += " AND task_id = ?"
        rec_params.append(task_id)
    if run_id:
        rec_query += " AND run_id = ?"
        rec_params.append(run_id)
    rec_query += " ORDER BY created_at ASC"

    for r in conn.execute(rec_query, tuple(rec_params)).fetchall():
        row = dict(r)
        origin = row.get("origin") or "monthly_review"
        rec_status = row.get("status") or "draft"

        if rec_status == "draft":
            entry = TimelineEntry(
                ts=row["created_at"],
                kind="approval_pending",
                title=f"Pending Recommendation ({origin})",
                detail=row["text"],
                status="awaiting_approval",
                ref={"recommendation_id": row["id"]},
            )
            raw_entries.append(entry)
            pending_approvals.append(entry)
        else:
            ts = row.get("decided_at") or row["created_at"]
            raw_entries.append(
                TimelineEntry(
                    ts=ts,
                    kind="decision",
                    title=f"Recommendation {rec_status.capitalize()} ({origin})",
                    detail=row["text"],
                    status=rec_status,
                    ref={"recommendation_id": row["id"]},
                )
            )

    # 7. Audit Events
    audit_query = (
        "SELECT id, run_id, occurred_at, actor, event_type, entity_type, "
        "entity_id, reason, after_json FROM audit_events WHERE user_id = ?"
    )
    audit_params: list[Any] = [user_id]
    if run_id:
        audit_query += " AND run_id = ?"
        audit_params.append(run_id)
    audit_query += " ORDER BY occurred_at ASC, rowid ASC"

    for r in conn.execute(audit_query, tuple(audit_params)).fetchall():
        row = dict(r)
        ev_type = row["event_type"]

        if ev_type == "input_refused":
            raw_entries.append(
                TimelineEntry(
                    ts=row["occurred_at"],
                    kind="refusal",
                    title="Input Refused",
                    detail=row["reason"],
                    status="refused",
                    ref={"event_id": row["id"]},
                )
            )
        elif ev_type == "plan_rejected":
            raw_entries.append(
                TimelineEntry(
                    ts=row["occurred_at"],
                    kind="plan",
                    title="Proposed Plan Rejected",
                    detail=row["reason"],
                    status="rejected",
                    ref={"event_id": row["id"]},
                )
            )
        elif ev_type == "tool_failure":
            raw_entries.append(
                TimelineEntry(
                    ts=row["occurred_at"],
                    kind="error",
                    title="Tool Failure",
                    detail=row["reason"],
                    status="error",
                    ref={"event_id": row["id"]},
                )
            )
        elif ev_type == "alert_suppressed":
            raw_entries.append(
                TimelineEntry(
                    ts=row["occurred_at"],
                    kind="alert",
                    title="Alert Suppressed (Muted)",
                    detail=row["reason"],
                    status="suppressed",
                    ref={"event_id": row["id"]},
                )
            )
        elif ev_type == "tool_executed":
            tool_name = row["entity_id"] or "tool"
            raw_entries.append(
                TimelineEntry(
                    ts=row["occurred_at"],
                    kind="tool_call",
                    title=f"Tool Executed: {tool_name}",
                    detail=row["reason"],
                    status="done",
                    ref={"tool_name": tool_name, "event_id": row["id"]},
                )
            )

    # 8. Commitments
    commitments_query = (
        "SELECT id, name, direction, kind, amount_paise, certainty, schedule_kind, "
        "status, created_at FROM commitments WHERE user_id = ? ORDER BY created_at ASC"
    )
    for r in conn.execute(commitments_query, (user_id,)).fetchall():
        row = dict(r)
        amt_str = f"₹{(row.get('amount_paise') or 0) / 100:.2f}"
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="commitment",
                title=f"Commitment: {row['name']} ({row['kind']})",
                detail=f"Amount: {amt_str}, schedule: {row['schedule_kind']}, certainty: {row['certainty']}",
                status=row["status"],
                ref={"commitment_id": row["id"]},
            )
        )

    # 9. Reallocation Drafts & Buckets
    drafts_query = (
        "SELECT id, from_bucket_id, to_bucket_id, amount_paise, status, created_at, decided_at "
        "FROM reallocation_drafts WHERE user_id = ? ORDER BY created_at ASC"
    )
    for r in conn.execute(drafts_query, (user_id,)).fetchall():
        row = dict(r)
        amt_str = f"₹{(row.get('amount_paise') or 0) / 100:.2f}"
        if row["status"] == "draft":
            entry = TimelineEntry(
                ts=row["created_at"],
                kind="approval_pending",
                title="Pending Reallocation Draft",
                detail=f"Reallocate {amt_str} between buckets",
                status="awaiting_approval",
                ref={"draft_id": row["id"]},
            )
            raw_entries.append(entry)
            pending_approvals.append(entry)
        else:
            ts = row.get("decided_at") or row["created_at"]
            raw_entries.append(
                TimelineEntry(
                    ts=ts,
                    kind="allocation",
                    title=f"Reallocation Draft {row['status'].capitalize()}",
                    detail=f"Reallocated {amt_str} between buckets",
                    status=row["status"],
                    ref={"draft_id": row["id"]},
                )
            )

    # 10. Readiness Assessments
    readiness_query = (
        "SELECT id, run_id, assessed_on, level, criteria_json, numbers_json "
        "FROM readiness_assessments WHERE user_id = ? ORDER BY assessed_on ASC"
    )
    for r in conn.execute(readiness_query, (user_id,)).fetchall():
        row = dict(r)
        raw_entries.append(
            TimelineEntry(
                ts=f"{row['assessed_on']}T00:00:00Z",
                kind="readiness",
                title=f"Investment Readiness: {row['level'].upper()}",
                detail=f"Assessed readiness on {row['assessed_on']}, level: {row['level']}",
                status=row["level"],
                ref={"readiness_id": row["id"]},
            )
        )

    # 11. Contribution Plans
    cont_plans_query = (
        "SELECT id, run_id, period_from, horizon_months, created_at "
        "FROM contribution_plans WHERE user_id = ? ORDER BY created_at ASC"
    )
    for r in conn.execute(cont_plans_query, (user_id,)).fetchall():
        row = dict(r)
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="contribution_plan",
                title=f"Contribution Plan ({row['horizon_months']}M)",
                detail=f"Waterfall plan from {row['period_from']}, horizon {row['horizon_months']} months",
                status="completed",
                ref={"contribution_plan_id": row["id"]},
            )
        )

    # 12. Tradeoff Analyses
    tradeoff_query = (
        "SELECT id, run_id, created_at FROM tradeoff_analyses WHERE user_id = ? ORDER BY created_at ASC"
    )
    for r in conn.execute(tradeoff_query, (user_id,)).fetchall():
        row = dict(r)
        raw_entries.append(
            TimelineEntry(
                ts=row["created_at"],
                kind="tradeoff",
                title="Trade-off Analysis",
                detail="Comparative analysis of scenario alternatives against hard constraints",
                status="completed",
                ref={"tradeoff_id": row["id"]},
            )
        )

    # 13. Behavioral Memory Items (forgotten memories appear without content)
    memory_query = (
        "SELECT id, kind, subject_key, statement_json, status, created_at "
        "FROM memory_items WHERE user_id = ? ORDER BY created_at ASC"
    )
    for r in conn.execute(memory_query, (user_id,)).fetchall():
        row = dict(r)
        if row["status"] == "forgotten":
            raw_entries.append(
                TimelineEntry(
                    ts=row["created_at"],
                    kind="memory",
                    title="Memory Item Forgotten",
                    detail="Memory item was forgotten at user request.",
                    status="forgotten",
                    ref={"memory_id": row["id"]},
                )
            )
        else:
            raw_entries.append(
                TimelineEntry(
                    ts=row["created_at"],
                    kind="memory",
                    title=f"Memory: {row['kind']} ({row['status']})",
                    detail=f"Subject: {row['subject_key']}, status: {row['status']}",
                    status=row["status"],
                    ref={"memory_id": row["id"]},
                )
            )

    # 8. Filter by since if specified
    if since_iso:
        raw_entries = [e for e in raw_entries if e.ts >= since_iso]
        pending_approvals = [e for e in pending_approvals if e.ts >= since_iso]

    # 9. Stable chronological sort: primary key ts, tie-breakers kind and title
    sorted_entries = sorted(
        raw_entries,
        key=lambda e: (e.ts, e.kind, e.title, e.status),
    )

    return Timeline(
        user_id=user_id,
        entries=sorted_entries,
        pending_approvals=pending_approvals,
    )
