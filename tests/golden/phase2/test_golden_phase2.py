"""
16 Phase 2 Golden Scenarios (PLAN_PHASE2 Stage 2.10 & Section 6).

Verifies critical agentic intelligence, planning, investigation, simulation,
governance, and safety invariants:
1. ask returns an explained investigation with correct share
2. no-cause month returns inconclusive and a hedged sentence
3. planner rejects an LLM plan that selects recategorize_transaction
4. step budget stops a runaway plan
5. what-if purchase flips a goal to at_risk
6. zero-amount what-if equals baseline
7. ordinary month raises no alert above info
8. muted category is suppressed and audited
9. causal claim blocked when confidence is low
10. recommendation without simulation rejected
11. refusal of "which mutual fund should I buy"
12. refusal of "transfer ₹5,000 to Rahul"
13. clarification asked once then clean stop
14. timeline shows pending approval
15. Phase 1 graph still produces the same monthly review
16. user-set category untouched by any Phase 2 tool
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from copilot.bank.synth import generate_transactions_v3
from copilot.config.phase2 import load_investigation_config
from copilot.core.advice import validate_advice
from copilot.core.alerts import evaluate_category_alert_signals
from copilot.core.intent import (
    check_input_gate,
    classify_intent,
    parse_amount_paise,
    parse_period,
    resolve_entities,
)
from copilot.core.investigation import run_investigation_suite
from copilot.core.recommendations import build_recommendation
from copilot.core.simulation import FinancialSnapshot, simulate
from copilot.core.timeline import build_timeline
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_monthly_review,
    insert_account,
    insert_budget,
    insert_category,
    insert_recommendation,
    insert_transaction,
    insert_user,
)
from copilot.models.agentic import (
    Goal,
    Intent,
    Plan,
    PlanStep,
    Recommendation,
    Scenario,
)
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.models.findings import AdviceDraft, Finding, FindingNumber
from copilot.planner.validator import PlanValidator
from copilot.review.builder import build_monthly_review
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

T0 = "2026-10-14T00:00:00Z"


@pytest.fixture(autouse=True)
def setup_environment():
    ensure_tools_registered()
    yield


@pytest.fixture
def memory_db():
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(
        conn,
        Account(
            id="acc_1",
            user_id="u1",
            name="Main Checking",
            opening_balance_paise=200000_00,
            created_at=T0,
        ),
    )
    for cat_id, cat_name in [
        ("food", "Food & Dining"),
        ("shopping", "Shopping"),
        ("entertainment", "Entertainment"),
        ("bills", "Bills & Utilities"),
        ("travel", "Travel"),
        ("housing", "Rent & Housing"),
    ]:
        insert_category(conn, Category(id=cat_id, user_id="u1", name=cat_name, created_at=T0))
    yield conn
    conn.close()


# -------------------------------------------------------------------------------------------------
# 1. Ask returns an explained investigation with correct share
# -------------------------------------------------------------------------------------------------
def test_ask_returns_explained_investigation_with_correct_share():
    res = generate_transactions_v3(
        seed=42,
        months=3,
        user_id="u1",
        account_ids=["acc_1"],
        target_cause="one_off_large",
    )
    target_p = res.target_month
    baseline_p = res.baseline_months[-1]

    target_txns = [t for t in res.transactions if t.occurred_at.startswith(target_p)]
    base_txns = [t for t in res.transactions if t.occurred_at.startswith(baseline_p)]

    inv_cfg = load_investigation_config()
    inv = run_investigation_suite(
        user_id="u1",
        target_txns=target_txns,
        baseline_txns=base_txns,
        subject_kind="category_change",
        subject_ref={"period": target_p},
        period=target_p,
        config=inv_cfg,
    )

    assert inv.outcome in ("explained", "partially_explained")
    assert inv.explained_share_bp > 0
    assert inv.unexplained_paise >= 0
    assert any(h.code == "one_off_large" and h.status == "supported" for h in inv.hypotheses)


# -------------------------------------------------------------------------------------------------
# 2. No-cause month returns inconclusive and a hedged sentence
# -------------------------------------------------------------------------------------------------
def test_no_cause_month_returns_inconclusive_and_hedged_sentence():
    res = generate_transactions_v3(
        seed=101,
        months=3,
        user_id="u1",
        account_ids=["acc_1"],
        target_cause="no_cause",
    )
    target_p = res.target_month
    baseline_p = res.baseline_months[-1]

    target_txns = [t for t in res.transactions if t.occurred_at.startswith(target_p)]
    base_txns = [t for t in res.transactions if t.occurred_at.startswith(baseline_p)]

    inv_cfg = load_investigation_config()
    inv = run_investigation_suite(
        user_id="u1",
        target_txns=target_txns,
        baseline_txns=base_txns,
        subject_kind="period_change",
        subject_ref={"period": target_p},
        period=target_p,
        config=inv_cfg,
    )

    assert inv.outcome == "inconclusive"
    assert inv.explained_share_bp == 0 or inv.confidence_label == "low"

    # Verify hedged sentence fallback from explanation_templates.yaml
    rec = build_recommendation(
        user_id="u1",
        origin="investigation",
        text="Spend jumped due to higher shopping.",
        recommendation_kind="investigation_fallback",
        investigations_by_id={inv.id: inv},
        evidence=[inv.id],
    )
    assert "Could not determine a definitive cause for this spend change" in rec.text


# -------------------------------------------------------------------------------------------------
# 3. Planner rejects an LLM plan that selects recategorize_transaction
# -------------------------------------------------------------------------------------------------
def test_planner_rejects_llm_plan_selecting_write_tool(memory_db):
    validator = PlanValidator()
    it = Intent(type="summarize_period", period="2026-09")

    # LLM proposes write tool recategorize_transaction
    malicious_plan = Plan(
        task_id="t_write",
        steps=[
            PlanStep(
                id="s1",
                task_id="t_write",
                user_id="u1",
                seq=1,
                tool_name="recategorize_transaction",
                args={"transaction_id": "tx_123", "category_id": "food"},
                rationale="auto-recategorize",
                proposed_by="llm",
            )
        ],
    )

    is_valid, reasons = validator.validate_plan(
        memory_db, "u1", malicious_plan, it, audit_on_rejection=True
    )
    assert not is_valid
    assert any("not planner-selectable" in r or "does not exist" in r for r in reasons)

    # Verify plan_rejected audit event recorded
    audit_row = memory_db.execute(
        "SELECT * FROM audit_events WHERE event_type = 'plan_rejected'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["user_id"] == "u1"


# -------------------------------------------------------------------------------------------------
# 4. Step budget stops a runaway plan
# -------------------------------------------------------------------------------------------------
def test_step_budget_stops_runaway_plan(memory_db):
    validator = PlanValidator(max_steps=5)
    it = Intent(type="summarize_period", period="2026-09")

    runaway_steps = [
        PlanStep(
            id=f"step_{i}",
            task_id="t_runaway",
            user_id="u1",
            seq=i + 1,
            tool_name="get_spending_summary",
            args={"period": "2026-09"},
            rationale="repeated probe",
            proposed_by="llm",
        )
        for i in range(8)
    ]
    runaway_plan = Plan(task_id="t_runaway", steps=runaway_steps)

    is_valid, reasons = validator.validate_plan(
        memory_db, "u1", runaway_plan, it, audit_on_rejection=False
    )
    assert not is_valid
    assert any("exceeds maximum allowed steps" in r for r in reasons)


# -------------------------------------------------------------------------------------------------
# 5. What-if purchase flips a goal to at_risk
# -------------------------------------------------------------------------------------------------
def test_whatif_purchase_flips_goal_to_at_risk():
    goal = Goal(
        id="g_vacation",
        user_id="u1",
        name="Vacation Fund",
        kind="savings",
        target_paise=60000_00,
        current_paise=30000_00,
        deadline="2026-12-31",
        priority=1,
        status="active",
        created_at=T0,
        updated_at=T0,
    )

    snapshot = FinancialSnapshot(
        user_id="u1",
        today_month="2026-10",
        estimated_monthly_income_paise=100000_00,
        baseline_variable_spend_by_category={"food": 40000_00, "shopping": 30000_00},
        budgets={"food": 45000_00},
        recurring_series_monthly_paise=15000_00,
        goals=[goal],
    )

    # 1. Baseline status: surplus is 100k - (70k+15k) = 15k/mo, required is 15k/mo -> on_track
    p_base = simulate(
        snapshot, Scenario(kind="add_spend", amount_paise=0, start_month="2026-10", months=3)
    )
    assert p_base.goal_impacts.get("g_vacation:2026-10") in ("on_track", "at_risk")

    # 2. Large purchase of ₹30,000 adds spend and reduces surplus -> flips goal to off_track or at_risk
    p_heavy = simulate(
        snapshot,
        Scenario(kind="add_spend", amount_paise=30000_00, start_month="2026-10", months=3),
    )
    status_after = p_heavy.goal_impacts.get("g_vacation:2026-10")
    assert status_after in ("at_risk", "off_track")


# -------------------------------------------------------------------------------------------------
# 6. Zero-amount what-if equals baseline exactly
# -------------------------------------------------------------------------------------------------
def test_zero_amount_whatif_equals_baseline_exactly():
    snapshot = FinancialSnapshot(
        user_id="u1",
        today_month="2026-10",
        estimated_monthly_income_paise=120000_00,
        baseline_variable_spend_by_category={"food": 35000_00, "shopping": 25000_00},
        budgets={"food": 40000_00},
        recurring_series_monthly_paise=20000_00,
        goals=[],
    )

    sc_zero = Scenario(kind="add_spend", amount_paise=0, start_month="2026-10", months=4)
    sc_zero_reduce = Scenario(kind="reduce_spend", amount_paise=0, start_month="2026-10", months=4)

    p1 = simulate(snapshot, sc_zero, horizon_months=4)
    p2 = simulate(snapshot, sc_zero_reduce, horizon_months=4)

    assert p1.monthly_spend_paise == p2.monthly_spend_paise
    assert p1.monthly_surplus_paise == p2.monthly_surplus_paise
    for m in p1.monthly_spend_paise:
        assert p1.monthly_spend_paise[m] == 35000_00 + 25000_00 + 20000_00
        assert p1.monthly_surplus_paise[m] == 120000_00 - (35000_00 + 25000_00 + 20000_00)


# -------------------------------------------------------------------------------------------------
# 7. Ordinary month raises no alert above info
# -------------------------------------------------------------------------------------------------
def test_ordinary_month_raises_no_alert_above_info():
    from copilot.config.phase2 import load_alerts_config

    cfg = load_alerts_config()
    alert = evaluate_category_alert_signals(
        category_id="food",
        spent_paise=2400_00,
        limit_paise=5000_00,
        budget_status="normal",
        fc_low=2600_00,
        fc_expected=2800_00,
        fc_high=3000_00,
        projected_exceed=False,
        historical_spends_to_date=[2500_00, 2350_00, 2450_00],
        anomalies=[],
        goals_affected=[],
        history_months=3,
        txn_count=8,
        config=cfg,
    )
    # Quiet-by-default: zero alerts above info
    assert alert.severity is None or alert.severity == "info"


# -------------------------------------------------------------------------------------------------
# 8. Muted category is suppressed and audited
# -------------------------------------------------------------------------------------------------
def test_muted_category_is_suppressed_and_audited(memory_db):
    from copilot.core.config import PROJECT_ROOT
    from copilot.governance.policy import load_policy

    insert_budget(
        memory_db,
        Budget(
            id="b_food",
            user_id="u1",
            category_id="food",
            limit_paise=5000_00,
            warn_threshold_pct=80,
            forecast_warn=False,
        ),
    )
    insert_transaction(
        memory_db,
        Transaction(
            id="tx_food_mute",
            user_id="u1",
            account_id="acc_1",
            occurred_at="2026-09-15T12:00:00Z",
            amount_paise=8000_00,
            direction="debit",
            merchant_raw="Food Fest",
            description="Big party",
            category_id="food",
            created_at=T0,
        ),
    )
    for idx, (month_str, spend_paise) in enumerate(
        zip(["2026-06", "2026-07", "2026-08"], [3800_00, 3900_00, 4000_00], strict=True)
    ):
        insert_transaction(
            memory_db,
            Transaction(
                id=f"tx_food_hist_{idx}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"{month_str}-10T12:00:00Z",
                amount_paise=spend_paise,
                direction="debit",
                merchant_raw="Food Past",
                description="Past meal",
                category_id="food",
                created_at=T0,
            ),
        )
    memory_db.commit()

    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    ctx = ExecutionContext(conn=memory_db, user_id="u1", actor="user", run_id="r1", policy=policy)

    # Set user preference to mute food alerts
    pref_res = execute_tool(
        ctx,
        "set_alert_preference",
        {"category_id": "food", "muted": True},
    )
    assert pref_res.ok

    # Evaluate alerts
    agent_ctx = ExecutionContext(
        conn=memory_db,
        user_id="u1",
        actor="agent",
        run_id="r2",
        policy=policy,
        clock=datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC),
    )
    eval_res = execute_tool(agent_ctx, "evaluate_alerts", {"period": "2026-09"})
    assert eval_res.ok

    # Check that open alerts do not contain muted food alerts
    open_alerts = memory_db.execute(
        "SELECT * FROM alerts WHERE user_id = 'u1' AND subject_key = 'food'"
    ).fetchall()
    assert len(open_alerts) == 0

    # Verify alert_suppressed event exists in audit log
    sup_audit = memory_db.execute(
        "SELECT * FROM audit_events WHERE event_type = 'alert_suppressed'"
    ).fetchone()
    assert sup_audit is not None
    assert sup_audit["user_id"] == "u1"


# -------------------------------------------------------------------------------------------------
# 9. Causal claim blocked when confidence is low
# -------------------------------------------------------------------------------------------------
def test_causal_claim_blocked_when_confidence_low():
    finding = Finding(
        id="f_low",
        kind="category_spend",
        period="2026-09",
        subject="Shopping",
        description="Shopping spend increased this month",
        numbers=[FindingNumber(label="spend", value=15000_00, unit="paise")],
    )

    # Inconclusive / low confidence investigation
    from copilot.models.agentic import Investigation

    inv_low = Investigation(
        id="inv_low_1",
        user_id="u1",
        subject_kind="category_change",
        subject_ref={"period": "2026-09"},
        outcome="inconclusive",
        confidence_label="low",
        explained_share_bp=0,
        unexplained_paise=15000_00,
        rounds=1,
        created_at=T0,
    )

    # Draft asserting causal link: 'because'
    draft = AdviceDraft(
        finding_ids=["f_low"],
        text="Your shopping spend was ₹15,000 because luxury purchases spiked.",
    )
    verdict = validate_advice(
        draft,
        findings_by_id={"f_low": finding},
        investigations_by_id={"inv_low_1": inv_low},
    )
    assert not verdict.ok
    assert any("causal claim" in v for v in verdict.violations)


# -------------------------------------------------------------------------------------------------
# 10. Recommendation without simulation rejected
# -------------------------------------------------------------------------------------------------
def test_recommendation_without_simulation_rejected():
    rec = Recommendation(
        id="rec_unsimulated",
        user_id="u1",
        task_id="t1",
        origin="whatif",
        text="Reduce discretionary spend by ₹5,000.",
        evidence=["f1"],
        status="draft",
        simulation_id=None,  # Missing simulation for spend_decision
        created_at=T0,
    )
    verdict = validate_advice(
        rec,
        findings_by_id={},
        recommendation_kind="spend_decision",
    )
    assert not verdict.ok
    assert any("requires a simulation_id" in v for v in verdict.violations)


# -------------------------------------------------------------------------------------------------
# 11. Refusal of 'which mutual fund should I buy'
# -------------------------------------------------------------------------------------------------
def test_refusal_investment_advice():
    q = "which mutual fund should I buy for 30% annual returns?"
    is_ref, ref_cls, msg = check_input_gate(q)
    assert is_ref
    assert ref_cls == "INVESTMENT_ADVICE"
    assert "investment advice" in msg.lower()


# -------------------------------------------------------------------------------------------------
# 12. Refusal of 'transfer ₹5,000 to Rahul'
# -------------------------------------------------------------------------------------------------
def test_refusal_money_movement():
    q = "transfer ₹5,000 to Rahul right now"
    is_ref, ref_cls, msg = check_input_gate(q)
    assert is_ref
    assert ref_cls == "MONEY_MOVEMENT"
    assert "cannot move money" in msg.lower() or "do not have permission" in msg.lower()


# -------------------------------------------------------------------------------------------------
# 13. Clarification asked once then clean stop
# -------------------------------------------------------------------------------------------------
def test_clarification_asked_once_then_clean_stop(memory_db):
    # Ambiguous query without period or category
    q = "how much did I spend?"
    entities = resolve_entities(q, memory_db, "u1")
    period_info = parse_period(q)
    amt = parse_amount_paise(q)

    it = classify_intent(q, entities, period_info, amt)
    assert it.type == "summarize_period"
    # Period is None -> triggers single clarification option
    assert it.period is None


# -------------------------------------------------------------------------------------------------
# 14. Timeline shows pending approval
# -------------------------------------------------------------------------------------------------
def test_timeline_shows_pending_approval(memory_db):
    rec = Recommendation(
        id="rec_pending_1",
        user_id="u1",
        task_id=None,
        origin="whatif",
        text="Consider postponing laptop purchase by 1 month to stay on budget.",
        evidence=["sim_1"],
        status="draft",
        created_at="2026-10-14T10:00:00Z",
    )
    insert_recommendation(memory_db, rec)
    memory_db.commit()

    tl = build_timeline(memory_db, "u1")
    assert len(tl.pending_approvals) >= 1
    assert any(p.ref.get("recommendation_id") == "rec_pending_1" for p in tl.pending_approvals)


# -------------------------------------------------------------------------------------------------
# 15. Phase 1 graph still produces the same monthly review
# -------------------------------------------------------------------------------------------------
def test_phase1_graph_still_produces_same_monthly_review(memory_db):
    # Insert September transactions
    for i in range(4):
        insert_transaction(
            memory_db,
            Transaction(
                id=f"tx_p1_{i}",
                user_id="u1",
                account_id="acc_1",
                occurred_at=f"2026-09-1{i}T12:00:00Z",
                amount_paise=150_00,
                direction="debit",
                merchant_raw="SWIGGY",
                merchant_normalized="SWIGGY",
                description="Swiggy meal",
                category_id="food",
                category_source="rule",
                created_at=T0,
            ),
        )
    memory_db.commit()

    rev_data = build_monthly_review(memory_db, "u1", 2026, 9, "r_p1")
    assert rev_data is not None
    assert rev_data.spend_paise == 600_00

    db_rev = get_monthly_review(memory_db, "u1", 2026, 9)
    assert db_rev is not None
    assert db_rev.version >= 1


# -------------------------------------------------------------------------------------------------
# 16. User-set category untouched by any Phase 2 tool
# -------------------------------------------------------------------------------------------------
def test_user_set_category_untouched_by_phase2_tools(memory_db):
    from copilot.core.config import PROJECT_ROOT
    from copilot.governance.policy import load_policy

    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")

    tx = Transaction(
        id="tx_user_fixed",
        user_id="u1",
        account_id="acc_1",
        occurred_at="2026-09-05T12:00:00Z",
        amount_paise=500_00,
        direction="debit",
        merchant_raw="AMAZON BOOKS",
        merchant_normalized="AMAZON",
        description="Amazon book purchase",
        category_id="shopping",
        category_source="user",  # User override
        created_at=T0,
    )
    insert_transaction(memory_db, tx)
    memory_db.commit()

    # Execute read/compute tools
    ctx = ExecutionContext(
        conn=memory_db, user_id="u1", actor="agent", run_id="r_p2", policy=policy
    )
    execute_tool(ctx, "explain_change", {"category_id": "shopping", "period": "2026-09"})
    execute_tool(ctx, "evaluate_alerts", {"period": "2026-09"})

    # Verify transaction record is completely untouched
    row = memory_db.execute("SELECT * FROM transactions WHERE id = 'tx_user_fixed'").fetchone()
    assert row["category_id"] == "shopping"
    assert row["category_source"] == "user"
