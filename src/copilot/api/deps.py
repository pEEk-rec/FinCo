"""
What every protected route depends on: the session token and a database connection.

Both read the `ApiState` the app was built with (`app.state.api`), so the route modules need no
closure over `create_app`. A route declares `dependencies=auth` and takes `conn: Conn`.
"""

import secrets
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from copilot.api.errors import ApiError, ApiException
from copilot.api.state import ApiState, connection_scope


def api_state(request: Request) -> ApiState:
    return request.app.state.api


def require_token(request: Request) -> None:
    """Every route but /api/health needs the per-session bearer token, compared in constant time."""
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    if not supplied or not secrets.compare_digest(supplied, api_state(request).token):
        raise ApiException(
            401, ApiError(code="UNAUTHORIZED", message="Missing or invalid session token.")
        )


def db(request: Request) -> Iterator[sqlite3.Connection]:
    yield from connection_scope(api_state(request))


Conn = Annotated[sqlite3.Connection, Depends(db)]
auth = [Depends(require_token)]
