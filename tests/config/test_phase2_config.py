"""
Tests for Phase 2 configuration loading and Pydantic validation (PLAN_PHASE2 Stage 2.0).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from copilot.config.phase2 import (
    AlertsConfig,
    PlannerCapabilitiesConfig,
    load_alerts_config,
    load_explanation_templates,
    load_goals_config,
    load_intent_patterns,
    load_investigation_config,
    load_plan_templates,
    load_planner_capabilities,
    load_whatif_config,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_all_phase2_configs_load_successfully():
    """Verify that all 8 Phase 2 YAML configs load cleanly without errors."""
    caps = load_planner_capabilities(CONFIG_DIR / "planner_capabilities.yaml")
    assert len(caps.tools) >= 17

    intents = load_intent_patterns(CONFIG_DIR / "intent_patterns.yaml")
    assert "INVESTMENT_ADVICE" in intents.refusal_classes
    assert "MONEY_MOVEMENT" in intents.refusal_classes
    assert "summarize_period" in intents.intent_keywords

    plans = load_plan_templates(CONFIG_DIR / "plan_templates.yaml")
    assert "summarize_period" in plans.templates

    inv = load_investigation_config(CONFIG_DIR / "investigation.yaml")
    assert inv.lookback_months == 3
    assert len(inv.catalogue_hypotheses) == 8

    goals = load_goals_config(CONFIG_DIR / "goals.yaml")
    assert goals.max_horizon_months == 60
    assert 1 in goals.allowed_priorities

    whatif = load_whatif_config(CONFIG_DIR / "whatif.yaml")
    assert whatif.max_horizon_months == 6
    assert whatif.max_scenarios_per_comparison == 3

    alerts = load_alerts_config(CONFIG_DIR / "alerts.yaml")
    assert sum(alerts.signal_weights_bp.values()) == 10000
    assert alerts.quiet_mode is True

    explanations = load_explanation_templates(CONFIG_DIR / "explanation_templates.yaml")
    assert "spend_decision" in explanations.recommendation_templates
    assert "general" in explanations.fallback_templates


def test_planner_capabilities_blocks_selectable_write_tools():
    """Safety rule: write-class tools can never be planner_selectable."""
    bad_data = {
        "tools": {
            "illegal_tool": {
                "planner_selectable": True,
                "tool_class": "write_logical",
                "cost": "cheap",
                "short_description": "Illegal selectable write",
                "intents": [],
            }
        }
    }
    with pytest.raises(ValidationError) as exc_info:
        PlannerCapabilitiesConfig.model_validate(bad_data)
    assert "Safety invariant violated" in str(exc_info.value)


def test_alerts_config_rejects_invalid_weights_sum():
    """Alerts signal weights must sum to exactly 10,000 basis points."""
    bad_alerts = {
        "signal_weights_bp": {"threshold": 3000, "forecast": 3000},
        "tier_thresholds_bp": {"info": 2500, "notice": 5000, "warning": 7500, "critical": 9000},
        "cooldown_days": 7,
        "default_max_open_alerts": 5,
        "quiet_mode": True,
    }
    with pytest.raises(ValidationError) as exc_info:
        AlertsConfig.model_validate(bad_alerts)
    assert "10,000 basis points" in str(exc_info.value)


def test_all_registered_tools_exist_in_planner_capabilities():
    """Rule 5.1: Every registered tool must have an entry in planner_capabilities.yaml."""
    from copilot.tools.registry import list_specs
    from copilot.workflow.nodes import ensure_tools_registered

    ensure_tools_registered()
    registered = list_specs()
    caps = load_planner_capabilities(CONFIG_DIR / "planner_capabilities.yaml")

    for tool in registered:
        assert tool.name in caps.tools, (
            f"Registered tool '{tool.name}' is missing an entry in config/planner_capabilities.yaml"
        )
