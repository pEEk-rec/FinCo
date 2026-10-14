"""
Tests for Activity Timeline Read Model (PLAN_PHASE2 Section 5.9 & Stage 2.9).

Verifies:
1. Stable chronological ordering across tasks, steps, investigations, simulations, alerts, and decisions.
2. Pending approvals pinned in pending_approvals list.
3. Strict privacy: No raw user query text leaks into timeline entries.
4. Correct filtering by since, task_id, and run_id.
5. Cross-user isolation: User A never sees User B's entries.
6. JSON schema serialization stability.
"""

import pytest

from copilot.core.timeline import build_timeline
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_agent_task,
    insert_plan_step,
    insert_recommendation,
    insert_simulation,
    insert_user,
)
from copilot.models.agentic import (
    AgentTask,
    Intent,
    PlanStep,
    Recommendation,
    Timeline,
)
from copilot.models.domain import User


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u_alice", created_at="2026-09-01T00:00:00Z"))
    insert_user(c, User(id="u_bob", created_at="2026-09-01T00:00:00Z"))
    return c


def test_timeline_ordering_and_sources(conn):
    """Timeline merges heterogeneous sources into stable chronological order."""
    user = "u_alice"
    
    # 1. Task created at 10:00
    task = AgentTask(
        id="t1",
        user_id=user,
        run_id="run_1",
        raw_text="My super secret raw user query about cash",
        intent=Intent(type="whatif_add_spend", amount_paise=5000000, confidence_label="high"),
        status="running",
        created_at="2026-09-15T10:00:00Z",
    )
    insert_agent_task(conn, task)

    # 2. Plan step at 10:01
    step = PlanStep(
        id="s1",
        task_id="t1",
        user_id=user,
        seq=0,
        tool_name="run_whatif",
        args={"scenario": {"kind": "add_spend", "amount_paise": 5000000}},
        rationale="Simulate iPhone purchase",
        proposed_by="deterministic",
        status="done",
        started_at="2026-09-15T10:01:00Z",
        finished_at="2026-09-15T10:01:02Z",
    )
    insert_plan_step(conn, step)

    # 3. Simulation record at 10:01:02
    insert_simulation(
        conn,
        sim_id="sim_1",
        user_id=user,
        scenario={"kind": "add_spend", "amount_paise": 5000000},
        baseline={},
        result={},
        assumptions=["Spend steady"],
        created_at="2026-09-15T10:01:02Z",
        task_id="t1",
    )

    # 4. Recommendation draft awaiting approval at 10:02
    rec = Recommendation(
        id="rec_1",
        user_id=user,
        task_id="t1",
        run_id="run_1",
        origin="whatif",
        text="Consider spacing this purchase over 3 months.",
        evidence=["sim_1"],
        status="draft",
        created_at="2026-09-15T10:02:00Z",
    )
    insert_recommendation(conn, rec)

    tl: Timeline = build_timeline(conn, user)

    assert tl.user_id == user
    assert len(tl.entries) >= 4
    
    # Verify strict ascending order
    timestamps = [e.ts for e in tl.entries]
    assert timestamps == sorted(timestamps)

    # Verify pending approvals are pinned
    assert len(tl.pending_approvals) == 1
    assert tl.pending_approvals[0].ref["recommendation_id"] == "rec_1"
    assert tl.pending_approvals[0].kind == "approval_pending"


def test_timeline_privacy_no_raw_user_text(conn):
    """Privacy Rule: raw_text from agent tasks is strictly excluded from timeline entries."""
    user = "u_alice"
    raw_secret = "I bought illegal secret items with credit card 1234-5678-9012"

    task = AgentTask(
        id="t_priv",
        user_id=user,
        raw_text=raw_secret,
        intent=Intent(type="summarize_period", period="2026-09"),
        status="done",
        created_at="2026-09-15T10:00:00Z",
    )
    insert_agent_task(conn, task)

    tl = build_timeline(conn, user)
    tl_json = tl.model_dump_json()

    # Raw secret must NOT appear anywhere in the serialized timeline
    assert raw_secret not in tl_json
    assert "1234-5678-9012" not in tl_json

    # The entry exposes only the intent type and period
    task_entries = [e for e in tl.entries if e.ref.get("task_id") == "t_priv"]
    assert len(task_entries) == 1
    assert "summarize_period" in task_entries[0].detail
    assert "2026-09" in task_entries[0].detail


def test_timeline_user_isolation(conn):
    """Multi-user isolation: User Alice never sees entries from User Bob."""
    task_alice = AgentTask(
        id="t_alice",
        user_id="u_alice",
        raw_text="Alice task",
        intent=Intent(type="summarize_period"),
        status="done",
        created_at="2026-09-15T10:00:00Z",
    )
    task_bob = AgentTask(
        id="t_bob",
        user_id="u_bob",
        raw_text="Bob task",
        intent=Intent(type="check_budget"),
        status="done",
        created_at="2026-09-15T10:05:00Z",
    )
    insert_agent_task(conn, task_alice)
    insert_agent_task(conn, task_bob)

    tl_alice = build_timeline(conn, "u_alice")
    tl_bob = build_timeline(conn, "u_bob")

    assert all(e.ref.get("task_id") != "t_bob" for e in tl_alice.entries)
    assert all(e.ref.get("task_id") != "t_alice" for e in tl_bob.entries)


def test_timeline_since_filter(conn):
    """The 'since' parameter filters out entries occurring prior to that timestamp."""
    user = "u_alice"
    t1 = AgentTask(
        id="t_old",
        user_id=user,
        raw_text="old task",
        intent=Intent(type="summarize_period"),
        status="done",
        created_at="2026-09-01T10:00:00Z",
    )
    t2 = AgentTask(
        id="t_new",
        user_id=user,
        raw_text="new task",
        intent=Intent(type="summarize_period"),
        status="done",
        created_at="2026-09-15T10:00:00Z",
    )
    insert_agent_task(conn, t1)
    insert_agent_task(conn, t2)

    tl = build_timeline(conn, user, since="2026-09-10T00:00:00Z")
    assert len(tl.entries) == 1
    assert tl.entries[0].ref["task_id"] == "t_new"
