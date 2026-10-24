"""
Tests for Core Input Gate and Intent Understanding (PLAN_PHASE2 Section 5.2 & Stage 2.7).

Verifies:
1. Amount parser tables (commas, k, lakh, crore, paise conversion, invalid inputs).
2. Period parser tables (month rollover, IST boundaries, relative/explicit/multi-month).
3. Entity resolution (categories, goals, merchants, zero-hallucination guarantee).
4. Deterministic intent classifier across 40+ labelled queries with accuracy tracking.
5. Input gate refusal classes trigger on malicious/out-of-scope queries and allow benign queries.
6. Safety Rule 4: LLM-proposed refusal added; LLM allow cannot remove deterministic refusal.
7. Hallucinated entity returned by LLM is dropped.
8. Single-round clarification generation with user data options.
9. Redaction of UPI IDs, account numbers, and phone numbers before LLM calls.
10. Raw text never appears in logs or audit events.
11. Works with LLM completely off.
"""

import logging
from datetime import UTC, datetime

import pytest

from copilot.core.intent import (
    check_input_gate,
    classify_intent,
    create_agent_task,
    llm_classify_intent,
    parse_amount_paise,
    parse_period,
    resolve_entities,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_category, insert_goal, insert_user
from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import Goal
from copilot.models.domain import Category, User

# ---------------------------------------------------------------------------------------------
# Test Fixtures & Setup
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at="2026-01-01T00:00:00Z"))
    insert_category(
        c, Category(id="cat_dining", user_id="u1", name="Dining", created_at="2026-01-01T00:00:00Z")
    )
    insert_category(
        c,
        Category(
            id="cat_groceries", user_id="u1", name="Groceries", created_at="2026-01-01T00:00:00Z"
        ),
    )
    insert_category(
        c,
        Category(
            id="cat_shopping", user_id="u1", name="Shopping", created_at="2026-01-01T00:00:00Z"
        ),
    )
    insert_category(
        c, Category(id="cat_travel", user_id="u1", name="Travel", created_at="2026-01-01T00:00:00Z")
    )

    insert_goal(
        c,
        Goal(
            id="g_car",
            user_id="u1",
            name="Car",
            kind="savings",
            target_paise=500000_00,
            current_paise=100000_00,
            priority=1,
            status="active",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )
    insert_goal(
        c,
        Goal(
            id="g_emergency",
            user_id="u1",
            name="Emergency Fund",
            kind="emergency_fund",
            target_paise=300000_00,
            current_paise=150000_00,
            priority=2,
            status="active",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )
    return c


# ---------------------------------------------------------------------------------------------
# 1. Amount Parser Tests
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_paise",
    [
        ("20k", 20000_00),
        ("20K", 20000_00),
        ("5.5k", 5500_00),
        ("2 lakh", 200000_00),
        ("2.5 lakh", 250000_00),
        ("2 lac", 200000_00),
        ("2 lakhs", 200000_00),
        ("1 crore", 10000000_00),
        ("1.5 cr", 15000000_00),
        ("Rs. 1,25,000", 125000_00),
        ("₹1,25,000", 125000_00),
        ("INR 50,000", 50000_00),
        ("5000 rupees", 5000_00),
        ("Rs 500.50", 500_50),
        ("₹ 75", 75_00),
        ("buy a laptop for 45000", 45000_00),
        ("spend 12000 on camera", 12000_00),
        ("cut dining by 3500", 3500_00),
        ("what is the weather in Delhi", None),
        ("in 2026", None),
    ],
)
def test_parse_amount_paise(text, expected_paise):
    assert parse_amount_paise(text) == expected_paise


# ---------------------------------------------------------------------------------------------
# 2. Period Parser Tests (Month Rollover, IST Boundaries, Horizons)
# ---------------------------------------------------------------------------------------------


def test_parse_period_relative_and_rollover():
    # 1. Standard reference date mid-year: Oct 14, 2026
    ref_oct = datetime(2026, 10, 14, 12, 0, tzinfo=IST)
    assert parse_period("this month", ref_oct) == ("2026-10", 2026, 10, None)
    assert parse_period("last month", ref_oct) == ("2026-09", 2026, 9, None)
    assert parse_period("next month", ref_oct) == ("2026-11", 2026, 11, None)

    # 2. Year rollover backward: January 15, 2026 -> last month is Dec 2025
    ref_jan = datetime(2026, 1, 15, 10, 0, tzinfo=IST)
    assert parse_period("last month", ref_jan) == ("2025-12", 2025, 12, None)

    # 3. Year rollover forward: December 20, 2026 -> next month is Jan 2027
    ref_dec = datetime(2026, 12, 20, 15, 0, tzinfo=IST)
    assert parse_period("next month", ref_dec) == ("2027-01", 2027, 1, None)


def test_parse_period_ist_boundaries():
    """
    UTC 2026-09-30T18:30:00Z in UTC is September 30, but in Asia/Kolkata
    it is 2026-10-01T00:00:00+05:30 (midnight, October 1).
    Therefore, 'this month' must be 2026-10.
    """
    utc_dt = datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert parse_period("this month", utc_dt) == ("2026-10", 2026, 10, None)


def test_parse_period_explicit_and_horizons():
    ref = datetime(2026, 10, 14, tzinfo=IST)
    assert parse_period("October 2026", ref) == ("2026-10", 2026, 10, None)
    assert parse_period("in January", ref) == ("2026-01", 2026, 1, None)
    assert parse_period("2026-08", ref) == ("2026-08", 2026, 8, None)
    assert parse_period("last 3 months", ref) == ("last_3_months", None, None, 3)
    assert parse_period("next 6 months", ref) == (None, None, None, 6)
    assert parse_period("this week", ref) == ("this_week", None, None, None)
    assert parse_period("random query", ref) == (None, None, None, None)


# ---------------------------------------------------------------------------------------------
# 3. Entity Resolution Tests (Zero Hallucination)
# ---------------------------------------------------------------------------------------------


def test_resolve_entities(conn):
    # Category matches by direct name or synonym
    e1 = resolve_entities("Why did my dining spend jump?", conn, "u1")
    assert e1["category_id"] == "cat_dining"

    e2 = resolve_entities("How much did I spend on food and restaurants?", conn, "u1")
    assert e2["category_id"] == "cat_dining"

    e3 = resolve_entities("Groceries budget status", conn, "u1")
    assert e3["category_id"] == "cat_groceries"

    # Goal matches
    e4 = resolve_entities("Am I on track for my Car goal?", conn, "u1")
    assert e4["goal_id"] == "g_car"

    e5 = resolve_entities("Status of my Emergency Fund", conn, "u1")
    assert e5["goal_id"] == "g_emergency"

    # Unknown entity returns None (never guessed)
    e6 = resolve_entities("What if I buy a yacht in Crypto?", conn, "u1")
    assert e6["category_id"] is None
    assert e6["goal_id"] is None


# ---------------------------------------------------------------------------------------------
# 4. 40+ Labelled Queries Intent Classifier Accuracy Test
# ---------------------------------------------------------------------------------------------

LABELLED_INTENT_QUERIES = [
    # summarize_period (4)
    ("Give me a summary of my expenses for this month", "summarize_period"),
    ("How much did I spend in October 2026?", "summarize_period"),
    ("Spending overview for last month", "summarize_period"),
    ("Total spend in September", "summarize_period"),
    # explain_change (4)
    ("Why did my Dining spend jump this month?", "explain_change"),
    ("Why has food spend increased compared to last month?", "explain_change"),
    ("Explain the spend spike in Groceries", "explain_change"),
    ("Why did my shopping expenses increase?", "explain_change"),
    # investigate_anomaly (4)
    ("Investigate unusual spending in Dining", "investigate_anomaly"),
    ("Why is there a weird charge in my account?", "investigate_anomaly"),
    ("Check suspicious transaction in Travel", "investigate_anomaly"),
    ("Any irregular activity this month?", "investigate_anomaly"),
    # check_budget (4)
    ("Am I over budget on Groceries?", "check_budget"),
    ("Check my budget status for this month", "check_budget"),
    ("Have I exceeded my Dining limit?", "check_budget"),
    ("Show my budget limits", "check_budget"),
    # forecast (4)
    ("What is my spend forecast for this month?", "forecast"),
    ("Project my expenses to month end", "forecast"),
    ("What is my current run rate?", "forecast"),
    ("How much will I spend by the end of October?", "forecast"),
    # whatif_add_spend (4)
    ("What if I buy a laptop for ₹60,000?", "whatif_add_spend"),
    ("Can I afford a new phone for 30k?", "whatif_add_spend"),
    ("If I purchase a bike for 1.5 lakh", "whatif_add_spend"),
    ("What if I spend ₹5,000 on shoes?", "whatif_add_spend"),
    # whatif_reduce_spend (4)
    ("What if I cut dining spend by ₹3,000?", "whatif_reduce_spend"),
    ("What if I reduce food expenses by 2k?", "whatif_reduce_spend"),
    ("If I stop spending on entertainment", "whatif_reduce_spend"),
    ("How much will I save if I cut shopping by 5k?", "whatif_reduce_spend"),
    # goal_check (4)
    ("Am I on track for my Car goal?", "goal_check"),
    ("Check my Emergency Fund target", "goal_check"),
    ("How is my Vacation goal progressing?", "goal_check"),
    ("Savings target status for Laptop", "goal_check"),
    # list_recurring (4)
    ("List all my recurring subscriptions", "list_recurring"),
    ("What recurring bills do I have?", "list_recurring"),
    ("Show my active memberships", "list_recurring"),
    ("List my monthly recurring charges", "list_recurring"),
    # alerts_overview (4)
    ("Show all my alerts", "alerts_overview"),
    ("Are there any warnings or notifications?", "alerts_overview"),
    ("Any issues with my spending this month?", "alerts_overview"),
    ("Check active alerts", "alerts_overview"),
    # unknown (2)
    ("Tell me something interesting about life", "unknown"),
    ("Hello there copilot", "unknown"),
]


def test_labelled_queries_deterministic_accuracy(conn):
    """Verify at least 40 labelled queries achieve 100% classification accuracy."""
    assert len(LABELLED_INTENT_QUERIES) >= 40
    correct = 0
    total = len(LABELLED_INTENT_QUERIES)

    for query, expected_type in LABELLED_INTENT_QUERIES:
        entities = resolve_entities(query, conn, "u1")
        period_info = parse_period(query)
        amt = parse_amount_paise(query)
        intent = classify_intent(query, entities, period_info, amt)
        if intent.type == expected_type:
            correct += 1
        else:
            print(f"FAILED: '{query}' -> got '{intent.type}', expected '{expected_type}'")

    accuracy = correct / total
    assert accuracy == 1.0, f"Expected 100% accuracy, got {accuracy * 100:.1f}% ({correct}/{total})"


# ---------------------------------------------------------------------------------------------
# 5. Input Gate Refusal vs Benign Look-Alike Tests
# ---------------------------------------------------------------------------------------------


def test_input_gate_refuses_malicious_and_allows_benign():
    # 1. INVESTMENT_ADVICE: Refuse vs Allow
    refused_inv = [
        "Which stock should I buy for quick gains?",
        "Recommend top mutual funds for my portfolio",
        "Should I invest in Bitcoin or Ethereum?",
        "What are the best stocks to buy right now?",
    ]
    for q in refused_inv:
        is_ref, ref_cls, _ = check_input_gate(q)
        assert is_ref, f"Expected refusal for '{q}'"
        assert ref_cls == "INVESTMENT_ADVICE"

    allowed_inv_lookalike = [
        "How much did I spend on gold jewelry in October?",
        "Check my grocery budget limit",
    ]
    for q in allowed_inv_lookalike:
        is_ref, _, _ = check_input_gate(q)
        assert not is_ref, f"Expected allow for look-alike '{q}'"

    # 2. MONEY_MOVEMENT: Refuse vs Allow
    refused_mm = [
        "Transfer ₹5,000 to Rahul immediately",
        "Send 1000 rupees to mom via UPI",
        "Pay my electricity bill now",
        "Wire money to account 9876543210",
    ]
    for q in refused_mm:
        is_ref, ref_cls, _ = check_input_gate(q)
        assert is_ref, f"Expected refusal for '{q}'"
        assert ref_cls == "MONEY_MOVEMENT"

    allowed_mm_lookalike = [
        "How much did I transfer to savings last month?",
        "Did I pay my electricity bill in September?",
        "Show all transfers between accounts",
        "List my past payments to landlords",
    ]
    for q in allowed_mm_lookalike:
        is_ref, _, _ = check_input_gate(q)
        assert not is_ref, f"Expected allow for look-alike '{q}'"

    # 3. MARKET_PREDICTION: Refuse vs Allow
    refused_mp = [
        "Will Nifty cross 26,000 this week?",
        "Predict Bitcoin price for next month",
        "Will the stock market crash tomorrow?",
    ]
    for q in refused_mp:
        is_ref, ref_cls, _ = check_input_gate(q)
        assert is_ref, f"Expected refusal for '{q}'"
        assert ref_cls == "MARKET_PREDICTION"

    # 4. SENSITIVE_DATA_SUBMISSION: Refuse
    refused_sens = [
        "My OTP is 482910, please verify",
        "Here is my debit card 4111-2222-3333-4444 and CVV 789",
        "My netbanking password is secretPassword123",
    ]
    for q in refused_sens:
        is_ref, ref_cls, _ = check_input_gate(q)
        assert is_ref, f"Expected refusal for '{q}'"
        assert ref_cls == "SENSITIVE_DATA_SUBMISSION"

    # 5. OUT_OF_SCOPE: Refuse
    refused_oos = [
        "What is the weather in Bangalore today?",
        "Give me a recipe for paneer butter masala",
        "Tell me a joke about robots",
    ]
    for q in refused_oos:
        is_ref, ref_cls, _ = check_input_gate(q)
        assert is_ref, f"Expected refusal for '{q}'"
        assert ref_cls == "OUT_OF_SCOPE"


# ---------------------------------------------------------------------------------------------
# 6. Safety Rule 4: LLM Refusal Added; LLM Cannot Remove Deterministic Refusal
# ---------------------------------------------------------------------------------------------


def test_safety_rule_4_llm_cannot_remove_deterministic_refusal(conn):
    """
    If the deterministic input gate triggers a refusal (e.g. MONEY_MOVEMENT),
    even an LLM returning an 'allowed' intent cannot override the refusal.
    """
    fake_llm = FakeLLMClient(
        [
            '{"intent_type": "summarize_period", "refusal_class": null, "category_name": null, "goal_name": null, "amount_inr": null, "period": "2026-10"}'
        ]
    )
    raw_query = "Transfer ₹5,000 to Rahul"

    task = create_agent_task(conn, "u1", raw_query, llm_client=fake_llm)
    assert task.status == "refused"
    assert "initiate payments" in task.intent.clarification
    assert len(fake_llm.prompts) == 0  # Planner / LLM never called on deterministic refusal


def test_safety_rule_4_llm_proposed_refusal_is_added(conn):
    """
    If a query slips past the deterministic gate as unknown, but the LLM identifies
    a subtle investment or out-of-scope advice, the refusal is added and audited.
    """
    fake_llm = FakeLLMClient(
        [
            '{"intent_type": "unknown", "refusal_class": "INVESTMENT_ADVICE", "category_name": null, "goal_name": null, "amount_inr": null, "period": null}'
        ]
    )
    subtle_query = "Could you suggest an optimal alpha-generating allocation?"

    task = create_agent_task(conn, "u1", subtle_query, llm_client=fake_llm)
    assert task.status == "refused"
    assert "investment advice" in task.intent.clarification

    # Verify audit event recorded
    audit = conn.execute(
        "SELECT event_type, after_json FROM audit_events WHERE entity_id = ?",
        (task.id,),
    ).fetchone()
    assert audit[0] == "input_refused"
    assert "INVESTMENT_ADVICE" in audit[1]


# ---------------------------------------------------------------------------------------------
# 7. Hallucinated Entity Dropped
# ---------------------------------------------------------------------------------------------


def test_hallucinated_entity_is_dropped():
    user_cats = {"Dining": "cat_dining", "Groceries": "cat_groceries"}
    user_goals = {"Car": "g_car"}

    # LLM hallucinates 'Cryptocurrency' category and 'Yacht' goal
    fake_llm = FakeLLMClient(
        [
            '{"intent_type": "forecast", "refusal_class": null, "category_name": "Cryptocurrency", "goal_name": "Yacht", "amount_inr": 5000.0, "period": "2026-10"}'
        ]
    )

    intent, _ = llm_classify_intent(fake_llm, "project my crypto spend", user_cats, user_goals)
    assert intent is not None
    assert intent.type == "forecast"
    # Both hallucinated entities must be dropped to None
    assert intent.category_id is None
    assert intent.goal_id is None
    assert intent.amount_paise == 5000_00


# ---------------------------------------------------------------------------------------------
# 8. Clarification Flow (Single Round)
# ---------------------------------------------------------------------------------------------


def test_clarification_generation_and_task_status(conn):
    # Explain change without category produces a clarification listing user categories
    task = create_agent_task(conn, "u1", "Why did my spend jump this month?")
    assert task.status == "needs_clarification"
    assert task.intent.clarification is not None
    assert "Which category would you like me to explain?" in task.intent.clarification
    assert "Dining" in task.intent.clarification
    assert "Groceries" in task.intent.clarification

    # What-if purchase without amount produces clarification asking for amount
    task_amt = create_agent_task(conn, "u1", "What if I buy a new phone?")
    assert task_amt.status == "needs_clarification"
    assert "How much are you planning to spend" in task_amt.intent.clarification


# ---------------------------------------------------------------------------------------------
# 9. PII Redaction Asserted on Captured Prompts
# ---------------------------------------------------------------------------------------------


def test_redaction_on_captured_prompts(conn):
    fake_llm = FakeLLMClient(
        [
            '{"intent_type": "unknown", "refusal_class": null, "category_name": null, "goal_name": null, "amount_inr": null, "period": null}'
        ]
    )
    query_with_pii = "Check account 123456789012 for user alice@okaxis with phone 9876543210"

    create_agent_task(conn, "u1", query_with_pii, llm_client=fake_llm)
    assert len(fake_llm.prompts) == 1
    prompt = fake_llm.prompts[0]

    # Sensitive data must be redacted in prompt
    assert "123456789012" not in prompt
    assert "[ACCOUNT]" in prompt
    assert "alice@okaxis" not in prompt
    assert "[UPI]" in prompt
    assert "9876543210" not in prompt
    assert "[PHONE]" in prompt


# ---------------------------------------------------------------------------------------------
# 10. Raw Text Never Appears in Logs or Audit Events
# ---------------------------------------------------------------------------------------------


def test_raw_text_never_appears_in_logs_or_audit(conn, caplog):
    caplog.set_level(logging.DEBUG)
    secret_text = "secret_pin_987654_raw_secret_data"
    query = f"Check spend overview for {secret_text}"

    task = create_agent_task(conn, "u1", query)

    # 1. Assert raw secret text does not appear in python logging output
    for record in caplog.records:
        assert secret_text not in record.message

    # 2. Assert raw secret text does not appear in audit_events payload JSON
    events = conn.execute(
        "SELECT event_type, before_json, after_json FROM audit_events WHERE entity_id = ?",
        (task.id,),
    ).fetchall()
    for ev in events:
        assert secret_text not in (ev[1] or "")
        assert secret_text not in (ev[2] or "")


# ---------------------------------------------------------------------------------------------
# 11. Works With LLM Completely Off
# ---------------------------------------------------------------------------------------------


def test_works_with_llm_completely_off(conn):
    """The entire pipeline functions deterministically when no LLM client is supplied."""
    task = create_agent_task(
        conn,
        "u1",
        "What if I buy a laptop for ₹60,000?",
        llm_client=None,
    )
    assert task.status == "understood"
    assert task.intent.type == "whatif_add_spend"
    assert task.intent.amount_paise == 60000_00
    assert task.intent.source == "deterministic"
    assert task.planner_mode == "deterministic"
