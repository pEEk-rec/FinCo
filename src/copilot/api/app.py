"""
The FinCo HTTP API: a thin, typed, governed layer over the tools.

This file only builds the app: CORS, request logging, error shapes. The routes live in
`copilot.api.routes`, one module per area (ledger, ask, capture, personal, ...); the request and
response models in `contracts.py`; the token check and database dependency in `deps.py`.

Rules (PLAN_UI 6.1):
- localhost only, one local user, a per-session bearer token on every route but /api/health;
- every write calls execute_tool with an ExecutionContext(actor="user");
- errors carry a stable `code` (see errors.py); logs record method, route, status and timing
  only, never request or response bodies;
- there is no route that can pay, transfer, trade, withdraw or deposit (tested).
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from copilot.api import routes
from copilot.api.errors import ApiError, ApiException
from copilot.api.services import register_all_tools
from copilot.api.state import ApiState

log = logging.getLogger("copilot.api")


def create_app(state: ApiState) -> FastAPI:
    """Build the API around one ApiState."""
    register_all_tools()
    app = FastAPI(
        title="FinCo API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        responses={401: {"model": ApiError}, 404: {"model": ApiError}, 409: {"model": ApiError}},
    )
    app.state.api = state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(state.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def log_counts_and_codes(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        log.info(
            "%s %s %s %.0fms",
            request.method,
            path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @app.exception_handler(ApiException)
    async def api_error(_: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        body = ApiError(code="INVALID_INPUT", message=f"{where}: {first.get('msg', 'invalid')}")
        return JSONResponse(status_code=422, content=body.model_dump())

    for area in routes.AREAS:
        area.register(app, state)
    return app
