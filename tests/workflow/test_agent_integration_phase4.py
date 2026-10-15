"""
Tests for Stage 4.10 Agent Integration (PLAN_PHASE4 Section 5.11 & Stage 4.10).

Test Coverage:
1. Intent classification accuracy on labelled examples for all 5 Phase 4 intents (>= 8 examples each).
2. Refusal of betting, wagers, lottery-style requests with typed refusal text.
3. Tool minimality per intent in plan templates.
4. Adversarial plans selecting Phase 4 write tools rejected and audited.
5. CoachAgent specialist execution in multi-agent graph and tool subset isolation.
6. CoachAgent graceful degradation on failure without crashing the supervisor.
7. Runtime maintenance jobs idempotency with leases for all 6 Phase 4 jobs.
8. MCP server exposes strictly read tools and excludes all Phase 4 write tools.
9. Unified activity timeline integration across offers, experiments, check-ins, adjustments, reviews, XP, and badges.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from copilot.config.phase2 import load_intent_patterns, load_plan_templates
from copilot.core.intent import (
    check_input_gate,
    classify_intent,
    parse_amount_paise,
    parse_period,
    resolve_entities,
)
from copilot.core.timeline import build_timeline
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_goal, insert_user
from copilot.db.repo_phase4 import (
    insert_adjustment_proposal,
    insert_badge_award,
    insert_experiment,
    insert_experiment_checkin,
    insert_experiment_review,
    insert_offer,
    insert_xp_event,
)
from copilot.governance.policy import decide, load_policy
from copilot.models.agentic import Goal
from copilot.models.domain import Account, User
from copilot.models.phase3 import SubQuestion
from copilot.models.phase4 import (
    AdjustmentProposal,
    BadgeAward,
    Baseline,
    Experiment,
    ExperimentCheckin,
    ExperimentReview,
    Hypothesis,
    MetricDef,
    Offer,
    XpEvent,
)
from copilot.runtime.runner import run_job
from copilot.tools.executor import ExecutionContext
from copilot.tools.registry import get as get_tool
from copilot.workflow.nodes import ensure_tools_registered
from copilot.workflow.specialists import execute_specialist_tool, run_specialist

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def setup_tools():
    ensure_tools_registered()


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u = User(id="u_coach", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u)
    a = Account(
        id="a_coach",
        user_id="u_coach",
        name="Main Account",
        opening_balance_paise=50_000_000,
        created_at="2026-09-01T00:00:00Z",
    )
    insert_account(c, a)
    g = Goal(
        id="g_trip",
        user_id="u_coach",
        name="Goa Trip",
        kind="savings",
        target_paise=3000000,
        current_paise=0,
        priority=1,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    insert_goal(c, g)
    yield c
    c.close()


@pytest.fixture
def ctx(conn):
    policy = load_policy(PROJECT_ROOT / "config" / "policy.yaml")
    return ExecutionContext(
        conn=conn,
        user_id="u_coach",
        run_id="run_test_agent_p4",
        policy=policy,
        clock=datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC),
    )


# -------------------------------------------------------------------------------------------------
# 1. Intent Classification Accuracy on Labelled Examples (>= 8 per intent)
# -------------------------------------------------------------------------------------------------
def test_phase4_intent_classification_labelled_accuracy(conn):
    cfg_path = PROJECT_ROOT / "config" / "intent_patterns.yaml"
    cfg = load_intent_patterns(cfg_path)

    phase4_intents = [
        "start_experiment",
        "experiment_status",
        "what_worked",
        "challenge_suggestions",
        "progress_summary",
    ]

    for itype in phase4_intents:
        examples = cfg.labelled_examples.get(itype, [])
        assert len(examples) >= 8, f"Intent '{itype}' must have at least 8 labelled examples; found {len(examples)}"

        for query in examples:
            entities = resolve_entities(query, conn, "u_coach")
            p_info = parse_period(query)
            amt = parse_amount_paise(query)
            detected = classify_intent(query, entities, p_info, amt)
            assert detected.type == itype, (
                f"Classification mismatch for query '{query}': expected '{itype}', got '{detected.type}'"
            )


# -------------------------------------------------------------------------------------------------
# 2. Refusal of Betting, Wagers, and Lottery-style Requests
# -------------------------------------------------------------------------------------------------
def test_betting_gambling_refusal():
    betting_queries = [
        "I want to bet 500 rupees with my friend on who spends less",
        "Can we do a money wager on my dining budget?",
        "Is there a cash prize or lottery for completing the delivery challenge?",
        "Let's put 1000 on a bet for this week expenses",
        "Can I challenge my coworker for money?",
    ]

    for q in betting_queries:
        is_ref, ref_class, ref_text = check_input_gate(q)
        assert is_ref, f"Expected betting query to be refused: '{q}'"
        assert ref_class == "BETTING_GAMBLING"
        assert "FinCo strictly prohibits financial betting" in ref_text
        assert "self-competition" in ref_text


# -------------------------------------------------------------------------------------------------
# 3. Tool Minimality per Intent in Plan Templates
# -------------------------------------------------------------------------------------------------
def test_plan_templates_tool_minimality():
    plans = load_plan_templates(PROJECT_ROOT / "config" / "plan_templates.yaml")

    phase4_intents = [
        "start_experiment",
        "experiment_status",
        "what_worked",
        "challenge_suggestions",
        "progress_summary",
    ]

    for itype in phase4_intents:
        assert itype in plans.templates, f"Missing plan template for '{itype}'"
        tpl = plans.templates[itype]
        assert len(tpl.default_steps) >= 1
        assert len(tpl.required_tools) >= 1
        # Each step's tool must be in allowed_tools
        for s in tpl.default_steps:
            assert s.tool_name in tpl.allowed_tools, f"Tool '{s.tool_name}' not in allowed_tools for '{itype}'"


# -------------------------------------------------------------------------------------------------
# 4. Adversarial Plans Selecting Phase 4 Write Tools Rejected by Policy
# -------------------------------------------------------------------------------------------------
def test_adversarial_plans_reject_phase4_write_tools(ctx):
    write_tools = [
        "accept_offer",
        "dismiss_offer",
        "start_experiment",
        "pause_experiment",
        "abandon_experiment",
        "answer_checkin",
        "submit_review_feedback",
        "accept_adjustment",
        "reject_adjustment",
    ]

    for w_tool in write_tools:
        spec = get_tool(w_tool)
        assert spec is not None, f"Tool '{w_tool}' not registered"

        # Agent actor attempt is denied
        dec_agent = decide(ctx.policy, spec, actor="agent")
        assert dec_agent.outcome == "deny", f"Tool '{w_tool}' should be DENIED for actor='agent'"

        # User actor attempt is allowed
        dec_user = decide(ctx.policy, spec, actor="user")
        assert dec_user.outcome == "allow", f"Tool '{w_tool}' should be ALLOWED for actor='user'"


# -------------------------------------------------------------------------------------------------
# 5. CoachAgent Execution in Multi-Agent Graph & Tool Subset Isolation
# -------------------------------------------------------------------------------------------------
def test_coach_agent_execution_and_tool_isolation(ctx):
    # Allowed tools execution through CoachAgent
    res = execute_specialist_tool(ctx, "CoachAgent", "list_experiments", {})
    assert res.ok

    res_off = execute_specialist_tool(ctx, "CoachAgent", "list_offers", {})
    assert res_off.ok

    # CoachAgent attempting a forbidden tool outside its allowlist is rejected and audited
    with pytest.raises(PermissionError, match="forbidden tool 'create_bucket'"):
        execute_specialist_tool(ctx, "CoachAgent", "create_bucket", {"name": "test"})

    audit_rows = ctx.conn.execute(
        "SELECT event_type, reason FROM audit_events WHERE event_type = 'specialist_tool_rejected'"
    ).fetchall()
    assert len(audit_rows) >= 1
    assert "outside allowed subset for role 'CoachAgent'" in audit_rows[0][1]


# -------------------------------------------------------------------------------------------------
# 6. CoachAgent Graceful Degradation on Failure
# -------------------------------------------------------------------------------------------------
def test_coach_agent_graceful_degradation(ctx):
    subq = SubQuestion(domain="coaching", question_kind="challenge_potential", parameters={})
    report = run_specialist("CoachAgent", subq, ctx, task_id="task_coach_01")
    assert report.status in ("ok", "partial")
    assert report.agent_role == "CoachAgent"

    # Injected unhandled question kind gracefully returns partial/failed without throwing exception
    subq_unknown = SubQuestion(domain="coaching", question_kind="non_existent_kind_xyz", parameters={})
    report_unknown = run_specialist("CoachAgent", subq_unknown, ctx, task_id="task_coach_02")
    assert report_unknown.status in ("failed", "partial")
    assert len(report_unknown.gaps_json) >= 1


# -------------------------------------------------------------------------------------------------
# 7. Runtime Maintenance Jobs Idempotency with Leases
# -------------------------------------------------------------------------------------------------
def test_runtime_jobs_idempotency_phase4(conn):
    ref_dt = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
    user_id = "u_coach"

    jobs = [
        "create_checkins",
        "create_due_reviews",
        "expire_offers",
        "run_adaptive_detectors",
        "weekly_offers",
        "award_xp_and_badges",
    ]

    for j in jobs:
        # Run 1: Should execute
        run1 = run_job(conn, user_id=user_id, job_kind=j, as_of=ref_dt)
        assert run1.status in ("completed", "ok"), f"Job '{j}' failed on initial run: {run1.summary_json}"

        # Run 2: Same period key should be skipped due to idempotency
        run2 = run_job(conn, user_id=user_id, job_kind=j, as_of=ref_dt)
        assert run2.status == "skipped", f"Job '{j}' was not idempotent for same period: {run2.status}"
        assert run2.summary_json.get("reason") == "idempotent_already_run_for_period"


# -------------------------------------------------------------------------------------------------
# 8. MCP Server Lists Only Read Tools
# -------------------------------------------------------------------------------------------------
def test_mcp_lists_only_read_tools_phase4():
    mcp_path = PROJECT_ROOT / "config" / "mcp.yaml"
    data = yaml.safe_load(mcp_path.read_text(encoding="utf-8"))
    exposed = set(data.get("exposed_tools", []))

    # Phase 4 read tools must be present
    assert "list_experiments" in exposed
    assert "experiment_progress" in exposed
    assert "get_user_progress" in exposed
    assert "get_personal_bests" in exposed
    assert "list_offers" in exposed

    # Phase 4 write tools must NOT be present
    forbidden_write_tools = [
        "accept_offer",
        "dismiss_offer",
        "start_experiment",
        "pause_experiment",
        "resume_experiment",
        "abandon_experiment",
        "answer_checkin",
        "submit_review_feedback",
        "accept_adjustment",
        "reject_adjustment",
        "weekly_offers",
        "award_xp_and_badges",
    ]
    for fw in forbidden_write_tools:
        assert fw not in exposed, f"Write tool '{fw}' must NEVER be exposed in MCP"


# -------------------------------------------------------------------------------------------------
# 9. Unified Activity Timeline Integration across Phase 4 Entities
# -------------------------------------------------------------------------------------------------
def test_timeline_integration_phase4(conn):
    user_id = "u_coach"
    t0 = "2026-10-10T10:00:00Z"

    # 1. Offer
    offer = Offer(
        id="off_tl_01",
        user_id=user_id,
        week_start="2026-10-12",
        template_code="dining_reduction",
        difficulty="medium",
        params_json={"title": "Cap Dining Spend", "target_value": 400000},
        rank=1,
        propensity_bp=5000,
        policy_version="v1",
        rng_seed=42,
        reason_json={"rationale": "High dining spend"},
        status="shown",
        created_at=t0,
    )
    insert_offer(conn, offer)

    # 2. Experiment
    exp = Experiment(
        id="exp_tl_01",
        user_id=user_id,
        title="Cap Dining Spend",
        template_code="dining_reduction",
        hypothesis_json=Hypothesis(
            intervention="Cook dinners at home",
            metric="category_spend",
            direction="lower",
            target=400000,
        ).model_dump(mode="json"),
        metric_def_json=MetricDef(
            metric="category_spend",
            categories=["dining"],
        ).model_dump(mode="json"),
        params_json={},
        difficulty="medium",
        window_start="2026-10-12",
        window_end="2026-10-26",
        baseline_json=Baseline(
            k=3,
            window_values=[500000, 480000, 520000],
            median=500000,
            low=450000,
            high=550000,
        ).model_dump(mode="json"),
        target_value=400000,
        status="active",
        origin="offer",
        created_at="2026-10-12T10:00:00Z",
        started_at="2026-10-12T10:00:00Z",
    )
    insert_experiment(conn, exp)

    # 3. Checkin
    chk = ExperimentCheckin(
        id="chk_tl_01",
        user_id=user_id,
        experiment_id=exp.id,
        checkin_date="2026-10-19",
        observed_value=180000,
        pace_status="on_pace",
        created_at="2026-10-19T10:00:00Z",
    )
    insert_experiment_checkin(conn, chk)

    # 4. Adjustment Proposal
    adj = AdjustmentProposal(
        id="adj_tl_01",
        user_id=user_id,
        experiment_id=exp.id,
        kind="ease_target",
        reason_code="two_behind_checkins",
        params_json={"new_target": 450000},
        status="proposed",
        created_at="2026-10-20T10:00:00Z",
    )
    insert_adjustment_proposal(conn, adj)

    # 5. Review
    rev = ExperimentReview(
        id="rev_tl_01",
        user_id=user_id,
        experiment_id=exp.id,
        observed_value=380000,
        outcome="beyond_usual_range",
        rank_p_bp=9500,
        effect_value=120000,
        target_met=True,
        integrity_json={"integrity_flag": "clean"},
        data_quality_json={"data_quality_flag": "good"},
        created_at="2026-10-26T10:00:00Z",
    )
    insert_experiment_review(conn, rev)

    # 6. XP Event
    xp = XpEvent(
        id="xp_tl_01",
        user_id=user_id,
        rule_code="challenge_completion",
        points=150,
        ref_kind="experiment",
        ref_id=exp.id,
        period_day="2026-10-26",
        created_at="2026-10-26T10:05:00Z",
    )
    insert_xp_event(conn, xp)

    # 7. Badge Award
    badge = BadgeAward(
        id="badge_tl_01",
        user_id=user_id,
        badge_code="first_experiment",
        awarded_at="2026-10-26T10:10:00Z",
        evidence_json={"experiment_id": exp.id},
    )
    insert_badge_award(conn, badge)

    # Build timeline
    tl = build_timeline(conn, user_id)

    # Assert all kinds are represented
    kinds = [e.kind for e in tl.entries]
    assert "challenge_offer" in kinds
    assert "experiment" in kinds
    assert "experiment_checkin" in kinds
    assert "adjustment" in kinds
    assert "experiment_review" in kinds
    assert "xp_award" in kinds
    assert "badge_award" in kinds

    # Pending proposal must appear in pending_approvals
    pending_refs = [a.ref.get("proposal_id") for a in tl.pending_approvals]
    assert "adj_tl_01" in pending_refs
