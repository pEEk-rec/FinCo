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
    assert p.tools["recategorize_transaction"].decision == "needs_approval"


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
