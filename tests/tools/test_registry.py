import pytest
from pydantic import BaseModel, ValidationError

from copilot.core.errors import ErrorCode, ToolError
from copilot.tools.contracts import SideEffect, ToolResult, ToolSpec
from copilot.tools.registry import clear_registry, get, list_specs, register


class DummyInput(BaseModel):
    amount: int

class DummyOutput(BaseModel):
    result: str

def dummy_handler(ctx, amount: int) -> str:
    return f"Processed {amount}"

@pytest.fixture(autouse=True)
def setup_registry():
    clear_registry()
    yield
    clear_registry()

def test_register_and_fetch():
    spec = ToolSpec(
        name="dummy_tool",
        description="A dummy tool",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.READ,
        handler=dummy_handler
    )
    register(spec)
    
    fetched = get("dummy_tool")
    assert fetched is not None
    assert fetched.name == "dummy_tool"
    
    specs = list_specs()
    assert len(specs) == 1
    assert specs[0].name == "dummy_tool"

def test_duplicate_name_rejected():
    spec = ToolSpec(
        name="dummy_tool",
        description="A dummy tool",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.READ,
        handler=dummy_handler
    )
    register(spec)
    
    with pytest.raises(ValueError, match="already registered"):
        register(spec)

def test_unknown_tool_returns_not_found_behavior():
    fetched = get("unknown_tool")
    assert fetched is None
    
    # Simulate what executor will do
    result = ToolResult(
        ok=False, error=ToolError(code=ErrorCode.NOT_FOUND, message="Tool not found")
    )
    assert result.error is not None
    assert result.error.code == ErrorCode.NOT_FOUND

def test_invalid_input_returns_invalid_input_behavior():
    spec = ToolSpec(
        name="dummy_tool",
        description="A dummy tool",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.READ,
        handler=dummy_handler
    )
    
    raw_input = {"amount": "not_an_int"}
    
    # Simulate what executor will do
    try:
        validated = spec.input_model(**raw_input)
        result = ToolResult(ok=True, data=validated)
    except ValidationError as e:
        result = ToolResult(
            ok=False, 
            error=ToolError(code=ErrorCode.INVALID_INPUT, message=str(e))
        )
        
    assert not result.ok
    assert result.error is not None
    assert result.error.code == ErrorCode.INVALID_INPUT
