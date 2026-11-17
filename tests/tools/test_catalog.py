"""The tool catalogue is complete and every tool it registers is governed and described."""

from pathlib import Path

import yaml

from copilot.tools.catalog import FAMILIES, register_all
from copilot.tools.registry import clear_registry, list_specs

ROOT = Path(__file__).resolve().parents[2]


def _all_tools():
    clear_registry()
    register_all(include_api_only=True)
    names = {s.name for s in list_specs()}
    clear_registry()
    return names


def test_every_family_registers_its_probe_tool():
    names = _all_tools()
    missing = [f.name for f in FAMILIES if f.probe not in names]
    assert not missing, missing


def test_every_registered_tool_has_a_policy_rule():
    policy = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text("utf-8"))["tools"]
    missing = sorted(_all_tools() - set(policy))
    assert not missing, f"add these to config/policy.yaml: {missing}"


def test_every_registered_tool_is_described_for_the_planner():
    caps = yaml.safe_load((ROOT / "config" / "planner_capabilities.yaml").read_text("utf-8"))
    described = set(caps.get("tools", caps))
    missing = sorted(_all_tools() - described)
    assert not missing, f"add these to config/planner_capabilities.yaml: {missing}"


def test_registering_twice_changes_nothing():
    clear_registry()
    register_all()
    first = {s.name for s in list_specs()}
    register_all()
    assert {s.name for s in list_specs()} == first
    clear_registry()
