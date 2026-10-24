"""
Integration tests for the LangGraph FinCo workflow graph.

Verifies:
- Full graph runs offline end-to-end with MemorySaver checkpointing.
- Interrupt-based human review pauses execution and resumes applying decisions.
- Conditional edge after ingest skips categorize when 0 new transactions are found.
- Categorization failure routes to error node, audits failure, and exits cleanly.
- Monthly review graph executes analyze -> advise -> review -> finalize.
- Interoperability with Phase 0 RunState and to_llm_projection.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from copilot.bank.ingest import set_connector
from copilot.bank.mock_bank import MockAAConnector
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_budget, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Budget, Category, User
from copilot.models.run_state import to_llm_projection
from copilot.tools.executor import ExecutionContext
from copilot.workflow.graph import build_agent_graph, build_monthly_review_graph
from copilot.workflow.nodes import ensure_tools_registered
from copilot.workflow.state import AgentState, to_run_state
from copilot.workflow.trace import format_trace, print_trace

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")
T0 = "2024-01-01T00:00:00Z"
ALL_TIME = ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(c, Account(id="a1", user_id="u1", name="Checking", created_at=T0))
    insert_category(c, Category(id="cat_groceries", user_id="u1", name="Groceries", created_at=T0))
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=T0))
    insert_category(c, Category(id="cat_shopping", user_id="u1", name="Shopping", created_at=T0))
    insert_budget(
        c,
        Budget(
            id="b1",
            user_id="u1",
            category_id="cat_groceries",
            limit_paise=1000000,
            warn_threshold_pct=80,
        ),
    )
    return c


@pytest.fixture
def exec_ctx(conn):
    ensure_tools_registered()
    return ExecutionContext(
        conn=conn,
        user_id="u1",
        actor="agent",
        run_id="run_graph_test",
        clock=datetime(2024, 2, 15, tzinfo=UTC),
        policy=POLICY,
    )


def test_full_agent_graph_offline_end_to_end_with_interrupt(conn, exec_ctx):
    connector = MockAAConnector.from_seed(42, 2, "u1", "a1")
    set_connector(connector)

    cid = connector.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    connector.approve_consent(cid)

    conn.execute(
        """
        INSERT INTO consents (id, user_id, purpose, fi_types, account_ids,
                              date_range_from, date_range_to, status, expires_at, created_at)
        VALUES (?, 'u1', 'sync', 'DEPOSIT', '["a1"]', ?, ?, 'active', ?, ?)
        """,
        (cid, ALL_TIME[0], ALL_TIME[1], ALL_TIME[1], T0),
    )

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)

    thread_id = "thread-run-1"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "exec_ctx": exec_ctx,
        }
    }

    initial_state: AgentState = {
        "run_id": "run_graph_test",
        "user_id": "u1",
        "consent_id": cid,
        "account_id": "a1",
        "year": 2024,
        "month": 2,
        "clock": "2024-02-15T10:00:00Z",
        "trace": [],
    }

    # First invoke runs until review node interrupts
    interrupted_result = graph.invoke(initial_state, config=config)

    # Must contain interrupt payload with drafts
    assert "__interrupt__" in interrupted_result
    interrupts = interrupted_result["__interrupt__"]
    assert len(interrupts) > 0
    drafts = interrupts[0].value.get("drafts", [])
    assert len(drafts) > 0

    # User decides to approve the first advice item
    first_advice_id = drafts[0]["id"]
    resume_command = Command(resume=[{"advice_id": first_advice_id, "decision": "approved"}])

    final_result = graph.invoke(resume_command, config=config)

    # Workflow completed successfully
    assert final_result.get("status") == "completed"
    assert "financial_state" in final_result
    assert final_result["financial_state"] is not None

    # Verify decision applied in database
    row = conn.execute(
        "SELECT status FROM advice_items WHERE id = ?", (first_advice_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == "approved"

    # Verify run trace
    trace = final_result.get("trace", [])
    nodes_executed = [entry["node"] for entry in trace]
    assert nodes_executed == [
        "ingest",
        "categorize",
        "analyze",
        "advise",
        "review",
        "finalize",
    ]
    assert all(entry["status"] == "ok" for entry in trace)

    # Format trace string must be clean and printable
    formatted = format_trace(trace)
    assert "WORKFLOW RUN TRACE" in formatted
    assert "finalize" in formatted
    print_trace(trace)

    # Verify Phase 0 RunState projection
    run_state = to_run_state(final_result)
    assert run_state.run_id == "run_graph_test"
    assert run_state.confidence == 1.0
    projection = to_llm_projection(run_state, ["run_id", "user_id", "confidence"])
    assert projection == {"run_id": "run_graph_test", "user_id": "u1", "confidence": 1.0}


def test_conditional_edge_zero_txns_skips_categorize_to_analyze(conn, exec_ctx):
    # Ingest without a consent -> 0 txns ingested
    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": "thread-zero-analyze",
            "exec_ctx": exec_ctx,
        }
    }

    state: AgentState = {
        "run_id": "run_zero_1",
        "user_id": "u1",
        "consent_id": None,  # no consent -> 0 new txns
        "year": 2024,
        "month": 2,
        "on_zero_txns": "analyze",
        "review_decisions": [],  # auto-review so it doesn't interrupt
        "trace": [],
    }

    result = graph.invoke(state, config=config)
    assert result.get("status") == "completed"

    trace_nodes = [e["node"] for e in result.get("trace", [])]
    assert "ingest" in trace_nodes
    assert "categorize" not in trace_nodes  # skipped categorize!
    assert "analyze" in trace_nodes
    assert "finalize" in trace_nodes


def test_conditional_edge_zero_txns_skips_to_finalize(conn, exec_ctx):
    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": "thread-zero-finalize",
            "exec_ctx": exec_ctx,
        }
    }

    state: AgentState = {
        "run_id": "run_zero_2",
        "user_id": "u1",
        "consent_id": None,
        "year": 2024,
        "month": 2,
        "on_zero_txns": "finalize",
        "trace": [],
    }

    result = graph.invoke(state, config=config)
    assert result.get("status") == "completed"

    trace_nodes = [e["node"] for e in result.get("trace", [])]
    assert trace_nodes == ["ingest", "finalize"]


def test_categorize_failure_routes_to_error_with_audit(conn, exec_ctx):
    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": "thread-error-cat",
            "exec_ctx": exec_ctx,
        }
    }

    # Seed 1 txn so ingest routes to categorize
    connector = MockAAConnector.from_seed(42, 1, "u1", "a1")
    set_connector(connector)
    cid = connector.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    connector.approve_consent(cid)
    conn.execute(
        """
        INSERT INTO consents (id, user_id, purpose, fi_types, account_ids,
                              date_range_from, date_range_to, status, expires_at, created_at)
        VALUES (?, 'u1', 'sync', 'DEPOSIT', '["a1"]', ?, ?, 'active', ?, ?)
        """,
        (cid, ALL_TIME[0], ALL_TIME[1], ALL_TIME[1], T0),
    )

    state: AgentState = {
        "run_id": "run_fail_1",
        "user_id": "u1",
        "consent_id": cid,
        "account_id": "a1",
        "year": 2024,
        "month": 2,
        "trace": [],
    }

    with patch(
        "copilot.workflow.nodes.run_categorization_pipeline",
        side_effect=RuntimeError("Categorization model failed permanently"),
    ):
        result = graph.invoke(state, config=config)

    assert result.get("status") == "failed"
    assert result.get("error") is not None
    assert "Categorization model failed" in result["error"]["message"]

    trace = result.get("trace", [])
    assert trace[-1]["node"] == "error"
    assert trace[-1]["status"] == "error"

    # Verify audited event
    row = conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'run_failed'"
    ).fetchone()
    assert row is not None
    assert "Categorization model failed" in row[1]


def test_monthly_review_graph_mode(conn, exec_ctx):
    # Monthly review starts directly at analyze -> advise -> review -> finalize
    checkpointer = MemorySaver()
    graph = build_monthly_review_graph(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": "thread-monthly-1",
            "exec_ctx": exec_ctx,
        }
    }

    state: AgentState = {
        "run_id": "run_monthly_1",
        "user_id": "u1",
        "year": 2024,
        "month": 2,
        "review_decisions": [],  # non-interactive review for test
        "trace": [],
    }

    result = graph.invoke(state, config=config)
    assert result.get("status") == "completed"

    trace_nodes = [e["node"] for e in result.get("trace", [])]
    assert trace_nodes == ["analyze", "advise", "review", "finalize"]
