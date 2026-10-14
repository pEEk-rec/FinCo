from pathlib import Path

import pytest
from pydantic import ValidationError

from copilot.governance.policy import PolicySettings, decide, load_policy
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec

REPO_POLICY = Path(__file__).resolve().parents[2] / "config" / "policy.yaml"


class DummyInput(ToolInput):
    pass


class DummyOutput(ToolOutput):
    pass


def spec(name: str, side_effect: SideEffect) -> ToolSpec:
    return ToolSpec(name, "desc", DummyInput, DummyOutput, side_effect, lambda ctx: {})


def policy(**kwargs) -> PolicySettings:
    return PolicySettings.model_validate(kwargs)


def test_tool_rule_overrides_side_effect_rule():
    p = policy(
        side_effects={"read": {"decision": "allow"}},
        tools={"special_read": {"decision": "needs_approval"}},
    )
    assert decide(p, spec("special_read", SideEffect.READ)).outcome == "needs_approval"


def test_side_effect_rule():
    p = policy(side_effects={"read": {"decision": "allow"}})
    assert decide(p, spec("normal_read", SideEffect.READ)).outcome == "allow"


def test_default_is_deny():
    d = decide(policy(), spec("unknown", SideEffect.WRITE_LOGICAL))
    assert d.outcome == "deny"
    assert "default" in d.reason


def test_external_always_denied_even_if_config_allows():
    p = policy(
        side_effects={"external": {"decision": "allow"}}, tools={"wire": {"decision": "allow"}}
    )
    d = decide(p, spec("wire", SideEffect.EXTERNAL))
    assert d.outcome == "deny"
    assert "external" in d.reason


@pytest.mark.parametrize(
    "data",
    [
        {"default": "allow"},
        {"default": "needs_approval"},
        {"tools": {"get_balance": {"decision": "deny "}}},
        {"tools": {"get_balance": {"decison": "deny"}}},
        {"side_effects": {"READ": {"decision": "allow"}}},
        {"side_effects": {"money": {"decision": "deny"}}},
        {"unknown_section": {}},
    ],
)
def test_malformed_policy_rejected(data):
    with pytest.raises(ValidationError):
        PolicySettings.model_validate(data)


def test_load_repo_policy():
    p = load_policy(REPO_POLICY)
    assert p.default == "deny"
    assert p.tools["recategorize_transaction"].get_outcome("agent") == "needs_approval"
    assert p.tools["recategorize_transaction"].get_outcome("user") == "allow"
    assert p.tools["create_goal"].get_outcome("agent") == "needs_approval"
    assert p.tools["create_goal"].get_outcome("user") == "allow"
    assert p.tools["update_goal"].get_outcome("agent") == "needs_approval"
    assert p.tools["update_goal"].get_outcome("user") == "allow"
    assert p.tools["list_goals"].get_outcome("agent") == "allow"
    assert p.tools["evaluate_goal_impact"].get_outcome("agent") == "allow"
    assert p.tools["run_whatif"].get_outcome("agent") == "allow"
    assert p.tools["compare_options"].get_outcome("agent") == "allow"


def test_load_policy_rejects_empty_file(tmp_path):
    empty = tmp_path / "p.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_policy(empty)


def test_load_policy_rejects_typo(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("default: deny\ntools:\n  get_balance: {decision: alow}\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_policy(bad)


USER_ONLY_TOOLS = ("decide_advice", "approve_consent", "revoke_consent", "build_monthly_review")


def test_user_only_actions_are_denied_to_the_agent_by_the_real_policy():
    """A rule that lists only `user: allow` would leave the agent on the needs-approval default."""
    from copilot.api.services import register_all_tools
    from copilot.tools.registry import get as get_tool

    register_all_tools()
    policy = load_policy(REPO_POLICY)
    for name in USER_ONLY_TOOLS:
        spec = get_tool(name)
        assert spec is not None, name
        assert decide(policy, spec, "agent").outcome == "deny", (
            f"{name} must be denied to the agent"
        )
        assert decide(policy, spec, "user").outcome == "allow", f"{name} must work for the user"
