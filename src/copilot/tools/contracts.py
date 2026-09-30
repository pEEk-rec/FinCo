"""
Tool contracts: side-effect classes, the ToolSpec definition, and ToolResult.

There is deliberately no side-effect class for moving money, and none may be added.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from copilot.core.errors import ToolError

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class SideEffect(StrEnum):
    """What a tool may touch. Values match the keys used in config/policy.yaml."""

    READ = "read"
    WRITE_LOGICAL = "write_logical"  # changes our own database, reversible
    EXTERNAL = "external"  # touches the outside world; always denied in Phase 0


class ToolInput(BaseModel):
    """Base for tool inputs. Unknown fields are rejected, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class ToolOutput(BaseModel):
    """Base for tool outputs."""

    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    """Outcome of one tool call: `data` when ok, `error` otherwise (never both)."""

    ok: bool
    data: Any | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def _ok_matches_error(self) -> "ToolResult":
        """An ok result has no error; a failed result must carry one."""
        if self.ok and self.error is not None:
            raise ValueError("ok result must not carry an error")
        if not self.ok and self.error is None:
            raise ValueError("failed result must carry an error")
        return self


@dataclass(frozen=True)
class ToolSpec:
    """
    Declaration of a tool: metadata governance reads, plus the handler.

    The handler is called only by `tools.executor.execute_tool`, as
    `handler(ctx, **validated_input_fields)`, and returns a dict or `output_model` instance.
    """

    name: str
    description: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    side_effect: SideEffect
    handler: Callable[..., Any]

    def __post_init__(self) -> None:
        """Reject malformed specs at registration time instead of at call time."""
        if not isinstance(self.name, str) or not _TOOL_NAME.match(self.name):
            raise ValueError(f"Tool name must be snake_case, got {self.name!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"Tool {self.name!r} needs a description")
        if not (isinstance(self.input_model, type) and issubclass(self.input_model, ToolInput)):
            raise TypeError(f"Tool {self.name!r}: input_model must subclass ToolInput")
        if not (isinstance(self.output_model, type) and issubclass(self.output_model, ToolOutput)):
            raise TypeError(f"Tool {self.name!r}: output_model must subclass ToolOutput")
        if not isinstance(self.side_effect, SideEffect):
            raise TypeError(f"Tool {self.name!r}: side_effect must be a SideEffect")
        if not callable(self.handler):
            raise TypeError(f"Tool {self.name!r}: handler must be callable")
