"""
Capability Matrix loader, enforcement, and tool catalogue projection
(PLAN_PHASE2 Section 5.1 & Stage 2.8).

Enforces:
- Rule 1: Only 'read' and 'compute' tools may have planner_selectable: true.
- Tools that mutate financial or user state are NEVER planner-selectable.
- Provides sanitized tool catalogue projections for LLM planner prompts.
"""

from typing import Any

from copilot.config.phase2 import PlannerCapabilitiesConfig, load_planner_capabilities
from copilot.tools.contracts import ToolSpec
from copilot.tools.registry import get as get_tool
from copilot.tools.registry import list_specs


def is_planner_selectable(
    tool_name: str,
    config: PlannerCapabilitiesConfig | None = None,
) -> bool:
    """Check if a tool is allowed to be selected by an autonomous planner."""
    cfg = config or load_planner_capabilities()
    cap = cfg.tools.get(tool_name)
    if cap is None:
        return False
    return cap.planner_selectable and cap.tool_class in ("read", "compute")


def get_selectable_tools(
    config: PlannerCapabilitiesConfig | None = None,
) -> list[str]:
    """Return all tool names that are currently planner-selectable, sorted."""
    cfg = config or load_planner_capabilities()
    return sorted(
        name
        for name, cap in cfg.tools.items()
        if cap.planner_selectable and cap.tool_class in ("read", "compute")
    )


def project_tool_catalogue(
    config: PlannerCapabilitiesConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Project planner-selectable tools into a compact schema representation for planner prompts.
    Strictly excludes all write-class and prohibited tools.
    """
    cfg = config or load_planner_capabilities()
    selectable_names = set(get_selectable_tools(cfg))
    catalogue: list[dict[str, Any]] = []

    for name in sorted(selectable_names):
        spec: ToolSpec | None = get_tool(name)
        cap = cfg.tools.get(name)
        if spec is None or cap is None:
            continue

        # Extract parameter details from Pydantic input model
        input_schema: dict[str, Any] = {}
        if hasattr(spec.input_model, "model_json_schema"):
            schema = spec.input_model.model_json_schema()
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for field_name, field_info in properties.items():
                input_schema[field_name] = {
                    "type": field_info.get("type", "any"),
                    "description": field_info.get("description", ""),
                    "required": field_name in required,
                }

        catalogue.append(
            {
                "tool_name": name,
                "short_description": cap.short_description or spec.description,
                "tool_class": cap.tool_class,
                "cost": cap.cost,
                "intents": cap.intents,
                "parameters": input_schema,
            }
        )

    return catalogue


def verify_capabilities_safety(
    config: PlannerCapabilitiesConfig | None = None,
) -> None:
    """
    Assert safety invariants across the entire tool registry and capabilities config:
    1. Every registered tool has an entry in planner_capabilities.yaml.
    2. No write-class tool is planner-selectable.
    """
    cfg = config or load_planner_capabilities()
    all_registered = list_specs()

    for spec in all_registered:
        if spec.name not in cfg.tools:
            raise ValueError(
                f"Safety invariant violated: registered tool '{spec.name}' "
                "lacks an entry in planner_capabilities.yaml."
            )
        cap = cfg.tools[spec.name]
        if cap.planner_selectable and cap.tool_class not in ("read", "compute"):
            raise ValueError(
                f"Safety invariant violated: tool '{spec.name}' is planner_selectable "
                f"but has class '{cap.tool_class}'. Only read and compute are allowed."
            )
