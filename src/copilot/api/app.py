"""
The FinCo HTTP API: a thin, typed, governed layer over the Phase 1 and 2 services.

Rules (PLAN_UI 6.1):
- localhost only, one local user, a per-session bearer token on every route but /api/health;
- every write calls execute_tool with an ExecutionContext(actor="user");
- errors carry a stable `code` (see errors.py); logs record method, route, status and timing
  only, never request or response bodies;
- there is no route that can pay, transfer, trade, withdraw or deposit (tested).
"""

import logging
import secrets
import sqlite3
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from copilot.api import read_models as rm
from copilot.api.errors import ApiError, ApiException, not_found, unwrap
from copilot.api.services import draft_month_advice, register_all_tools, run_import
from copilot.api.state import ApiState, connection_scope
from copilot.core.simulation import ScenarioComparison
from copilot.core.timeline import build_timeline
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.repo import get_monthly_review, list_categories, list_goals, list_monthly_reviews
from copilot.models.agentic import Goal, Investigation, Projection, Timeline
from copilot.review.models import MonthlyReviewData
from copilot.tools.executor import execute_tool

log = logging.getLogger("copilot.api")


# ---------------------------------------------------------------------------------------------
# Small response models
# ---------------------------------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["ok"]


class Session(BaseModel):
    user_id: str
    as_of: str
    period: str
    data_source: Literal["synthetic_demo", "connected"]
    demo_clock: bool
    llm_available: bool = False


class CategoryOut(BaseModel):
    id: str
    name: str


class RecategorizeIn(BaseModel):
    category_id: str | None
    remember: bool = False


class RecategorizeOut(BaseModel):
    transaction_id: str
    previous_category_id: str | None
    new_category_id: str | None
    audit_event_id: str
    detail: rm.TransactionDetail


class UndoIn(BaseModel):
    audit_event_id: str


class UndoOut(BaseModel):
    undone_event_id: str
    new_audit_event_id: str


class ConsentDecisionOut(BaseModel):
    consent_id: str
    status: Literal["pending", "active", "expired", "revoked"]
    audit_event_id: str


class ReviewVersion(BaseModel):
    version: int
    generated_at: str


class MonthlyReviewOut(BaseModel):
    period: str
    versions: list[ReviewVersion]
    review: MonthlyReviewData | None


class GenerateReviewIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class AdviceDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


class AdviceDecisionOut(BaseModel):
    advice_id: str
    status: Literal["approved", "rejected"]


class AdviceExplanation(BaseModel):
    id: str
    text: str
    status: str
    origin: str | None
    confidence_label: str | None
    evidence: list[Any]
    calculations: list[Any]
    assumptions: list[Any]
    tools_used: list[Any]
    memories: list[Any]
    simulation_id: str | None


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    clarification: str | None = Field(default=None, max_length=300)
    use_llm: bool = True


class PlanStepOut(BaseModel):
    seq: int
    tool_name: str
    rationale: str
    proposed_by: str
    status: str


class TraceNodeOut(BaseModel):
    node: str
    status: str
    duration_ms: float
    counts: dict[str, int]


class AnswerOut(BaseModel):
    headline: str
    points: list[str] = []
    followups: list[str] = []
    confidence: str | None = None
    written_by: str = "rules"
    causal_ok: bool = False
    facts: list[Any] = []


class LlmUsedOut(BaseModel):
    available: bool
    model: str | None = None
    calls: int = 0
    failures: int = 0
    planner: str = "rules"


class AskOut(BaseModel):
    answer: AnswerOut | None = None
    llm: LlmUsedOut | None = None
    task_id: str | None
    status: str
    stop_reason: str | None
    question: str | None
    refusal_reason: str | None
    intent: dict[str, Any] | None
    recommendations: list[dict[str, Any]]
    pending_recommendations: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    investigations: list[dict[str, Any]]
    plan: list[PlanStepOut]
    trace: list[TraceNodeOut]
    rounds: int
    planner_mode: str


class AnomalyOut(BaseModel):
    id: str
    transaction_id: str
    merchant: str
    amount_paise: int
    occurred_at: str
    kind: str
    status: str


class InvestigateAnomalyIn(BaseModel):
    anomaly_id: str


class InvestigateChangeIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    category_id: str | None = None
    baseline_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class InvestigationOut(BaseModel):
    investigation: Investigation
    decomposition: dict[str, int]


class AlertsOut(BaseModel):
    alerts: list[dict[str, Any]]


class AlertDecisionIn(BaseModel):
    action: Literal["acknowledge", "dismiss", "snooze"]
    reason: str | None = None
    snooze_days: int | None = Field(default=None, ge=1, le=90)


class AlertPreferenceIn(BaseModel):
    category_id: str | None = None
    kind: str | None = None
    min_severity: Literal["info", "notice", "warning", "critical"] = "info"
    muted: bool = False


class GoalsOut(BaseModel):
    goals: list[Goal]


class WhatIfIn(BaseModel):
    kind: Literal["add_spend", "reduce_spend", "change_contribution"]
    category_id: str | None = None
    amount_paise: int = Field(ge=1)
    recurring: bool = True
    months: int = Field(default=3, ge=1, le=12)
    goal_id: str | None = None


class WhatIfOut(BaseModel):
    projection: Projection
    simulation_id: str


class CompareIn(BaseModel):
    scenarios: list[WhatIfIn] = Field(min_length=1, max_length=4)


class CompareOut(BaseModel):
    comparison: ScenarioComparison
    simulation_id: str


# ---------------------------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------------------------


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

    # -- health and session ----------------------------------------------------------------
    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    @app.get("/api/session", response_model=Session, dependencies=auth)
    def session() -> Session:
        now = now_utc(state.clock)
        ist = now.astimezone(IST)
        return Session(
            user_id=state.user_id,
            as_of=to_utc_iso(now),
            period=f"{ist.year:04d}-{ist.month:02d}",
            data_source=state.data_source,
            demo_clock=state.clock is not None,
            llm_available=state.get_llm() is not None,
        )

    # -- reads -------------------------------------------------------------------------------
    @app.get("/api/dashboard", response_model=rm.Dashboard, dependencies=auth)
    def dashboard(
        conn: Conn, period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")
    ) -> rm.Dashboard:
        return rm.build_dashboard(conn, state.user_id, state.clock, state.data_source, period)

    @app.get("/api/categories", response_model=list[CategoryOut], dependencies=auth)
    def categories(conn: Conn) -> list[CategoryOut]:
        return [CategoryOut(id=c.id, name=c.name) for c in list_categories(conn, state.user_id)]

    @app.get("/api/transactions", response_model=rm.TransactionPage, dependencies=auth)
    def transactions(
        conn: Conn,
        period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
        category_id: str | None = None,
        uncategorised: bool = False,
        needs_review: bool | None = None,
        source: Literal["user", "rule", "llm", "cache", "override", "none"] | None = None,
        q: str | None = Query(None, max_length=80),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ) -> rm.TransactionPage:
        return rm.list_transaction_page(
            conn,
            state.user_id,
            period=period,
            category_id=category_id,
            uncategorised=uncategorised,
            needs_review=needs_review,
            source=source,
            q=q,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/transactions/{tx_id}", response_model=rm.TransactionDetail, dependencies=auth)
    def transaction_detail(tx_id: str, conn: Conn) -> rm.TransactionDetail:
        detail = rm.build_transaction_detail(conn, state.user_id, tx_id)
        if detail is None:
            raise not_found("Transaction not found.")
        return detail

    @app.get("/api/review-queue", response_model=rm.ReviewQueue, dependencies=auth)
    def review_queue(conn: Conn) -> rm.ReviewQueue:
        return rm.build_review_queue(conn, state.user_id)

    # -- writes: transactions ---------------------------------------------------------------
    @app.post(
        "/api/transactions/{tx_id}/category", response_model=RecategorizeOut, dependencies=auth
    )
    def recategorize(tx_id: str, body: RecategorizeIn, conn: Conn) -> RecategorizeOut:
        ctx = state.context(conn, "user")
        out = unwrap(
            execute_tool(
                ctx,
                "recategorize_transaction",
                {
                    "transaction_id": tx_id,
                    "new_category_id": body.category_id,
                    "remember": body.remember,
                },
            )
        )
        conn.commit()
        detail = rm.build_transaction_detail(conn, state.user_id, tx_id)
        assert detail is not None
        return RecategorizeOut(
            transaction_id=out.transaction_id,  # type: ignore[attr-defined]
            previous_category_id=out.previous_category_id,  # type: ignore[attr-defined]
            new_category_id=out.new_category_id,  # type: ignore[attr-defined]
            audit_event_id=out.audit_event_id,  # type: ignore[attr-defined]
            detail=detail,
        )

    @app.post("/api/undo", response_model=UndoOut, dependencies=auth)
    def undo(body: UndoIn, conn: Conn) -> UndoOut:
        ctx = state.context(conn, "user")
        result = execute_tool(ctx, "undo", {"audit_event_id": body.audit_event_id})
        conn.commit()  # a refused undo is audited too
        out = unwrap(result)
        return UndoOut(
            undone_event_id=out.undone_event_id,  # type: ignore[attr-defined]
            new_audit_event_id=out.new_audit_event_id,  # type: ignore[attr-defined]
        )

    # -- consents and import ----------------------------------------------------------------
    @app.get("/api/consents", response_model=list[rm.ConsentView], dependencies=auth)
    def consents(conn: Conn) -> list[rm.ConsentView]:
        return rm.list_consent_views(conn, state.user_id, state.clock)

    @app.get("/api/imports", response_model=list[rm.ImportBatchView], dependencies=auth)
    def imports(conn: Conn) -> list[rm.ImportBatchView]:
        return rm.list_import_batches(conn, state.user_id)

    def consent_decision(
        tool: str, consent_id: str, conn: sqlite3.Connection
    ) -> ConsentDecisionOut:
        out = unwrap(execute_tool(state.context(conn, "user"), tool, {"consent_id": consent_id}))
        conn.commit()
        return ConsentDecisionOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.post(
        "/api/consents/{consent_id}/approve", response_model=ConsentDecisionOut, dependencies=auth
    )
    def approve_consent(consent_id: str, conn: Conn) -> ConsentDecisionOut:
        return consent_decision("approve_consent", consent_id, conn)

    @app.post(
        "/api/consents/{consent_id}/revoke", response_model=ConsentDecisionOut, dependencies=auth
    )
    def revoke_consent(consent_id: str, conn: Conn) -> ConsentDecisionOut:
        return consent_decision("revoke_consent", consent_id, conn)

    @app.post(
        "/api/consents/{consent_id}/import", response_model=rm.ImportResult, dependencies=auth
    )
    def import_statements(consent_id: str, conn: Conn) -> rm.ImportResult:
        return run_import(state, conn, consent_id)

    # -- monthly review and advice ----------------------------------------------------------
    @app.get("/api/monthly-reviews/{period}", response_model=MonthlyReviewOut, dependencies=auth)
    def monthly_review(
        conn: Conn, period: str, version: int | None = Query(None, ge=1)
    ) -> MonthlyReviewOut:
        year, month = _period(period)
        versions = [
            ReviewVersion(version=r.version, generated_at=r.created_at)
            for r in list_monthly_reviews(conn, state.user_id, year, month)
        ]
        row = get_monthly_review(conn, state.user_id, year, month, version)
        review = None
        if row is not None:
            raw = row.review_json
            review = (
                MonthlyReviewData.model_validate_json(raw)
                if isinstance(raw, str)
                else MonthlyReviewData.model_validate(raw)
            )
            review = _refresh_advice_status(conn, review)
        return MonthlyReviewOut(period=period, versions=versions, review=review)

    @app.post("/api/monthly-reviews", response_model=MonthlyReviewOut, dependencies=auth)
    def generate_review(body: GenerateReviewIn, conn: Conn) -> MonthlyReviewOut:
        year, month = _period(body.period)
        draft_month_advice(state, conn, year, month)
        unwrap(
            execute_tool(
                state.context(conn, "user"), "build_monthly_review", {"year": year, "month": month}
            )
        )
        conn.commit()
        return monthly_review(conn, body.period, None)

    @app.get("/api/advice/{advice_id}", response_model=AdviceExplanation, dependencies=auth)
    def advice_explanation(advice_id: str, conn: Conn) -> AdviceExplanation:
        r = conn.execute(
            "SELECT * FROM advice_items WHERE id = ? AND user_id = ?", (advice_id, state.user_id)
        ).fetchone()
        if r is None:
            raise not_found("Advice not found.")
        return AdviceExplanation(
            id=r["id"],
            text=r["text"],
            status=r["status"],
            origin=r["origin"],
            confidence_label=r["confidence_label"],
            evidence=_json_list(r["evidence_json"]),
            calculations=_json_list(r["calculations_json"]),
            assumptions=_json_list(r["assumptions_json"]),
            tools_used=_json_list(r["tools_used_json"]),
            memories=_json_list(r["memories_json"]),
            simulation_id=r["simulation_id"],
        )

    @app.post(
        "/api/advice/{advice_id}/decision", response_model=AdviceDecisionOut, dependencies=auth
    )
    def decide_advice(advice_id: str, body: AdviceDecisionIn, conn: Conn) -> AdviceDecisionOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "decide_advice",
                {"advice_id": advice_id, "decision": body.decision},
            )
        )
        conn.commit()
        return AdviceDecisionOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    # -- agent surfaces ---------------------------------------------------------------------
    @app.post("/api/ask", response_model=AskOut, dependencies=auth)
    def ask(body: AskIn, conn: Conn) -> AskOut:
        from copilot.api.agent import run_ask

        text = body.text if not body.clarification else f"{body.text} ({body.clarification})"
        return AskOut.model_validate(run_ask(state, conn, text, use_llm=body.use_llm))

    @app.get("/api/llm/status", dependencies=auth)
    def llm_status() -> dict[str, Any]:
        llm = state.get_llm()
        status = getattr(llm, "status", lambda: None)() if llm is not None else None
        return {"available": llm is not None, "router": status}

    @app.get("/api/timeline", response_model=Timeline, dependencies=auth)
    def timeline(conn: Conn, task_id: str | None = None, run_id: str | None = None) -> Timeline:
        return build_timeline(conn, state.user_id, task_id=task_id, run_id=run_id)

    @app.get("/api/investigations/{investigation_id}", dependencies=auth)
    def investigation(investigation_id: str, conn: Conn) -> dict[str, Any]:
        from copilot.db.repo import get_investigation

        inv = get_investigation(conn, state.user_id, investigation_id)
        if inv is None:
            raise not_found("Investigation not found.")
        return inv.model_dump(mode="json")

    @app.get("/api/anomalies", response_model=list[AnomalyOut], dependencies=auth)
    def anomalies(conn: Conn) -> list[AnomalyOut]:
        """Unusual transactions from the deterministic detector (a read; nothing is stored)."""
        from copilot.core.anomalies import detect_anomalies
        from copilot.db.repo import list_transactions

        txs = list_transactions(conn, state.user_id, "1970-01-01T00:00:00Z", "2100-01-01T00:00:00Z")
        by_id = {t.id: t for t in txs}
        found: dict[str, AnomalyOut] = {}
        for item in detect_anomalies(txs):
            tx = by_id.get(item["transaction_ids"][-1])
            if tx is None or tx.id in found:
                continue
            found[tx.id] = AnomalyOut(
                id=tx.id,
                transaction_id=tx.id,
                kind=item["kind"],
                status="open",
                merchant=(tx.merchant_normalized or tx.merchant_raw).strip(),
                amount_paise=abs(tx.amount_paise),
                occurred_at=tx.occurred_at,
            )
        order = {"large_transaction": 0, "duplicate_charge": 1, "new_merchant": 2}
        ranked = sorted(found.values(), key=lambda a: (order.get(a.kind, 9), -a.amount_paise))
        return ranked[:8]

    @app.post("/api/investigate/anomaly", response_model=InvestigationOut, dependencies=auth)
    def investigate_anomaly(body: InvestigateAnomalyIn, conn: Conn) -> InvestigationOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "investigate_anomaly", {"anomaly_id": body.anomaly_id}
            )
        )
        conn.commit()
        return InvestigationOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.post("/api/investigate/change", response_model=InvestigationOut, dependencies=auth)
    def investigate_change(body: InvestigateChangeIn, conn: Conn) -> InvestigationOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "explain_change",
                {
                    "period": body.period,
                    "category_id": body.category_id,
                    "merchant": None,
                    "baseline_period": body.baseline_period,
                },
            )
        )
        conn.commit()
        return InvestigationOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.get("/api/alerts", response_model=AlertsOut, dependencies=auth)
    def alerts(
        conn: Conn, status: Literal["open", "acknowledged", "dismissed", "snoozed"] | None = None
    ) -> AlertsOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "list_alerts", {"status": status, "limit": 50}
            )
        )
        conn.commit()
        return AlertsOut(alerts=[a.model_dump(mode="json") for a in out.alerts])  # type: ignore[attr-defined]

    @app.post("/api/alerts/{alert_id}/decision", dependencies=auth)
    def decide_alert(alert_id: str, body: AlertDecisionIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "decide_alert",
                {
                    "alert_id": alert_id,
                    "action": body.action,
                    "reason": body.reason,
                    "snooze_days": body.snooze_days,
                },
            )
        )
        conn.commit()
        return out.model_dump(mode="json")  # type: ignore[attr-defined]

    @app.post("/api/alert-preferences", dependencies=auth)
    def alert_preference(body: AlertPreferenceIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "set_alert_preference",
                {
                    **body.model_dump(),
                    "max_open_alerts": None,
                },
            )
        )
        conn.commit()
        return out.model_dump(mode="json")  # type: ignore[attr-defined]

    @app.get("/api/goals", response_model=GoalsOut, dependencies=auth)
    def goals(conn: Conn) -> GoalsOut:
        return GoalsOut(goals=list_goals(conn, state.user_id))

    def _scenario(s: WhatIfIn) -> dict[str, Any]:
        now = now_utc(state.clock).astimezone(IST)
        nxt = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        return {**s.model_dump(), "start_month": f"{nxt.year:04d}-{nxt.month:02d}"}

    @app.post("/api/whatif", response_model=WhatIfOut, dependencies=auth)
    def whatif(body: WhatIfIn, conn: Conn) -> WhatIfOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "run_whatif",
                {"scenario": _scenario(body), "horizon_months": body.months},
            )
        )
        conn.commit()
        return WhatIfOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    @app.post("/api/whatif/compare", response_model=CompareOut, dependencies=auth)
    def compare(body: CompareIn, conn: Conn) -> CompareOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "compare_options",
                {
                    "scenarios": [_scenario(s) for s in body.scenarios],
                    "horizon_months": max(s.months for s in body.scenarios),
                },
            )
        )
        conn.commit()
        return CompareOut.model_validate(out.model_dump())  # type: ignore[attr-defined]

    return app


def _period(period: str) -> tuple[int, int]:
    try:
        year, month = (int(p) for p in period.split("-"))
    except ValueError as exc:
        raise ApiException(
            422, ApiError(code="INVALID_INPUT", message="period must be YYYY-MM")
        ) from exc
    if not 1 <= month <= 12:
        raise ApiException(422, ApiError(code="INVALID_INPUT", message="month must be 01..12"))
    return year, month


def _json_list(raw: str | None) -> list[Any]:
    import json

    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else [value]


def _refresh_advice_status(
    conn: sqlite3.Connection, review: MonthlyReviewData
) -> MonthlyReviewData:
    """Show only this period's advice, with each item's current decision status."""
    items = []
    for item in review.advice:
        row = conn.execute(
            "SELECT status, evidence_json FROM advice_items WHERE id = ?", (item.id,)
        ).fetchone()
        if row is None or f'"period": "{review.period}"' not in (row["evidence_json"] or ""):
            continue
        status = (
            row["status"] if row["status"] in ("draft", "approved", "rejected") else item.status
        )
        items.append(item.model_copy(update={"status": status}))
    return review.model_copy(update={"advice": items})
