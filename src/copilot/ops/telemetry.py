"""
Ops Telemetry and Observability Aggregator (PLAN_PHASE3 Section 5.15).

Aggregates:
- p50/p95 latency per node and per skill
- LLM calls and estimated tokens per task (with cost calculation)
- Failure counts by error code
- Budget stops
- Validator fallback rate
- Critic catch rate and revision success rate
- Job success and dead-letter counts
- Parallel speed-up (sum of specialist durations ÷ wall time)
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from copilot.config.phase3 import OpsConfig, load_ops_config
from copilot.core.config import PROJECT_ROOT


def _percentile(values: list[float | int], p: int) -> float:
    """Calculate the p-th percentile from an unsorted list of numeric values."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_v[int(k)])
    d0 = sorted_v[f] * (c - k)
    d1 = sorted_v[c] * (k - f)
    return float(round(d0 + d1, 2))


@dataclass
class OpsReport:
    """Consolidated telemetry and ops report."""

    p50_p95_nodes: dict[str, dict[str, float]] = field(default_factory=dict)
    p50_p95_skills: dict[str, dict[str, float]] = field(default_factory=dict)
    llm_calls_per_task: float = 0.0
    tokens_per_task: float = 0.0
    total_tokens: int = 0
    estimated_cost_str: str = "not configured"
    failure_counts_by_code: dict[str, int] = field(default_factory=dict)
    budget_stops_count: int = 0
    validator_fallback_rate: float = 0.0
    critic_catch_rate: float = 0.0
    revision_success_rate: float = 0.0
    job_counts: dict[str, int] = field(default_factory=dict)
    parallel_speed_up: float = 1.0


def compute_ops_telemetry(
    conn: sqlite3.Connection,
    user_id: str | None = None,
    config: OpsConfig | None = None,
) -> OpsReport:
    """
    Compute comprehensive system telemetry from trace_spans, job_runs,
    audit_events, context_manifests, and reflections.
    """
    if config is None:
        config_path = PROJECT_ROOT / "config" / "ops.yaml"
        config = load_ops_config(config_path)

    report = OpsReport()

    # 1. Latency Percentiles (Nodes & Skills)
    query_spans = "SELECT kind, name, duration_ms FROM trace_spans"
    params_spans: list[Any] = []
    if user_id is not None:
        query_spans += " WHERE user_id = ?"
        params_spans.append(user_id)

    span_rows = conn.execute(query_spans, params_spans).fetchall()
    node_durations: dict[str, list[int]] = {}
    skill_durations: dict[str, list[int]] = {}

    for r in span_rows:
        kind, name, dur = r[0], r[1], r[2]
        if kind == "node":
            node_durations.setdefault(name, []).append(dur)
        elif kind == "skill":
            skill_durations.setdefault(name, []).append(dur)

    for name, durs in node_durations.items():
        report.p50_p95_nodes[name] = {
            "p50_ms": _percentile(durs, 50),
            "p95_ms": _percentile(durs, 95),
            "count": len(durs),
        }

    for name, durs in skill_durations.items():
        report.p50_p95_skills[name] = {
            "p50_ms": _percentile(durs, 50),
            "p95_ms": _percentile(durs, 95),
            "count": len(durs),
        }

    # 2. LLM calls and tokens per task
    query_llm = "SELECT trace_id, attrs_json FROM trace_spans WHERE kind = 'llm'"
    params_llm: list[Any] = []
    if user_id is not None:
        query_llm += " AND user_id = ?"
        params_llm.append(user_id)

    llm_rows = conn.execute(query_llm, params_llm).fetchall()
    task_llm_counts: dict[str, int] = {}
    task_token_counts: dict[str, int] = {}
    total_tokens = 0

    for r in llm_rows:
        tid, attrs_str = r[0], r[1]
        task_llm_counts[tid] = task_llm_counts.get(tid, 0) + 1
        attrs = json.loads(attrs_str) if isinstance(attrs_str, str) else {}
        tokens = int(attrs.get("tokens_used", 0))
        task_token_counts[tid] = task_token_counts.get(tid, 0) + tokens
        total_tokens += tokens

    num_tasks = len(task_llm_counts)
    if num_tasks > 0:
        report.llm_calls_per_task = round(len(llm_rows) / num_tasks, 2)
        report.tokens_per_task = round(total_tokens / num_tasks, 2)
    else:
        report.llm_calls_per_task = 0.0
        report.tokens_per_task = 0.0
    report.total_tokens = total_tokens

    if config.price_per_1k_tokens > 0.0:
        cost = (total_tokens / 1000.0) * config.price_per_1k_tokens
        report.estimated_cost_str = f"{cost:.4f} {config.currency}"
    else:
        report.estimated_cost_str = "not configured"

    # 3. Failures by error code
    query_errors = (
        "SELECT error_code FROM trace_spans WHERE status = 'error' AND error_code IS NOT NULL"
    )
    params_errors: list[Any] = []
    if user_id is not None:
        query_errors += " AND user_id = ?"
        params_errors.append(user_id)

    err_rows = conn.execute(query_errors, params_errors).fetchall()
    error_counts: dict[str, int] = {}
    for r in err_rows:
        code = str(r[0])
        error_counts[code] = error_counts.get(code, 0) + 1

    report.failure_counts_by_code = error_counts

    # 4. Budget Stops
    query_budget = "SELECT COUNT(*) FROM audit_events WHERE event_type = 'budget_stop'"
    params_b: list[Any] = []
    if user_id is not None:
        query_budget += " AND user_id = ?"
        params_b.append(user_id)
    report.budget_stops_count = int(conn.execute(query_budget, params_b).fetchone()[0])

    # 5. Validator Fallback Rate
    query_fb = "SELECT COUNT(*) FROM audit_events WHERE event_type = 'validator_fallback'"
    query_plans = (
        "SELECT COUNT(*) FROM audit_events "
        "WHERE event_type IN ('plan_validated', 'plan_rejected', 'validator_fallback')"
    )
    params_p: list[Any] = []
    if user_id is not None:
        query_fb += " AND user_id = ?"
        query_plans += " AND user_id = ?"
        params_p.append(user_id)
    fb_count = int(conn.execute(query_fb, params_p).fetchone()[0])
    total_plans = int(conn.execute(query_plans, params_p).fetchone()[0])
    report.validator_fallback_rate = (
        round(fb_count / total_plans, 4) if total_plans > 0 else 0.0
    )

    # 6. Critic catch rate & Revision success rate
    query_ref = "SELECT round, outcome, critique_codes_json FROM reflections"
    params_ref: list[Any] = []
    if user_id is not None:
        query_ref += " WHERE user_id = ?"
        params_ref.append(user_id)

    ref_rows = conn.execute(query_ref, params_ref).fetchall()
    total_reviews = len(ref_rows)
    critic_catches = 0
    revisions = 0
    improved = 0

    for r in ref_rows:
        rnd, outc, cc_str = r[0], r[1], r[2]
        cc = json.loads(cc_str) if isinstance(cc_str, str) else []
        if rnd >= 1 or len(cc) > 0:
            critic_catches += 1
        if outc in ("fixed", "improved", "gave_up"):
            revisions += 1
            if outc in ("fixed", "improved"):
                improved += 1

    report.critic_catch_rate = (
        round(critic_catches / total_reviews, 4) if total_reviews > 0 else 0.0
    )
    report.revision_success_rate = (
        round(improved / revisions, 4) if revisions > 0 else 0.0
    )

    # 7. Job Success & Dead Letter Counts
    query_jobs = "SELECT status, COUNT(*) FROM job_runs"
    params_j: list[Any] = []
    if user_id is not None:
        query_jobs += " WHERE user_id = ?"
        params_j.append(user_id)
    query_jobs += " GROUP BY status"

    j_rows = conn.execute(query_jobs, params_j).fetchall()
    j_counts = {"ok": 0, "failed": 0, "skipped": 0, "dead_letter": 0}
    for r in j_rows:
        j_counts[str(r[0])] = int(r[1])
    report.job_counts = j_counts

    # 8. Parallel Speed-up: sum of specialist durations / wall time
    query_fanout = (
        "SELECT trace_id, duration_ms FROM trace_spans "
        "WHERE kind = 'node' AND name = 'parallel_specialists_fanout'"
    )
    fanout_rows = conn.execute(query_fanout).fetchall()
    speedups: list[float] = []

    for f_row in fanout_rows:
        tid, wall_ms = f_row[0], f_row[1]
        if wall_ms > 0:
            spec_rows = conn.execute(
                "SELECT duration_ms FROM trace_spans WHERE trace_id = ? AND kind = 'specialist'",
                (tid,),
            ).fetchall()
            spec_sum = sum(s[0] for s in spec_rows)
            if spec_sum > 0:
                speedups.append(round(spec_sum / wall_ms, 2))

    if speedups:
        report.parallel_speed_up = round(sum(speedups) / len(speedups), 2)
    else:
        report.parallel_speed_up = 1.0

    return report
