"""
Orchestration used by the API: demo seeding and the import pipeline.

Import = ingest_statements (agent) -> categorisation pipeline (agent, writes through
categorize_batch) -> transfer, recurring, anomaly and alert detection (agent). Every step goes
through execute_tool. With no LLM configured the categoriser's AI step returns nothing, so
merchants without a rule go to the review queue; nothing is invented.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from copilot.api.errors import ApiError, ApiException, unwrap
from copilot.api.read_models import ImportResult, categorisation_events, list_consent_views
from copilot.api.state import ApiState
from copilot.bank.ingest import set_connector
from copilot.bank.mock_bank import MockAAConnector
from copilot.bank.synth import generate_transactions
from copilot.core.categorisation import load_aliases, load_rules
from copilot.core.config import load_settings
from copilot.core.pipeline import run_categorization_pipeline
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.connection import savepoint
from copilot.db.repo import (
    get_account,
    get_category,
    get_user,
    insert_account,
    insert_budget,
    insert_category,
    insert_user,
    list_budgets,
)
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

DEMO_SEED = 42
DEMO_MONTHS = 3
DEMO_ACCOUNT = "a1"
#: "Today" in the demo world: the synthetic history runs January to March 2024.
DEMO_CLOCK = datetime(2024, 3, 18, 12, 0, tzinfo=IST)
T0 = "2024-01-01T00:00:00Z"

DEMO_CATEGORIES = (
    ("food", "Dining"),
    ("groceries", "Groceries"),
    ("travel", "Travel"),
    ("shopping", "Shopping"),
    ("bills", "Utilities"),
    ("subscriptions", "Subscriptions"),
    ("education", "Education"),
    ("entertainment", "Entertainment"),
    ("housing", "Rent"),
    ("income", "Income"),
)
DEMO_BUDGETS = (("food", 700000), ("travel", 150000), ("shopping", 250000), ("groceries", 150000))


def register_all_tools() -> None:
    """Register every tool the API can reach (idempotent)."""
    ensure_tools_registered()
    from copilot.tools.consents import register_consent_tools

    register_consent_tools()


#: Local-shop UPI payments no categorisation rule recognises: they exercise the review queue.
_LOCAL_SHOPS = (
    ("UPI-RAMESH GENERAL STORE-rameshgs@okaxis-REF300114", 18000, "2024-02-09T13:10:00Z"),
    ("UPI-9876543210@ybl-PAYMENT FROM PHONE", 25000, "2024-02-14T16:40:00Z"),
    ("UPI-SHARMA STATIONERS-sharma77@paytm-REF300871", 14500, "2024-02-21T11:05:00Z"),
    ("UPI-KRISHNA JUICE CENTRE-krishnaj@ibl-REF301224", 6000, "2024-02-27T17:20:00Z"),
    ("UPI-AMIT KUMAR-amit.k42@oksbi-REF301990", 50000, "2024-03-03T19:30:00Z"),
    ("UPI-SAI COPY AND PRINT-saicp@ybl-REF302418", 9000, "2024-03-07T10:15:00Z"),
    ("UPI-MAHESH PAN SHOP-mahesh9@okaxis-REF303005", 3000, "2024-03-11T21:45:00Z"),
    ("UPI-CITY CYCLE WORKS-citycycle@ibl-REF303377", 42000, "2024-03-14T12:00:00Z"),
)


def _local_shop_transactions(user_id: str, account_id: str) -> list[Transaction]:
    return [
        Transaction(
            id=f"demo_local_{i}",
            user_id=user_id,
            account_id=account_id,
            occurred_at=when,
            amount_paise=paise,
            direction="debit",
            merchant_raw=raw,
            description="UPI payment",
            created_at=when,
        )
        for i, (raw, paise, when) in enumerate(_LOCAL_SHOPS, start=1)
    ]


def register_demo_connector(state: ApiState, conn: sqlite3.Connection) -> MockAAConnector:
    """
    Register the synthetic bank (regenerated from the fixed seed) and mirror DB consents into it.

    The mock connector checks expiry against the wall clock, not the injected demo clock, so
    the mirrored expiry is the DB value only when it lies in the real future; otherwise the
    DB-level check in run_import (which uses the demo clock) is the one that applies.
    """
    synth = generate_transactions(
        seed=DEMO_SEED, months=DEMO_MONTHS, user_id=state.user_id, account_ids=[DEMO_ACCOUNT]
    )
    connector = MockAAConnector(
        [*synth.transactions, *_local_shop_transactions(state.user_id, DEMO_ACCOUNT)]
    )
    real_now = to_utc_iso(datetime.now(tz=IST))
    for r in conn.execute("SELECT * FROM consents WHERE user_id = ?", (state.user_id,)):
        expires = r["expires_at"] if (r["expires_at"] or "") > real_now else "2999-01-01T00:00:00Z"
        connector._consents[r["id"]] = {
            "user_id": state.user_id,
            "account_ids": json.loads(r["account_ids"]),
            "range_from": r["date_range_from"],
            "range_to": r["date_range_to"],
            "status": r["status"],
            "expires_at": expires,
        }
    set_connector(connector)
    return connector


def seed_demo(
    state: ApiState, conn: sqlite3.Connection, mode: Literal["empty", "imported"] = "empty"
) -> str:
    """
    Seed the demo user with categories, budgets and a pending consent. Returns the consent id.

    mode 'empty': no transactions yet (the demo starts at Connect).
    mode 'imported': also approves the consent and runs the real import pipeline.
    """
    register_all_tools()
    clock = state.clock or DEMO_CLOCK
    consent_id = f"consent_demo_{state.user_id}"
    with savepoint(conn):
        if get_user(conn, state.user_id) is None:
            insert_user(conn, User(id=state.user_id, created_at=T0))
        if get_account(conn, state.user_id, DEMO_ACCOUNT) is None:
            insert_account(
                conn,
                Account(
                    id=DEMO_ACCOUNT,
                    user_id=state.user_id,
                    name="Student savings",
                    opening_balance_paise=2500000,
                    created_at=T0,
                ),
            )
        for cid, name in DEMO_CATEGORIES:
            if get_category(conn, state.user_id, cid) is None:
                insert_category(
                    conn, Category(id=cid, user_id=state.user_id, name=name, created_at=T0)
                )
        existing = {b.category_id for b in list_budgets(conn, state.user_id)}
        for cid, limit in DEMO_BUDGETS:
            if cid not in existing:
                insert_budget(
                    conn,
                    Budget(
                        id=f"b_{cid}",
                        user_id=state.user_id,
                        category_id=cid,
                        limit_paise=limit,
                        warn_threshold_pct=80,
                        forecast_warn=True,
                    ),
                )
        if conn.execute("SELECT 1 FROM consents WHERE id = ?", (consent_id,)).fetchone() is None:
            conn.execute(
                "INSERT INTO consents (id, user_id, purpose, fi_types, account_ids, "
                "date_range_from, date_range_to, status, expires_at, created_at) "
                "VALUES (?, ?, 'Budgeting and spending analysis', 'DEPOSIT', ?, ?, ?, "
                "'pending', ?, ?)",
                (
                    consent_id,
                    state.user_id,
                    json.dumps([DEMO_ACCOUNT]),
                    T0,
                    to_utc_iso(clock),
                    to_utc_iso(clock + timedelta(days=180)),
                    to_utc_iso(clock - timedelta(minutes=5)),
                ),
            )
    user_ctx = state.context(conn, actor="user")
    if not conn.execute(
        "SELECT 1 FROM goals WHERE user_id = ? LIMIT 1", (state.user_id,)
    ).fetchone():
        execute_tool(
            user_ctx,
            "create_goal",
            {
                "name": "Laptop fund",
                "kind": "purchase",
                "target_paise": 4500000,
                "current_paise": 800000,
                "deadline": "2024-09-30",
                "priority": 1,
            },
        )
        conn.commit()
    if mode == "imported":
        ctx = user_ctx
        unwrap(execute_tool(ctx, "approve_consent", {"consent_id": consent_id}))
        conn.commit()
        run_import(state, conn, consent_id)
    return consent_id


def run_import(state: ApiState, conn: sqlite3.Connection, consent_id: str) -> ImportResult:
    """Import statements for an active consent and categorise them, through the executor."""
    register_all_tools()
    consent = next(
        (c for c in list_consent_views(conn, state.user_id, state.clock) if c.id == consent_id),
        None,
    )
    if consent is None:
        raise ApiException(404, ApiError(code="NOT_FOUND", message="Consent not found."))
    if consent.status != "active":
        raise ApiException(
            409,
            ApiError(
                code="STALE_DATA",
                message=f"Consent is {consent.status}; approve it before importing.",
            ),
        )
    register_demo_connector(state, conn)
    agent = state.context(conn, actor="agent")

    fetched = inserted = skipped = duplicates = 0
    for account_id in consent.account_ids:
        out = unwrap(
            execute_tool(
                agent, "ingest_statements", {"account_id": account_id, "consent_id": consent_id}
            )
        )
        fetched += out.fetched  # type: ignore[attr-defined]
        inserted += out.inserted  # type: ignore[attr-defined]
        skipped += out.skipped_existing  # type: ignore[attr-defined]
        duplicates += out.duplicates_flagged  # type: ignore[attr-defined]
    conn.commit()

    batch = conn.execute(
        "SELECT id FROM ingestion_batches WHERE user_id = ? AND consent_id = ? "
        "ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (state.user_id, consent_id),
    ).fetchone()
    batch_id = batch["id"] if batch else None

    settings = load_settings()
    rules = (
        load_rules(settings.categorization_rules_path)
        if settings.categorization_rules_path.exists()
        else []
    )
    aliases = (
        load_aliases(settings.merchant_aliases_path)
        if settings.merchant_aliases_path.exists()
        else {}
    )
    run_categorization_pipeline(agent, FakeLLMClient([]), rules, aliases, "none", "v1", settings)
    conn.commit()

    now = now_utc(state.clock).astimezone(IST)
    prev_year, prev_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    for tool, args in (
        ("detect_transfers", {}),
        ("detect_recurring", {}),
        ("detect_anomalies", {}),
        # The month in progress and the one just closed: closed months are where budgets broke.
        ("evaluate_alerts", {"period": f"{prev_year:04d}-{prev_month:02d}"}),
        ("evaluate_alerts", {"period": f"{now.year:04d}-{now.month:02d}"}),
    ):
        execute_tool(agent, tool, args)  # best effort: failures are audited, not fatal
        conn.commit()

    events = categorisation_events(conn, state.user_id, batch_id)
    by_rule = sum(1 for e in events if e.source in ("rule", "override") and not e.needs_review)
    by_ai = sum(1 for e in events if e.source in ("llm", "cache") and not e.needs_review)
    review = sum(1 for e in events if e.needs_review)
    return ImportResult(
        batch_id=batch_id,
        fetched=fetched,
        inserted=inserted,
        skipped_existing=skipped,
        duplicates_flagged=duplicates,
        by_rule=by_rule,
        by_ai=by_ai,
        needs_review=review,
        other=len(events) - by_rule - by_ai - review,
        events=events,
    )


def ensure_demo(state: ApiState, mode: Literal["empty", "imported"]) -> None:
    """Seed the demo database if it has no user yet."""
    conn = state.connect()
    try:
        if get_user(conn, state.user_id) is None:
            seed_demo(state, conn, mode)
            conn.commit()
    finally:
        conn.close()


def draft_month_advice(state: ApiState, conn: sqlite3.Connection, year: int, month: int) -> int:
    """
    Draft advice for a month from validated findings, all through the executor.

    Same path as the Phase 1 workflow: analysis tools -> findings -> draft_advice (which
    validates every number against the findings and falls back to templates). Skips months
    that already have draft advice so repeated review builds do not pile up duplicates.
    """
    from copilot.db.repo import list_categories
    from copilot.workflow.findings import build_findings_from_analysis

    register_all_tools()
    existing = conn.execute(
        "SELECT 1 FROM advice_items WHERE user_id = ? AND evidence_json LIKE ? LIMIT 1",
        (state.user_id, f'%"period": "{year:04d}-{month:02d}"%'),
    ).fetchone()
    if existing:
        return 0
    agent = state.context(conn, actor="agent")
    names = {c.id: c.name for c in list_categories(conn, state.user_id)}

    budgets = []
    res = execute_tool(agent, "check_budgets", {"year": year, "month": month})
    if res.ok:
        for b in res.data.statuses:  # type: ignore[union-attr]
            row = b.model_dump(mode="json")
            row["category_name"] = names.get(b.category_id, b.category_id)
            budgets.append(row)
    forecast_res = execute_tool(agent, "forecast_month", {"year": year, "month": month})
    forecast = (
        forecast_res.data.model_dump(mode="json") if forecast_res.ok and forecast_res.data else {}
    )
    anomalies_res = execute_tool(agent, "detect_anomalies", {})
    anomalies = []
    for a in getattr(anomalies_res.data, "anomalies", []) if anomalies_res.ok else []:
        tx_id = a.get("txn_id") or a.get("transaction_id")
        row = conn.execute(
            "SELECT amount_paise, merchant_raw, merchant_normalized, occurred_at FROM transactions "
            "WHERE id = ? AND user_id = ?",
            (tx_id, state.user_id),
        ).fetchone()
        if row is None or not row["occurred_at"].startswith(f"{year:04d}-{month:02d}"):
            continue
        anomalies.append(
            {
                "transaction_id": tx_id,
                "amount_paise": abs(row["amount_paise"]),
                "merchant_raw": (row["merchant_normalized"] or row["merchant_raw"]).title(),
            }
        )
    findings = build_findings_from_analysis(
        year, month, {"budgets": budgets, "forecast": forecast, "anomalies": anomalies}
    )
    if not findings:
        return 0
    out = execute_tool(agent, "draft_advice", {"findings": [f.model_dump() for f in findings]})
    conn.commit()
    return len(getattr(out.data, "advice_items", [])) if out.ok else 0
