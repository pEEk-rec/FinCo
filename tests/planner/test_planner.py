"""
Tests for DeterministicPlanner, LLMPlanner, and Bounded Execution Loop (PLAN_PHASE2 Section 5.3 & Stage 2.8).
"""

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_agent_task, insert_plan_step, insert_user
from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import AgentTask, Intent, PlanStep
from copilot.models.domain import Account, User
from copilot.planner.deterministic import DeterministicPlanner
from copilot.planner.execution import execute_plan_step
from copilot.planner.llm_planner import LLMPlanner, LLMPlanProposal, LLMStepProposal
from copilot.tools.executor import ExecutionContext
from copilot.workflow.nodes import ensure_tools_registered


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    ensure_tools_registered()
    return c


from datetime import datetime

from copilot.core.config import PROJECT_ROOT
from copilot.governance.policy import load_policy


@pytest.fixture
def user_ctx(conn):
    user = User(id="user_test", created_at="2026-09-01T00:00:00Z")
    insert_user(conn, user)
    acc = Account(
        id="acc_main",
        user_id="user_test",
        name="Main",
        opening_balance_paise=1000000,
        created_at="2026-09-01T00:00:00Z",
    )
    insert_account(conn, acc)
    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    ctx = ExecutionContext(
        conn=conn,
        user_id="user_test",
        actor="agent",
        run_id="run_test",
        policy=policy,
        clock=datetime.fromisoformat("2026-09-15T12:00:00+00:00"),
    )
    return ctx


def test_deterministic_planner_minimality_across_all_intents():
    """Minimality requirement: Deterministic planner produces minimal tool sets for each canonical intent."""
    planner = DeterministicPlanner()

    canonical_cases = [
        ("summarize_period", ["aggregate_spend_by_category"]),
        ("check_budget", ["check_budgets"]),
        ("forecast", ["forecast_month"]),
        ("investigate_anomaly", ["detect_anomalies"]),
        ("explain_change", ["aggregate_spend_by_category"]),
        ("whatif_add_spend", ["check_budgets"]),
        ("whatif_reduce_spend", ["check_budgets"]),
        ("goal_check", ["get_balance"]),
        ("list_recurring", ["get_transactions"]),
        ("alerts_overview", ["check_budgets"]),
    ]

    for intent_type, expected_tools in canonical_cases:
        intent = Intent(
            type=intent_type,  # type: ignore[arg-type]
            period="2026-09",
            year=2026,
            month=9,
            amount_paise=1500000,
        )
        plan = planner.propose("task_1", "user_test", intent)
        tools = [s.tool_name for s in plan.steps]
        assert tools == expected_tools, f"Intent {intent_type} planned {tools}, expected {expected_tools}"
        assert all(s.proposed_by == "deterministic" for s in plan.steps)


def test_llm_planner_with_fake_provider(user_ctx):
    """LLMPlanner generates plan via structured output when client is provided."""
    proposal = LLMPlanProposal(
        steps=[
            LLMStepProposal(
                tool_name="aggregate_spend_by_category",
                args={"year": 2026, "month": 9},
                rationale="Analyze category spend",
            )
        ]
    )
    fake_client = FakeLLMClient(replies=[proposal.model_dump_json()])
    planner = LLMPlanner(client=fake_client)

    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)
    plan = planner.propose("task_llm", "user_test", intent)

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "aggregate_spend_by_category"
    assert plan.steps[0].proposed_by == "llm"


def test_llm_planner_failure_falls_back_to_deterministic():
    """If LLM client fails or raises error, LLMPlanner falls back safely to deterministic plan."""
    broken_client = FakeLLMClient(replies=[])  # Empty replies will raise RuntimeError on call
    planner = LLMPlanner(client=broken_client)

    intent = Intent(type="check_budget", period="2026-09", year=2026, month=9)
    plan = planner.propose("task_fallback", "user_test", intent)

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "check_budgets"
    assert plan.steps[0].proposed_by == "deterministic"


def test_execution_loop_memoization(user_ctx):
    """Execution loop: identical (tool, args) returns earlier result as skipped_memoized."""
    memo_cache = {}
    call_history = []

    task = AgentTask(
        id="t_memo",
        user_id=user_ctx.user_id,
        raw_text="Check balance",
        status="planned",
        planner_mode="deterministic",
        created_at="2026-09-15T12:00:00Z",
    )
    insert_agent_task(user_ctx.conn, task)

    step1 = PlanStep(
        id="step_m1",
        task_id="t_memo",
        user_id=user_ctx.user_id,
        seq=0,
        tool_name="get_balance",
        args={},
        rationale="Get balance first",
        proposed_by="deterministic",
    )
    insert_plan_step(user_ctx.conn, step1)

    obs1, stop1, reason1 = execute_plan_step(user_ctx, step1, memo_cache, call_history)
    assert obs1.ok is True
    assert stop1 is False
    assert len(memo_cache) == 1
    assert len(call_history) == 1

    # Second call with identical tool and args
    step2 = PlanStep(
        id="step_m2",
        task_id="t_memo",
        user_id=user_ctx.user_id,
        seq=1,
        tool_name="get_balance",
        args={},
        rationale="Get balance second (redundant)",
        proposed_by="deterministic",
    )
    insert_plan_step(user_ctx.conn, step2)

    obs2, stop2, reason2 = execute_plan_step(user_ctx, step2, memo_cache, call_history)
    assert obs2.ok is True
    assert stop2 is False
    assert obs2.data_summary.get("memoized") is True
    # The actual tool was NOT executed again in call_history
    assert len(call_history) == 1

    # Check status in plan_steps table
    row = user_ctx.conn.execute("SELECT status FROM plan_steps WHERE id = 'step_m2'").fetchone()
    assert row is not None
    assert row[0] == "skipped_memoized"


def test_execution_loop_loop_detection(user_ctx):
    """Execution loop: calling the same tool beyond max_repeat ends task with loop_detected."""
    memo_cache = {}
    call_history = []

    task = AgentTask(
        id="t_loop",
        user_id=user_ctx.user_id,
        raw_text="Check balance loop",
        status="planned",
        planner_mode="deterministic",
        created_at="2026-09-15T12:00:00Z",
    )
    insert_agent_task(user_ctx.conn, task)

    for i in range(3):
        step = PlanStep(
            id=f"step_loop_{i}",
            task_id="t_loop",
            user_id=user_ctx.user_id,
            seq=i,
            tool_name="get_balance",
            args={"account_id": f"acc_{i}"},  # Different args to bypass memoization
            rationale=f"Call {i}",
            proposed_by="deterministic",
        )
        insert_plan_step(user_ctx.conn, step)
        obs, should_stop, stop_reason = execute_plan_step(
            user_ctx, step, memo_cache, call_history, max_repeat=3
        )
        assert should_stop is False

    # 4th call reaches max_repeat=3 limit!
    step4 = PlanStep(
        id="step_loop_3",
        task_id="t_loop",
        user_id=user_ctx.user_id,
        seq=3,
        tool_name="get_balance",
        args={"account_id": "acc_3"},
        rationale="Exceeds max repeat",
        proposed_by="deterministic",
    )
    insert_plan_step(user_ctx.conn, step4)
    obs4, should_stop, stop_reason = execute_plan_step(
        user_ctx, step4, memo_cache, call_history, max_repeat=3
    )

    assert should_stop is True
    assert stop_reason == "loop_detected"
    assert "Loop detected" in obs4.error
