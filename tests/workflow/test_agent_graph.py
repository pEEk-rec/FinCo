"""
Integration tests for Phase 2 Planner-Driven Agent Graph (PLAN_PHASE2 Section 5.10 & Stage 2.8).

Tests:
- End-to-end offline graph execution across canonical intents
- Refusal path immediately finalizes with status='refused'
- Clarification interrupt and resumption
- Review interrupt for consequential recommendations
- Bounds enforcement: step budget, loop detection
- Adversarial LLM plan rejected, audited, and deterministic plan runs
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_agent_task,
    insert_account,
    insert_category,
    insert_goal,
    insert_user,
    list_plan_steps,
)
from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, User
from copilot.planner.llm_planner import LLMPlanProposal, LLMStepProposal
from copilot.workflow.agent_graph import build_planner_agent_graph
from copilot.workflow.agentic_state import AgenticState


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    # Seed base user and account
    u = User(id="user_alice", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u)
    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=5000000,
        created_at="2026-09-01T00:00:00Z",
    )
    insert_account(c, acc)
    cat = Category(
        id="cat_food",
        user_id="user_alice",
        name="Food & Dining",
        created_at="2026-09-01T00:00:00Z",
    )
    insert_category(c, cat)
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


def test_agent_graph_end_to_end_summarize_period(conn):
    """End-to-end execution of a summarize_period query through the planner agent graph."""
    graph = build_planner_agent_graph()
    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "how much did I spend in September 2026?",
        "clock": "2026-09-15T12:00:00Z",
        "planner_mode": "deterministic",
        "step_budget": 5,
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"conn": conn, "actor": "agent"}},
    )

    assert result["status"] == "completed"
    assert result["stop_reason"] == "completed"

    task_id = result["task_id"]
    task = get_agent_task(conn, "user_alice", task_id)
    assert task is not None
    assert task.status == "done"
    assert task.stop_reason == "completed"

    # Plan steps were recorded and completed
    steps = list_plan_steps(conn, "user_alice", task_id)
    assert len(steps) >= 1
    assert steps[0].tool_name == "aggregate_spend_by_category"
    assert steps[0].status == "done"

    # Node trace recorded
    nodes_visited = [entry["node"] for entry in result["trace"]]
    assert "understand" in nodes_visited
    assert "plan" in nodes_visited
    assert "act" in nodes_visited
    assert "finalize" in nodes_visited


def test_agent_graph_refusal_terminates_immediately(conn):
    """Safety Rule: An investment advice query is refused deterministically and halts at finalize."""
    graph = build_planner_agent_graph()
    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "which stock should I invest in for high returns?",
        "clock": "2026-09-15T12:00:00Z",
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"conn": conn, "actor": "agent"}},
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "completed"
    assert result["refusal_reason"] is not None

    task = get_agent_task(conn, "user_alice", result["task_id"])
    assert task is not None
    assert task.status == "refused"

    # No plan or act steps executed
    steps = list_plan_steps(conn, "user_alice", result["task_id"])
    assert steps == []

    nodes_visited = [entry["node"] for entry in result["trace"]]
    assert "understand" in nodes_visited
    assert "finalize" in nodes_visited
    assert "plan" not in nodes_visited
    assert "act" not in nodes_visited


def test_agent_graph_clarification_interrupt_and_resume(conn):
    """Single-round clarification flow: graph interrupts for missing entity and resumes upon user reply."""
    checkpointer = MemorySaver()
    graph = build_planner_agent_graph(checkpointer=checkpointer)

    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "how much did I spend?",  # Ambiguous: no period or category specified!
        "clock": "2026-09-15T12:00:00Z",
        "planner_mode": "deterministic",
    }
    thread_config = {
        "configurable": {"thread_id": "thread_clarify_1", "conn": conn, "actor": "agent"}
    }

    # First invoke should trigger clarify interrupt
    _ = graph.invoke(initial_state, config=thread_config)
    state_snap = graph.get_state(thread_config)
    assert len(state_snap.tasks) > 0
    assert len(state_snap.tasks[0].interrupts) > 0

    interrupt_payload = state_snap.tasks[0].interrupts[0].value
    assert "question" in interrupt_payload

    # Resume graph with user clarification: "in September 2026"
    from langgraph.types import Command

    res2 = graph.invoke(
        Command(resume="in September 2026"),
        config=thread_config,
    )
    assert res2["status"] == "completed"


def test_agent_graph_step_budget_exhaustion(conn):
    """Bounds: step budget exhaustion cleanly stops the task with stop_reason='step_budget'."""
    graph = build_planner_agent_graph()
    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "how much did I spend in September 2026?",
        "clock": "2026-09-15T12:00:00Z",
        "planner_mode": "deterministic",
        "step_budget": 0,  # 0 step budget forces immediate exhaustion!
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"conn": conn, "actor": "agent"}},
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "step_budget"

    task = get_agent_task(conn, "user_alice", result["task_id"])
    assert task is not None
    assert task.stop_reason == "step_budget"


def test_agent_graph_replaces_adversarial_llm_plan_with_deterministic(conn):
    """Safety Rule: LLM proposing write tools has its plan rejected and replaced by deterministic plan."""
    # LLM proposes an illegal write tool (recategorize_transaction)
    adversarial_proposal = LLMPlanProposal(
        steps=[
            LLMStepProposal(
                tool_name="recategorize_transaction",
                args={"transaction_id": "tx_bad", "new_category_id": "cat_food"},
                rationale="Adversarial write injection",
            )
        ]
    )
    fake_client = FakeLLMClient(replies=[adversarial_proposal.model_dump_json()])

    graph = build_planner_agent_graph()
    initial_state: AgenticState = {
        "user_id": "user_alice",
        "raw_text": "check my budgets for September 2026",
        "clock": "2026-09-15T12:00:00Z",
        "planner_mode": "llm",
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"conn": conn, "actor": "agent", "llm_client": fake_client}},
    )

    assert result["status"] == "completed"

    # Verify that plan_rejected was audited
    audit_row = conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'plan_rejected'"
    ).fetchone()
    assert audit_row is not None
    assert "recategorize_transaction" in audit_row[1]

    # Verify that the executed steps were the deterministic plan (check_budgets), NOT the write tool!
    steps = list_plan_steps(conn, "user_alice", result["task_id"])
    assert len(steps) >= 1
    assert steps[0].tool_name == "check_budgets"
    assert steps[0].status == "done"
