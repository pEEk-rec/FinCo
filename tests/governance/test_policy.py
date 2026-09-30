from pydantic import BaseModel

from copilot.governance.policy import PolicySettings, decide
from copilot.tools.contracts import SideEffect, ToolSpec


class DummyInput(BaseModel):
    pass

class DummyOutput(BaseModel):
    pass

def dummy_handler(ctx):
    pass

def test_decide_tool_specific():
    policy = PolicySettings(
        default="deny",
        side_effects={"read": {"decision": "allow"}},
        tools={"special_read": {"decision": "needs_approval"}}
    )
    
    spec = ToolSpec(
        name="special_read",
        description="",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.READ,
        handler=dummy_handler
    )
    
    decision = decide(policy, spec)
    assert decision.outcome == "needs_approval"
    
def test_decide_side_effect():
    policy = PolicySettings(
        default="deny",
        side_effects={"read": {"decision": "allow"}},
        tools={}
    )
    
    spec = ToolSpec(
        name="normal_read",
        description="",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.READ,
        handler=dummy_handler
    )
    
    decision = decide(policy, spec)
    assert decision.outcome == "allow"
    
def test_decide_default():
    policy = PolicySettings(
        default="deny",
        side_effects={},
        tools={}
    )
    
    spec = ToolSpec(
        name="unknown",
        description="",
        input_model=DummyInput,
        output_model=DummyOutput,
        side_effect=SideEffect.EXTERNAL,
        handler=dummy_handler
    )
    
    decision = decide(policy, spec)
    assert decision.outcome == "deny"
