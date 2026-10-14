"""Typed error mapping: ToolError codes become HTTP statuses with a stable `code` field."""

from fastapi import HTTPException
from pydantic import BaseModel

from copilot.core.errors import ErrorCode, ToolError
from copilot.tools.contracts import ToolResult

HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DENIED_BY_POLICY: 403,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.STALE_DATA: 409,
    ErrorCode.TOOL_FAILURE: 502,
    ErrorCode.INTERNAL: 500,
}


class ApiError(BaseModel):
    """Body of every non-2xx response."""

    code: str
    message: str
    retryable: bool = False


class ApiException(HTTPException):
    """An HTTPException that carries a typed ApiError body."""

    def __init__(self, status: int, error: ApiError) -> None:
        super().__init__(status_code=status, detail=error.model_dump())
        self.error = error


def raise_for_tool_error(error: ToolError) -> None:
    """Raise the HTTP form of a ToolError."""
    raise ApiException(
        HTTP_STATUS.get(error.code, 500),
        ApiError(code=error.code.value, message=error.message, retryable=error.retryable),
    )


def unwrap(result: ToolResult) -> object:
    """Return `result.data`, or raise the mapped HTTP error."""
    if not result.ok:
        assert result.error is not None
        raise_for_tool_error(result.error)
    return result.data


def not_found(message: str) -> ApiException:
    """A 404 with the standard body."""
    return ApiException(404, ApiError(code=ErrorCode.NOT_FOUND.value, message=message))
