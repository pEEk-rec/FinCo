"""
Architecture enforcement tests (PLAN_PHASE1 Section 5.7).

RULE:
No module outside the executor / tool definition specs may import a tool handler.
The agent workflow and all higher layers must invoke tools STRICTLY through `execute_tool`.
"""

import ast
from pathlib import Path


def test_no_module_outside_tools_imports_tool_handler():
    """
    Enforce that no module outside src/copilot/tools/ imports any *_handler function.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "copilot"
    assert src_root.exists(), f"Source root does not exist: {src_root}"

    violations: list[str] = []

    for py_file in src_root.rglob("*.py"):
        # Files inside tools/ define tools and assemble ToolSpecs with their own handlers
        rel_path = py_file.relative_to(src_root)
        parts = rel_path.parts

        # Modules under workflow, planner, models, governance, db, audit, etc.
        # must NEVER import any handler.
        if parts[0] == "tools":
            # Inside tools/, only executor.py or ToolSpec definition files exist.
            # executor.py itself does NOT import handlers (it calls spec.handler dynamically).
            if rel_path.name == "executor.py":
                # Ensure executor doesn't import any specific tool handler directly
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name.endswith("_handler"):
                                violations.append(f"{rel_path}: imports {alias.name}")
            continue

        # All other directories (workflow, planner, bank, etc.)
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.endswith("_handler"):
                        violations.append(f"{rel_path}: imports {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("_handler"):
                        violations.append(f"{rel_path}: imports {alias.name}")

    assert not violations, (
        "Architecture rule violated: tool handlers imported outside tool specs:\n"
        + "\n".join(violations)
    )


def test_workflow_nodes_only_call_tools_via_execute_tool():
    """
    Verify that workflow/nodes.py explicitly uses execute_tool for tool executions.
    """
    nodes_file = Path(__file__).resolve().parents[2] / "src" / "copilot" / "workflow" / "nodes.py"
    content = nodes_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(nodes_file))

    # Collect all called function names
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)

    assert "execute_tool" in calls, "nodes.py must invoke tools through execute_tool"

    # Confirm no direct calls to any *_handler
    handler_calls = [c for c in calls if c.endswith("_handler")]
    assert not handler_calls, f"Direct handler calls detected in nodes.py: {handler_calls}"
