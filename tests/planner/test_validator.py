"""
Tests for PlanValidator and Adversarial Plan Rejections (PLAN_PHASE2 Section 5.3 & Stage 2.8).

Adversarial plans tested:
- A write tool (e.g. recategorize_transaction, undo, create_goal)
- A prohibited or nonexistent tool
- Invalid tool parameters (schema violations)
- Another user's referenced ID (category_id, goal_id, account_id, anomaly_id)
- Exceeding max_steps
- Plan missing required tools for the intent
- Duplicate steps
"""

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_category, insert_goal, insert_user
from copilot.models.agentic import Goal, Intent, Plan, PlanStep
from copilot.models.domain import Category, User
from copilot.planner.validator import PlanValidator
from copilot.workflow.nodes import ensure_tools_registered


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    ensure_tools_registered()
    return c


@pytest.fixture
def sample_user(conn):
    user_a = User(id="user_alice", created_at="2026-09-01T00:00:00Z")
    user_b = User(id="user_bob", created_at="2026-09-01T00:00:00Z")
    insert_user(conn, user_a)
    insert_user(conn, user_b)

    cat_a = Category(
        id="cat_groceries",
        user_id="user_alice",
        name="Groceries",
        created_at="2026-09-01T00:00:00Z",
    )
    cat_b = Category(
        id="cat_bob_secret",
        user_id="user_bob",
        name="Bob Secret",
        created_at="2026-09-01T00:00:00Z",
    )
    insert_category(conn, cat_a)
    insert_category(conn, cat_b)

    goal_a = Goal(
        id="goal_trip",
        user_id="user_alice",
        name="Trip to Goa",
        kind="savings",
        target_paise=5000000,
        current_paise=2000000,
        priority=1,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    goal_b = Goal(
        id="goal_bob_car",
        user_id="user_bob",
        name="Bob Car",
        kind="purchase",
        target_paise=10000000,
        current_paise=1000000,
        priority=2,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    insert_goal(conn, goal_a)
    insert_goal(conn, goal_b)

    return "user_alice"


def test_validator_accepts_valid_minimal_plan(conn, sample_user):
    """Validator accepts a well-formed plan matching intent requirements."""
    validator = PlanValidator(max_steps=5)
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    step = PlanStep(
        id="s1",
        task_id="t1",
        user_id=sample_user,
        seq=0,
        tool_name="aggregate_spend_by_category",
        args={"year": 2026, "month": 9},
        rationale="Get spend totals",
        proposed_by="deterministic",
    )
    plan = Plan(task_id="t1", steps=[step])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is True
    assert reasons == []


def test_validator_rejects_write_tool(conn, sample_user):
    """Safety Rule 1: Validator rejects any plan containing a write tool and audits plan_rejected."""
    validator = PlanValidator()
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    step1 = PlanStep(
        id="s1",
        task_id="t1",
        user_id=sample_user,
        seq=0,
        tool_name="aggregate_spend_by_category",
        args={"year": 2026, "month": 9},
        rationale="Spend",
        proposed_by="llm",
    )
    step2 = PlanStep(
        id="s2",
        task_id="t1",
        user_id=sample_user,
        seq=1,
        tool_name="recategorize_transaction",  # WRITE TOOL
        args={"transaction_id": "tx1", "new_category_id": "cat_groceries"},
        rationale="Illegal write",
        proposed_by="llm",
    )
    plan = Plan(task_id="t1", steps=[step1, step2])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("not planner-selectable" in r for r in reasons)

    # Verify plan_rejected audit event was recorded
    row = conn.execute(
        "SELECT event_type, reason, after_json FROM audit_events WHERE entity_id = 't1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "plan_rejected"
    assert "recategorize_transaction" in row[1] or "recategorize_transaction" in row[2]


def test_validator_rejects_nonexistent_tool(conn, sample_user):
    """Validator rejects nonexistent tools."""
    validator = PlanValidator()
    intent = Intent(type="check_budget", period="2026-09", year=2026, month=9)

    step = PlanStep(
        id="s1",
        task_id="t2",
        user_id=sample_user,
        seq=0,
        tool_name="nonexistent_magic_tool",
        args={},
        rationale="Magic",
        proposed_by="llm",
    )
    plan = Plan(task_id="t2", steps=[step])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("does not exist" in r for r in reasons)


def test_validator_rejects_schema_mismatch_arguments(conn, sample_user):
    """Validator rejects arguments that violate the tool's Pydantic input schema."""
    validator = PlanValidator()
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    step = PlanStep(
        id="s1",
        task_id="t3",
        user_id=sample_user,
        seq=0,
        tool_name="aggregate_spend_by_category",
        args={"year": "not_an_int", "month": 99},  # Invalid schema
        rationale="Malformed",
        proposed_by="llm",
    )
    plan = Plan(task_id="t3", steps=[step])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("do not conform to input schema" in r for r in reasons)


def test_validator_rejects_cross_user_entity_id(conn, sample_user):
    """Validator enforces user isolation: referencing another user's entity ID is rejected."""
    validator = PlanValidator()
    intent = Intent(type="forecast", period="2026-09", year=2026, month=9)

    step1 = PlanStep(
        id="s1",
        task_id="t4",
        user_id=sample_user,
        seq=0,
        tool_name="forecast_month",
        args={"year": 2026, "month": 9},
        rationale="Forecast",
        proposed_by="llm",
    )
    step2 = PlanStep(
        id="s2",
        task_id="t4",
        user_id=sample_user,
        seq=1,
        tool_name="forecast_category_spend",
        args={
            "year": 2026,
            "month": 9,
            "category_id": "cat_bob_secret",
        },  # Belongs to Bob, not Alice!
        rationale="Cross-user leak",
        proposed_by="llm",
    )
    plan = Plan(task_id="t4", steps=[step1, step2])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("cat_bob_secret' does not exist for user" in r for r in reasons)


def test_validator_rejects_too_many_steps(conn, sample_user):
    """Validator enforces step budget limits."""
    validator = PlanValidator(max_steps=2)
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    steps = [
        PlanStep(
            id=f"s_{i}",
            task_id="t5",
            user_id=sample_user,
            seq=i,
            tool_name="aggregate_spend_by_category",
            args={"year": 2026, "month": 9},
            rationale="Spend",
            proposed_by="llm",
        )
        for i in range(3)  # Exceeds max_steps=2
    ]
    plan = Plan(task_id="t5", steps=steps)

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("exceeds maximum allowed steps" in r for r in reasons)


def test_validator_rejects_missing_required_tool(conn, sample_user):
    """Validator rejects plans that omit tools marked required by the intent template."""
    validator = PlanValidator()
    # summarize_period requires aggregate_spend_by_category
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    step = PlanStep(
        id="s1",
        task_id="t6",
        user_id=sample_user,
        seq=0,
        tool_name="get_balance",  # Allowed, but aggregate_spend_by_category is required!
        args={},
        rationale="Balance only",
        proposed_by="llm",
    )
    plan = Plan(task_id="t6", steps=[step])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("missing required tool 'aggregate_spend_by_category'" in r for r in reasons)


def test_validator_rejects_duplicate_steps(conn, sample_user):
    """Validator rejects plans containing duplicate steps with identical tool and args."""
    validator = PlanValidator()
    intent = Intent(type="summarize_period", period="2026-09", year=2026, month=9)

    step1 = PlanStep(
        id="s1",
        task_id="t7",
        user_id=sample_user,
        seq=0,
        tool_name="aggregate_spend_by_category",
        args={"year": 2026, "month": 9},
        rationale="First call",
        proposed_by="llm",
    )
    step2 = PlanStep(
        id="s2",
        task_id="t7",
        user_id=sample_user,
        seq=1,
        tool_name="aggregate_spend_by_category",
        args={"year": 2026, "month": 9},  # Duplicate!
        rationale="Second call identical",
        proposed_by="llm",
    )
    plan = Plan(task_id="t7", steps=[step1, step2])

    is_valid, reasons = validator.validate_plan(conn, sample_user, plan, intent)
    assert is_valid is False
    assert any("Duplicate step detected" in r for r in reasons)
