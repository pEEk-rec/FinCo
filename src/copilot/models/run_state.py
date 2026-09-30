"""
Per-run state (in memory, never in the database).

Kept separate from persistent financial state on purpose (PLAN section 2). A RunState is
versioned and JSON-serialisable; anything handed to an LLM must be a small projection made by
`to_llm_projection`, never the whole object.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot.models.domain import Id, UtcTimestamp
from copilot.tools.contracts import ToolResult

SCHEMA_VERSION = 1


class _StateModel(BaseModel):
    """Base for run-state parts: unknown fields are an error."""

    model_config = ConfigDict(extra="forbid")


class ToolCallRecord(_StateModel):
    """Compact, JSON-safe summary of one tool call."""

    tool_name: str
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    data: dict[str, Any] | None = None


class PendingAction(_StateModel):
    """A tool call waiting for user approval."""

    tool_name: str
    tool_input: dict[str, Any]
    reason: str


class RunState(_StateModel):
    """Everything one agent run knows. Loading a different schema_version fails."""

    schema_version: Literal[1] = SCHEMA_VERSION
    run_id: Id
    user_id: Id
    intent: str | None = None
    plan: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    tool_results: list[ToolCallRecord] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: UtcTimestamp


def summarize_tool_result(tool_name: str, result: ToolResult) -> ToolCallRecord:
    """Turn an executor ToolResult into a JSON-safe record for RunState."""
    data = result.data.model_dump(mode="json") if isinstance(result.data, BaseModel) else None
    return ToolCallRecord(
        tool_name=tool_name,
        ok=result.ok,
        error_code=result.error.code.value if result.error else None,
        error_message=result.error.message if result.error else None,
        data=data,
    )


def to_llm_projection(state: RunState, fields: list[str]) -> dict[str, Any]:
    """
    Return only the requested fields of `state`, JSON-ready.

    Unknown field names raise ValueError so a typo cannot silently send an empty context.
    """
    unknown = set(fields) - set(RunState.model_fields)
    if unknown:
        raise ValueError(f"Unknown RunState fields: {sorted(unknown)}")
    return state.model_dump(mode="json", include=set(fields))
