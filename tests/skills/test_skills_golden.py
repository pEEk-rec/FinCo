"""
Golden evaluation tests for all 5 skills across all eval cases (PLAN_PHASE3 Section 5.12).

Validates:
- affordability_check eval cases (3 cases)
- monthly_close eval cases (3 cases)
- trip_planning eval cases (3 cases)
- contribution_review eval cases (3 cases)
- explain_month_change eval cases (3 cases)
"""

import json
import sqlite3
from datetime import datetime

import pytest

from copilot.core.config import PROJECT_ROOT
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_goal,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import (
    insert_bucket,
    insert_commitment,
    insert_memory_item,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import Bucket, Commitment, MemoryItem
from copilot.skills.runner import run_skill
from copilot.tools.executor import ExecutionContext
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


def _setup_full_persona(conn: sqlite3.Connection, user_id: str):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id="a1",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=25_000_000,  # 2.5 Lakh
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat_name, cat_id in [
        ("dining", "c_dining"),
        ("shopping", "c_shopping"),
        ("groceries", "c_groceries"),
        ("travel", "c_travel"),
        ("education", "c_education"),
        ("utilities", "c_utilities"),
    ]:
        insert_category(conn, Category(id=cat_id, user_id=user_id, name=cat_name, created_at="2026-01-01T00:00:00Z"))

    # Add 3 months of transactions for stable history
    for m in range(7, 11):
        month_str = f"2026-{m:02d}"
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_inc_{m}",
                account_id="a1",
                user_id=user_id,
                amount_paise=-10_000_000,  # 1 Lakh income (negative for credit)
                direction="credit",
                merchant_raw="Employer",
                description="Salary",
                occurred_at=f"{month_str}-01T10:00:00Z",
                created_at=f"{month_str}-01T10:00:00Z",
            ),
        )
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_din_{m}",
                account_id="a1",
                user_id=user_id,
                amount_paise=1_000_000,
                direction="debit",
                category_id="c_dining",
                merchant_raw="Restaurant",
                description="Dining out",
                occurred_at=f"{month_str}-05T12:00:00Z",
                created_at=f"{month_str}-05T12:00:00Z",
            ),
        )
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_groc_{m}",
                account_id="a1",
                user_id=user_id,
                amount_paise=2_000_000,
                direction="debit",
                category_id="c_groceries",
                merchant_raw="Supermarket",
                description="Groceries",
                occurred_at=f"{month_str}-10T12:00:00Z",
                created_at=f"{month_str}-10T12:00:00Z",
            ),
        )

    # Active goal
    from copilot.models.agentic import Goal
    insert_goal(
        conn,
        Goal(
            id="g_trip",
            user_id=user_id,
            name="Trip Goal",
            kind="savings",
            target_paise=5_000_000,
            current_paise=1_000_000,
            deadline="2027-06-01",
            priority=1,
            status="active",
            created_at="2026-08-01T00:00:00Z",
            updated_at="2026-08-01T00:00:00Z",
        ),
    )

    # Active commitment
    insert_commitment(
        conn,
        Commitment(
            id="comm_rent",
            user_id=user_id,
            name="Apartment Rent",
            direction="outflow",
            kind="rent",
            amount_paise=2_500_000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day": 5},
            start_date="2026-01-01",
            status="active",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )

    # Spending bucket
    insert_bucket(
        conn,
        Bucket(
            id="b_dining",
            user_id=user_id,
            name="Dining Bucket",
            kind="spending",
            period_policy="reset_monthly",
            status="active",
            sort_order=1,
            created_at="2026-01-01T00:00:00Z",
        ),
    )

    # Active memory item
    insert_memory_item(
        conn,
        MemoryItem(
            id="mem_din",
            user_id=user_id,
            kind="recurring_pattern",
            subject_key="category:dining",
            statement_json={"pattern": "weekend_heavy"},
            source="observed",
            status="active",
            prior_bp=7000,
            created_at="2026-08-01T00:00:00Z",
            last_evidence_at="2026-10-01T00:00:00Z",
        ),
    )


def _get_ctx(conn: sqlite3.Connection, user_id: str) -> ExecutionContext:
    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    return ExecutionContext(
        conn=conn,
        user_id=user_id,
        actor="agent",
        run_id="run_golden_eval",
        policy=policy,
        clock=datetime.fromisoformat("2026-10-15T12:00:00+00:00"),
    )


@pytest.mark.parametrize(
    "skill_name,case_file",
    [
        ("affordability_check", "case_01.json"),
        ("affordability_check", "case_02.json"),
        ("affordability_check", "case_03.json"),
        ("contribution_review", "case_01.json"),
        ("contribution_review", "case_02.json"),
        ("contribution_review", "case_03.json"),
        ("explain_month_change", "case_01.json"),
        ("explain_month_change", "case_02.json"),
        ("explain_month_change", "case_03.json"),
        ("monthly_close", "case_01.json"),
        ("monthly_close", "case_02.json"),
        ("monthly_close", "case_03.json"),
        ("trip_planning", "case_01.json"),
        ("trip_planning", "case_02.json"),
        ("trip_planning", "case_03.json"),
    ],
)
def test_skill_eval_cases(conn, skill_name, case_file):
    """Execute each golden eval case and verify expected status and tool outputs."""
    case_path = PROJECT_ROOT / "tests" / "skills" / skill_name / case_file
    case_data = json.loads(case_path.read_text(encoding="utf-8"))

    user_id = f"u_eval_{skill_name}_{case_file.replace('.json', '')}"
    _setup_full_persona(conn, user_id)
    ctx = _get_ctx(conn, user_id)

    res = run_skill(ctx, skill_name, case_data["inputs"])
    assert res.status == case_data["expected_status"], f"Eval case {case_file} failed: {res.reason}"

    for expected_key in case_data.get("expected_outputs_contain", []):
        assert expected_key in res.outputs, f"Missing output '{expected_key}' in {skill_name} result"
