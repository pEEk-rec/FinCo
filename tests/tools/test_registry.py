import pytest
from pydantic import BaseModel

from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolResult, ToolSpec
from copilot.tools.registry import clear_registry, get, list_specs, register


class DummyInput(ToolInput):
    amount: int


class DummyOutput(ToolOutput):
    result: str


def dummy_handler(ctx, amount: int) -> dict:
    return {"result": f"Processed {amount}"}


def make_spec(**overrides) -> ToolSpec:
    fields = {
        "name": "dummy_tool",
        "description": "A dummy tool",
        "input_model": DummyInput,
        "output_model": DummyOutput,
        "side_effect": SideEffect.READ,
        "handler": dummy_handler,
    }
    fields.update(overrides)
    return ToolSpec(**fields)


@pytest.fixture(autouse=True)
def setup_registry():
    clear_registry()
    yield
    clear_registry()


def test_register_and_fetch():
    register(make_spec())
    fetched = get("dummy_tool")
    assert fetched is not None
    assert fetched.name == "dummy_tool"
    assert [s.name for s in list_specs()] == ["dummy_tool"]


def test_list_specs_sorted():
    register(make_spec(name="zeta"))
    register(make_spec(name="alpha"))
    assert [s.name for s in list_specs()] == ["alpha", "zeta"]


def test_duplicate_name_rejected():
    register(make_spec())
    with pytest.raises(ValueError, match="already registered"):
        register(make_spec())


def test_unknown_tool_is_none():
    assert get("unknown_tool") is None


def test_register_rejects_non_spec():
    with pytest.raises(TypeError):
        register({"name": "x"})  # type: ignore[arg-type]


class PlainModel(BaseModel):
    x: int


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "Transfer Money"},
        {"description": " "},
        {"input_model": PlainModel},
        {"output_model": dict},
        {"side_effect": "read"},
        {"handler": None},
    ],
)
def test_malformed_spec_rejected(overrides):
    with pytest.raises((ValueError, TypeError)):
        make_spec(**overrides)


def test_spec_is_immutable():
    spec = make_spec()
    with pytest.raises(AttributeError):
        spec.side_effect = SideEffect.EXTERNAL  # type: ignore[misc]


def test_side_effect_has_no_money_movement_class():
    assert {e.value for e in SideEffect} == {"read", "write_logical", "external"}


def test_tool_result_ok_and_error_are_exclusive():
    from copilot.core.errors import ErrorCode, ToolError

    with pytest.raises(ValueError):
        ToolResult(ok=True, error=ToolError(code=ErrorCode.INTERNAL, message="x"))
    with pytest.raises(ValueError):
        ToolResult(ok=False)
