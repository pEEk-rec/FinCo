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
    """One entry in the matrix. Can be a single outcome or per-actor outcomes."""

    model_config = ConfigDict(extra="forbid")

    decision: Outcome | None = None
    agent: Outcome | None = None
    user: Outcome | None = None

    def get_outcome(self, actor: str) -> Outcome | None:
        if actor == "user" and self.user is not None:
            return self.user
        if actor == "agent" and self.agent is not None:
            return self.agent
        return self.decision


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


def decide(policy: PolicySettings, tool_spec: ToolSpec, actor: str = "agent") -> Decision:
    """Decide whether `tool_spec` may run under `policy` for `actor`."""
    if tool_spec.side_effect is SideEffect.EXTERNAL:
        return Decision(
            outcome="deny",
            reason=f"'{tool_spec.name}' has an external side effect; these are never allowed.",
        )

    tool_rule = policy.tools.get(tool_spec.name)
    if tool_rule is not None:
        outcome = tool_rule.get_outcome(actor)
        if outcome is not None:
            return Decision(
                outcome=outcome,
                reason=f"Tool rule for '{tool_spec.name}' acting as '{actor}' says {outcome}.",
            )

    effect_rule = policy.side_effects.get(tool_spec.side_effect)
    if effect_rule is not None:
        outcome = effect_rule.get_outcome(actor)
        if outcome is not None:
            return Decision(
                outcome=outcome,
                reason=f"Rule for {tool_spec.side_effect.value} tools acting as '{actor}' says {outcome}.",  # noqa: E501
            )

    return Decision(
        outcome=policy.default,
        reason=f"No rule matches '{tool_spec.name}', so the default ({policy.default}) applies.",
    )
