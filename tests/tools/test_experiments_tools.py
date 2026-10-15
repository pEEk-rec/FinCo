"""
Through-executor tests for experiment tools (PLAN_PHASE4 Section 5.3, Stage 4.3).

Verifies:
- Agent cannot start, pause or abandon experiments (policy denial / approval required)
- User actor can design, start, pause, resume, abandon, answer checkins, and submit reviews
- Runtime jobs (create_checkins, create_due_reviews) allowed for maintenance
- Read tools (get_experiment, list_experiments, experiment_progress) allowed for all
- Every tool execution writes structured audit events to audit_events table
"""

from datetime import datetime

import pytest

from copilot.core.baseline import generate_candidate_windows
from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.experiments import register_experiment_tools
from copilot.tools.registry import clear_registry

T0 = "2026-01-01T00:00:00Z"
DT0 = datetime.fromisoformat("2026-09-01T10:00:00+05:30")


@pytest.fixture
def test_ctx():
    clear_registry()
    register_experiment_tools()

    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u = User(id="user_alice", created_at=T0)
    insert_user(c, u)
    acc = Account(
        id="acc_main",
        user_id="user_alice",
        name="Main Checking",
        opening_balance_paise=10000000,
        created_at=T0,
    )
    insert_account(c, acc)

    for cat_id, cat_name in [
        ("dining_out", "Dining Out"),
        ("groceries", "Groceries"),
        ("shopping", "Shopping"),
    ]:
        insert_category(
            c,
            Category(
                id=cat_id,
                user_id="user_alice",
                name=cat_name,
                created_at=T0,
            ),
        )

    # Load real policy from config/policy.yaml
    policy = load_policy("config/policy.yaml")

    ctx = ExecutionContext(
        conn=c,
        user_id="user_alice",
        run_id="run_user_1",
        actor="user",
        policy=policy,
        clock=DT0,
    )
    return ctx


def _insert_txn(
    conn,
    user_id: str,
    tx_id: str,
    occurred_at: str,
    amount_paise: int,
    category_id: str = "dining_out",
):
    query = """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, category_id, category_source, created_at
        ) VALUES (?, ?, 'acc_main', ?, ?, 'debit', 'Merchant', 'Merchant', ?, 'rule', ?)
    """
    conn.execute(query, (tx_id, user_id, occurred_at, amount_paise, category_id, occurred_at))


def test_agent_cannot_start_pause_or_abandon_experiments(test_ctx):
    """Agent actor must be denied or require approval when attempting write actions."""
    # Seed baseline
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(test_ctx.conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 200000)

    # User designs experiment first
    res_design = execute_tool(
        test_ctx,
        "design_experiment",
        {
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "difficulty": "medium",
            "duration_days": 14,
        },
    )
    assert res_design.ok
    exp_id = res_design.data.experiment.id

    agent_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="user_alice",
        run_id="run_agent_1",
        actor="agent",
        policy=test_ctx.policy,
        clock=DT0,
    )

    # 1. Agent cannot start experiment
    res_start = execute_tool(agent_ctx, "start_experiment", {"experiment_id": exp_id})
    assert not res_start.ok
    assert res_start.error.code == ErrorCode.DENIED_BY_POLICY

    # 2. Agent cannot pause experiment
    res_pause = execute_tool(agent_ctx, "pause_experiment", {"experiment_id": exp_id})
    assert not res_pause.ok
    assert res_pause.error.code == ErrorCode.DENIED_BY_POLICY

    # 3. Agent cannot abandon experiment
    res_abandon = execute_tool(agent_ctx, "abandon_experiment", {"experiment_id": exp_id})
    assert not res_abandon.ok
    assert res_abandon.error.code == ErrorCode.DENIED_BY_POLICY


def test_user_experiment_tools_end_to_end_with_audit_events(test_ctx):
    """
    User can design, start, pause, resume, progress, checkin, review, and feedback.
    Every step is verified in the audit_events table.
    """
    # Seed baseline
    windows = generate_candidate_windows("2026-09-01", duration_days=14, k=6)
    for idx, (ws, _we) in enumerate(windows, 1):
        _insert_txn(test_ctx.conn, "user_alice", f"tb_{idx}", f"{ws}T10:00:00Z", 300000)

    # 1. Design experiment
    res_design = execute_tool(
        test_ctx,
        "design_experiment",
        {
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "difficulty": "medium",
            "duration_days": 14,
        },
    )
    assert res_design.ok
    exp = res_design.data.experiment
    assert exp.status == "offered"
    assert exp.target_value == 240000  # 20% below 300000 = 240000
    exp_id = exp.id

    # 2. Start experiment
    res_start = execute_tool(test_ctx, "start_experiment", {"experiment_id": exp_id})
    assert res_start.ok
    assert res_start.data.experiment.status == "active"

    # 3. Pause experiment
    res_pause = execute_tool(
        test_ctx,
        "pause_experiment",
        {"experiment_id": exp_id, "reason": "going_home_for_festival"},
    )
    assert res_pause.ok
    assert res_pause.data.experiment.status == "paused"

    # 4. Resume experiment
    res_resume = execute_tool(test_ctx, "resume_experiment", {"experiment_id": exp_id})
    assert res_resume.ok
    assert res_resume.data.experiment.status == "active"

    # 5. Read tools (get_experiment, list_experiments, experiment_progress)
    res_get = execute_tool(test_ctx, "get_experiment", {"experiment_id": exp_id})
    assert res_get.ok
    assert res_get.data.experiment.id == exp_id

    res_list = execute_tool(test_ctx, "list_experiments", {"status": "active"})
    assert res_list.ok
    assert len(res_list.data.experiments) == 1

    res_prog = execute_tool(test_ctx, "experiment_progress", {"experiment_id": exp_id})
    assert res_prog.ok
    assert res_prog.data.progress.target_value == 240000

    # 6. Runtime job: create_checkins on day 7
    clock_day7 = datetime.fromisoformat("2026-09-08T10:00:00+05:30")
    test_ctx.clock = clock_day7
    res_chks = execute_tool(test_ctx, "create_checkins", {})
    assert res_chks.ok
    assert len(res_chks.data.checkins) == 1
    chk_id = res_chks.data.checkins[0].id

    # 7. Answer check-in
    res_ans = execute_tool(
        test_ctx,
        "answer_checkin",
        {"checkin_id": chk_id, "response": "going_well", "note": "Cooking at hostel"},
    )
    assert res_ans.ok
    assert res_ans.data.checkin.user_response == "going_well"

    # 8. Runtime job: create_due_reviews on day 16 (14 days + 2 delay days)
    clock_day16 = datetime.fromisoformat("2026-09-17T10:00:00+05:30")
    test_ctx.clock = clock_day16
    res_revs = execute_tool(test_ctx, "create_due_reviews", {})
    assert res_revs.ok
    assert len(res_revs.data.reviews) == 1
    rev_id = res_revs.data.reviews[0].id

    # 9. Submit review feedback
    res_fb = execute_tool(
        test_ctx,
        "submit_review_feedback",
        {
            "review_id": rev_id,
            "difficulty_rating": 2,
            "user_helpful": True,
            "would_repeat": True,
        },
    )
    assert res_fb.ok
    assert res_fb.data.review.user_difficulty == 2
    assert res_fb.data.review.user_helpful is True

    # 10. Verify audit events recorded in database
    audit_rows = test_ctx.conn.execute(
        "SELECT event_type, actor FROM audit_events WHERE user_id = ? ORDER BY occurred_at ASC",
        ("user_alice",),
    ).fetchall()
    recorded_events = [r[0] for r in audit_rows]

    expected_events = [
        "experiment_designed",
        "experiment_started",
        "experiment_paused",
        "experiment_resumed",
        "checkins_created",
        "checkin_answered",
        "reviews_created",
        "review_feedback_submitted",
    ]
    for ev in expected_events:
        assert ev in recorded_events, f"Expected event '{ev}' was not logged in audit_events"
