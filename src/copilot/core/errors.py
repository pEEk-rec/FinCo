"""Standard error types."""
from enum import Enum

from pydantic import BaseModel


class ErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    DENIED_BY_POLICY = "DENIED_BY_POLICY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TOOL_FAILURE = "TOOL_FAILURE"
    STALE_DATA = "STALE_DATA"
    INTERNAL = "INTERNAL"

class ToolError(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
