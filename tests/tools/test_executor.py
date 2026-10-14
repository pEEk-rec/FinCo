from datetime import datetime

import pytest

from copilot.audit.events import list_events
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import PolicySettings
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry, register

CALLS: list[str] = []


class DummyInput(ToolInput):
    val: int


class DummyOutput(ToolOutput):
    result: int


def read_handler(ctx, val: int) -> dict:
    CALLS.append("read_tool")
    return {"result": val * 2}


def write_handler(ctx, val: int) -> dict:
    CALLS.append("write_tool")
    ctx.conn.execute(
        "INSERT INTO users (id, created_at) VALUES ('new_user', '2023-01-01T00:00:00Z')"
    )
    return {"result": val}


def error_handler(ctx, val: int) -> dict:
    raise RuntimeError("Intentional crash")


def not_found_handler(ctx, val: int) -> dict:
    raise ToolFailure(ErrorCode.NOT_FOUND, f"Thing {val} not found")


def write_then_crash(ctx, val: int) -> dict:
    ctx.conn.execute("INSERT INTO users (id, created_at) VALUES ('ghost', '2023-01-01T00:00:00Z')")
    raise RuntimeError("crash after write")


def write_bad_output(ctx, val: int) -> dict:
    ctx.conn.execute("INSERT INTO users (id, created_at) VALUES ('ghost', '2023-01-01T00:00:00Z')")
    return {"result": "not-an-int"}


def custom_fail_handler(ctx, val: int) -> dict:
    ctx.conn.execute("INSERT INTO users (id, created_at) VALUES ('ghost', '2023-01-01T00:00:00Z')")
    raise ToolFailure(
        ErrorCode.INVALID_INPUT,
        "Custom domain refusal",
        audit_event_type="plan_rejected",
        audit_metadata={"refusal_reason": "disallowed_step", "step_idx": val},
    )


TOOLS = {
    "read_tool": (SideEffect.READ, read_handler),
    "write_tool": (SideEffect.WRITE_LOGICAL, write_handler),
    "error_tool": (SideEffect.READ, error_handler),
    "not_found_tool": (SideEffect.READ, not_found_handler),
    "crash_tool": (SideEffect.READ, write_then_crash),
    "bad_output_tool": (SideEffect.READ, write_bad_output),
    "unruled_write": (SideEffect.WRITE_LOGICAL, write_handler),
    "external_tool": (SideEffect.EXTERNAL, read_handler),
    "custom_fail_tool": (SideEffect.READ, custom_fail_handler),
}


@pytest.fixture
def ctx():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2023-01-01T00:00:00Z')")
    conn.commit()
    policy = PolicySettings.model_validate(
        {
            "side_effects": {"read": {"decision": "allow"}},
            "tools": {
                "write_tool": {"decision": "needs_approval"},
                "external_tool": {"decision": "allow"},
            },
        }
    )
    clock = datetime(2024, 1, 15, 12, 0, tzinfo=IST)
    return ExecutionContext(conn, "u1", "run1", policy, clock)


@pytest.fixture(autouse=True)
def setup_registry():
    clear_registry()
    CALLS.clear()
    for name, (side_effect, handler) in TOOLS.items():
        register(ToolSpec(name, name, DummyInput, DummyOutput, side_effect, handler))
    yield
    clear_registry()


def user_exists(ctx, user_id: str) -> bool:
    row = ctx.conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)).fetchone()
    return row[0] == 1


def test_read_tool_allowed_and_audited(ctx):
    result = execute_tool(ctx, "read_tool", {"val": 10})
    assert result.ok
    assert result.data.result == 20

    [event] = list_events(ctx.conn, "u1")
    assert event.event_type == "tool_call"
    assert event.policy_decision == "allow"
    assert event.entity_id == "read_tool"
    assert event.run_id == "run1"
    assert event.actor == "agent"
    assert event.before == {"val": 10}
    assert event.after == {"result": 20}
    assert event.occurred_at == "2024-01-15T06:30:00Z"  # context clock is used


def test_write_tool_blocked_without_approval_and_handler_not_called(ctx):
    result = execute_tool(ctx, "write_tool", {"val": 10}, approved=False)
    assert result.error.code == ErrorCode.APPROVAL_REQUIRED
    assert CALLS == []
    assert not user_exists(ctx, "new_user")

    [event] = list_events(ctx.conn, "u1")
    assert event.policy_decision == "needs_approval"
    assert event.metadata == {"approved": False, "error_code": "APPROVAL_REQUIRED"}


def test_write_tool_runs_with_approval(ctx):
    result = execute_tool(ctx, "write_tool", {"val": 10}, approved=True)
    assert result.ok
    assert CALLS == ["write_tool"]
    assert user_exists(ctx, "new_user")
    assert list_events(ctx.conn, "u1")[0].metadata["approved"] is True


def test_tool_with_no_rule_is_denied_and_not_called(ctx):
    result = execute_tool(ctx, "unruled_write", {"val": 1}, approved=True)
    assert result.error.code == ErrorCode.DENIED_BY_POLICY
    assert CALLS == []
    assert list_events(ctx.conn, "u1")[0].policy_decision == "deny"


def test_external_tool_denied_even_when_policy_allows(ctx):
    result = execute_tool(ctx, "external_tool", {"val": 1}, approved=True)
    assert result.error.code == ErrorCode.DENIED_BY_POLICY
    assert CALLS == []


def test_unknown_tool_not_found_and_audited(ctx):
    result = execute_tool(ctx, "transfer_money", {"to": "x", "amount": 10**9})
    assert result.error.code == ErrorCode.NOT_FOUND
    [event] = list_events(ctx.conn, "u1")
    assert event.entity_id == "transfer_money"
    assert event.policy_decision is None
    assert event.before == {"to": "x", "amount": 10**9}


@pytest.mark.parametrize(
    "raw_input", [{"val": "ten"}, {}, {"val": 1, "extra": 2}, None, [1, 2], "val=1"]
)
def test_invalid_input_returns_invalid_input_and_is_audited(ctx, raw_input):
    result = execute_tool(ctx, "read_tool", raw_input)
    assert result.error.code == ErrorCode.INVALID_INPUT
    assert CALLS == []
    assert len(list_events(ctx.conn, "u1")) == 1


def test_non_json_input_never_raises(ctx):
    result = execute_tool(ctx, "read_tool", {"val": object()})
    assert result.error.code == ErrorCode.INVALID_INPUT
    assert "object object" in list_events(ctx.conn, "u1")[0].before["val"]


def test_handler_exception_becomes_tool_failure_and_is_audited(ctx):
    result = execute_tool(ctx, "error_tool", {"val": 10})
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert "Intentional crash" in result.error.message
    [event] = list_events(ctx.conn, "u1")
    assert event.metadata["error_code"] == "TOOL_FAILURE"
    assert "Intentional crash" in event.reason


def test_tool_failure_keeps_its_code(ctx):
    result = execute_tool(ctx, "not_found_tool", {"val": 7})
    assert result.error.code == ErrorCode.NOT_FOUND
    assert result.error.message == "Thing 7 not found"


def test_failed_handler_writes_are_rolled_back(ctx):
    result = execute_tool(ctx, "crash_tool", {"val": 1})
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert not user_exists(ctx, "ghost")
    assert [e.policy_decision for e in list_events(ctx.conn, "u1")] == ["allow"]


def test_invalid_output_rolls_back_handler_writes(ctx):
    result = execute_tool(ctx, "bad_output_tool", {"val": 1})
    assert result.error.code == ErrorCode.TOOL_FAILURE
    assert not user_exists(ctx, "ghost")


def test_audit_failure_rolls_back_the_action(ctx, monkeypatch):
    import copilot.tools.executor as executor

    def broken_audit(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(executor, "record_event", broken_audit)
    result = execute_tool(ctx, "write_tool", {"val": 1}, approved=True)
    assert result.error.code == ErrorCode.INTERNAL
    assert "audit failed" in result.error.message
    assert not user_exists(ctx, "new_user")


def test_every_outcome_is_audited(ctx):
    execute_tool(ctx, "read_tool", {"val": 1})
    execute_tool(ctx, "write_tool", {"val": 1})
    execute_tool(ctx, "unruled_write", {"val": 1})
    execute_tool(ctx, "nope", {})
    execute_tool(ctx, "read_tool", {"val": "x"})
    execute_tool(ctx, "error_tool", {"val": 1})
    codes = [e.metadata["error_code"] for e in list_events(ctx.conn, "u1", run_id="run1")]
    assert codes == [
        None,
        "APPROVAL_REQUIRED",
        "DENIED_BY_POLICY",
        "NOT_FOUND",
        "INVALID_INPUT",
        "TOOL_FAILURE",
    ]


def test_failure_path_custom_audit_event_and_metadata(ctx):
    """
    Verify that when ToolFailure carries custom audit_event_type and audit_metadata:
    1. Handler internal writes are rolled back by savepoint.
    2. ToolResult reflects failure with ErrorCode.
    3. The failure audit event survives with the custom event_type and extra metadata.
    """
    result = execute_tool(ctx, "custom_fail_tool", {"val": 42})
    assert not result.ok
    assert result.error.code == ErrorCode.INVALID_INPUT
    assert "Custom domain refusal" in result.error.message

    # Handler writes rolled back
    assert not user_exists(ctx, "ghost")

    # Audit event preserved with custom event_type and metadata
    events = list_events(ctx.conn, "u1", run_id="run1")
    custom_events = [e for e in events if e.event_type == "plan_rejected"]
    assert len(custom_events) == 1
    evt = custom_events[0]
    assert evt.metadata["refusal_reason"] == "disallowed_step"
    assert evt.metadata["step_idx"] == 42
    assert evt.metadata["error_code"] == "INVALID_INPUT"

