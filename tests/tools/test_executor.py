import pytest
from pydantic import BaseModel

from copilot.audit.events import list_events
from copilot.core.errors import ErrorCode
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import PolicySettings
from copilot.tools.contracts import SideEffect, ToolSpec
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry, list_specs, register


class DummyInput(BaseModel):
    val: int


class DummyOutput(BaseModel):
    result: int


def read_handler(ctx, val: int) -> dict:
    return {"result": val * 2}


def write_handler(ctx, val: int) -> dict:
    ctx.conn.execute(
        "INSERT INTO users (id, created_at) VALUES ('new_user', '2023-01-01T00:00:00Z')"
    )
    return {"result": val}


def error_handler(ctx, val: int) -> dict:
    raise RuntimeError("Intentional crash")


@pytest.fixture
def ctx():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")

    policy = PolicySettings(
        default="deny",
        side_effects={
            "read": {"decision": "allow"},
            "write_logical": {"decision": "needs_approval"},
            "external": {"decision": "deny"},
        },
        tools={"read_tool": {"decision": "allow"}, "write_tool": {"decision": "needs_approval"}},
    )
    return ExecutionContext(conn, "u1", "run1", policy)


@pytest.fixture(autouse=True)
def setup_registry():
    clear_registry()

    register(
        ToolSpec(
            name="read_tool",
            description="Read",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.READ,
            handler=read_handler,
        )
    )

    register(
        ToolSpec(
            name="write_tool",
            description="Write",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.WRITE_LOGICAL,
            handler=write_handler,
        )
    )

    register(
        ToolSpec(
            name="error_tool",
            description="Error",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.READ,
            handler=error_handler,
        )
    )

    yield
    clear_registry()


def test_read_tool_allowed_and_audited(ctx):
    result = execute_tool(ctx, "read_tool", {"val": 10})
    assert result.ok
    assert result.data.result == 20

    events = list_events(ctx.conn, "u1")
    assert len(events) == 1
    assert events[0]["event_type"] == "tool_execution"
    assert events[0]["policy_decision"] == "allow"
    assert events[0]["entity_id"] == "read_tool"


def test_write_tool_blocked_without_approval(ctx):
    result = execute_tool(ctx, "write_tool", {"val": 10}, approved=False)
    assert not result.ok
    assert result.error.code == ErrorCode.APPROVAL_REQUIRED

    # Verify handler NOT called (no new user inserted)
    users = ctx.conn.execute("SELECT * FROM users WHERE id = 'new_user'").fetchall()
    assert len(users) == 0

    events = list_events(ctx.conn, "u1")
    assert len(events) == 1
    assert events[0]["policy_decision"] == "needs_approval"


def test_write_tool_runs_with_approval(ctx):
    result = execute_tool(ctx, "write_tool", {"val": 10}, approved=True)
    assert result.ok

    users = ctx.conn.execute("SELECT * FROM users WHERE id = 'new_user'").fetchall()
    assert len(users) == 1


def test_tool_no_policy_denied(ctx):
    register(
        ToolSpec(
            name="unknown_tool",
            description="Unknown",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.READ,
            handler=read_handler,
        )
    )

    # Remove all policy rules
    ctx.policy = PolicySettings(default="deny", side_effects={}, tools={})

    result = execute_tool(ctx, "unknown_tool", {"val": 10})
    assert not result.ok
    assert result.error.code == ErrorCode.DENIED_BY_POLICY


def test_handler_exception_returns_failure(ctx):
    result = execute_tool(ctx, "error_tool", {"val": 10})
    assert not result.ok
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert "Intentional crash" in result.error.message

    events = list_events(ctx.conn, "u1")
    assert len(events) == 1
    assert "failed" in events[0]["reason"]


def test_no_money_movement_tools_registered():
    """
    Assert that no tool name contains words like transfer, pay, send_money, trade,
    withdraw, deposit; also assert no SideEffect.EXTERNAL tool is registered in Phase 0.
    """
    banned_words = ["transfer", "pay", "send_money", "trade", "withdraw", "deposit"]

    for spec in list_specs():
        assert spec.side_effect != SideEffect.EXTERNAL, (
            f"External tool {spec.name} is not allowed in Phase 0"
        )
        for word in banned_words:
            assert word not in spec.name.lower(), (
                f"Tool {spec.name} contains banned money-movement word '{word}'"
            )


def test_failed_handler_writes_are_rolled_back(ctx):
    def write_then_crash(ctx, val: int) -> dict:
        ctx.conn.execute(
            "INSERT INTO users (id, created_at) VALUES ('ghost', '2023-01-01T00:00:00Z')"
        )
        raise RuntimeError("crash after write")

    register(
        ToolSpec(
            name="crash_tool",
            description="Crash",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.READ,
            handler=write_then_crash,
        )
    )
    ctx.policy = PolicySettings(default="deny", tools={"crash_tool": {"decision": "allow"}})

    result = execute_tool(ctx, "crash_tool", {"val": 1})
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert ctx.conn.execute("SELECT COUNT(*) FROM users WHERE id = 'ghost'").fetchone()[0] == 0
    # The failure itself is still audited
    assert [e["policy_decision"] for e in list_events(ctx.conn, "u1")] == ["allow"]


def test_invalid_output_rolls_back_handler_writes(ctx):
    def write_bad_output(ctx, val: int) -> dict:
        ctx.conn.execute(
            "INSERT INTO users (id, created_at) VALUES ('ghost', '2023-01-01T00:00:00Z')"
        )
        return {"result": "not-an-int"}

    register(
        ToolSpec(
            name="bad_output_tool",
            description="Bad",
            input_model=DummyInput,
            output_model=DummyOutput,
            side_effect=SideEffect.READ,
            handler=write_bad_output,
        )
    )
    ctx.policy = PolicySettings(default="deny", tools={"bad_output_tool": {"decision": "allow"}})

    result = execute_tool(ctx, "bad_output_tool", {"val": 1})
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert ctx.conn.execute("SELECT COUNT(*) FROM users WHERE id = 'ghost'").fetchone()[0] == 0
