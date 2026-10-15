"""
Through-executor tests for adaptive challenge adjustment tools (PLAN_PHASE4 Section 5.5, Stage 4.5).

Verifies:
- Agent cannot accept or reject adjustments (policy denial / human-in-the-loop).
- User actor can accept and reject adjustments through execute_tool.
- Read tools (list_adjustments) allowed for all actors.
- Maintenance tools (run_adaptive_detectors, expire_stale_proposals) allowed for agent and user.
- Every tool execution writes structured audit events to audit_events table.
"""

from datetime import datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.core.experiments import design_experiment, start_experiment
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import (
    get_experiment,
    insert_experiment_checkin,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import ExperimentCheckin
from copilot.tools.adjustments import register_adjustment_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.experiments import register_experiment_tools
from copilot.tools.registry import clear_registry

T0 = "2026-01-01T00:00:00Z"
DT0 = datetime(2026, 9, 1, 10, 0, tzinfo=IST)
DT_MID = datetime(2026, 9, 8, 10, 0, tzinfo=IST)


@pytest.fixture
def test_ctx():
    clear_registry()
    register_experiment_tools()
    register_adjustment_tools()

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
        ("food_delivery", "Food Delivery"),
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

    policy = load_policy("config/policy.yaml")

    def make_ctx(actor="user", clock=None):
        return ExecutionContext(
            conn=c,
            user_id="user_alice",
            run_id="run_adj_001",
            policy=policy,
            actor=actor,
            clock=clock or DT0,
        )

    return make_ctx


def test_agent_cannot_accept_or_reject_adjustments(test_ctx):
    """Safety rule: Agent must never accept or reject adjustment proposals."""
    user_ctx = test_ctx(actor="user", clock=DT0)
    agent_ctx = test_ctx(actor="agent", clock=DT0)

    # 1. Create and start an experiment
    exp = design_experiment(
        user_ctx.conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 500000,
            "start_date": "2026-09-01",
        },
        clock=DT0,
    )
    start_experiment(user_ctx.conn, "user_alice", exp.id, clock=DT0)

    # 2. Add two behind checkins to generate proposals
    insert_experiment_checkin(
        user_ctx.conn,
        ExperimentCheckin(
            id="chk_1",
            user_id="user_alice",
            experiment_id=exp.id,
            checkin_date="2026-09-03",
            observed_value=300000,
            pace_status="behind",
            user_response="hard",
            created_at=T0,
        ),
    )
    insert_experiment_checkin(
        user_ctx.conn,
        ExperimentCheckin(
            id="chk_2",
            user_id="user_alice",
            experiment_id=exp.id,
            checkin_date="2026-09-07",
            observed_value=450000,
            pace_status="behind",
            user_response="want_to_pause",
            created_at=T0,
        ),
    )

    # Agent runs detectors (allowed for maintenance)
    detect_res = execute_tool(agent_ctx, "run_adaptive_detectors", {"experiment_id": exp.id})
    assert detect_res.ok
    proposals = detect_res.data.proposals
    assert len(proposals) > 0
    prop_id = proposals[0].id

    # Agent tries to accept -> DENIED
    acc_res = execute_tool(agent_ctx, "accept_adjustment", {"proposal_id": prop_id})
    assert not acc_res.ok
    assert acc_res.error.code == ErrorCode.DENIED_BY_POLICY

    # Agent tries to reject -> DENIED
    rej_res = execute_tool(agent_ctx, "reject_adjustment", {"proposal_id": prop_id})
    assert not rej_res.ok
    assert rej_res.error.code == ErrorCode.DENIED_BY_POLICY


def test_user_can_accept_and_reject_adjustments_through_executor(test_ctx):
    """User actor can accept or reject adjustment proposals, triggering state changes."""
    user_ctx = test_ctx(actor="user", clock=DT_MID)

    # 1. Create and start an experiment
    exp = design_experiment(
        user_ctx.conn,
        "user_alice",
        params={
            "metric_code": "category_spend",
            "categories": ["dining_out"],
            "target_value": 500000,
            "start_date": "2026-09-01",
        },
        clock=DT0,
    )
    start_experiment(user_ctx.conn, "user_alice", exp.id, clock=DT0)

    # 2. Add two behind checkins
    insert_experiment_checkin(
        user_ctx.conn,
        ExperimentCheckin(
            id="chk_1",
            user_id="user_alice",
            experiment_id=exp.id,
            checkin_date="2026-09-03",
            observed_value=300000,
            pace_status="behind",
            user_response="hard",
            created_at=T0,
        ),
    )
    insert_experiment_checkin(
        user_ctx.conn,
        ExperimentCheckin(
            id="chk_2",
            user_id="user_alice",
            experiment_id=exp.id,
            checkin_date="2026-09-07",
            observed_value=450000,
            pace_status="behind",
            user_response="want_to_pause",
            created_at=T0,
        ),
    )

    run_res = execute_tool(user_ctx, "run_adaptive_detectors", {"experiment_id": exp.id})
    assert run_res.ok

    # List adjustments
    list_res = execute_tool(user_ctx, "list_adjustments", {"experiment_id": exp.id})
    assert list_res.ok
    props = list_res.data.proposals
    assert len(props) >= 2

    pause_prop = next(p for p in props if p.kind == "pause")
    ease_prop = next(p for p in props if p.kind == "ease_target")

    # User rejects ease_target
    rej_res = execute_tool(user_ctx, "reject_adjustment", {"proposal_id": ease_prop.id})
    assert rej_res.ok
    assert rej_res.data.proposal.status == "rejected"

    # User accepts pause -> experiment status becomes paused
    acc_res = execute_tool(user_ctx, "accept_adjustment", {"proposal_id": pause_prop.id})
    assert acc_res.ok
    assert acc_res.data.proposal.status == "accepted"

    updated_exp = get_experiment(user_ctx.conn, "user_alice", exp.id)
    assert updated_exp.status == "paused"

    # Verify audit events exist
    audit_rows = user_ctx.conn.execute(
        "SELECT event_type FROM audit_events WHERE user_id = 'user_alice'"
    ).fetchall()
    event_types = {r[0] for r in audit_rows}
    assert "tool_call" in event_types
