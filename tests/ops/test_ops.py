"""
Tests for Observability, Distributed Tracing, Safety Rule 19, and Ops Telemetry (PLAN_PHASE3 Section 5.15 & Stage 3.13).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from copilot.config.phase3 import OpsConfig
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_user
from copilot.db.repo_phase3 import (
    insert_job_run,
    insert_reflection,
    insert_span,
    list_spans,
    upsert_scheduled_job,
)
from copilot.models.domain import User
from copilot.models.phase3 import JobRun, Reflection, ScheduledJob, Span
from copilot.ops.telemetry import compute_ops_telemetry
from copilot.ops.tracing import (
    FORBIDDEN_ATTR_KEYS,
    build_span_tree,
    export_trace_spans_jsonl,
    sanitize_and_validate_attrs,
    span,
    trace_context,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = get_connection(":memory:")
    init_db(c)
    u = User(id="u1", created_at="2026-01-01T00:00:00Z")
    insert_user(c, u)
    return c


# -------------------------------------------------------------------------------------------------
# 1. Spans form a correct tree for a multi-agent task
# -------------------------------------------------------------------------------------------------
def test_spans_form_correct_tree(conn: sqlite3.Connection) -> None:
    with trace_context(user_id="u1", trace_id="tr_multi_agent", conn=conn):
        with span(kind="node", name="supervisor_root", attrs={"step": 1}):
            with span(kind="specialist", name="CashflowAgent", attrs={"role": "CashflowAgent"}):
                with span(kind="tool", name="get_calendar", attrs={"tool_name": "get_calendar"}):
                    pass
                with span(kind="llm", name="planning", attrs={"tokens_used": 150}):
                    pass

    spans = list_spans(conn, user_id="u1", trace_id="tr_multi_agent")
    assert len(spans) == 4

    tree = build_span_tree(spans)
    assert len(tree) == 1  # 1 root

    root_node = tree[0]
    assert root_node["span"].name == "supervisor_root"
    assert root_node["span"].kind == "node"
    assert len(root_node["children"]) == 1

    spec_node = root_node["children"][0]
    assert spec_node["span"].name == "CashflowAgent"
    assert spec_node["span"].kind == "specialist"
    assert len(spec_node["children"]) == 2

    child_names = {c["span"].name for c in spec_node["children"]}
    assert child_names == {"get_calendar", "planning"}


# -------------------------------------------------------------------------------------------------
# 2. No span attribute contains user text, merchant names, or statements (Safety Rule 19)
# -------------------------------------------------------------------------------------------------
def test_no_span_attribute_contains_user_text(conn: sqlite3.Connection) -> None:
    # 1. Direct validation: forbidden keys must raise ValueError
    for forbidden_key in FORBIDDEN_ATTR_KEYS:
        with pytest.raises(ValueError, match="Safety Rule 19 violation"):
            sanitize_and_validate_attrs({forbidden_key: "some_value"})

    # 2. Free-form user prose in values must raise ValueError
    with pytest.raises(ValueError, match="Safety Rule 19 violation"):
        sanitize_and_validate_attrs(
            {
                "notes": "Hello copilot please buy groceries from BigBasket for my dinner party tonight"
                * 2
            }
        )

    # 3. Allowed structural attributes must succeed
    allowed = {
        "tool_name": "get_calendar",
        "tokens_used": 420,
        "model": "gemini-2.5-flash",
        "attempt": 1,
        "count": 5,
        "is_valid": True,
    }
    cleaned = sanitize_and_validate_attrs(allowed)
    assert cleaned == allowed

    # 4. Scan database: assert no persisted span contains prohibited keys or user text
    with trace_context(user_id="u1", trace_id="tr_scan_test", conn=conn):
        with span(
            kind="tool",
            name="check_balance",
            attrs={"tool_name": "check_balance", "account_id": "acc_1"},
        ):
            pass

    rows = conn.execute("SELECT attrs_json FROM trace_spans WHERE user_id = 'u1'").fetchall()
    for (attrs_json,) in rows:
        d = json.loads(attrs_json)
        for k in d:
            assert k.lower() not in FORBIDDEN_ATTR_KEYS


# -------------------------------------------------------------------------------------------------
# 3. Export trace spans as JSON Lines
# -------------------------------------------------------------------------------------------------
def test_export_trace_spans_jsonl(conn: sqlite3.Connection, tmp_path: Path) -> None:
    with trace_context(user_id="u1", trace_id="tr_export_test", conn=conn):
        with span(kind="tool", name="list_accounts", attrs={"tool_name": "list_accounts"}):
            pass
        with span(kind="llm", name="intent", attrs={"tokens_used": 75}):
            pass

    out_file = tmp_path / "traces" / "trace_export.jsonl"
    jsonl_str = export_trace_spans_jsonl(
        conn, user_id="u1", trace_id="tr_export_test", output_path=out_file
    )

    assert out_file.is_file()
    lines = [json.loads(line) for line in jsonl_str.strip().split("\n")]
    assert len(lines) == 2
    assert lines[0]["user_id"] == "u1"
    assert lines[0]["trace_id"] == "tr_export_test"


# -------------------------------------------------------------------------------------------------
# 4. Ops telemetry numbers equal hand-counted values on fixture trace
# -------------------------------------------------------------------------------------------------
def test_ops_telemetry_hand_counted_fixture(conn: sqlite3.Connection) -> None:
    """
    Populate fixture with known values and assert that compute_ops_telemetry
    computes exact hand-counted metrics.
    """
    config = OpsConfig(
        price_per_1k_tokens=0.002,
        currency="USD",
        retention_days=30,
        latency_percentiles=[50, 95],
    )

    # 1. Insert 4 Node spans for 'supervisor_node': durations [100, 200, 300, 400]
    # p50 = 250.0, p95 = 385.0
    for i, dur in enumerate([100, 200, 300, 400]):
        insert_span(
            conn,
            Span(
                id=f"sp_node_{i}",
                user_id="u1",
                trace_id="tr_fix",
                span_id=f"s_n_{i}",
                kind="node",
                name="supervisor_node",
                started_at="2026-04-01T00:00:00Z",
                duration_ms=dur,
                status="ok",
                attrs={},
                created_at="2026-04-01T00:00:00Z",
            ),
        )

    # 2. Insert 3 Skill spans for 'monthly_close': durations [50, 150, 250]
    # p50 = 150.0, p95 = 240.0
    for i, dur in enumerate([50, 150, 250]):
        insert_span(
            conn,
            Span(
                id=f"sp_skill_{i}",
                user_id="u1",
                trace_id="tr_fix",
                span_id=f"s_s_{i}",
                kind="skill",
                name="monthly_close",
                started_at="2026-04-01T00:00:00Z",
                duration_ms=dur,
                status="ok",
                attrs={},
                created_at="2026-04-01T00:00:00Z",
            ),
        )

    # 3. Insert LLM spans across 2 tasks:
    # Task A: 2 calls, tokens: 400 + 600 = 1000
    # Task B: 1 call, tokens: 500
    # Total calls: 3, Total tokens: 1500, Tasks: 2
    # Avg calls/task = 3 / 2 = 1.5, Avg tokens/task = 1500 / 2 = 750.0
    # Cost = (1500 / 1000) * 0.002 = 0.003 USD
    insert_span(
        conn,
        Span(
            id="sp_llm_1",
            user_id="u1",
            trace_id="task_A",
            span_id="s_l_1",
            kind="llm",
            name="planning",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=100,
            status="ok",
            attrs={"tokens_used": 400},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_span(
        conn,
        Span(
            id="sp_llm_2",
            user_id="u1",
            trace_id="task_A",
            span_id="s_l_2",
            kind="llm",
            name="critique",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=120,
            status="ok",
            attrs={"tokens_used": 600},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_span(
        conn,
        Span(
            id="sp_llm_3",
            user_id="u1",
            trace_id="task_B",
            span_id="s_l_3",
            kind="llm",
            name="intent",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=80,
            status="ok",
            attrs={"tokens_used": 500},
            created_at="2026-04-01T00:00:00Z",
        ),
    )

    # 4. Error spans: 2 TIMEOUT, 1 INVALID_INPUT
    for i, err in enumerate(["TIMEOUT", "TIMEOUT", "INVALID_INPUT"]):
        insert_span(
            conn,
            Span(
                id=f"sp_err_{i}",
                user_id="u1",
                trace_id="tr_err",
                span_id=f"s_e_{i}",
                kind="tool",
                name="failed_tool",
                started_at="2026-04-01T00:00:00Z",
                duration_ms=10,
                status="error",
                error_code=err,
                attrs={},
                created_at="2026-04-01T00:00:00Z",
            ),
        )

    # 5. Audit events: 1 budget_stop, 1 validator_fallback out of 4 total plan evaluations
    conn.execute(
        "INSERT INTO audit_events (id, user_id, actor, event_type, reason, occurred_at) VALUES ('ae_bs', 'u1', 'agent', 'budget_stop', 'budget exceeded', '2026-04-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO audit_events (id, user_id, actor, event_type, reason, occurred_at) VALUES ('ae_vf', 'u1', 'agent', 'validator_fallback', 'fallback used', '2026-04-01T00:00:00Z')"
    )
    for i in range(3):
        conn.execute(
            f"INSERT INTO audit_events (id, user_id, actor, event_type, reason, occurred_at) VALUES ('ae_pv_{i}', 'u1', 'agent', 'plan_validated', 'plan valid', '2026-04-01T00:00:00Z')"
        )

    # 6. Reflections: 2 reflections (1 fixed, 1 gave_up). Both had critic findings (round >= 1)
    # critic_catch_rate = 2/2 = 1.0, revision_success_rate = 1/2 = 0.5
    insert_reflection(
        conn,
        Reflection(
            id="ref_1",
            user_id="u1",
            task_id="task_1",
            round=1,
            critique_codes=["missing_coverage"],
            source="llm_critic",
            revised=True,
            outcome="fixed",
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_reflection(
        conn,
        Reflection(
            id="ref_2",
            user_id="u1",
            task_id="task_2",
            round=1,
            critique_codes=["unsupported_claim"],
            source="llm_critic",
            revised=False,
            outcome="gave_up",
            created_at="2026-04-01T00:00:00Z",
        ),
    )

    # 7. Scheduled job & runs: 3 ok, 1 dead_letter, 1 failed, 1 skipped
    upsert_scheduled_job(
        conn,
        ScheduledJob(
            id="job_rollover",
            user_id="u1",
            job_kind="rollover_buckets",
            schedule="daily@00:05",
            next_run_at="2026-04-02T00:05:00Z",
            consecutive_failures=0,
            enabled=True,
            updated_at="2026-04-01T00:00:00Z",
        ),
    )

    for i in range(3):
        insert_job_run(
            conn,
            JobRun(
                id=f"jr_ok_{i}",
                user_id="u1",
                job_id="job_rollover",
                started_at="2026-04-01T00:00:00Z",
                status="ok",
                attempt=1,
                summary_json={},
                created_at="2026-04-01T00:00:00Z",
            ),
        )
    insert_job_run(
        conn,
        JobRun(
            id="jr_dl",
            user_id="u1",
            job_id="job_rollover",
            started_at="2026-04-01T00:00:00Z",
            status="dead_letter",
            attempt=3,
            summary_json={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_job_run(
        conn,
        JobRun(
            id="jr_fail",
            user_id="u1",
            job_id="job_rollover",
            started_at="2026-04-01T00:00:00Z",
            status="failed",
            attempt=1,
            summary_json={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_job_run(
        conn,
        JobRun(
            id="jr_skip",
            user_id="u1",
            job_id="job_rollover",
            started_at="2026-04-01T00:00:00Z",
            status="skipped",
            attempt=1,
            summary_json={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )

    # 8. Multi-agent fan-out parallel speed-up:
    # Wall time = 200 ms, Specialists = 150 ms + 250 ms = 400 ms -> Speedup = 400 / 200 = 2.0x
    insert_span(
        conn,
        Span(
            id="sp_fanout",
            user_id="u1",
            trace_id="tr_speedup",
            span_id="s_fan",
            kind="node",
            name="parallel_specialists_fanout",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=200,
            status="ok",
            attrs={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_span(
        conn,
        Span(
            id="sp_spec_1",
            user_id="u1",
            trace_id="tr_speedup",
            span_id="s_sp_1",
            kind="specialist",
            name="CashflowAgent",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=150,
            status="ok",
            attrs={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )
    insert_span(
        conn,
        Span(
            id="sp_spec_2",
            user_id="u1",
            trace_id="tr_speedup",
            span_id="s_sp_2",
            kind="specialist",
            name="GoalsAgent",
            started_at="2026-04-01T00:00:00Z",
            duration_ms=250,
            status="ok",
            attrs={},
            created_at="2026-04-01T00:00:00Z",
        ),
    )

    # Compute telemetry
    report = compute_ops_telemetry(conn, user_id="u1", config=config)

    # Verify exact hand-counted equality:
    # Node percentiles
    assert report.p50_p95_nodes["supervisor_node"]["p50_ms"] == 250.0
    assert report.p50_p95_nodes["supervisor_node"]["p95_ms"] == 385.0

    # Skill percentiles
    assert report.p50_p95_skills["monthly_close"]["p50_ms"] == 150.0
    assert report.p50_p95_skills["monthly_close"]["p95_ms"] == 240.0

    # LLM metrics
    assert report.llm_calls_per_task == 1.5
    assert report.tokens_per_task == 750.0
    assert report.total_tokens == 1500
    assert report.estimated_cost_str == "0.0030 USD"

    # Failure counts by code
    assert report.failure_counts_by_code == {"TIMEOUT": 2, "INVALID_INPUT": 1}

    # Budget stops
    assert report.budget_stops_count == 1

    # Validator fallback rate: 1 fallback out of 4 total plans = 0.25
    assert report.validator_fallback_rate == 0.25

    # Critic catch rate: 2/2 = 1.0, Revision success rate: 1/2 = 0.5
    assert report.critic_catch_rate == 1.0
    assert report.revision_success_rate == 0.5

    # Job counts
    assert report.job_counts == {"ok": 3, "dead_letter": 1, "failed": 1, "skipped": 1}

    # Parallel speed-up: 400 / 200 = 2.0
    assert report.parallel_speed_up == 2.0
