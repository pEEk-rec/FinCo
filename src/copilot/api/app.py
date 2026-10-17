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
import re
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
from copilot.api.coach_view import CoachView, build_coach_view
from copilot.api.errors import ApiError, ApiException, not_found, unwrap
from copilot.api.services import draft_month_advice, register_all_tools, run_import
from copilot.api.state import ApiState, connection_scope
from copilot.audit.events import record_event
from copilot.core.simulation import ScenarioComparison
from copilot.core.timeline import build_timeline
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.repo import (
    get_monthly_review,
    insert_category,
    list_categories,
    list_goals,
    list_monthly_reviews,
)
from copilot.models.agentic import Goal, Investigation, Projection, Timeline
from copilot.models.domain import Category
from copilot.models.phase3 import GoalProgress
from copilot.review.models import MonthlyReviewData
from copilot.tools.executor import execute_tool

log = logging.getLogger("copilot.api")


# ---------------------------------------------------------------------------------------------
# Small response models
# ---------------------------------------------------------------------------------------------


MAX_CATEGORIES = 60

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


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


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
    #: which way this response was produced: llm, fallback (model asked but not usable), or rules
    path: str = "rules"
    path_reason: str = ""


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
    progress: list[GoalProgress] = Field(default_factory=list)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["savings", "purchase", "emergency_fund", "other"] = "savings"
    target_paise: int = Field(gt=0)
    current_paise: int = Field(default=0, ge=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: int = Field(default=2, ge=1, le=3)


class GoalUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_paise: int | None = Field(default=None, gt=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: int | None = Field(default=None, ge=1, le=3)
    status: Literal["active", "paused", "done"] | None = None


class GoalContributionIn(BaseModel):
    amount_paise: int = Field(ge=1)


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


class CommitmentIn(BaseModel):
    name: str = Field(min_length=1)
    amount_paise: int = Field(ge=1)
    start_date: str = Field(default="2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    category_id: str | None = None
    schedule_kind: Literal["monthly", "weekly", "yearly", "custom"] = "monthly"
    schedule_json: dict[str, Any] = Field(default_factory=lambda: {"day": 1})
    direction: Literal["outflow", "inflow"] = "outflow"
    kind: Literal[
        "bill", "subscription", "emi", "sip", "rent", "tax", "income", "other"
    ] = "bill"
    certainty: Literal["firm", "variable", "discretionary"] = "firm"
    goal_id: str | None = None
    bucket_id: str | None = None


class BucketIn(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["spending", "goal", "commitment", "flexible"] = "spending"
    period_policy: Literal["reset_monthly", "accumulate"] | None = None
    goal_id: str | None = None
    commitment_id: str | None = None
    sort_order: int = 0


class BucketAllocateIn(BaseModel):
    bucket_id: str
    amount_paise: int = Field(ge=1)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class BucketReallocateIn(BaseModel):
    from_bucket_id: str
    to_bucket_id: str
    amount_paise: int = Field(ge=1)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class MemoryForgetIn(BaseModel):
    memory_id: str
    reason: str = "user_request"


class LearningResetIn(BaseModel):
    subject_kind: str | None = None
    subject_key: str | None = None


# -- Phase 4 Input Models ---------------------------------------------------------------------
class ExperimentDesignIn(BaseModel):
    template_code: str | None = None
    metric_code: str | None = None
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    duration_days: int = 14
    difficulty: str = "medium"
    target_value: int | None = None
    baseline_median: int | None = None
    start_date: str | None = None
    goal_id: str | None = None
    rationale: str | None = None


class ExperimentStartIn(BaseModel):
    experiment_id: str | None = None
    title: str | None = None
    metric_code: str | None = None
    template_code: str | None = None
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    duration_days: int = 14
    difficulty: str = "medium"
    target_value: int | None = None
    baseline_median: int | None = None
    start_date: str | None = None
    goal_id: str | None = None
    rationale: str | None = None
    origin: Literal["user", "offer", "goal_decomposition"] = "user"


class ExperimentAbandonIn(BaseModel):
    reason: str | None = None


class ExperimentCheckinIn(BaseModel):
    user_response: Literal["going_well", "hard", "want_to_pause", "skip"] | None = None


class ReviewFeedbackIn(BaseModel):
    difficulty_rating: int | None = Field(None, ge=1, le=5)
    user_difficulty: int | None = Field(None, ge=1, le=5)
    user_helpful: bool | None = None
    would_repeat: bool | None = None
    user_would_repeat: bool | None = None
    feedback_text: str | None = None


class OfferSuggestIn(BaseModel):
    week_start: str | None = None


class OfferDismissIn(BaseModel):
    reason: str | None = None


class AdjustmentRejectIn(BaseModel):
    reason: str | None = None


def _dump_data(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if isinstance(data, list):
        return [_dump_data(x) for x in data]
    if isinstance(data, dict):
        return {k: _dump_data(v) for k, v in data.items()}
    return data


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

    @app.post("/api/categories", response_model=CategoryOut, dependencies=auth)
    def create_category(body: CategoryIn, conn: Conn) -> CategoryOut:
        """Add a category of the user's own. The same name again returns the existing one."""
        name = " ".join(body.name.split())
        existing = list_categories(conn, state.user_id)
        for c in existing:
            if c.name.lower() == name.lower():
                return CategoryOut(id=c.id, name=c.name)
        if len(existing) >= MAX_CATEGORIES:
            raise ApiException(
                409, ApiError(code="LIMIT_REACHED", message="That is the most categories allowed.")
            )
        base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "custom"
        taken = {c.id for c in existing}
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}_{n}", n + 1
        now = now_utc(state.clock)
        insert_category(
            conn,
            Category(id=slug, user_id=state.user_id, name=name, created_at=to_utc_iso(now)),
        )
        record_event(
            conn, state.user_id, "user", "category_created", "User created a category.",
            entity_type="category", entity_id=slug, after_data={"name": name}, clock=now,
        )
        conn.commit()
        return CategoryOut(id=slug, name=name)

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
        return _goals_out(conn)

    def _goals_out(conn: sqlite3.Connection) -> GoalsOut:
        from copilot.core.goals import goal_progress

        items = list_goals(conn, state.user_id)
        today = now_utc(state.clock).astimezone(IST).date()
        progress = [goal_progress(conn, state.user_id, g, today) for g in items]
        return GoalsOut(goals=items, progress=progress)

    @app.post("/api/goals", response_model=GoalsOut, dependencies=auth)
    def create_goal_api(body: GoalIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_goal",
                body.model_dump(exclude_none=True),
            )
        )
        conn.commit()
        return _goals_out(conn)

    @app.post("/api/goals/{goal_id}/update", response_model=GoalsOut, dependencies=auth)
    def update_goal_api(goal_id: str, body: GoalUpdateIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "update_goal",
                {"goal_id": goal_id, **body.model_dump(exclude_none=True)},
            )
        )
        conn.commit()
        return _goals_out(conn)

    @app.post("/api/goals/{goal_id}/contributions", response_model=GoalsOut, dependencies=auth)
    def goal_contribution_api(goal_id: str, body: GoalContributionIn, conn: Conn) -> GoalsOut:
        unwrap(
            execute_tool(
                state.context(conn, "user"),
                "record_goal_contribution",
                {"goal_id": goal_id, "amount_paise": body.amount_paise},
            )
        )
        conn.commit()
        return _goals_out(conn)

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

    # -- Phase 3: Commitments -------------------------------------------------------------
    @app.get("/api/commitments", dependencies=auth)
    def list_commitments_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_phase3 import list_commitments

        items = list_commitments(conn, user_id=state.user_id, status=status)
        return [_dump_data(c) for c in items]

    @app.post("/api/commitments", dependencies=auth)
    def create_commitment_api(body: CommitmentIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_commitment",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/commitments/suggest", dependencies=auth)
    def suggest_commitments_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "suggest_commitments",
                {},
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 3: Calendar ----------------------------------------------------------------
    @app.get("/api/calendar", dependencies=auth)
    def calendar_forecast_api(
        conn: Conn, horizon_days: int = Query(60, ge=1, le=180)
    ) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_calendar",
                {"horizon_days": horizon_days},
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 3: Buckets -----------------------------------------------------------------
    @app.get("/api/buckets", dependencies=auth)
    def buckets_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_buckets",
                {},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/buckets", dependencies=auth)
    def create_bucket_api(body: BucketIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "create_bucket",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/buckets/allocate", dependencies=auth)
    def allocate_bucket_api(body: BucketAllocateIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "allocate_to_bucket",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/buckets/reallocate", dependencies=auth)
    def reallocate_bucket_api(body: BucketReallocateIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "reassign_between_buckets",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 3: Readiness ---------------------------------------------------------------
    @app.get("/api/readiness", dependencies=auth)
    def readiness_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "assess_investment_readiness",
                {},
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 3: Memories ----------------------------------------------------------------
    @app.get("/api/memories", dependencies=auth)
    def memories_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_phase3 import list_memory_items

        items = list_memory_items(conn, user_id=state.user_id, status=status)
        return [_dump_data(m) for m in items]

    @app.post("/api/memories/forget", dependencies=auth)
    def forget_memory_api(body: MemoryForgetIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "forget_memory",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.get("/api/memories/audit", dependencies=auth)
    def memory_audit_api(
        conn: Conn, limit: int = Query(50, ge=1, le=200)
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM memory_audit_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (state.user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Phase 3: Learning ----------------------------------------------------------------
    @app.get("/api/learning", dependencies=auth)
    def learning_profile_api(conn: Conn) -> dict[str, Any]:
        from copilot.core.learning import list_tenant_learning_stats

        stats = list_tenant_learning_stats(conn, state.user_id)
        return {"user_id": state.user_id, "stats": stats}

    @app.post("/api/learning/reset", dependencies=auth)
    def reset_learning_api(body: LearningResetIn, conn: Conn) -> dict[str, Any]:
        from copilot.core.learning import reset_learning

        deleted = reset_learning(
            conn,
            state.user_id,
            subject_kind=body.subject_kind,
            subject_key=body.subject_key,
            clock=now_utc(state.clock),
        )
        conn.commit()
        return {"status": "ok", "reset_count": deleted}

    # -- Phase 3: Ops & Jobs --------------------------------------------------------------
    @app.get("/api/ops", dependencies=auth)
    def ops_dashboard_api(conn: Conn) -> dict[str, Any]:
        import dataclasses

        from copilot.db.repo_phase3 import list_scheduled_jobs
        from copilot.ops.telemetry import compute_ops_telemetry

        telemetry = compute_ops_telemetry(conn, user_id=state.user_id)
        jobs = list_scheduled_jobs(conn, user_id=state.user_id, enabled_only=False)
        return {
            "status": "healthy",
            "telemetry": dataclasses.asdict(telemetry),
            "background_jobs": [_dump_data(j) for j in jobs],
        }

    @app.post("/api/jobs/run", dependencies=auth)
    def run_due_jobs_api(conn: Conn) -> dict[str, Any]:
        from copilot.runtime.runner import run_due_jobs

        runs = run_due_jobs(conn, user_id=state.user_id)
        conn.commit()
        return {"status": "ok", "jobs_executed": len(runs), "runs": [_dump_data(r) for r in runs]}

    # -- Phase 4: Experiments -------------------------------------------------------------
    @app.get("/api/experiments", dependencies=auth)
    def list_experiments_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        from copilot.db.repo_phase4 import list_experiments as repo_list_experiments

        exps = repo_list_experiments(conn, user_id=state.user_id, status=status)
        return [_dump_data(e) for e in exps]

    @app.get("/api/experiments/{id}", dependencies=auth)
    def get_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_experiment",
                {"experiment_id": id},
            )
        )
        return _dump_data(out)

    @app.get("/api/experiments/{id}/progress", dependencies=auth)
    def experiment_progress_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "experiment_progress",
                {"experiment_id": id},
            )
        )
        return _dump_data(out)

    @app.post("/api/experiments/design", dependencies=auth)
    def design_experiment_api(body: ExperimentDesignIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "design_experiment",
                body.model_dump(),
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/start", dependencies=auth)
    def start_experiment_api(body: ExperimentStartIn, conn: Conn) -> dict[str, Any]:
        if body.experiment_id:
            exp_id = body.experiment_id
        else:
            if not body.title or not body.metric_code:
                raise ApiException(
                    422,
                    ApiError(
                        code="INVALID_INPUT",
                        message="title and metric_code required when experiment_id is not provided",
                    ),
                )
            des_res = unwrap(
                execute_tool(
                    state.context(conn, "user"),
                    "design_experiment",
                    {
                        "title": body.title,
                        "metric_code": body.metric_code,
                        "template_code": body.template_code,
                        "categories": body.categories,
                        "merchants": body.merchants,
                        "duration_days": body.duration_days,
                        "difficulty": body.difficulty,
                        "target_value": body.target_value,
                        "baseline_median": body.baseline_median,
                        "start_date": body.start_date,
                        "goal_id": body.goal_id,
                        "rationale": body.rationale,
                        "origin": body.origin,
                    },
                )
            )
            exp_id = getattr(getattr(des_res, "experiment", des_res), "id", None)
            if not exp_id and isinstance(des_res, dict):
                exp_id = des_res.get("experiment", {}).get("id")

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "start_experiment",
                {"experiment_id": exp_id},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/{id}/pause", dependencies=auth)
    def pause_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "pause_experiment",
                {"experiment_id": id},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/{id}/resume", dependencies=auth)
    def resume_experiment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "resume_experiment",
                {"experiment_id": id},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/{id}/abandon", dependencies=auth)
    def abandon_experiment_api(id: str, body: ExperimentAbandonIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "abandon_experiment",
                {"experiment_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/{id}/checkin", dependencies=auth)
    def checkin_experiment_api(id: str, body: ExperimentCheckinIn, conn: Conn) -> dict[str, Any]:
        import uuid

        from copilot.core.experiments import calculate_pace
        from copilot.core.experiments import create_checkins as core_create_checkins
        from copilot.core.metrics import calculate_metric
        from copilot.core.timeutil import IST, now_utc, to_utc_iso
        from copilot.db.repo_phase4 import (
            get_experiment,
            insert_experiment_checkin,
        )
        from copilot.db.repo_phase4 import (
            list_experiment_checkins as repo_list_checkins,
        )
        from copilot.models.phase4 import ExperimentCheckin

        checkin_id = id if id.startswith("chk_") else None
        if not checkin_id:
            chks = repo_list_checkins(conn, user_id=state.user_id, experiment_id=id)
            if chks:
                checkin_id = chks[-1].id
            else:
                created = core_create_checkins(conn, user_id=state.user_id, clock=state.clock)
                matching = [c for c in created if c.experiment_id == id]
                if matching:
                    checkin_id = matching[0].id
                else:
                    exp = get_experiment(conn, state.user_id, id)
                    if exp is not None and exp.status == "active":
                        now_dt = state.clock or now_utc()
                        cur_date_str = now_dt.astimezone(IST).date().isoformat()
                        obs = calculate_metric(
                            conn,
                            state.user_id,
                            metric_code=exp.metric_def_json["metric_code"],
                            start_date=exp.window_start,
                            end_date=cur_date_str,
                            params=exp.params_json,
                        )
                        pace = calculate_pace(
                            observed_value=obs,
                            target_value=exp.target_value,
                            start_date=exp.window_start,
                            end_date=exp.window_end,
                            as_of_date=cur_date_str,
                            metric_code=exp.metric_def_json["metric_code"],
                        )
                        chk = ExperimentCheckin(
                            id=f"chk_{uuid.uuid4().hex[:12]}",
                            user_id=state.user_id,
                            experiment_id=exp.id,
                            checkin_date=cur_date_str,
                            observed_value=obs,
                            pace_status=pace,
                            created_at=to_utc_iso(now_dt),
                        )
                        insert_experiment_checkin(conn, chk)
                        checkin_id = chk.id
                    else:
                        raise not_found(f"Checkin for {id} not found")

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "answer_checkin",
                {"checkin_id": checkin_id, "response": body.user_response or "going_well"},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.get("/api/experiments/{id}/review", dependencies=auth)
    def get_review_api(id: str, conn: Conn) -> dict[str, Any]:
        from copilot.core.review_wording import describe_review
        from copilot.db.repo_phase4 import get_experiment as repo_get_experiment
        from copilot.db.repo_phase4 import get_experiment_review as repo_get_experiment_review

        rev = repo_get_experiment_review(conn, user_id=state.user_id, experiment_id=id)
        if not rev:
            raise not_found("Review", id)
        data = _dump_data(rev)
        exp = repo_get_experiment(conn, state.user_id, id)
        if exp is not None:
            w = describe_review(exp, rev)
            data["wording"] = {
                "headline": w.headline,
                "details": w.details,
                "needs_confirmation": w.needs_confirmation,
                "confirmation_prompt": w.confirmation_prompt,
            }
        return data

    @app.post("/api/experiments/{id}/confirm-integrity", dependencies=auth)
    def confirm_integrity_api(id: str, conn: Conn) -> dict[str, Any]:
        """The user vouches that recategorised payments in the window were genuine."""
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "confirm_review_integrity", {"experiment_id": id}
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/experiments/{id}/feedback", dependencies=auth)
    def review_feedback_api(id: str, body: ReviewFeedbackIn, conn: Conn) -> dict[str, Any]:
        from copilot.db.repo_phase4 import get_experiment_review as repo_get_experiment_review

        review_id = id if id.startswith("rev_") else None
        if not review_id:
            rev = repo_get_experiment_review(conn, user_id=state.user_id, experiment_id=id)
            if not rev:
                raise not_found(f"Review for experiment {id} not found")
            review_id = rev.id

        diff = body.difficulty_rating if body.difficulty_rating is not None else body.user_difficulty  # noqa: E501
        repeat = body.would_repeat if body.would_repeat is not None else body.user_would_repeat

        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "submit_review_feedback",
                {
                    "review_id": review_id,
                    "difficulty_rating": diff,
                    "user_helpful": body.user_helpful,
                    "would_repeat": repeat,
                    "feedback_text": body.feedback_text,
                },
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 4: Challenges & Offers -----------------------------------------------------
    @app.get("/api/challenges/offers", dependencies=auth)
    def list_offers_api(conn: Conn, status: str | None = None) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_offers",
                {"status": status},
            )
        )
        return _dump_data(out.offers if hasattr(out, "offers") else out)

    @app.post("/api/challenges/offers/suggest", dependencies=auth)
    def suggest_offers_api(body: OfferSuggestIn, conn: Conn) -> dict[str, Any]:
        ctx = state.context(conn, "user")
        ctx.llm_client = state.get_llm()  # None when no model is configured: rules only
        out = unwrap(execute_tool(ctx, "suggest_challenges", body.model_dump()))
        conn.commit()
        return _dump_data(out)

    @app.post("/api/challenges/offers/{id}/accept", dependencies=auth)
    def accept_offer_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "accept_offer",
                {"offer_id": id},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/challenges/offers/{id}/dismiss", dependencies=auth)
    def dismiss_offer_api(id: str, body: OfferDismissIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "dismiss_offer",
                {"offer_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 4: the screens' read model -------------------------------------------------
    @app.get("/api/coach", response_model=CoachView, dependencies=auth)
    def coach_api(conn: Conn) -> CoachView:
        return build_coach_view(conn, state.user_id, clock=now_utc(state.clock))

    # -- Phase 4: Adjustments -------------------------------------------------------------
    @app.get("/api/adjustments", dependencies=auth)
    def list_adjustments_api(
        conn: Conn, experiment_id: str | None = None
    ) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "list_adjustments",
                {"experiment_id": experiment_id},
            )
        )
        return _dump_data(out.proposals if hasattr(out, "proposals") else out)

    @app.post("/api/adjustments/{id}/accept", dependencies=auth)
    def accept_adjustment_api(id: str, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "accept_adjustment",
                {"proposal_id": id},
            )
        )
        conn.commit()
        return _dump_data(out)

    @app.post("/api/adjustments/{id}/reject", dependencies=auth)
    def reject_adjustment_api(id: str, body: AdjustmentRejectIn, conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "reject_adjustment",
                {"proposal_id": id, "reason": body.reason},
            )
        )
        conn.commit()
        return _dump_data(out)

    # -- Phase 4: Progress & Gamification -------------------------------------------------
    @app.get("/api/progress", dependencies=auth)
    def progress_api(conn: Conn) -> dict[str, Any]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_user_progress",
                {},
            )
        )
        return _dump_data(out)

    @app.get("/api/progress/bests", dependencies=auth)
    def personal_bests_api(conn: Conn) -> list[dict[str, Any]]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "get_personal_bests",
                {},
            )
        )
        return _dump_data(out.personal_bests if hasattr(out, "personal_bests") else out)

    # -- Phase 4: Goal Gap Decomposition --------------------------------------------------
    @app.post("/api/goals/{id}/decompose", dependencies=auth)
    def decompose_goal_api(id: str, conn: Conn) -> dict[str, Any]:
        from copilot.core.challenges import decompose_goal_gap

        decomp = decompose_goal_gap(conn, user_id=state.user_id, goal_id=id, clock=state.clock)
        return _dump_data(decomp)

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
