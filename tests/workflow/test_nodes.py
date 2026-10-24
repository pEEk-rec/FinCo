"""
Unit tests for individual LangGraph workflow nodes.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from copilot.bank.ingest import set_connector
from copilot.bank.mock_bank import MockAAConnector
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_budget, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Budget, Category, User
from copilot.models.findings import Finding, FindingNumber
from copilot.tools.executor import ExecutionContext
from copilot.workflow.nodes import (
    advise_node,
    analyze_node,
    categorize_node,
    ensure_tools_registered,
    error_node,
    finalize_node,
    ingest_node,
    review_node,
)
from copilot.workflow.state import AgentState

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")
T0 = "2026-10-01T00:00:00Z"


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(c, Account(id="a1", user_id="u1", name="Checking", created_at=T0))
    insert_category(c, Category(id="cat_groceries", user_id="u1", name="Groceries", created_at=T0))
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=T0))
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
        run_id="run_test",
        clock=datetime(2026, 10, 15, tzinfo=UTC),
        policy=POLICY,
    )


def test_ingest_node_without_consent(exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "consent_id": None,
        "trace": [],
    }
    out = ingest_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["node_results"]["ingest"]["inserted"] == 0
    assert out["trace"][0]["status"] == "skipped"


def test_ingest_node_with_consent(conn, exec_ctx):
    connector = MockAAConnector.from_seed(42, 1, "u1", "a1")
    set_connector(connector)

    cid = connector.create_consent(
        "u1", ["a1"], "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "sync"
    )
    connector.approve_consent(cid)

    # Insert consent record into db
    conn.execute(
        """
        INSERT INTO consents (id, user_id, purpose, fi_types, account_ids,
                              date_range_from, date_range_to, status, expires_at, created_at)
        VALUES (?, 'u1', 'sync', 'DEPOSIT', '["a1"]',
                '2020-01-01T00:00:00Z', '2030-01-01T00:00:00Z', 'active',
                '2030-01-01T00:00:00Z', ?)
        """,
        (cid, T0),
    )

    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "consent_id": cid,
        "account_id": "a1",
        "trace": [],
    }
    out = ingest_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["node_results"]["ingest"]["inserted"] > 0
    assert out["trace"][0]["status"] == "ok"
    assert "ingest_statements" in out["trace"][0]["tools_called"]


def test_ingest_node_failure(exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "consent_id": "missing_consent_id",
        "trace": [],
    }
    out = ingest_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["status"] == "failed"
    assert out["trace"][0]["status"] == "error"


def test_categorize_node(conn, exec_ctx):
    # Insert an uncategorized transaction
    conn.execute(
        """
        INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction,
                                  merchant_raw, description, category_source, created_at)
        VALUES ('tx_test1', 'u1', 'a1', '2026-10-05T10:00:00Z', 50000, 'debit',
                'BigBasket Grocery Store', 'Grocery test', 'none', '2026-10-05T10:00:00Z')
        """
    )
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "trace": [],
    }
    out = categorize_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert "categorize_batch" in out["trace"][0]["tools_called"]
    assert "categorize" in out["node_results"]


def test_categorize_node_failure(exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "trace": [],
    }
    with patch(
        "copilot.workflow.nodes.run_categorization_pipeline",
        side_effect=RuntimeError("pipeline exploded"),
    ):
        out = categorize_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
        assert out["status"] == "failed"
        assert out["trace"][0]["status"] == "error"
        assert "pipeline exploded" in out["error"]["message"]


def test_analyze_node(conn, exec_ctx):
    conn.execute(
        """
        INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction,
                                  merchant_raw, description, category_id, category_source, created_at)
        VALUES ('tx_cat1', 'u1', 'a1', '2026-10-05T10:00:00Z', 900000, 'debit',
                'Grocery Supermarket', 'Groceries', 'cat_groceries', 'user', '2026-10-05T10:00:00Z')
        """
    )
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "year": 2026,
        "month": 10,
        "trace": [],
    }
    out = analyze_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert "analyze" in out["node_results"]
    assert len(out["findings"]) > 0


def test_advise_node(exec_ctx):
    finding = Finding(
        id="f1",
        kind="category_spend",
        period="2026-10",
        subject="Groceries",
        numbers=[FindingNumber(label="spend", value=900000, unit="paise")],
        description="Category spend summary",
    )
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "findings": [finding.model_dump()],
        "trace": [],
    }
    out = advise_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert len(out["draft_advice"]) > 0


def test_advise_node_empty_findings(exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "findings": [],
        "trace": [],
    }
    out = advise_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert out["draft_advice"] == []


def test_review_node_with_presupplied_decisions(conn, exec_ctx):
    # Insert draft advice row
    conn.execute(
        """
        INSERT INTO advice_items (id, user_id, run_id, finding_ids_json, text, evidence_json, assumptions_json, status, created_at)
        VALUES ('aid_1', 'u1', 'run_test', '["f1"]', 'Advice text', '{}', '[]', 'draft', ?)
        """,
        (T0,),
    )
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "draft_advice": [{"id": "aid_1", "text": "Advice text"}],
        "review_decisions": [{"advice_id": "aid_1", "decision": "approved"}],
        "trace": [],
    }
    out = review_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert out["node_results"]["review"]["approved"] == 1
    assert out["decided_advice"][0]["status"] == "approved"

    # Verify DB state
    row = conn.execute("SELECT status FROM advice_items WHERE id = 'aid_1'").fetchone()
    assert row[0] == "approved"


def test_finalize_node(exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "trace": [],
    }
    out = finalize_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["trace"][0]["status"] == "ok"
    assert out["status"] == "completed"
    assert "financial_state" in out


def test_error_node(conn, exec_ctx):
    state: AgentState = {
        "run_id": "run_test",
        "user_id": "u1",
        "error": {"node": "test_node", "message": "something broke"},
        "trace": [],
    }
    out = error_node(state, config={"configurable": {"exec_ctx": exec_ctx}})
    assert out["status"] == "failed"
    assert out["trace"][0]["status"] == "error"

    # Verify audit event
    row = conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'run_failed'"
    ).fetchone()
    assert row is not None
    assert "something broke" in row[1]
