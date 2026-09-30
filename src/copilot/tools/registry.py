"""Tool registry."""
from typing import Dict, List, Optional

from copilot.tools.contracts import ToolSpec

_registry: Dict[str, ToolSpec] = {}

def register(spec: ToolSpec) -> None:
    """Register a new tool specification."""
    if spec.name in _registry:
        raise ValueError(f"Tool '{spec.name}' is already registered.")
    _registry[spec.name] = spec

def get(name: str) -> Optional[ToolSpec]:
    """Get a tool specification by name."""
    return _registry.get(name)

def list_specs() -> List[ToolSpec]:
    """List all registered tool specifications."""
    return list(_registry.values())

def clear_registry() -> None:
    """Clear the registry (useful for tests)."""
    _registry.clear()
