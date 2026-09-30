import pytest
from pydantic import ValidationError

from copilot.core.errors import ErrorCode, ToolError
from copilot.models.run_state import (
    PendingAction,
    RunState,
    summarize_tool_result,
    to_llm_projection,
)
from copilot.tools.contracts import ToolOutput, ToolResult


class Balance(ToolOutput):
    balance_paise: int


def full_state() -> RunState:
    return RunState(
        run_id="r1",
        user_id="u1",
        intent="how much did I spend",
        plan=["aggregate_spend_by_category"],
        observations=["Food is 40% of spend"],
        tool_results=[
            summarize_tool_result(
                "get_balance", ToolResult(ok=True, data=Balance(balance_paise=5))
            ),
            summarize_tool_result(
                "recategorize_transaction",
                ToolResult(
                    ok=False, error=ToolError(code=ErrorCode.APPROVAL_REQUIRED, message="ask")
                ),
            ),
        ],
        pending_actions=[
            PendingAction(
                tool_name="recategorize_transaction",
                tool_input={"transaction_id": "t1", "new_category_id": "food"},
                reason="User asked to move it",
            )
        ],
        confidence=0.7,
        created_at="2024-01-15T17:30:00+05:30",
    )


def test_round_trips_through_json():
    state = full_state()
    restored = RunState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.schema_version == 1
    assert restored.created_at == "2024-01-15T12:00:00Z"  # normalised


def test_tool_result_summary():
    ok, failed = full_state().tool_results
    assert (ok.ok, ok.data, ok.error_code) == (True, {"balance_paise": 5}, None)
    assert (failed.ok, failed.error_code, failed.data) == (False, "APPROVAL_REQUIRED", None)


def test_unknown_schema_version_rejected():
    data = full_state().model_dump(mode="json") | {"schema_version": 2}
    with pytest.raises(ValidationError):
        RunState.model_validate(data)


def test_projection_contains_only_requested_fields():
    projection = to_llm_projection(full_state(), ["intent", "plan"])
    assert projection == {"intent": "how much did I spend", "plan": ["aggregate_spend_by_category"]}


def test_projection_rejects_unknown_fields():
    with pytest.raises(ValueError, match="intnet"):
        to_llm_projection(full_state(), ["intnet"])


@pytest.mark.parametrize("change", [{"confidence": 1.5}, {"surprise": 1}, {"run_id": ""}])
def test_invalid_state_rejected(change):
    with pytest.raises(ValidationError):
        RunState.model_validate(full_state().model_dump() | change)
