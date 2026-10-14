"""
Routes for live mode, added to the main FastAPI app only when `copilot.live` starts it.

The demo app never loads this module, so the demo, its OpenAPI snapshot and its tests are
unchanged. Everything below `/api/live` needs the session token, except the SMS webhook,
which uses its own secret so a phone forwarder can call it.
"""

import json
import secrets
import time
from collections import deque
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from copilot.api.errors import ApiError, ApiException
from copilot.api.state import ApiState
from copilot.core.timeutil import now_utc
from copilot.live import service
from copilot.live.aa import AAClient, AAConfig, AAError
from copilot.live.statement import NotAStatement, parse_statement
from copilot.rails import engine as eng

WEBHOOK_PATH = "/api/live/webhook/sms"
MAX_WEBHOOK_BYTES = 4096
MAX_STATEMENT_CHARS = 5_000_000
WEBHOOK_PER_MINUTE = 120


class StatementIn(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_STATEMENT_CHARS)
    filename: str | None = Field(default=None, max_length=200)


class ReceiptIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class SplitDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


class AAConsentIn(BaseModel):
    mobile: str = Field(min_length=10, max_length=16)
    months: int = Field(default=3, ge=1, le=12)


class AAFetchIn(BaseModel):
    consent_id: str = Field(min_length=3, max_length=120)
    months: int = Field(default=3, ge=1, le=12)


def _bad(status: int, code: str, message: str) -> ApiException:
    return ApiException(status, ApiError(code=code, message=message))


def attach_live_routes(
    app: FastAPI,
    state: ApiState,
    webhook_secret: str,
    aa: AAClient | None,
) -> None:
    """Add the live routes. `aa` is None when no gateway credentials are configured."""
    uid = state.user_id
    recent: deque[float] = deque()

    def authed(request: Request) -> None:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not supplied or not secrets.compare_digest(supplied, state.token):
            raise _bad(401, "UNAUTHORIZED", "Missing or invalid session token.")

    def connection():
        conn = state.connect()
        service.seed_live(state, conn)
        conn.commit()
        return conn

    @app.get("/api/live/status")
    def status(request: Request) -> dict[str, Any]:
        authed(request)
        conn = connection()
        try:
            counts = {
                "transactions": conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE user_id = ?", (uid,)
                ).fetchone()[0],
                "needs_review": conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND needs_review = 1",
                    (uid,),
                ).fetchone()[0],
                "alerts_waiting": conn.execute(
                    "SELECT COUNT(*) FROM rail_events WHERE user_id = ? AND status = 'provisional'",
                    (uid,),
                ).fetchone()[0],
            }
        finally:
            conn.close()
        return {
            "live": True,
            "counts": counts,
            "webhook": {"path": WEBHOOK_PATH, "secret": webhook_secret},
            "aa": {
                "configured": aa is not None,
                "gateway": aa.config.host if aa else None,
                "note": (
                    "Gateway credentials are set."
                    if aa
                    else "Set AA_BASE_URL, AA_CLIENT_ID, AA_CLIENT_SECRET and "
                    "AA_PRODUCT_INSTANCE_ID to enable the consent flow."
                ),
            },
        }

    @app.post("/api/live/import/statement", response_model=service.ImportSummary)
    def import_statement(body: StatementIn, request: Request) -> service.ImportSummary:
        authed(request)
        try:
            parsed = parse_statement(body.text)
        except NotAStatement as exc:
            raise _bad(
                422, "INVALID_INPUT", f"This does not look like a bank statement CSV: {exc}."
            ) from exc
        if not parsed.rows:
            raise _bad(422, "INVALID_INPUT", "No readable transactions were found in that file.")
        conn = connection()
        try:
            out = service.import_rows(conn, uid, parsed.rows, "statement_csv", state.clock, parsed)
            conn.commit()
            return service.ai_categorize(state, conn, out)
        finally:
            conn.close()

    @app.post(WEBHOOK_PATH)
    async def sms_webhook(request: Request) -> dict[str, Any]:
        """Phone SMS forwarders post here. Auth: X-Webhook-Secret header (or ?secret=)."""
        supplied = request.headers.get("x-webhook-secret") or request.query_params.get("secret", "")
        if not supplied or not secrets.compare_digest(supplied, webhook_secret):
            raise _bad(401, "UNAUTHORIZED", "Missing or invalid webhook secret.")
        now = time.monotonic()
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= WEBHOOK_PER_MINUTE:
            raise _bad(429, "RATE_LIMITED", "Too many alerts this minute.")
        recent.append(now)
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise _bad(413, "INVALID_INPUT", "Message too large.")
        text = _message_text(raw, request.headers.get("content-type", ""))
        if not text:
            raise _bad(
                422, "INVALID_INPUT", "No message text found. Send JSON with text or message."
            )
        conn = connection()
        try:
            out = eng.ingest_sms(conn, uid, text, state.clock)
            conn.commit()
        finally:
            conn.close()
        return {"outcome": out.outcome, "reason": out.reason}

    @app.get("/api/live/pacing", response_model=eng.PacingOut)
    def pacing(request: Request) -> eng.PacingOut:
        authed(request)
        conn = connection()
        try:
            return eng.pacing(conn, uid, state.clock)
        finally:
            conn.close()

    @app.get("/api/live/events", response_model=list[eng.RailEventOut])
    def events(request: Request) -> list[eng.RailEventOut]:
        authed(request)
        conn = connection()
        try:
            return eng.list_events(conn, uid)
        finally:
            conn.close()

    @app.post("/api/live/reconcile", response_model=eng.ReconcileOut)
    def reconcile(request: Request) -> eng.ReconcileOut:
        authed(request)
        conn = connection()
        try:
            out = eng.reconcile(conn, uid, state.clock)
            conn.commit()
            return out
        finally:
            conn.close()

    @app.post("/api/live/receipt", response_model=eng.ReceiptOut)
    def receipt(body: ReceiptIn, request: Request) -> eng.ReceiptOut:
        authed(request)
        conn = connection()
        try:
            out = eng.ingest_receipt(conn, uid, body.text, state.clock)
            conn.commit()
            return out
        finally:
            conn.close()

    @app.post("/api/live/splits/{receipt_id}/decision")
    def decide(receipt_id: str, body: SplitDecisionIn, request: Request) -> dict[str, Any]:
        authed(request)
        conn = connection()
        try:
            changed = eng.decide_split(conn, uid, receipt_id, body.decision, state.clock)
            if not changed:
                raise _bad(404, "NOT_FOUND", "No undecided split for that receipt.")
            conn.commit()
            return {"receipt_id": receipt_id, "decision": body.decision, "parts": changed}
        finally:
            conn.close()

    # ---- Account Aggregator ----------------------------------------------------------------

    def need_aa() -> AAClient:
        if aa is None:
            raise _bad(
                409,
                "NOT_CONFIGURED",
                "No Account Aggregator gateway is configured. Set the AA_* environment variables.",
            )
        return aa

    @app.post("/api/live/aa/consent")
    def aa_consent(body: AAConsentIn, request: Request) -> dict[str, str]:
        authed(request)
        client = need_aa()
        now = now_utc(state.clock)
        try:
            return client.create_consent(
                body.mobile, now - timedelta(days=30 * body.months), now, body.months
            )
        except AAError as exc:
            raise _bad(502, "UPSTREAM_ERROR", str(exc)) from exc

    @app.get("/api/live/aa/consent/{consent_id}")
    def aa_consent_status(consent_id: str, request: Request) -> dict[str, str]:
        authed(request)
        client = need_aa()
        try:
            return {"id": consent_id, "status": client.consent_status(consent_id)}
        except AAError as exc:
            raise _bad(502, "UPSTREAM_ERROR", str(exc)) from exc

    @app.post("/api/live/aa/fetch", response_model=service.ImportSummary)
    def aa_fetch(body: AAFetchIn, request: Request) -> service.ImportSummary:
        authed(request)
        client = need_aa()
        now = now_utc(state.clock)
        try:
            rows = client.fetch_rows(body.consent_id, now - timedelta(days=30 * body.months), now)
        except AAError as exc:
            raise _bad(502, "UPSTREAM_ERROR", str(exc)) from exc
        conn = connection()
        try:
            out = service.import_rows(conn, uid, rows, "account_aggregator", state.clock)
            conn.commit()
            return service.ai_categorize(state, conn, out)
        finally:
            conn.close()


def _message_text(raw: bytes, content_type: str) -> str:
    """The alert text from the shapes common SMS forwarders send."""
    body = raw.decode("utf-8", "replace").strip()
    if not body:
        return ""
    if "json" in content_type or body.startswith("{"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return ""
        if isinstance(data, dict):
            for key in ("text", "message", "body", "sms", "content"):
                if isinstance(data.get(key), str):
                    return data[key].strip()
        return ""
    if "x-www-form-urlencoded" in content_type or "=" in body[:40]:
        fields = parse_qs(body)
        for key in ("text", "message", "body", "sms", "content"):
            if fields.get(key):
                return fields[key][0].strip()
    return body


def load_aa() -> AAClient | None:
    config = AAConfig.from_env()
    return AAClient(config) if config else None
