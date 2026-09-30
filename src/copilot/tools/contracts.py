"""Tool contracts and data models."""
from enum import Enum
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel

from copilot.core.errors import ToolError


class SideEffect(str, Enum):
    READ = "READ"
    WRITE_LOGICAL = "WRITE_LOGICAL"
    EXTERNAL = "EXTERNAL"

class ToolResult(BaseModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[ToolError] = None

class ToolSpec:
    def __init__(
        self,
        name: str,
        description: str,
        input_model: Type[BaseModel],
        output_model: Type[BaseModel],
        side_effect: SideEffect,
        handler: Callable[..., Any]
    ):
        self.name = name
        self.description = description
        self.input_model = input_model
        self.output_model = output_model
        self.side_effect = side_effect
        self.handler = handler
