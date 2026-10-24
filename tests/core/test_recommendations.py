"""
Tests for Explainable Recommendations & Narration Validation (PLAN_PHASE2 Section 5.8 & Stage 2.6).

Verifies:
- Number grounding across findings, investigations, simulations, and goals
- Rejection of invented numbers and wrong percentages
- Causal-claim rule (claims require explained outcome with >= medium confidence)
- Consequence rule (spend_decision, reduce_spend, contribution_change require simulation_id)
- Forbidden content rejection (investments, moving money, guarantees)
- Safe fallback template on validation failure
- Full explanation rendering for `copilot explain <id>`
- Strict user isolation in existing-memory lookup
"""

from copilot.core.advice import AdviceDraft, validate_advice
from copilot.core.recommendations import (
    build_recommendation,
    find_relevant_memories,
    format_recommendation_explanation,
)
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_recommendation, insert_user
from copilot.models.agentic import CalcStep, Recommendation
from copilot.models.domain import User
from copilot.models.findings import Finding, FindingNumber


class DummyInvestigation:
    def __init__(self, outcome="explained", confidence="medium", unexplained_paise=0):
        self.outcome = outcome
        self.confidence = confidence
        self.decomposition = {
            "volume_paise": 2000_00,
            "ticket_paise": 3000_00,
            "new_merchant_paise": 0,
            "stopped_merchant_paise": 0,
            "residual_paise": 0,
            "delta_spend_paise": 5000_00,
            "unexplained_paise": unexplained_paise,
        }
        self.evidence = []


class DummySimulation:
    def __init__(self, sim_id="sim_123"):
        self.id = sim_id
        self.scenario = {"amount_paise": 15000_00, "months": 6}
        self.projection = {
            "monthly_projections": [
                {"spend_expected_paise": 25000_00, "surplus_expected_paise": 10000_00}
            ]
        }


class DummyGoal:
    def __init__(self, goal_id="g_car"):
        self.id = goal_id
        self.target_paise = 500000_00
        self.current_paise = 200000_00
        self.required_monthly_paise = 25000_00
        self.months_remaining = 12


def test_validator_accepts_grounded_numbers():
    """Numbers matching cited findings and investigations pass validation."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="Dining",
            description="Dining spend jump",
            numbers=[
                FindingNumber(label="spend", value=5000_00, unit="paise"),
                FindingNumber(label="pct", value=25, unit="percent"),
            ],
        )
    }

    # ₹5,000 and 25% match finding exactly
    draft = AdviceDraft(
        text="Your Dining spend was ₹5,000, which is 25% of your total budget.",
        finding_ids=["f1"],
    )
    res = validate_advice(draft, findings)
    assert res.ok


def test_validator_rejects_invented_number_and_wrong_percentage():
    """Uncited amounts and hallucinated percentages are rejected."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="Dining",
            description="Dining spend jump",
            numbers=[
                FindingNumber(label="spend", value=5000_00, unit="paise"),
                FindingNumber(label="pct", value=25, unit="percent"),
            ],
        )
    }

    # ₹8,000 is not in findings
    draft_bad_num = AdviceDraft(
        text="Your Dining spend was ₹8,000 this month.",
        finding_ids=["f1"],
    )
    v1 = validate_advice(draft_bad_num, findings)
    assert not v1.ok
    assert any("not in the cited findings" in msg for msg in v1.violations)

    # 40% is not in findings
    draft_bad_pct = AdviceDraft(
        text="Dining represented 40% of your total budget.",
        finding_ids=["f1"],
    )
    v2 = validate_advice(draft_bad_pct, findings)
    assert not v2.ok
    assert any("not in the cited findings" in msg for msg in v2.violations)


def test_causal_claim_rule():
    """Causal claims require an investigation with explained outcome and >= medium confidence."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="anomaly",
            period="2026-10",
            subject="Dining",
            description="Spend jump",
            numbers=[FindingNumber(label="spend", value=5000_00, unit="paise")],
        )
    }

    # 1. Causal claim without investigation -> REJECTED
    draft_no_inv = AdviceDraft(
        text="Dining spend jumped because of weekend dining out.",
        finding_ids=["f1"],
    )
    v1 = validate_advice(draft_no_inv, findings)
    assert not v1.ok
    assert any("causal claim" in msg for msg in v1.violations)

    # 2. Causal claim with inconclusive investigation -> REJECTED
    inv_inconclusive = {"inv_1": DummyInvestigation(outcome="inconclusive", confidence="low")}
    v2 = validate_advice(
        draft_no_inv,
        findings,
        investigations_by_id=inv_inconclusive,
        investigation_id="inv_1",
    )
    assert not v2.ok
    assert any("causal claim" in msg for msg in v2.violations)

    # 3. Causal claim with low confidence -> REJECTED
    inv_low = {"inv_1": DummyInvestigation(outcome="explained", confidence="low")}
    v3 = validate_advice(
        draft_no_inv,
        findings,
        investigations_by_id=inv_low,
        investigation_id="inv_1",
    )
    assert not v3.ok
    assert any("causal claim" in msg for msg in v3.violations)

    # 4. Causal claim with explained outcome and medium/high confidence -> ACCEPTED
    inv_explained = {"inv_1": DummyInvestigation(outcome="explained", confidence="medium")}
    v4 = validate_advice(
        draft_no_inv,
        findings,
        investigations_by_id=inv_explained,
        investigation_id="inv_1",
    )
    assert v4.ok


def test_consequence_rule():
    """Consequential recommendations require a valid simulation_id."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="Laptop",
            description="Large purchase decision",
            numbers=[FindingNumber(label="cost", value=15000_00, unit="paise")],
        )
    }

    # 1. Consequential recommendation without simulation_id -> REJECTED
    draft_conseq = AdviceDraft(
        text="Purchasing the laptop will affect your monthly cashflow.",
        finding_ids=["f1"],
    )
    v1 = validate_advice(
        draft_conseq,
        findings,
        recommendation_kind="spend_decision",
        simulation_id=None,
    )
    assert not v1.ok
    assert any("requires a simulation_id" in msg for msg in v1.violations)

    # 2. With simulation_id not in simulations_by_id -> REJECTED
    v2 = validate_advice(
        draft_conseq,
        findings,
        recommendation_kind="spend_decision",
        simulation_id="sim_missing",
        simulations_by_id={"sim_123": DummySimulation("sim_123")},
    )
    assert not v2.ok
    assert any("unknown simulation id" in msg for msg in v2.violations)

    # 3. With valid simulation_id -> ACCEPTED
    v3 = validate_advice(
        draft_conseq,
        findings,
        recommendation_kind="spend_decision",
        simulation_id="sim_123",
        simulations_by_id={"sim_123": DummySimulation("sim_123")},
    )
    assert v3.ok


def test_forbidden_content_rejection():
    """Named investment products, payment instructions, and guarantees are rejected."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="General",
            description="Overview",
            numbers=[FindingNumber(label="amount", value=10000_00, unit="paise")],
        )
    }

    # Investment recommendation forbidden
    v_inv = validate_advice(
        AdviceDraft(
            text="You should buy mutual funds with your extra ₹10,000.", finding_ids=["f1"]
        ),
        findings,
    )
    assert not v_inv.ok
    assert any("names or recommends an investment product" in msg for msg in v_inv.violations)

    # Moving money instructions forbidden
    v_pay = validate_advice(
        AdviceDraft(text="Please transfer ₹10,000 to your savings account.", finding_ids=["f1"]),
        findings,
    )
    assert not v_pay.ok
    assert any("instructs moving or paying money" in msg for msg in v_pay.violations)

    # Guarantees forbidden
    v_guar = validate_advice(
        AdviceDraft(
            text="This approach is completely risk-free and guarantees results.", finding_ids=["f1"]
        ),
        findings,
    )
    assert not v_guar.ok
    assert any("makes a guarantee" in msg for msg in v_guar.violations)


def test_build_recommendation_applies_fallback_on_failure():
    """When LLM text fails validation, build_recommendation applies safe template fallback."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="Dining",
            description="Spend",
            numbers=[FindingNumber(label="spend", value=5000_00, unit="paise")],
        )
    }

    # Halucinated text with unverified causal claim and missing simulation
    rec = build_recommendation(
        user_id="u_alice",
        origin="investigation",
        text="Your spend jumped to ₹99,999 because of hidden fees.",
        evidence=["f1"],
        recommendation_kind="spend_decision",
        findings_by_id=findings,
    )

    # Text was replaced by deterministic safe fallback
    assert "₹99,999" not in rec.text
    assert any("Fallback template applied" in a for a in rec.assumptions)
    assert rec.status == "draft"


def test_format_recommendation_explanation():
    """Full explanation exposes all 8 required sections."""
    rec = Recommendation(
        id="rec_456",
        user_id="u_alice",
        origin="goal",
        text="Saving ₹7,000 monthly keeps your Emergency Fund goal on track.",
        evidence=["f_goal_1"],
        calculations=[
            CalcStep(
                label="Required Monthly Saving",
                formula_id="ceil_shortfall_div_months",
                inputs={"target_paise": 100000_00, "current_paise": 30000_00, "months": 10},
                result="₹7,000",
            )
        ],
        assumptions=["Income remains stable", "Discretionary spending paced"],
        tools_used=[{"tool": "evaluate_goal_impact", "status": "done"}],
        memories=[{"kind": "past_advice_decision", "summary": "Approved emergency fund plan"}],
        confidence_label="high",
        simulation_id="sim_789",
        status="draft",
        created_at=to_utc_iso(now_utc()),
    )

    formatted = format_recommendation_explanation(rec)
    assert "RECOMMENDATION: rec_456" in formatted
    assert "Origin: goal" in formatted
    assert "Evidence Cited:" in formatted
    assert "Calculations Performed:" in formatted
    assert "ceil_shortfall_div_months" in formatted
    assert "Assumptions:" in formatted
    assert "Tools Used in Generation:" in formatted
    assert "User Memories / Past Decisions Relied On:" in formatted
    assert "Linked Simulation Scenario: sim_789" in formatted


def test_existing_memories_strict_user_isolation():
    """User Alice cannot see or leak Bob's past decisions or preferences."""
    conn = get_connection(":memory:")
    init_db(conn)

    insert_user(conn, User(id="u_alice", created_at="2026-01-01T00:00:00Z"))
    insert_user(conn, User(id="u_bob", created_at="2026-01-01T00:00:00Z"))

    # Alice approved an advice item
    rec_alice = Recommendation(
        id="rec_alice_1",
        user_id="u_alice",
        origin="alert",
        text="Alice advice text",
        status="approved",
        created_at="2026-02-01T00:00:00Z",
    )
    insert_recommendation(conn, rec_alice)

    # Bob rejected an advice item
    rec_bob = Recommendation(
        id="rec_bob_1",
        user_id="u_bob",
        origin="goal",
        text="Bob private financial plan",
        status="rejected",
        created_at="2026-02-01T00:00:00Z",
    )
    insert_recommendation(conn, rec_bob)

    # Alice queries memories -> sees only her own
    alice_mems = find_relevant_memories(conn, "u_alice")
    assert len(alice_mems) == 1
    assert alice_mems[0]["id"] == "rec_alice_1"
    assert "Alice" in alice_mems[0]["summary"]
    assert "Bob" not in str(alice_mems)

    # Bob queries memories -> sees only his own
    bob_mems = find_relevant_memories(conn, "u_bob")
    assert len(bob_mems) == 1
    assert bob_mems[0]["id"] == "rec_bob_1"
    assert "Bob" in bob_mems[0]["summary"]
    assert "Alice" not in str(bob_mems)


def test_validator_rejects_unknown_id():
    """Validator rejects unknown finding ID cited in draft."""
    findings = {
        "f1": Finding(
            id="f1",
            kind="category_spend",
            period="2026-10",
            subject="Dining",
            description="Spend",
            numbers=[FindingNumber(label="spend", value=5000_00, unit="paise")],
        )
    }
    draft = AdviceDraft(
        text="Your spend was ₹5,000.",
        finding_ids=["f1", "f_unknown_999"],
    )
    res = validate_advice(draft, findings)
    assert not res.ok
    assert any("unknown finding id" in v for v in res.violations)
    assert "f_unknown_999" in str(res.violations)


def test_approval_triggers_no_action():
    """Approval of a recommendation changes only its status and triggers no financial actions/mutations."""
    from pathlib import Path

    from copilot.db.repo import insert_account
    from copilot.governance.policy import load_policy
    from copilot.models.domain import Account
    from copilot.tools.executor import ExecutionContext, execute_tool

    policy = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")
    conn = get_connection(":memory:")
    init_db(conn)

    insert_user(conn, User(id="u_alice", created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id="acc_1",
            user_id="u_alice",
            name="Checking",
            opening_balance_paise=50000_00,
            created_at="2026-01-01T00:00:00Z",
        ),
    )

    rec = Recommendation(
        id="rec_test_1",
        user_id="u_alice",
        origin="goal",
        text="Keep monthly dining spend under ₹5,000 to meet your goal.",
        status="draft",
        created_at="2026-02-01T00:00:00Z",
    )
    insert_recommendation(conn, rec)

    from copilot.tools.financial import register_financial_tools
    from copilot.tools.registry import get as get_tool

    if not get_tool("decide_advice"):
        register_financial_tools()

    # Snapshot financial tables before approval
    snap_acc_before = conn.execute("SELECT * FROM accounts").fetchall()
    snap_tx_before = conn.execute("SELECT * FROM transactions").fetchall()

    ctx = ExecutionContext(
        conn=conn,
        user_id="u_alice",
        actor="user",
        run_id="run_approve_test",
        clock=now_utc(),
        policy=policy,
    )

    # Approve recommendation through execute_tool
    res = execute_tool(
        ctx,
        "decide_advice",
        {"advice_id": "rec_test_1", "decision": "approved"},
    )

    assert res.ok
    assert res.data.status == "approved"

    # Verify recommendation row updated
    row = conn.execute(
        "SELECT status, decided_by FROM advice_items WHERE id = 'rec_test_1'"
    ).fetchone()
    assert row[0] == "approved"
    assert row[1] == "user"

    # Financial state invariant: absolutely no mutations to financial accounts or transactions
    snap_acc_after = conn.execute("SELECT * FROM accounts").fetchall()
    snap_tx_after = conn.execute("SELECT * FROM transactions").fetchall()
    assert snap_acc_after == snap_acc_before
    assert snap_tx_after == snap_tx_before
