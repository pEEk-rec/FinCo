"""In-process tool registry. Registration never makes a tool callable except via the executor."""

from copilot.tools.contracts import ToolSpec

_registry: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    """Register a tool specification. A duplicate name is an error."""
    if not isinstance(spec, ToolSpec):
        raise TypeError("register() expects a ToolSpec")
    if spec.name in _registry:
        raise ValueError(f"Tool '{spec.name}' is already registered.")
    _registry[spec.name] = spec


def get(name: str) -> ToolSpec | None:
    """Get a tool specification by name, or None."""
    return _registry.get(name)


def list_specs() -> list[ToolSpec]:
    """List all registered tool specifications, sorted by name."""
    return [_registry[name] for name in sorted(_registry)]


def clear_registry() -> None:
    """Remove every registered tool (tests only)."""
    _registry.clear()
