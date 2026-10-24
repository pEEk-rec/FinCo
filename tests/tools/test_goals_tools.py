"""
Through-executor and governance tests for goal tools (PLAN_PHASE2 Stage 2.2).

Verifies:
- All tools execute strictly through execute_tool(ctx, ...)
- Actor permissions:
    actor user -> create_goal and update_goal allowed
    actor agent -> create_goal and update_goal require approval (needs_approval)
    list_goals and evaluate_goal_impact allowed for both
- Audit events recorded on real execution path (goal_created, goal_updated)
- User isolation: User 2 cannot read or update User 1's goal
- Boundary error cases: unknown goal ID, negative or zero target paise
"""

from datetime import datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.goals import register_goals_tools
from copilot.tools.registry import clear_registry

T0 = "2026-10-15T10:00:00Z"
DT0 = datetime.fromisoformat("2026-10-15T10:00:00+00:00")


@pytest.fixture
def test_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    insert_account(
        c, Account(id="acc_1", user_id="u1", name="Main", opening_balance_paise=0, created_at=T0)
    )
    insert_category(c, Category(id="food", user_id="u1", name="Food", created_at=T0))

    # Standard policy rules
    p = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {"read": {"decision": "allow"}},
            "tools": {
                "create_goal": {"agent": "needs_approval", "user": "allow"},
                "update_goal": {"agent": "needs_approval", "user": "allow"},
                "record_goal_contribution": {"agent": "needs_approval", "user": "allow"},
                "get_goal_progress": {"decision": "allow"},
                "list_goals": {"decision": "allow"},
                "evaluate_goal_impact": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_goals_tools()

    ctx = ExecutionContext(
        conn=c,
        user_id="u1",
        run_id="run_1",
        policy=p,
        clock=DT0,
        actor="user",
    )
    yield ctx
    clear_registry()


def test_agent_cannot_create_or_update_goal_without_approval(test_ctx):
    """Safety rule: actor agent must be denied without approval."""
    agent_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u1",
        run_id="run_1",
        policy=test_ctx.policy,
        clock=DT0,
        actor="agent",
    )

    # Agent cannot create goal without approval
    res_create = execute_tool(
        agent_ctx,
        "create_goal",
        {"name": "Agent Goal", "target_paise": 10_000_00, "deadline": "2026-12-31"},
    )
    assert res_create.ok is False
    assert res_create.error.code == ErrorCode.APPROVAL_REQUIRED

    # Agent cannot update goal without approval
    res_update = execute_tool(
        agent_ctx,
        "update_goal",
        {"goal_id": "g_any", "name": "Updated Agent Goal"},
    )
    assert res_update.ok is False
    assert res_update.error.code == ErrorCode.APPROVAL_REQUIRED


def test_user_can_create_update_and_list_goals_with_audit(test_ctx):
    """User actor creates, updates, and lists goals, with audit events recorded."""
    # 1. Create goal
    res = execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "Emergency Fund",
            "kind": "emergency_fund",
            "target_paise": 50_000_00,
            "current_paise": 10_000_00,
            "deadline": "2027-04-30",
            "priority": 1,
        },
    )
    assert res.ok is True
    goal = res.data.goal
    goal_id = goal.id
    assert goal.name == "Emergency Fund"
    assert goal.target_paise == 50_000_00
    assert goal.current_paise == 10_000_00
    assert goal.priority == 1

    # Verify audit event for create
    audit_row = test_ctx.conn.execute(
        "SELECT event_type, metadata_json FROM audit_events WHERE event_type = 'goal_created'"
    ).fetchone()
    assert audit_row is not None
    assert "Emergency Fund" in audit_row["metadata_json"]

    # 2. Update goal
    res_up = execute_tool(
        test_ctx,
        "update_goal",
        {
            "goal_id": goal_id,
            "current_paise": 15_000_00,
            "priority": 2,
        },
    )
    assert res_up.ok is True
    up_goal = res_up.data.goal
    assert up_goal.current_paise == 15_000_00
    assert up_goal.priority == 2

    # Verify audit event for update
    audit_up = test_ctx.conn.execute(
        "SELECT event_type, metadata_json FROM audit_events WHERE event_type = 'goal_updated'"
    ).fetchone()
    assert audit_up is not None
    assert goal_id in audit_up["metadata_json"]

    # 3. List goals
    res_list = execute_tool(test_ctx, "list_goals", {"status": "active"})
    assert res_list.ok is True
    assert len(res_list.data.goals) == 1
    assert res_list.data.goals[0].id == goal_id


def test_user_isolation_for_goals(test_ctx):
    """User 2 cannot list or update goals created by User 1."""
    # User 1 creates goal
    res = execute_tool(
        test_ctx,
        "create_goal",
        {"name": "Private U1 Goal", "target_paise": 20_000_00},
    )
    assert res.ok is True
    g1_id = res.data.goal.id

    # User 2 tries to update User 1's goal -> NOT_FOUND
    u2_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u2",
        run_id="run_2",
        policy=test_ctx.policy,
        clock=DT0,
        actor="user",
    )
    res_u2 = execute_tool(u2_ctx, "update_goal", {"goal_id": g1_id, "current_paise": 5_000_00})
    assert res_u2.ok is False
    assert res_u2.error.code == ErrorCode.NOT_FOUND

    # User 2 listing goals sees 0 goals
    res_u2_list = execute_tool(u2_ctx, "list_goals", {})
    assert res_u2_list.ok is True
    assert len(res_u2_list.data.goals) == 0


def test_evaluate_goal_impact_through_executor(test_ctx):
    """evaluate_goal_impact runs through executor and evaluates impact."""
    # Add history transactions to establish surplus
    # Sep 2026: credit ₹50,000, debit ₹20,000 -> surplus ₹30,000
    insert_transaction(
        test_ctx.conn,
        Transaction(
            id="tx1",
            account_id="acc_1",
            user_id="u1",
            amount_paise=-5_000_000,
            direction="credit",
            merchant_raw="Salary",
            description="Salary",
            occurred_at="2026-09-01T10:00:00Z",
            created_at="2026-09-01T10:00:00Z",
        ),
    )
    insert_transaction(
        test_ctx.conn,
        Transaction(
            id="tx2",
            account_id="acc_1",
            user_id="u1",
            amount_paise=2_000_000,
            direction="debit",
            category_id="food",
            merchant_raw="Grocery",
            description="Food",
            occurred_at="2026-09-02T10:00:00Z",
            created_at="2026-09-02T10:00:00Z",
        ),
    )
    # Aug 2026: credit ₹50,000, debit ₹20,000 -> surplus ₹30,000
    insert_transaction(
        test_ctx.conn,
        Transaction(
            id="tx3",
            account_id="acc_1",
            user_id="u1",
            amount_paise=-5_000_000,
            direction="credit",
            merchant_raw="Salary",
            description="Salary",
            occurred_at="2026-08-01T10:00:00Z",
            created_at="2026-08-01T10:00:00Z",
        ),
    )
    insert_transaction(
        test_ctx.conn,
        Transaction(
            id="tx4",
            account_id="acc_1",
            user_id="u1",
            amount_paise=2_000_000,
            direction="debit",
            category_id="food",
            merchant_raw="Grocery",
            description="Food",
            occurred_at="2026-08-02T10:00:00Z",
            created_at="2026-08-02T10:00:00Z",
        ),
    )
    test_ctx.conn.commit()

    # Create active goal: needs ₹25,000 this month (deadline 2026-10-31)
    execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "Trip Goal",
            "target_paise": 25_000_00,
            "deadline": "2026-10-31",
            "priority": 1,
        },
    )

    # Evaluate impact of ₹10,000 purchase
    res = execute_tool(
        test_ctx,
        "evaluate_goal_impact",
        {"decision_paise": 10_000_00, "today": T0},
    )
    assert res.ok is True
    impact = res.data.impact
    assert impact.decision_paise == 10_000_00
    # Before: surplus was ₹30,000 >= ₹25,000 -> on_track
    assert impact.goals_before[0].status == "on_track"
    # After: surplus is ₹20,000 < ₹25,000 -> off_track, shortfall ₹5,000
    assert impact.goals_after[0].status == "off_track"
    assert impact.goals_after[0].shortfall_paise == 5_000_00


def test_create_and_update_goal_with_phase3_fields(test_ctx):
    """create_goal and update_goal accept Phase 3 extended fields."""
    res = execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "House Downpayment",
            "target_paise": 50_000_000,
            "target_date": "2028-12-31",
            "progress_source": "manual",
            "essential": True,
            "notes": "Emergency buffer protected",
        },
    )
    assert res.ok
    goal = res.data.goal
    assert goal.name == "House Downpayment"
    assert goal.deadline == "2028-12-31"
    assert goal.progress_source == "manual"
    assert goal.essential is True
    assert goal.notes == "Emergency buffer protected"

    # Update Phase 3 fields
    upd_res = execute_tool(
        test_ctx,
        "update_goal",
        {
            "goal_id": goal.id,
            "notes": "Updated note: target revised",
            "essential": False,
        },
    )
    assert upd_res.ok
    upd_goal = upd_res.data.goal
    assert upd_goal.notes == "Updated note: target revised"
    assert upd_goal.essential is False


def test_record_goal_contribution_and_governance(test_ctx):
    """record_goal_contribution enforces governance, validates source, and updates balance."""
    # Create manual goal
    res = execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "Bike",
            "target_paise": 100_000_00,
            "current_paise": 20_000_00,
            "progress_source": "manual",
        },
    )
    goal_id = res.data.goal.id

    # Agent cannot record contribution directly
    agent_ctx = ExecutionContext(
        conn=test_ctx.conn,
        user_id="u1",
        run_id="run_agent",
        actor="agent",
        policy=test_ctx.policy,
        clock=DT0,
    )
    res_agent = execute_tool(
        agent_ctx,
        "record_goal_contribution",
        {"goal_id": goal_id, "amount_paise": 10_000_00},
    )
    assert not res_agent.ok
    assert res_agent.error.code == ErrorCode.APPROVAL_REQUIRED

    # User can record contribution
    res_user = execute_tool(
        test_ctx,
        "record_goal_contribution",
        {"goal_id": goal_id, "amount_paise": 15_000_00, "occurred_on": "2026-10-15"},
    )
    assert res_user.ok
    assert res_user.data.goal_progress.current_paise == 35_000_00  # 20,000 + 15,000

    # User cannot contribute 0
    res_zero = execute_tool(
        test_ctx,
        "record_goal_contribution",
        {"goal_id": goal_id, "amount_paise": 0},
    )
    assert not res_zero.ok
    assert res_zero.error.code == ErrorCode.INVALID_INPUT

    # Bucket-sourced goal rejects manual contribution
    res_bucket_goal = execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "Bucket Goal",
            "target_paise": 50_000_00,
            "progress_source": "bucket",
        },
    )
    bg_id = res_bucket_goal.data.goal.id
    res_reject = execute_tool(
        test_ctx,
        "record_goal_contribution",
        {"goal_id": bg_id, "amount_paise": 5_000_00},
    )
    assert not res_reject.ok
    assert res_reject.error.code == ErrorCode.INVALID_INPUT


def test_get_goal_progress_tool(test_ctx):
    """get_goal_progress returns full GoalProgress model with pace and projected completion."""
    res = execute_tool(
        test_ctx,
        "create_goal",
        {
            "name": "Vacation",
            "target_paise": 60_000_00,
            "current_paise": 30_000_00,
            "deadline": "2026-12-31",
        },
    )
    goal_id = res.data.goal.id

    res_prog = execute_tool(
        test_ctx,
        "get_goal_progress",
        {"goal_id": goal_id, "today": "2026-10-15"},
    )
    assert res_prog.ok
    prog = res_prog.data.progress
    assert prog.goal_id == goal_id
    assert prog.target_paise == 60_000_00
    assert prog.current_paise == 30_000_00
    assert prog.remaining_paise == 30_000_00
    assert prog.percent_bp == 5000
    assert prog.required_monthly_paise == 10_000_00  # 30,000 / 3 months = 10,000
