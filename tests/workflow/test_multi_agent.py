"""
Tests for Stage 3.11 Multi-Agent Planning (PLAN_PHASE3 Section 5.13).

Test Coverage:
1. LLM decomposition (scripted fake) accepted when valid
2. LLM decomposition rejected and replaced by template fallback when it uses an unknown question kind
3. LLM decomposition rejected and replaced by template fallback when it misses required coverage
4. LLM decomposition rejected and replaced by template fallback when it references another user's IDs
5. Routing rule (single-domain -> single loop; multi-domain -> multi-agent)
6. Each specialist can call only its tool subset (attempt outside is rejected and audited as specialist_tool_rejected)
7. Parallel branches run concurrently (wall time below sum of injected delays)
8. Specialist failure/timeout yields partial answer that names missing part
9. Injected contradiction is detected, audited (merge_conflict), and excluded from narration
10. Reviewer catches missed subquestion and revision fixes it
11. Revision bound respected (<= max_revision_rounds)
12. LLM critic cannot change numbers (scripted critic output containing numbers is rejected)
13. Failure export writes candidate files
14. Same facts with critic on and off
15. End-to-end planner agent graph routes multi-domain intent to multi_agent node
"""

import json
import time

import pytest
import yaml

from copilot.audit.events import record_event
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_goal, insert_user
from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import Goal
from copilot.models.domain import Account, User
from copilot.models.phase3 import Reflection, SpecialistReport, SubQuestion
from copilot.ops.failures import export_failures
from copilot.tools.executor import ExecutionContext
from copilot.workflow.agent_graph import build_planner_agent_graph
from copilot.workflow.agentic_state import AgenticState
from copilot.workflow.decomposition import (
    decompose_intent,
    should_route_to_multi_agent,
)
from copilot.workflow.multi_agent import merge_specialist_reports, run_specialists_fanout
from copilot.workflow.multi_agent_graph import run_multi_agent_workflow
from copilot.workflow.reviewer import (
    deterministic_review,
    llm_critic_review,
    run_review_and_revision,
)
from copilot.workflow.specialists import execute_specialist_tool


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)

    u = User(id="user_alice", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u)
    u_bob = User(id="user_bob", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u_bob)

    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=5000000,
        created_at="2026-09-01T00:00:00Z",
    )
    insert_account(c, acc)

    goal = Goal(
        id="goal_vacation",
        user_id="user_alice",
        name="Vacation Fund",
        kind="savings",
        target_paise=10000000,
        current_paise=4000000,
        priority=1,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    insert_goal(c, goal)
    return c


from copilot.core.config import PROJECT_ROOT
from copilot.governance.policy import load_policy

POLICY = load_policy(PROJECT_ROOT / "config" / "policy.yaml")


@pytest.fixture
def ctx(conn):
    return ExecutionContext(
        conn=conn,
        user_id="user_alice",
        run_id="run_test_001",
        policy=POLICY,
        actor="agent",
    )



# -------------------------------------------------------------------------------------------------
# 1-4: Decomposition & Validation Tests
# -------------------------------------------------------------------------------------------------
def test_llm_decomposition_accepted_when_valid(conn):
    """LLM decomposition proposal is accepted when it complies with registered kinds and coverage."""
    valid_reply = json.dumps({
        "subquestions": [
            {"domain": "cashflow", "question_kind": "calendar_coverage", "parameters": {"horizon_days": 60}},
            {"domain": "goals", "question_kind": "goal_impact", "parameters": {"amount_paise": 50000}},
        ]
    })
    client = FakeLLMClient([valid_reply])
    subqs = decompose_intent(
        intent="affordability",
        llm_client=client,
        conn=conn,
        user_id="user_alice",
    )
    assert len(subqs) == 2
    assert subqs[0].domain == "cashflow"
    assert subqs[0].question_kind == "calendar_coverage"
    assert subqs[1].domain == "goals"
    assert subqs[1].question_kind == "goal_impact"


def test_llm_decomposition_rejected_unknown_question_kind(conn):
    """Proposal with an unknown question kind is rejected and replaced by template fallback."""
    invalid_reply = json.dumps({
        "subquestions": [
            {"domain": "cashflow", "question_kind": "invented_unknown_tool", "parameters": {}},
            {"domain": "goals", "question_kind": "goal_impact", "parameters": {}},
        ]
    })
    client = FakeLLMClient([invalid_reply])
    subqs = decompose_intent(
        intent="affordability",
        llm_client=client,
        conn=conn,
        user_id="user_alice",
        task_id="task_decomp_fail_01",
    )
    # Replaced by fallback template for affordability
    assert len(subqs) == 2
    assert subqs[0].question_kind == "calendar_coverage"
    assert subqs[1].question_kind == "goal_impact"

    # Fallback audit event recorded
    rows = conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE run_id = 'task_decomp_fail_01'"
    ).fetchall()
    assert any(r[0] == "validator_fallback" for r in rows)


def test_llm_decomposition_rejected_missing_required_coverage(conn):
    """Proposal that misses required coverage for the intent is rejected and replaced by template fallback."""
    # Affordability requires cashflow and goals; propose only cashflow
    missing_coverage_reply = json.dumps({
        "subquestions": [
            {"domain": "cashflow", "question_kind": "calendar_coverage", "parameters": {}},
        ]
    })
    client = FakeLLMClient([missing_coverage_reply])
    subqs = decompose_intent(
        intent="affordability",
        llm_client=client,
        conn=conn,
        user_id="user_alice",
        task_id="task_decomp_fail_02",
    )
    # Fallback template restores full coverage (cashflow + goals)
    assert len(subqs) == 2
    domains = {sq.domain for sq in subqs}
    assert domains == {"cashflow", "goals"}

    rows = conn.execute(
        "SELECT event_type FROM audit_events WHERE run_id = 'task_decomp_fail_02'"
    ).fetchall()
    assert any(r[0] == "validator_fallback" for r in rows)


def test_llm_decomposition_rejected_other_user_ids(conn):
    """Proposal referencing another user's entity IDs is rejected and audited."""
    cross_user_reply = json.dumps({
        "subquestions": [
            {"domain": "cashflow", "question_kind": "calendar_coverage", "parameters": {}},
            {"domain": "goals", "question_kind": "goal_impact", "parameters": {"goal_id": "goal_bob_secret"}},
        ]
    })
    client = FakeLLMClient([cross_user_reply])
    subqs = decompose_intent(
        intent="affordability",
        llm_client=client,
        conn=conn,
        user_id="user_alice",
        task_id="task_decomp_fail_03",
        other_user_ids={"goal_bob_secret"},
    )
    # Replaced by fallback
    assert len(subqs) == 2
    assert subqs[1].parameters.get("goal_id") != "goal_bob_secret"

    rows = conn.execute(
        "SELECT event_type FROM audit_events WHERE run_id = 'task_decomp_fail_03'"
    ).fetchall()
    assert any(r[0] == "validator_fallback" for r in rows)


# -------------------------------------------------------------------------------------------------
# 5: Routing Rule Test
# -------------------------------------------------------------------------------------------------
def test_routing_rule():
    """Assert routing rule: single-domain -> single loop; multi-domain -> multi-agent."""
    # Single-domain intents
    assert not should_route_to_multi_agent("summarize_period")
    assert not should_route_to_multi_agent("categorize_spend")
    assert not should_route_to_multi_agent("goal_check")
    assert not should_route_to_multi_agent("whatif_add_spend")
    assert not should_route_to_multi_agent("budget_status")

    # Multi-domain intents
    assert should_route_to_multi_agent("affordability")
    assert should_route_to_multi_agent("tradeoff_compare")
    assert should_route_to_multi_agent("contribution_check")
    assert should_route_to_multi_agent("trip_planning")

    # Multi-domain by subquestions
    multi_sqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage"),
        SubQuestion(domain="goals", question_kind="goal_impact"),
    ]
    assert should_route_to_multi_agent("custom_query", subquestions=multi_sqs)

    single_sqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage"),
        SubQuestion(domain="cashflow", question_kind="scenario_cashflow"),
    ]
    assert not should_route_to_multi_agent("custom_query", subquestions=single_sqs)


# -------------------------------------------------------------------------------------------------
# 6: Specialist Tool Isolation & Security Audit
# -------------------------------------------------------------------------------------------------
def test_specialist_tool_subset_isolation_and_audit(ctx):
    """Specialists can call ONLY their allowed tool subset; outside attempts are rejected and audited."""
    # 1. CashflowAgent allowed tool succeeds
    res = execute_specialist_tool(ctx, "CashflowAgent", "get_calendar", {"horizon_days": 30})
    assert res.ok

    # 2. CashflowAgent attempting GoalsAgent tool fails and is audited
    with pytest.raises(PermissionError, match="forbidden tool 'list_goals'"):
        execute_specialist_tool(ctx, "CashflowAgent", "list_goals", {})

    rows = ctx.conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'specialist_tool_rejected'"
    ).fetchall()
    assert len(rows) >= 1
    assert "outside allowed subset for role 'CashflowAgent'" in rows[0][1]

    # 3. GoalsAgent calling get_calendar fails and is audited
    with pytest.raises(PermissionError, match="forbidden tool 'get_calendar'"):
        execute_specialist_tool(ctx, "GoalsAgent", "get_calendar", {"horizon_days": 30})

    # 4. ReadinessAgent calling list_memories fails
    with pytest.raises(PermissionError, match="forbidden tool 'list_memories'"):
        execute_specialist_tool(ctx, "ReadinessAgent", "list_memories", {})

    # 5. BehaviourAgent calling plan_contributions fails
    with pytest.raises(PermissionError, match="forbidden tool 'plan_contributions'"):
        execute_specialist_tool(ctx, "BehaviourAgent", "plan_contributions", {})


# -------------------------------------------------------------------------------------------------
# 7: Parallel Concurrency Test
# -------------------------------------------------------------------------------------------------
def test_parallel_branches_run_concurrently(ctx):
    """Parallel branches run concurrently: wall time is below the sum of injected delays."""
    subqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage", parameters={"horizon_days": 30}),
        SubQuestion(domain="goals", question_kind="goal_impact", parameters={"amount_paise": 10000}),
    ]
    delays = {
        "CashflowAgent": 0.20,
        "GoalsAgent": 0.20,
    }
    sum_of_delays = 0.40

    t0 = time.perf_counter()
    reports = run_specialists_fanout(subqs, ctx, task_id="task_parallel_01", delays=delays)
    wall_time = time.perf_counter() - t0

    assert len(reports) == 2
    # Wall time should be well below 0.40s (concurrent execution ~0.20-0.30s)
    assert wall_time < sum_of_delays, f"Wall time {wall_time:.3f}s was not below sum {sum_of_delays:.3f}s"


# -------------------------------------------------------------------------------------------------
# 8: Fault Tolerance & Partial Answer Test
# -------------------------------------------------------------------------------------------------
def test_specialist_failure_or_timeout_yields_partial_answer(ctx):
    """One specialist failing or timing out yields a partial answer that names the missing part."""
    subqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage", parameters={"horizon_days": 30}),
        SubQuestion(domain="goals", question_kind="goal_impact", parameters={"amount_paise": 10000}),
    ]
    # Injected delay of 0.40s for GoalsAgent while setting timeout to 0.20s
    delays = {"GoalsAgent": 0.40}
    reports = run_specialists_fanout(
        subqs,
        ctx,
        task_id="task_partial_01",
        timeout_seconds=0.20,
        delays=delays,
    )


    merge = merge_specialist_reports(reports, ctx.user_id, "task_partial_01", conn=ctx.conn)
    assert merge["status"] == "partial"


    assert len(merge["findings"]) >= 1  # Cashflow succeeded
    assert any("timed out checking 'goal_impact'" in g for g in merge["gaps"])


# -------------------------------------------------------------------------------------------------
# 9: Contradiction Detection, Audit, and Exclusion
# -------------------------------------------------------------------------------------------------
def test_contradiction_detected_audited_and_excluded(ctx):
    """Injected contradiction is detected, audited as merge_conflict, and excluded from narration."""
    rep1 = SpecialistReport(
        id="sr_1",
        user_id="user_alice",
        task_id="task_conflict_01",
        agent_role="CashflowAgent",
        sub_question_json={"question_kind": "forecast"},
        status="ok",
        findings_json=[{
            "metric": "surplus_paise",
            "value": 500000,
            "confidence": "high",
            "evidence": "cashflow_engine",
        }],
        gaps_json=[],
        duration_ms=10,
        created_at="2026-09-15T12:00:00Z",
    )
    rep2 = SpecialistReport(
        id="sr_2",
        user_id="user_alice",
        task_id="task_conflict_01",
        agent_role="GoalsAgent",
        sub_question_json={"question_kind": "goal_impact"},
        status="ok",
        findings_json=[{
            "metric": "surplus_paise",
            "value": 200000,  # Contradicts rep1's 500000!
            "confidence": "high",
            "evidence": "goals_engine",
        }],
        gaps_json=[],
        duration_ms=10,
        created_at="2026-09-15T12:00:00Z",
    )

    merge = merge_specialist_reports([rep1, rep2], "user_alice", "task_conflict_01", conn=ctx.conn)

    # 1. Contradiction detected
    assert len(merge["contradictions"]) == 1
    assert merge["contradictions"][0]["metric"] == "surplus_paise"

    # 2. Conflicting metric excluded from final narration findings
    assert not any(f["metric"] == "surplus_paise" for f in merge["findings"])

    # 3. Gaps explicitly state the contradiction
    assert any("Contradiction detected for metric 'surplus_paise'" in g for g in merge["gaps"])

    # 4. Audit event recorded
    rows = ctx.conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'merge_conflict'"
    ).fetchall()
    assert len(rows) >= 1
    assert "metric 'surplus_paise'" in rows[0][1]


# -------------------------------------------------------------------------------------------------
# 10-11: Reviewer, Revision, and Bound Tests
# -------------------------------------------------------------------------------------------------
def test_reviewer_catches_missed_subquestion_and_revision_fixes_it(ctx):
    """Reviewer catches a missed sub-question and the revision fixes it."""
    subqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage", parameters={"horizon_days": 30}),
        SubQuestion(domain="goals", question_kind="goal_impact", parameters={"amount_paise": 10000}),
    ]

    # Initial merge only answered cashflow
    initial_reports = [
        SpecialistReport(
            id="sr_init_1",
            user_id="user_alice",
            task_id="task_rev_01",
            agent_role="CashflowAgent",
            sub_question_json={"question_kind": "calendar_coverage"},
            status="ok",
            findings_json=[{
                "metric": "calendar_coverage",
                "value": {"status": "covered"},
                "confidence": "high",
                "evidence": "calendar",
            }],
            gaps_json=[],
            duration_ms=10,
            created_at="2026-09-15T12:00:00Z",
        )
    ]
    initial_merge = merge_specialist_reports(initial_reports, "user_alice", "task_rev_01", conn=ctx.conn)

    # Review should catch missed_subquestion for goals
    det_codes = deterministic_review(subqs, initial_reports, initial_merge)
    assert "missed_subquestion" in det_codes

    # Run review & revision
    rev_merge, rev_reports, reflections = run_review_and_revision(
        subquestions=subqs,
        reports=initial_reports,
        merge_result=initial_merge,
        ctx=ctx,
        task_id="task_rev_01",
        max_revision_rounds=1,
    )

    # Revision re-ran the missed subquestion and fixed it!
    assert len(reflections) >= 2
    assert reflections[-1].outcome == "fixed"
    assert any(r.agent_role == "GoalsAgent" for r in rev_reports)


def test_revision_bound_respected(ctx):
    """Revision round bound (default 1) is strictly respected without infinite loops."""
    subqs = [
        SubQuestion(domain="cashflow", question_kind="calendar_coverage", parameters={"horizon_days": 30}),
    ]
    reports = run_specialists_fanout(subqs, ctx, task_id="task_bound_01")
    merge = merge_specialist_reports(reports, ctx.user_id, "task_bound_01", conn=ctx.conn)

    # Scripted LLM critic that consistently critiques (without numbers)
    critic = FakeLLMClient([
        json.dumps({"critique_code": "unclear_answer", "explanation": "findings need more clarity"}),
        json.dumps({"critique_code": "unclear_answer", "explanation": "still needs more clarity"}),
    ])

    _, _, reflections = run_review_and_revision(
        subquestions=subqs,
        reports=reports,
        merge_result=merge,
        ctx=ctx,
        task_id="task_bound_01",
        llm_client=critic,
        max_revision_rounds=1,
    )

    # Bound is respected: stopped after max_revision_rounds (1) with gave_up
    assert len(reflections) == 2
    assert reflections[0].round == 0
    assert reflections[0].outcome == "unchanged"
    assert reflections[-1].round == 1
    assert reflections[-1].outcome == "gave_up"



# -------------------------------------------------------------------------------------------------
# 12: LLM Critic Cannot Change Numbers (Safety Rule 14)
# -------------------------------------------------------------------------------------------------
def test_llm_critic_cannot_change_numbers(ctx):
    """The LLM critic cannot introduce or change numbers; scripted critic output with numbers is rejected."""
    subqs = [SubQuestion(domain="cashflow", question_kind="calendar_coverage")]
    merge = {"findings": [{"metric": "val", "confidence": "high", "evidence": "calc"}], "gaps": []}

    # Critic proposing numbers (forbidden by Safety Rule 14)
    number_reply = json.dumps({
        "critique_code": "unclear_answer",
        "explanation": "You should change the projected surplus to 75000 paise",
    })
    client = FakeLLMClient([number_reply])

    with pytest.raises(ValueError, match="Safety Rule 14"):
        llm_critic_review(
            llm_client=client,
            subquestions=subqs,
            merge_result=merge,
            conn=ctx.conn,
            user_id=ctx.user_id,
            task_id="task_critic_num_01",
        )

    # Rejection was audited
    rows = ctx.conn.execute(
        "SELECT event_type FROM audit_events WHERE event_type = 'critic_number_rejected'"
    ).fetchall()
    assert len(rows) >= 1


# -------------------------------------------------------------------------------------------------
# 13: Failure Export Test
# -------------------------------------------------------------------------------------------------
def test_failure_export_writes_candidate_files(conn, tmp_path):
    """Failure export writes candidate golden files into the target candidates directory."""
    # Insert gave_up reflection
    refl = Reflection(
        id="ref_fail_01",
        user_id="user_alice",
        task_id="task_export_01",
        round=1,
        critique_codes=["unclear_answer"],
        source="deterministic",
        revised=True,
        outcome="gave_up",
        created_at="2026-09-15T12:00:00Z",
    )
    conn.execute(
        "INSERT INTO reflections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (refl.id, refl.user_id, refl.task_id, refl.round, json.dumps(refl.critique_codes), refl.source, 1, refl.outcome, refl.created_at),
    )

    # Record merge conflict audit event
    record_event(
        conn=conn,
        user_id="user_alice",
        actor="agent",
        event_type="merge_conflict",
        reason="Contradictory numbers reported",
        run_id="task_export_02",
        metadata={"metric": "end_balance"},
    )

    exported = export_failures(conn, output_dir=tmp_path)
    assert len(exported) >= 2

    # Check exported file contents
    file1 = tmp_path / "task_export_01.yaml"
    assert file1.exists()
    with open(file1, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["task_id"] == "task_export_01"
    assert data["failure_type"] == "gave_up"
    assert "TODO" in data["expected_behavior"]


# -------------------------------------------------------------------------------------------------
# 14: Fact Invariance With Critic On vs Off
# -------------------------------------------------------------------------------------------------
def test_same_facts_with_critic_on_and_off(ctx):
    """Same facts are produced regardless of whether the critic is on or off."""
    intent = {"type": "affordability", "amount_paise": 50000}

    # 1. Critic OFF
    res_off = run_multi_agent_workflow(
        intent=intent,
        user_id="user_alice",
        task_id="task_fact_off",
        ctx=ctx,
        llm_client=None,
    )

    # 2. Critic ON (returning clean 'ok')
    client = FakeLLMClient([json.dumps({"critique_code": "ok", "explanation": "findings are solid"})])
    res_on = run_multi_agent_workflow(
        intent=intent,
        user_id="user_alice",
        task_id="task_fact_on",
        ctx=ctx,
        llm_client=client,
    )

    # Compare metrics and values
    metrics_off = [(f["metric"], f["value"]) for f in res_off.get("findings", [])]
    metrics_on = [(f["metric"], f["value"]) for f in res_on.get("findings", [])]
    assert metrics_off == metrics_on


# -------------------------------------------------------------------------------------------------
# 15: End-to-End Agent Graph Multi-Agent Routing
# -------------------------------------------------------------------------------------------------
def test_agent_graph_routes_multi_domain_to_multi_agent(conn):
    """Multi-domain intent routes to multi_agent node in the main planner agent graph."""
    graph = build_planner_agent_graph()
    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "Can I afford a 50000 phone without hurting commitments or goals?",
        "clock": "2026-09-15T12:00:00Z",
        "planner_mode": "deterministic",
        "step_budget": 5,
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"conn": conn, "actor": "agent"}},
    )

    assert result["status"] == "completed"
    nodes_visited = [entry["node"] for entry in result.get("trace", [])]
    assert "understand" in nodes_visited
    assert "multi_agent" in nodes_visited
    assert "plan" not in nodes_visited  # Multi-domain routes to multi_agent, skipping single plan loop
