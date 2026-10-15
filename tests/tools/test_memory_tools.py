"""
Tool execution tests for Behavioural Memory Tools (PLAN_PHASE3 Stage 3.8 & Section 5.8).

Verifies:
- All tools execute strictly through execute_tool choke point
- Policy rules respected: read/refresh allowed for agent; confirm/reject/edit/forget strictly user-only
- Content-free audit trails for forgetting
- Bounded edit validation (unbounded keys rejected)
- Multi-tenant isolation through executor
"""

from datetime import UTC, datetime

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase3 import (
    get_memory_item,
    insert_memory_evidence,
    insert_memory_item,
    list_memory_evidence,
)
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, User
from copilot.models.phase3 import MemoryEvidence, MemoryItem
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.memory import register_memory_tools
from copilot.tools.registry import clear_registry


@pytest.fixture
def conn():
    """In-memory SQLite connection with migrations applied."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def policy():
    """Policy settings matching config/policy.yaml for memory tools."""
    return PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "deny"},
            },
            "tools": {
                "list_memories": {"decision": "allow"},
                "explain_memory": {"decision": "allow"},
                "confirm_memory": {"agent": "deny", "user": "allow"},
                "reject_memory": {"agent": "deny", "user": "allow"},
                "edit_memory_statement": {"agent": "deny", "user": "allow"},
                "forget_memory": {"agent": "deny", "user": "allow"},
                "refresh_memories": {"agent": "allow", "user": "allow"},
                "record_contextual_exception": {"agent": "needs_approval", "user": "allow"},
            },
        }
    )


@pytest.fixture(autouse=True)
def setup_tools():
    """Register tools in clean registry before each test."""
    clear_registry()
    register_memory_tools()
    yield
    clear_registry()


def _setup_user(conn, user_id: str = "u_tool"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=10000000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat in ["dining", "utilities", "travel"]:
        insert_category(
            conn,
            Category(
                id=f"{cat}_{user_id}",
                user_id=user_id,
                name=cat.capitalize(),
                created_at="2026-01-01T00:00:00Z",
            ),
        )


# -------------------------------------------------------------------------------------------------
# 1. Read Tools: list_memories and explain_memory
# -------------------------------------------------------------------------------------------------

def test_list_and_explain_memories_through_executor(conn, policy):
    """Read tools list_memories and explain_memory execute through executor and return structured data."""
    user_id = "u_read"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Insert a sample memory item and evidence
    mem = MemoryItem(
        id="mem_sample_1",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"category": "dining", "pattern": "weekend_heavy", "ratio_bp": 18000},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    mev = MemoryEvidence(
        id="mev_sample_1",
        user_id=user_id,
        memory_id="mem_sample_1",
        polarity="supports",
        ref_kind="txn",
        ref_id="tx_123",
        observed_at="2026-04-01T00:00:00Z",
        weight_bp=1200,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_evidence(conn, mev)

    ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_tool_read",
        policy=policy,
        clock=clock,
        actor="agent",
    )

    # Execute list_memories
    res = execute_tool(ctx, "list_memories", {})
    assert res.ok is True
    memories = res.data.memories
    assert len(memories) == 1
    assert memories[0].id == "mem_sample_1"
    assert memories[0].statement_json["pattern"] == "weekend_heavy"
    assert memories[0].evidence_count == 1

    # Execute explain_memory
    res_exp = execute_tool(ctx, "explain_memory", {"memory_id": "mem_sample_1"})
    assert res_exp.ok is True
    assert res_exp.data.memory.id == "mem_sample_1"
    assert len(res_exp.data.evidence) == 1
    assert res_exp.data.evidence[0].ref_id == "tx_123"

    # Non-existent ID returns NOT_FOUND
    res_not_found = execute_tool(ctx, "explain_memory", {"memory_id": "mem_non_existent"})
    assert res_not_found.ok is False
    assert res_not_found.error.code == ErrorCode.NOT_FOUND


# -------------------------------------------------------------------------------------------------
# 2. Policy Governance: User Actor Only for Confirm/Reject/Edit/Forget
# -------------------------------------------------------------------------------------------------

def test_governance_user_tools_denied_for_agent(conn, policy):
    """Write operations (confirm, reject, edit, forget) are strictly DENIED for agent actor."""
    user_id = "u_gov"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    mem = MemoryItem(
        id="mem_gov_1",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"category": "dining", "pattern": "weekend_heavy"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    agent_ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_agent",
        policy=policy,
        clock=clock,
        actor="agent",
    )

    # Agent attempts to confirm -> DENIED
    res_c = execute_tool(agent_ctx, "confirm_memory", {"memory_id": "mem_gov_1"})
    assert res_c.ok is False
    assert res_c.error.code == ErrorCode.DENIED_BY_POLICY

    # Agent attempts to reject -> DENIED
    res_r = execute_tool(agent_ctx, "reject_memory", {"memory_id": "mem_gov_1"})
    assert res_r.ok is False
    assert res_r.error.code == ErrorCode.DENIED_BY_POLICY

    # Agent attempts to edit -> DENIED
    res_e = execute_tool(agent_ctx, "edit_memory_statement", {"memory_id": "mem_gov_1", "updates": {"pattern": "payday_spike"}})
    assert res_e.ok is False
    assert res_e.error.code == ErrorCode.DENIED_BY_POLICY

    # Agent attempts to forget -> DENIED
    res_f = execute_tool(agent_ctx, "forget_memory", {"memory_id": "mem_gov_1"})
    assert res_f.ok is False
    assert res_f.error.code == ErrorCode.DENIED_BY_POLICY


def test_user_actor_can_confirm_reject_and_edit_memory(conn, policy):
    """User actor is allowed to confirm, edit, and reject memory items."""
    user_id = "u_user_write"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    mem = MemoryItem(
        id="mem_uw_1",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy", "ratio_bp": 15000},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    user_ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_user",
        policy=policy,
        clock=clock,
        actor="user",
    )

    # 1. User confirms memory
    res_c = execute_tool(user_ctx, "confirm_memory", {"memory_id": "mem_uw_1"})
    assert res_c.ok is True
    assert res_c.data.status == "active"
    assert res_c.data.user_confirmed is True

    # 2. User edits bounded statement
    res_e = execute_tool(
        user_ctx,
        "edit_memory_statement",
        {"memory_id": "mem_uw_1", "updates": {"ratio_bp": 22000}},
    )
    assert res_e.ok is True
    assert res_e.data.statement_json["ratio_bp"] == 22000

    # 3. User rejects memory
    res_r = execute_tool(user_ctx, "reject_memory", {"memory_id": "mem_uw_1"})
    assert res_r.ok is True
    assert res_r.data.status == "rejected"


# -------------------------------------------------------------------------------------------------
# 3. Bounded Field Editing Enforcement
# -------------------------------------------------------------------------------------------------

def test_edit_memory_statement_rejects_unbounded_fields(conn, policy):
    """edit_memory_statement rejects attempts to add arbitrary keys or unallowed fields."""
    user_id = "u_edit_bounds"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    mem = MemoryItem(
        id="mem_eb_1",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    user_ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_user_bounds",
        policy=policy,
        clock=clock,
        actor="user",
    )

    # Attempt to modify unallowed field 'arbitrary_key'
    res_bad = execute_tool(
        user_ctx,
        "edit_memory_statement",
        {"memory_id": "mem_eb_1", "updates": {"arbitrary_key": "some text"}},
    )
    assert res_bad.ok is False
    assert res_bad.error.code == ErrorCode.INVALID_INPUT


# -------------------------------------------------------------------------------------------------
# 4. Forget Memory Through Executor (Content-Free Audit)
# -------------------------------------------------------------------------------------------------

def test_forget_memory_through_executor_clears_content(conn, policy):
    """forget_memory through executor clears content, deletes evidence, and records clean audit."""
    user_id = "u_exec_forget"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    mem = MemoryItem(
        id="mem_ef_1",
        user_id=user_id,
        kind="contextual_exception",
        subject_key="category:dining|period:2026-11",
        statement_json={"category": "dining", "period": "2026-11", "reason": "medical"},
        source="user_stated",
        status="active",
        prior_bp=6000,
        user_confirmed=True,
        confidence_bp=6000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    mev = MemoryEvidence(
        id="mev_ef_1",
        user_id=user_id,
        memory_id="mem_ef_1",
        polarity="supports",
        ref_kind="txn",
        ref_id="tx_secret",
        observed_at="2026-04-01T00:00:00Z",
        weight_bp=6000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_evidence(conn, mev)

    user_ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_user_forget",
        policy=policy,
        clock=clock,
        actor="user",
    )

    res_f = execute_tool(user_ctx, "forget_memory", {"memory_id": "mem_ef_1"})
    assert res_f.ok is True
    assert res_f.data.forgotten is True

    # Database verification
    item = get_memory_item(conn, user_id, "mem_ef_1")
    assert item is not None
    assert item.status == "forgotten"
    assert item.statement_json == {}

    ev_list = list_memory_evidence(conn, user_id, "mem_ef_1")
    assert len(ev_list) == 0

    # Audit event verification
    audit_row = conn.execute(
        """
        SELECT event_type, before_json, after_json
        FROM audit_events
        WHERE user_id = ? AND entity_id = 'mem_ef_1' AND event_type = 'memory_forgotten'
        """,
        (user_id,),
    ).fetchone()
    assert audit_row is not None
    ev_type, before_json, after_json = audit_row
    assert "medical" not in before_json
    assert "medical" not in after_json


# -------------------------------------------------------------------------------------------------
# 5. Refresh Memories and Record Contextual Exception Through Executor
# -------------------------------------------------------------------------------------------------

def test_refresh_memories_through_executor(conn, policy):
    """refresh_memories executes through executor and returns summary counts."""
    user_id = "u_exec_refresh"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_refresh",
        policy=policy,
        clock=clock,
        actor="agent",
    )

    res = execute_tool(ctx, "refresh_memories", {})
    assert res.ok is True
    assert res.data.user_id == user_id
    assert "counts" in res.data.model_dump()


def test_record_contextual_exception_through_executor(conn, policy):
    """record_contextual_exception validates reason and records active memory."""
    user_id = "u_exec_ctx_exc"
    _setup_user(conn, user_id)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    user_ctx = ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id="run_ctx_exc",
        policy=policy,
        clock=clock,
        actor="user",
    )

    # Valid allowed reason
    res = execute_tool(
        user_ctx,
        "record_contextual_exception",
        {
            "category": "dining",
            "period": "2026-11",
            "reason": "festival",
        },
    )
    assert res.ok is True
    assert res.data.status == "active"
    assert res.data.statement_json["reason"] == "festival"

    # Invalid reason
    res_bad = execute_tool(
        user_ctx,
        "record_contextual_exception",
        {
            "category": "dining",
            "period": "2026-11",
            "reason": "unauthorized_reason",
        },
    )
    assert res_bad.ok is False
    assert res_bad.error.code == ErrorCode.INVALID_INPUT


# -------------------------------------------------------------------------------------------------
# 6. Multi-Tenant Isolation Through Executor
# -------------------------------------------------------------------------------------------------

def test_executor_multi_tenant_isolation(conn, policy):
    """User A cannot explain, confirm, or forget User B's memory items."""
    user_a = "u_exec_a"
    user_b = "u_exec_b"
    _setup_user(conn, user_a)
    _setup_user(conn, user_b)
    clock = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    mem_b = MemoryItem(
        id="mem_b_sec",
        user_id=user_b,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at="2026-04-01T00:00:00Z",
    )
    insert_memory_item(conn, mem_b)

    ctx_a = ExecutionContext(
        conn=conn,
        user_id=user_a,
        run_id="run_a",
        policy=policy,
        clock=clock,
        actor="user",
    )

    # User A tries to explain B's memory -> NOT_FOUND
    res_exp = execute_tool(ctx_a, "explain_memory", {"memory_id": "mem_b_sec"})
    assert res_exp.ok is False
    assert res_exp.error.code == ErrorCode.NOT_FOUND

    # User A tries to confirm B's memory -> NOT_FOUND
    res_c = execute_tool(ctx_a, "confirm_memory", {"memory_id": "mem_b_sec"})
    assert res_c.ok is False
    assert res_c.error.code == ErrorCode.NOT_FOUND

    # User A tries to forget B's memory -> NOT_FOUND
    res_f = execute_tool(ctx_a, "forget_memory", {"memory_id": "mem_b_sec"})
    assert res_f.ok is False
    assert res_f.error.code == ErrorCode.NOT_FOUND
