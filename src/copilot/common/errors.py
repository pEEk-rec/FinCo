"""Standard error codes, the ToolError payload, and the exception handlers raise."""

from enum import StrEnum

from pydantic import BaseModel


class ErrorCode(StrEnum):
    """Machine-readable failure categories returned in a ToolResult."""

    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    DENIED_BY_POLICY = "DENIED_BY_POLICY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TOOL_FAILURE = "TOOL_FAILURE"
    STALE_DATA = "STALE_DATA"
    INTERNAL = "INTERNAL"


class ToolError(BaseModel):
    """Serialisable description of a failure (data, not an exception)."""

    code: ErrorCode
    message: str
    retryable: bool = False


class ToolFailure(Exception):
    """
    Raised by handlers or connectors to fail with a specific ErrorCode.

    The executor turns it into `ToolResult(ok=False, error=exc.error)`. Any other exception
    from a handler becomes TOOL_FAILURE.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retryable: bool = False,
        audit_event_type: str | None = None,
        audit_metadata: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error = ToolError(code=code, message=message, retryable=retryable)
        self.audit_event_type = audit_event_type
        self.audit_metadata = audit_metadata
