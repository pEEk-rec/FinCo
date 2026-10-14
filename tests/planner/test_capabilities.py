"""
Tests for Planner Capabilities and Tool Catalogue Projection (PLAN_PHASE2 Section 5.1 & Stage 2.8).
"""

import pytest

from copilot.config.phase2 import ToolCapability
from copilot.planner.capabilities import (
    get_selectable_tools,
    is_planner_selectable,
    project_tool_catalogue,
    verify_capabilities_safety,
)
from copilot.workflow.nodes import ensure_tools_registered


@pytest.fixture(autouse=True)
def setup_tools():
    ensure_tools_registered()


def test_selectable_tools_only_include_read_and_compute():
    """Safety Rule 1: Only read and compute tools may be planner-selectable."""
    selectable = get_selectable_tools()
    assert len(selectable) >= 10

    # Ensure known read/compute tools are selectable
    assert "get_transactions" in selectable
    assert "get_balance" in selectable
    assert "aggregate_spend_by_category" in selectable
    assert "check_budgets" in selectable
    assert "forecast_month" in selectable
    assert "detect_anomalies" in selectable
    assert "run_whatif" in selectable
    assert "compare_options" in selectable
    assert "investigate_anomaly" in selectable
    assert "explain_change" in selectable
    assert "list_goals" in selectable
    assert "list_alerts" in selectable


def test_write_tools_are_strictly_not_planner_selectable():
    """Safety Rule 1: Write tools must NEVER be planner-selectable."""
    write_tools = [
        "recategorize_transaction",
        "categorize_batch",
        "undo_categorize_batch",
        "ingest_statements",
        "detect_transfers",
        "detect_recurring",
        "undo",
        "draft_advice",
        "decide_advice",
        "create_goal",
        "update_goal",
        "dismiss_anomaly",
        "evaluate_alerts",
        "decide_alert",
        "set_alert_preference",
    ]

    for tool_name in write_tools:
        assert not is_planner_selectable(tool_name), (
            f"Safety invariant violated: write tool '{tool_name}' is marked planner-selectable"
        )


def test_project_tool_catalogue_excludes_write_tools():
    """Prompt sanitization: projected tool catalogue must contain zero write tools."""
    catalogue = project_tool_catalogue()
    catalogue_names = {t["tool_name"] for t in catalogue}

    assert "get_balance" in catalogue_names
    assert "aggregate_spend_by_category" in catalogue_names
    assert "recategorize_transaction" not in catalogue_names
    assert "undo" not in catalogue_names
    assert "create_goal" not in catalogue_names
    assert "categorize_batch" not in catalogue_names

    for item in catalogue:
        assert item["tool_class"] in ("read", "compute")
        assert "parameters" in item


def test_verify_capabilities_safety_passes_on_valid_registry():
    """All registered tools must have a valid, non-violating entry in capabilities config."""
    # Should not raise
    verify_capabilities_safety()


def test_pydantic_schema_rejects_selectable_write_tool():
    """Capability model validator catches any attempt to mark write tool as selectable."""
    with pytest.raises(ValueError, match="Safety invariant violated"):
        ToolCapability(
            planner_selectable=True,
            tool_class="write_logical",
            cost="cheap",
            short_description="Illegal write tool",
            intents=[],
        )
