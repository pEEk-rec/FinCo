"""
The rails API: a separate app (own port, own database) for the multi-rail demo.

It shares no routes, state or schema with the main FinCo API, so the existing demo link is
untouched. It reuses the same building blocks (money, rules, audit, categories, budgets).
"""

import re
import secrets
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from copilot.api.errors import ApiError, ApiException
from copilot.api.state import ApiState, connection_scope
from copilot.core.advice import format_inr
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.rails import demo
from copilot.rails import engine as eng
from copilot.rails.receipts import rails_config

PAGE = Path(__file__).with_name("demo_page.html")


class SmsIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class SmsBatchIn(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=25)


class ReceiptIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class SplitDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


def create_rails_app(state: ApiState) -> FastAPI:
    """Build the rails API around an ApiState (database path, token, demo clock)."""
    app = FastAPI(title="FinCo Rails API", version="1.0.0")

    @app.exception_handler(ApiException)
    async def api_error(_: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        body = ApiError(code="INVALID_INPUT", message=f"{where}: {first.get('msg', 'invalid')}")
        return JSONResponse(status_code=422, content=body.model_dump())

    def require_token(request: Request) -> None:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not supplied or not secrets.compare_digest(supplied, state.token):
            raise ApiException(
                401, ApiError(code="UNAUTHORIZED", message="Missing or invalid session token.")
            )

    def db() -> Iterator[sqlite3.Connection]:
        yield from connection_scope(state)

    Conn = Annotated[sqlite3.Connection, Depends(db)]
    auth = [Depends(require_token)]
    uid = state.user_id

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/rails/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "rails"}

    @app.get("/rails/session", dependencies=auth)
    def session() -> dict[str, Any]:
        return {
            "as_of": to_utc_iso(now_utc(state.clock)),
            "demo_clock": state.clock is not None,
            "rails": [
                "account_aggregator (statement, source of truth)",
                "sms alerts",
                "receipts",
                "bill-pay billers",
            ],
        }

    @app.post("/rails/sms", response_model=eng.IngestOut, dependencies=auth)
    def sms(body: SmsIn, conn: Conn) -> eng.IngestOut:
        out = eng.ingest_sms(conn, uid, body.text, state.clock)
        conn.commit()
        return out

    @app.post("/rails/sms/batch", response_model=list[eng.IngestOut], dependencies=auth)
    def sms_batch(body: SmsBatchIn, conn: Conn) -> list[eng.IngestOut]:
        outs = [eng.ingest_sms(conn, uid, m[:600], state.clock) for m in body.messages]
        conn.commit()
        return outs

    @app.post("/rails/receipt", response_model=eng.ReceiptOut, dependencies=auth)
    def receipt(body: ReceiptIn, conn: Conn) -> eng.ReceiptOut:
        out = eng.ingest_receipt(conn, uid, body.text, state.clock)
        conn.commit()
        return out

    @app.get("/rails/events", response_model=list[eng.RailEventOut], dependencies=auth)
    def events(conn: Conn) -> list[eng.RailEventOut]:
        return eng.list_events(conn, uid)

    @app.get("/rails/pacing", response_model=eng.PacingOut, dependencies=auth)
    def pacing(conn: Conn) -> eng.PacingOut:
        return eng.pacing(conn, uid, state.clock)

    @app.post("/rails/reconcile", response_model=eng.ReconcileOut, dependencies=auth)
    def reconcile(conn: Conn) -> eng.ReconcileOut:
        out = eng.reconcile(conn, uid, state.clock)
        conn.commit()
        return out

    @app.post("/rails/sync", dependencies=auth)
    def sync(conn: Conn) -> dict[str, Any]:
        """Stand-in for the nightly Account Aggregator pull, then reconcile."""
        out = demo.nightly_sync(conn, uid, state.clock)
        conn.commit()
        return {
            "posted": out.posted,
            "skipped_existing": out.skipped_existing,
            "verified": out.reconcile.verified,
            "still_provisional": out.reconcile.still_provisional,
            "matches": out.reconcile.matches,
        }

    @app.get("/rails/splits", dependencies=auth)
    def splits(conn: Conn) -> list[dict]:
        return eng.list_splits(conn, uid)

    @app.post("/rails/splits/{receipt_id}/decision", dependencies=auth)
    def decide(receipt_id: str, body: SplitDecisionIn, conn: Conn) -> dict[str, Any]:
        changed = eng.decide_split(conn, uid, receipt_id, body.decision, state.clock)
        if not changed:
            raise ApiException(
                404, ApiError(code="NOT_FOUND", message="No undecided split for that receipt.")
            )
        conn.commit()
        return {"receipt_id": receipt_id, "decision": body.decision, "parts": changed}

    @app.get("/rails/billers", dependencies=auth)
    def billers(q: str = "") -> dict[str, Any]:
        """Which bill-pay biller (and category) a merchant text belongs to."""
        cfg = rails_config()
        hits = [
            {"name": b["name"], "category_id": b["category_id"], "mcc": b["mcc"]}
            for b in cfg["billers"]
            if q and re.search(b["match"], q, re.I)
        ]
        return {"query": q, "billers": hits, "mcc": {str(k): v for k, v in cfg["mcc"].items()}}

    @app.get("/rails/audit", dependencies=auth)
    def audit(conn: Conn) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT occurred_at, actor, event_type, entity_type, entity_id, reason FROM audit_events"  # noqa: E501
            " WHERE user_id = ? AND event_type LIKE 'rail_%' ORDER BY occurred_at DESC, rowid DESC"
            " LIMIT 60",
            (uid,),
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/rails/demo/script", dependencies=auth)
    def script() -> dict[str, Any]:
        return {"alerts": demo.ALERTS, "noise": demo.NOISE, "receipt": demo.RECEIPT}

    @app.post("/rails/demo/reset", dependencies=auth)
    def reset(conn: Conn) -> dict[str, str]:
        demo.reset(conn, uid)
        conn.commit()
        return {"status": "reset", "as_of": to_utc_iso(now_utc(state.clock)), "note": format_inr(0)}

    return app
