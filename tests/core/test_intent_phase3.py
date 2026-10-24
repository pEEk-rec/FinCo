"""
Tests for Phase 3 Intent Classification, Refusals, Plan Minimality, and Adversarial Rejection (Stage 3.10 & Section 5.10).
"""

import sqlite3
from datetime import datetime

import pytest
import yaml

from copilot.config.phase2 import load_intent_patterns
from copilot.core.config import PROJECT_ROOT
from copilot.core.intent import (
    check_input_gate,
    classify_intent,
    parse_amount_paise,
    parse_period,
    resolve_entities,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_category, insert_goal, insert_user
from copilot.models.agentic import Goal, Intent, Plan, PlanStep
from copilot.models.domain import Category, User
from copilot.planner.deterministic import DeterministicPlanner
from copilot.planner.validator import PlanValidator
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


def _setup_intent_entities(conn: sqlite3.Connection, user_id: str = "u_intent"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    for cat_name, cat_id in [
        ("dining", "c_dining"),
        ("shopping", "c_shopping"),
        ("groceries", "c_groceries"),
        ("travel", "c_travel"),
    ]:
        insert_category(
            conn,
            Category(id=cat_id, user_id=user_id, name=cat_name, created_at="2026-01-01T00:00:00Z"),
        )

    insert_goal(
        conn,
        Goal(
            id="g_vacation",
            user_id=user_id,
            name="Vacation Goal",
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


def test_refusal_suite():
    """Verify input gate refusals for financial products, market growth, and money movement."""
    # 1. Product recommendation refusal
    refused, r_class, msg = check_input_gate("Which SIP should I invest in?")
    assert refused
    assert r_class == "INVESTMENT_ADVICE"
    assert "cannot recommend specific funds, stocks, or SIP products" in (msg or "")

    refused, r_class, msg = check_input_gate("which fund is best for high returns")
    assert refused
    assert r_class == "INVESTMENT_ADVICE"

    # 2. Market growth / return prediction refusal
    refused, r_class, msg = check_input_gate("How much will my SIP grow in 5 years?")
    assert refused
    assert r_class == "MARKET_PREDICTION"
    assert "Balances never grow by assumption" in (msg or "")

    # 3. Money movement refusal
    refused, r_class, msg = check_input_gate("Move money to my savings account please")
    assert refused
    assert r_class == "MONEY_MOVEMENT"
    assert "FinCo does not move money" in (msg or "")


def test_intent_accuracy_on_labelled_examples(conn):
    """Test classification on all >=8 labelled examples per Phase 3 intent type."""
    _setup_intent_entities(conn, "u_intent")
    cfg = load_intent_patterns()

    patterns_yaml = PROJECT_ROOT / "config" / "intent_patterns.yaml"
    data = yaml.safe_load(patterns_yaml.read_text(encoding="utf-8"))
    labelled = data.get("labelled_examples", {})

    expected_types = [
        "goal_progress",
        "commitment_check",
        "calendar_lookahead",
        "bucket_status",
        "investment_readiness",
        "contribution_check",
        "tradeoff_compare",
        "affordability",
        "trip_planning",
        "memory_query",
    ]

    for intent_name in expected_types:
        examples = labelled.get(intent_name, [])
        assert len(examples) >= 8, f"Intent {intent_name} has fewer than 8 labelled examples"

        for query in examples:
            entities = resolve_entities(query, conn, "u_intent")
            period_info = parse_period(query, reference_date=datetime(2026, 10, 15))
            amount_paise = parse_amount_paise(query)

            classified = classify_intent(query, entities, period_info, amount_paise, cfg)
            assert classified.type == intent_name, (
                f"Query '{query}' classified as {classified.type}, expected {intent_name}"
            )


def test_tool_minimality_per_phase3_intent():
    """Verify deterministic plans select the minimal tool/skill set for each Phase 3 intent."""
    planner = DeterministicPlanner()

    cases = [
        ("affordability", ["affordability_check"]),
        ("trip_planning", ["trip_planning"]),
        ("contribution_check", ["contribution_review"]),
        ("goal_progress", ["get_goal_progress"]),
        ("commitment_check", ["check_commitment_coverage"]),
        ("calendar_lookahead", ["get_calendar"]),
        ("bucket_status", ["get_bucket_status", "get_allocation_summary"]),
        ("investment_readiness", ["assess_investment_readiness"]),
        ("tradeoff_compare", ["compare_tradeoffs"]),
        ("memory_query", ["list_memories"]),
    ]

    for intent_type, expected_tools in cases:
        intent = Intent(
            type=intent_type, period="2026-10", amount_paise=3000000, goal_id="g_vacation"
        )
        plan = planner.propose(
            task_id="t_mini",
            user_id="u_mini",
            intent=intent,
            state_projection={"clock": "2026-10-15T12:00:00Z"},
        )
        planned_tools = [s.tool_name for s in plan.steps]
        assert planned_tools == expected_tools, (
            f"Intent {intent_type} planned {planned_tools}, expected {expected_tools}"
        )


def test_adversarial_plans_with_write_tools_rejected_and_audited(conn):
    """Adversarial plans proposing Phase 3 write tools are rejected and audited."""
    _setup_intent_entities(conn, "u_adv")
    validator = PlanValidator()
    intent = Intent(type="bucket_status", period="2026-10")

    # Propose plan selecting write tools
    adversarial_plan = Plan(
        task_id="t_adv",
        steps=[
            PlanStep(
                id="s1",
                task_id="t_adv",
                user_id="u_adv",
                seq=0,
                tool_name="allocate_to_bucket",
                args={"bucket_id": "b1", "amount_paise": 100000},
                rationale="Inject write tool",
                proposed_by="llm",
                status="proposed",
            )
        ],
    )

    is_valid, reasons = validator.validate_plan(
        conn=conn,
        user_id="u_adv",
        plan=adversarial_plan,
        intent=intent,
        audit_on_rejection=True,
    )

    assert not is_valid
    assert any("not planner-selectable" in r for r in reasons)

    # Check audit log
    audit_row = conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE user_id = ? AND event_type = 'plan_rejected'",
        ("u_adv",),
    ).fetchone()
    assert audit_row is not None
    assert "allocate_to_bucket" in audit_row[1]
