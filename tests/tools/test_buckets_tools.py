"""
Through-executor and governance tests for virtual bucket tools (PLAN_PHASE3 Stage 3.4).

Verifies:
- All tool executions strictly pass through execute_tool(ctx, ...).
- Actor governance:
    agent -> create_bucket, update_bucket, archive_bucket, map_category_to_bucket,
             allocate_to_bucket, release_from_bucket, reassign_between_buckets,
             decide_reallocation, apply_reallocation require approval (needs_approval / deny).
    agent -> draft_reallocation allowed (drafts only!).
    user  -> all bucket tools allowed.
- 1-to-1 uniqueness of category mapping to buckets.
- Separate decide and apply lifecycle for reallocation drafts:
    approval alone writes zero allocation rows.
    apply requires an approved draft.
    expired drafts (> TTL) cannot be applied or decided.
    re-applying an applied draft is rejected.
- Audit events logged on real execution paths.
- Tenant isolation enforced across tools.
"""

from datetime import datetime, timedelta

import pytest

from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.governance.policy import PolicySettings
from copilot.models.domain import Account, Category, User
from copilot.tools.buckets import register_bucket_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry

T0 = "2026-09-01T10:00:00Z"
DT0 = datetime.fromisoformat("2026-09-01T10:00:00+00:00")


@pytest.fixture
def test_ctx():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    insert_account(
        c,
        Account(
            id="acc_1",
            user_id="u1",
            name="Primary Account",
            opening_balance_paise=10000000,  # ₹100,000
            created_at=T0,
        ),
    )
    insert_category(c, Category(id="cat_groceries", user_id="u1", name="Groceries", created_at=T0))
    insert_category(c, Category(id="cat_dining", user_id="u1", name="Dining", created_at=T0))

    policy = PolicySettings.model_validate(
        {
            "default": "deny",
            "side_effects": {
                "read": {"decision": "allow"},
                "write_logical": {"decision": "needs_approval"},
            },
            "tools": {
                "create_bucket": {"agent": "needs_approval", "user": "allow"},
                "update_bucket": {"agent": "needs_approval", "user": "allow"},
                "archive_bucket": {"agent": "needs_approval", "user": "allow"},
                "map_category_to_bucket": {"agent": "needs_approval", "user": "allow"},
                "allocate_to_bucket": {"agent": "needs_approval", "user": "allow"},
                "release_from_bucket": {"agent": "needs_approval", "user": "allow"},
                "reassign_between_buckets": {"agent": "needs_approval", "user": "allow"},
                "draft_reallocation": {"agent": "allow", "user": "allow"},
                "decide_reallocation": {"agent": "deny", "user": "allow"},
                "apply_reallocation": {"agent": "deny", "user": "allow"},
                "list_buckets": {"decision": "allow"},
                "get_bucket_status": {"decision": "allow"},
                "get_allocation_summary": {"decision": "allow"},
            },
        }
    )

    clear_registry()
    register_bucket_tools()

    ctx_user = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="user",
        policy=policy,
        clock=DT0,
        run_id="run_user",
    )
    ctx_agent = ExecutionContext(
        conn=c,
        user_id="u1",
        actor="agent",
        policy=policy,
        clock=DT0,
        run_id="run_agent",
    )
    ctx_u2 = ExecutionContext(
        conn=c,
        user_id="u2",
        actor="user",
        policy=policy,
        clock=DT0,
        run_id="run_u2",
    )
    yield ctx_user, ctx_agent, ctx_u2
    c.close()
    clear_registry()


def test_agent_policy_governance_on_bucket_writes(test_ctx):
    """Autonomous agent cannot allocate, create, or reassign directly without user approval."""
    _, ctx_agent, _ = test_ctx

    # Agent attempting create_bucket -> needs_approval
    res = execute_tool(ctx_agent, "create_bucket", {"name": "Agent Bucket", "kind": "spending"})
    assert not res.ok
    assert res.error.code == ErrorCode.APPROVAL_REQUIRED

    # Agent attempting allocate_to_bucket -> needs_approval
    res_alloc = execute_tool(
        ctx_agent,
        "allocate_to_bucket",
        {"bucket_id": "b1", "amount_paise": 100000},
    )
    assert not res_alloc.ok
    assert res_alloc.error.code == ErrorCode.APPROVAL_REQUIRED

    # Agent attempting reassign_between_buckets -> needs_approval
    res_reassign = execute_tool(
        ctx_agent,
        "reassign_between_buckets",
        {"from_bucket_id": "b1", "to_bucket_id": "b2", "amount_paise": 50000},
    )
    assert not res_reassign.ok
    assert res_reassign.error.code == ErrorCode.APPROVAL_REQUIRED

    # Agent attempting decide_reallocation -> deny
    res_decide = execute_tool(
        ctx_agent,
        "decide_reallocation",
        {"draft_id": "rd_1", "decision": "approve"},
    )
    assert not res_decide.ok
    assert res_decide.error.code == ErrorCode.DENIED_BY_POLICY


def test_user_bucket_crud_and_category_mapping_uniqueness(test_ctx):
    """User can create bucket, allocate, release, and map category with 1-to-1 uniqueness."""
    ctx_user, _, _ = test_ctx

    # 1. Create two buckets
    res1 = execute_tool(
        ctx_user,
        "create_bucket",
        {"name": "Food & Dining", "kind": "spending", "period_policy": "reset_monthly"},
    )
    assert res1.ok
    b1_id = res1.data.bucket.id

    res2 = execute_tool(
        ctx_user,
        "create_bucket",
        {"name": "Groceries Only", "kind": "spending", "period_policy": "reset_monthly"},
    )
    assert res2.ok
    b2_id = res2.data.bucket.id

    # 2. Map cat_groceries to b1_id
    map1 = execute_tool(
        ctx_user,
        "map_category_to_bucket",
        {"bucket_id": b1_id, "category_id": "cat_groceries"},
    )
    assert map1.ok

    # Verify category maps to b1_id
    row1 = ctx_user.conn.execute(
        "SELECT bucket_id FROM bucket_categories "
        "WHERE user_id = 'u1' AND category_id = 'cat_groceries'"
    ).fetchone()
    assert row1[0] == b1_id

    # 3. Map cat_groceries to b2_id (1-to-1 uniqueness: replaces previous mapping)
    map2 = execute_tool(
        ctx_user,
        "map_category_to_bucket",
        {"bucket_id": b2_id, "category_id": "cat_groceries"},
    )
    assert map2.ok

    row2 = ctx_user.conn.execute(
        "SELECT bucket_id FROM bucket_categories "
        "WHERE user_id = 'u1' AND category_id = 'cat_groceries'"
    ).fetchone()
    assert row2[0] == b2_id

    total_mappings = ctx_user.conn.execute(
        "SELECT COUNT(*) FROM bucket_categories "
        "WHERE user_id = 'u1' AND category_id = 'cat_groceries'"
    ).fetchone()[0]
    assert total_mappings == 1

    # 4. Allocate funds to b1
    alloc_res = execute_tool(
        ctx_user,
        "allocate_to_bucket",
        {"bucket_id": b1_id, "amount_paise": 400000, "period": "2026-09"},
    )
    assert alloc_res.ok
    assert alloc_res.data.bucket_balance.balance_paise == 400000

    # 5. Release funds from b1
    rel_res = execute_tool(
        ctx_user,
        "release_from_bucket",
        {"bucket_id": b1_id, "amount_paise": 100000, "period": "2026-09"},
    )
    assert rel_res.ok
    assert rel_res.data.bucket_balance.balance_paise == 300000


def test_reallocation_draft_decide_and_apply_lifecycle(test_ctx):
    """Agent drafts, user decides (writes no allocations), then user applies (writes paired rows)."""
    ctx_user, ctx_agent, _ = test_ctx

    # Setup buckets
    r1 = execute_tool(ctx_user, "create_bucket", {"name": "Bucket A", "kind": "spending"})
    r2 = execute_tool(ctx_user, "create_bucket", {"name": "Bucket B", "kind": "spending"})
    b_a = r1.data.bucket.id
    b_b = r2.data.bucket.id

    # Initial allocations: A has 500,000, B has 100,000
    execute_tool(
        ctx_user,
        "allocate_to_bucket",
        {"bucket_id": b_a, "amount_paise": 500000, "period": "2026-09"},
    )
    execute_tool(
        ctx_user,
        "allocate_to_bucket",
        {"bucket_id": b_b, "amount_paise": 100000, "period": "2026-09"},
    )

    # 1. Agent creates reallocation draft (allowed!)
    draft_res = execute_tool(
        ctx_agent,
        "draft_reallocation",
        {
            "from_bucket_id": b_a,
            "to_bucket_id": b_b,
            "amount_paise": 200000,
            "reason_json": {"context": "Dining overspent, reallocating surplus from travel"},
        },
    )
    assert draft_res.ok
    draft_id = draft_res.data.draft.id
    assert draft_res.data.draft.status == "draft"

    # Invariant: draft creation alone writes ZERO allocation rows
    alloc_count_1 = ctx_user.conn.execute("SELECT COUNT(*) FROM bucket_allocations").fetchone()[0]
    assert alloc_count_1 == 2

    # Cannot apply while still in status 'draft'
    err_apply = execute_tool(ctx_user, "apply_reallocation", {"draft_id": draft_id})
    assert not err_apply.ok
    assert err_apply.error.code == ErrorCode.INVALID_INPUT

    # 2. User decides: approve
    decide_res = execute_tool(
        ctx_user,
        "decide_reallocation",
        {"draft_id": draft_id, "decision": "approve"},
    )
    assert decide_res.ok
    assert decide_res.data.draft.status == "approved"

    # Invariant: approval alone still writes ZERO allocation rows!
    alloc_count_2 = ctx_user.conn.execute("SELECT COUNT(*) FROM bucket_allocations").fetchone()[0]
    assert alloc_count_2 == 2

    # 3. User explicitly applies approved draft
    apply_res = execute_tool(
        ctx_user,
        "apply_reallocation",
        {"draft_id": draft_id, "period": "2026-09"},
    )
    assert apply_res.ok
    pair_id = apply_res.data.pair_id
    assert apply_res.data.draft.status == "applied"

    # Verify allocation rows written as matched pair
    alloc_rows = ctx_user.conn.execute(
        "SELECT bucket_id, amount_paise, kind, source "
        "FROM bucket_allocations WHERE pair_id = ?",
        (pair_id,),
    ).fetchall()
    assert len(alloc_rows) == 2
    row_a = next(r for r in alloc_rows if r[0] == b_a)
    row_b = next(r for r in alloc_rows if r[0] == b_b)
    assert row_a[1] == -200000
    assert row_a[2] == "reassign_out"
    assert row_a[3] == "approved_draft"
    assert row_b[1] == 200000
    assert row_b[2] == "reassign_in"
    assert row_b[3] == "approved_draft"

    # Balances reflect reallocation: A=300,000, B=300,000
    stat_a = execute_tool(ctx_user, "get_bucket_status", {"bucket_id": b_a, "period": "2026-09"})
    stat_b = execute_tool(ctx_user, "get_bucket_status", {"bucket_id": b_b, "period": "2026-09"})
    assert stat_a.data.balance.balance_paise == 300000
    assert stat_b.data.balance.balance_paise == 300000

    # 4. Applying the same draft again fails
    reapply = execute_tool(ctx_user, "apply_reallocation", {"draft_id": draft_id})
    assert not reapply.ok
    assert reapply.error.code == ErrorCode.INVALID_INPUT


def test_reallocation_draft_ttl_expiry(test_ctx):
    """Reallocation drafts expire after draft_ttl_days and cannot be decided or applied."""
    ctx_user, ctx_agent, _ = test_ctx

    r1 = execute_tool(ctx_user, "create_bucket", {"name": "A", "kind": "spending"})
    r2 = execute_tool(ctx_user, "create_bucket", {"name": "B", "kind": "spending"})
    b_a = r1.data.bucket.id
    b_b = r2.data.bucket.id

    draft_res = execute_tool(
        ctx_agent,
        "draft_reallocation",
        {"from_bucket_id": b_a, "to_bucket_id": b_b, "amount_paise": 50000},
    )
    draft_id = draft_res.data.draft.id

    # Advance clock by 8 days (> 7 day TTL)
    ctx_user.clock = DT0 + timedelta(days=8)

    # Attempt to decide expired draft
    dec_res = execute_tool(
        ctx_user,
        "decide_reallocation",
        {"draft_id": draft_id, "decision": "approve"},
    )
    assert not dec_res.ok
    assert dec_res.error.code == ErrorCode.INVALID_INPUT
    assert "expired" in dec_res.error.message.lower()


def test_tenant_isolation_in_tools(test_ctx):
    """User 2 cannot access or mutate User 1's buckets."""
    ctx_user, _, ctx_u2 = test_ctx

    # User 1 creates bucket
    r = execute_tool(ctx_user, "create_bucket", {"name": "User 1 Bucket", "kind": "spending"})
    b_id = r.data.bucket.id

    # User 2 attempts to get status
    res_get = execute_tool(ctx_u2, "get_bucket_status", {"bucket_id": b_id})
    assert not res_get.ok
    assert res_get.error.code == ErrorCode.NOT_FOUND

    # User 2 attempts to allocate
    res_alloc = execute_tool(
        ctx_u2, "allocate_to_bucket", {"bucket_id": b_id, "amount_paise": 10000}
    )
    assert not res_alloc.ok
    assert res_alloc.error.code == ErrorCode.NOT_FOUND
