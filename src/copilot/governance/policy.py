"""
Policy evaluation for tools.
"""
from typing import Dict, Literal

import yaml
from pydantic import BaseModel

from copilot.tools.contracts import ToolSpec


class Decision(BaseModel):
    outcome: Literal["allow", "deny", "needs_approval"]
    reason: str

class PolicySettings(BaseModel):
    default: Literal["allow", "deny", "needs_approval"]
    side_effects: Dict[str, Dict[str, str]] = {}
    tools: Dict[str, Dict[str, str]] = {}

def load_policy(path: str) -> PolicySettings:
    """Load policy from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return PolicySettings(**data)

def decide(policy: PolicySettings, tool_spec: ToolSpec) -> Decision:
    """
    Decide whether a tool can be executed based on the policy.
    Tool-specific rules override side-effect defaults.
    """
    tool_name = tool_spec.name
    side_effect = tool_spec.side_effect.value.lower()
    
    # 1. Check tool-specific rule
    if policy.tools and tool_name in policy.tools:
        outcome = policy.tools[tool_name].get("decision")
        if outcome in ["allow", "deny", "needs_approval"]:
            return Decision(
                outcome=outcome, # type: ignore
                reason=f"Tool-specific policy rule applied: {outcome}"
            )
            
    # 2. Check side-effect default
    if policy.side_effects and side_effect in policy.side_effects:
        outcome = policy.side_effects[side_effect].get("decision")
        if outcome in ["allow", "deny", "needs_approval"]:
            return Decision(
                outcome=outcome, # type: ignore
                reason=f"Side-effect policy rule applied: {outcome}"
            )
            
    # 3. Apply global default
    return Decision(
        outcome=policy.default,
        reason=f"Default policy rule applied: {policy.default}"
    )
