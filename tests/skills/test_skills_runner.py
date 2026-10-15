"""
Tests for Skill Runner, Preconditions, Execution Tracking, and Isolation (Stage 3.10 & Section 5.12).
"""

import sqlite3
from datetime import datetime

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import get_skill_run, list_skill_runs
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, Transaction, User
from copilot.skills.runner import run_skill
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def setup_tools():
    ensure_tools_registered()


def _setup_user_with_data(conn: sqlite3.Connection, user_id: str = "u_runner", has_txns: bool = True):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id="a1",
            user_id=user_id,
            name="Main Checking",
            opening_balance_paise=10_000_000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    insert_category(conn, Category(id="c_food", user_id=user_id, name="dining", created_at="2026-01-01T00:00:00Z"))
    if has_txns:
        insert_transaction(
            conn,
            Transaction(
                id="tx_01",
                account_id="a1",
                user_id=user_id,
                amount_paise=250000,
                direction="debit",
                category_id="c_food",
                merchant_raw="Food Place",
                description="Dinner",
                occurred_at="2026-10-05T12:00:00Z",
                created_at="2026-10-05T12:00:00Z",
            ),
        )


def _get_ctx(conn: sqlite3.Connection, user_id: str = "u_runner", actor: str = "agent") -> ExecutionContext:
    from copilot.core.config import PROJECT_ROOT

    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    return ExecutionContext(
        conn=conn,
        user_id=user_id,
        actor=actor,
        run_id="run_runner_test",
        policy=policy,
        clock=datetime.fromisoformat("2026-10-15T12:00:00+00:00"),
    )


def test_precondition_failure_cannot_run(conn):
    """User with no transactions triggers typed 'cannot_run' status."""
    _setup_user_with_data(conn, "u_notx", has_txns=False)
    ctx = _get_ctx(conn, "u_notx")

    result = run_skill(ctx, "affordability_check", {"amount_paise": 3000000})
    assert result.status == "cannot_run"
    assert "User has no transactions" in (result.reason or "")

    runs = list_skill_runs(conn, "u_notx")
    assert len(runs) == 1
    assert runs[0].status == "cannot_run"
    assert runs[0].skill_name == "affordability_check"


def test_precondition_success_runs_ok(conn):
    """User with transactions satisfies preconditions and executes successfully."""
    _setup_user_with_data(conn, "u_withtx", has_txns=True)
    ctx = _get_ctx(conn, "u_withtx")

    result = run_skill(ctx, "affordability_check", {"amount_paise": 3000000})
    assert result.status == "ok"
    assert "get_calendar" in result.outputs
    assert "run_whatif" in result.outputs
    assert "check_commitment_coverage" in result.outputs
    assert "evaluate_goal_impact" in result.outputs

    run_row = get_skill_run(conn, "u_withtx", result.skill_run_id)
    assert run_row is not None
    assert run_row.status == "ok"
    assert run_row.finished_at is not None
    assert "get_calendar" in run_row.outputs_json


def test_missing_required_input_cannot_run(conn):
    """Failing to provide required input results in 'cannot_run'."""
    _setup_user_with_data(conn, "u_req", has_txns=True)
    ctx = _get_ctx(conn, "u_req")

    # affordability_check requires amount_paise
    result = run_skill(ctx, "affordability_check", {})
    assert result.status == "cannot_run"
    assert "Missing required input 'amount_paise'" in (result.reason or "")


def test_registered_skill_tool_execution(conn):
    """Executing affordability_check through execute_tool works seamlessly."""
    _setup_user_with_data(conn, "u_tool_exec", has_txns=True)
    ctx = _get_ctx(conn, "u_tool_exec")

    exec_res = execute_tool(
        ctx,
        "affordability_check",
        {"amount_paise": 1500000, "category_id": "c_food"},
    )
    assert exec_res.ok
    assert exec_res.data.status == "ok"
    assert exec_res.data.skill_name == "affordability_check"
    assert "get_calendar" in exec_res.data.outputs


def test_generic_run_skill_tool(conn):
    """Executing run_skill tool with valid parameters works cleanly."""
    _setup_user_with_data(conn, "u_generic", has_txns=True)
    ctx = _get_ctx(conn, "u_generic")

    exec_res = execute_tool(
        ctx,
        "run_skill",
        {
            "skill_name": "affordability_check",
            "inputs": {"amount_paise": 500000},
        },
    )
    assert exec_res.ok
    assert exec_res.data.status == "ok"
    assert exec_res.data.skill_name == "affordability_check"
