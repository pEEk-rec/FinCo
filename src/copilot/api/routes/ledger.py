"""The ledger: dashboard, categories, transactions, the review queue, consents and imports."""

import re
import sqlite3
from typing import Literal

from fastapi import FastAPI, Query

from copilot.api import read_models as rm
from copilot.api.contracts import (
    CategoryIn,
    CategoryOut,
    ConsentDecisionOut,
    RecategorizeIn,
    RecategorizeOut,
    UndoIn,
    UndoOut,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import ApiError, ApiException, not_found, unwrap
from copilot.api.helpers import MAX_CATEGORIES
from copilot.api.services import run_import
from copilot.api.state import ApiState
from copilot.audit.events import record_event
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.db.repo import (
    insert_category,
    list_categories,
)
from copilot.models.domain import Category
from copilot.tools.executor import execute_tool


def register(app: FastAPI, state: ApiState) -> None:
    # -- reads ---------------------------------------------------------------------------------
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
            conn,
            state.user_id,
            "user",
            "category_created",
            "User created a category.",
            entity_type="category",
            entity_id=slug,
            after_data={"name": name},
            clock=now,
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

    # -- writes: transactions ------------------------------------------------------------------
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

    # -- consents and import -------------------------------------------------------------------
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
