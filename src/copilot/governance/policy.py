"""
Governance policy: a capability matrix loaded from YAML, and `decide()`.

Order of evaluation:
  1. EXTERNAL side effects are always denied (hard rule in code, not overridable by config).
  2. A tool-specific rule, if present.
  3. The rule for the tool's side-effect class, if present.
  4. The global default, which must be `deny`.

The file is validated strictly: a typo such as `decision: "deny "` or an unknown key is a load
error, never a silent fall-through to a more permissive rule.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from copilot.tools.contracts import SideEffect, ToolSpec

Outcome = Literal["allow", "deny", "needs_approval"]


class Decision(BaseModel):
    """Governance verdict for one tool, with a readable reason."""

    outcome: Outcome
    reason: str


class PolicyRule(BaseModel):
    """One entry in the matrix."""

    model_config = ConfigDict(extra="forbid")

    decision: Outcome


class PolicySettings(BaseModel):
    """The whole capability matrix. `default` can only be `deny` (default-deny principle)."""

    model_config = ConfigDict(extra="forbid")

    default: Literal["deny"] = "deny"
    side_effects: dict[SideEffect, PolicyRule] = {}
    tools: dict[str, PolicyRule] = {}


def load_policy(path: str | Path) -> PolicySettings:
    """Load and strictly validate a policy YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Policy file {path} must contain a mapping, got {type(data).__name__}")
    return PolicySettings.model_validate(data)


def decide(policy: PolicySettings, tool_spec: ToolSpec) -> Decision:
    """Decide whether `tool_spec` may run under `policy`."""
    if tool_spec.side_effect is SideEffect.EXTERNAL:
        return Decision(
            outcome="deny",
            reason=f"'{tool_spec.name}' has an external side effect; these are never allowed.",
        )

    tool_rule = policy.tools.get(tool_spec.name)
    if tool_rule is not None:
        return Decision(
            outcome=tool_rule.decision,
            reason=f"Tool rule for '{tool_spec.name}' says {tool_rule.decision}.",
        )

    effect_rule = policy.side_effects.get(tool_spec.side_effect)
    if effect_rule is not None:
        return Decision(
            outcome=effect_rule.decision,
            reason=f"Rule for {tool_spec.side_effect.value} tools says {effect_rule.decision}.",
        )

    return Decision(
        outcome=policy.default,
        reason=f"No rule matches '{tool_spec.name}', so the default ({policy.default}) applies.",
    )
