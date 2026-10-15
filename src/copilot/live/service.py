"""
Live mode: set up an empty real profile and import real statement rows into it.

Rows are stored with the same columns and rules as the demo's imports (integer paise, UTC
timestamps, fingerprints), so every existing screen, tool and the Ask agent work on them
unchanged. Raw narrations stay in the local database; the audit event holds counts only.
"""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from copilot.api.services import DEMO_CATEGORIES, T0, register_all_tools
from copilot.api.state import ApiState
from copilot.audit.events import record_event
from copilot.core.categorisation import load_aliases, load_rules, normalize_merchant
from copilot.core.config import load_settings
from copilot.core.money import rupees_to_paise
from copilot.core.pipeline import get_categories, get_overrides, run_categorization_pipeline
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo import (
    get_account,
    get_category,
    get_user,
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
    list_budgets,
)
from copilot.live.statement import ParsedStatement, StatementRow
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.rails.engine import categorize, ensure_schema, reconcile

# Real life needs more than a student demo does. Users can add their own on top of these.
LIVE_CATEGORIES = (
    *DEMO_CATEGORIES,
    ("health", "Healthcare"),
    ("cash", "Cash withdrawal"),
    ("transfers", "Friends and family"),
    ("personal", "Personal care"),
    ("gifts", "Gifts and donations"),
    ("fees", "Bank fees and charges"),
)

LIVE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "live.yaml"


def live_config() -> dict:
    return yaml.safe_load(LIVE_CONFIG.read_text(encoding="utf-8"))


def account_id() -> str:
    return live_config()["account"]["id"]


def seed_live(state: ApiState, conn: sqlite3.Connection) -> None:
    """Create the user, one account, categories and budgets. Idempotent, no sample data."""
    cfg = live_config()
    if get_user(conn, state.user_id) is None:
        insert_user(conn, User(id=state.user_id, created_at=T0))
    acct = cfg["account"]
    if get_account(conn, state.user_id, acct["id"]) is None:
        insert_account(
            conn,
            Account(
                id=acct["id"],
                user_id=state.user_id,
                name=acct["name"],
                opening_balance_paise=0,
                created_at=T0,
            ),
        )
    for cid, name in LIVE_CATEGORIES:
        if get_category(conn, state.user_id, cid) is None:
            insert_category(conn, Category(id=cid, user_id=state.user_id, name=name, created_at=T0))
    have = {b.category_id for b in list_budgets(conn, state.user_id)}
    for cid, rupees in cfg["budgets"].items():
        if cid not in have and get_category(conn, state.user_id, cid) is not None:
            insert_budget(
                conn,
                Budget(
                    id=f"b_{cid}",
                    user_id=state.user_id,
                    category_id=cid,
                    limit_paise=rupees_to_paise(int(rupees)),
                    warn_threshold_pct=80,
                    forecast_warn=True,
                ),
            )
    ensure_schema(conn)


class ImportSummary(BaseModel):
    source: str
    read: int
    inserted: int
    skipped_existing: int
    needs_review: int
    unreadable: int
    unreadable_examples: list[str] = []
    verified_alerts: int = 0
    still_provisional: int = 0
    ai_used: bool = False
    ai_applied: int = 0  # rows the model labelled with enough confidence to apply
    ai_calls: int = 0
    ai_failed_calls: int = 0
    ai_note: str | None = None


def _mode(narration: str) -> str:
    low = narration.lower()
    for key, mode in (
        ("upi", "upi"),
        ("atm", "atm"),
        ("neft", "neft"),
        ("imps", "imps"),
        ("pos ", "card"),
        ("card", "card"),
    ):
        if key in low:
            return mode
    return "other"


def import_rows(
    conn: sqlite3.Connection,
    user_id: str,
    rows: list[StatementRow],
    source: str,
    clock: datetime | None = None,
    parsed: ParsedStatement | None = None,
) -> ImportSummary:
    """
    Insert statement rows once each. Re-importing an overlapping statement adds nothing.

    Two genuinely identical rows on one day (no reference) are both kept: the fingerprint
    includes how many identical rows came before it in this file.
    """
    ensure_schema(conn)
    now = now_utc(clock)
    aliases = load_aliases(load_settings().merchant_aliases_path)
    acct = account_id()
    overrides = get_overrides(conn, user_id)  # what the user already taught us
    known = get_categories(conn, user_id)
    seen: dict[str, int] = {}
    inserted = skipped = review = 0
    for row in rows:
        signed = row.amount_paise if row.direction == "debit" else -row.amount_paise
        base = f"{acct}|{row.occurred_at}|{signed}|{row.narration}|{row.reference or ''}"
        seen[base] = seen.get(base, 0) + 1
        fingerprint = hashlib.sha256(f"{user_id}|{base}|{seen[base]}".encode()).hexdigest()
        if conn.execute(
            "SELECT 1 FROM transactions WHERE user_id = ? AND fingerprint = ?",
            (user_id, fingerprint),
        ).fetchone():
            skipped += 1
            continue
        normalized = normalize_merchant(row.narration, aliases)
        if overrides.get(normalized) in known:
            category, source_tag = overrides[normalized], "override"
        else:
            category, source_tag = categorize(row.narration, row.amount_paise, row.direction)
            if category not in known:
                category, source_tag = None, "none"
        needs_review = category is None and row.direction == "debit"
        insert_transaction(
            conn,
            Transaction(
                id="st_" + fingerprint[:24],
                user_id=user_id,
                account_id=acct,
                occurred_at=row.occurred_at,
                amount_paise=signed,
                direction=row.direction,  # type: ignore[arg-type]
                merchant_raw=row.narration,
                description=row.reference or "",
                category_id=category,
                category_confidence=1.0 if source_tag == "override" else 0.9 if category else None,
                category_source=(
                    "override" if source_tag == "override" else "rule" if category else "none"
                ),
                created_at=to_utc_iso(now),
                fingerprint=fingerprint,
                merchant_normalized=normalized,
                mode=_mode(row.narration),  # type: ignore[arg-type]
                needs_review=needs_review,
            ),
        )
        inserted += 1
        review += int(needs_review)
    unreadable = parsed.rejected_count if parsed else 0
    record_event(
        conn,
        user_id,
        "user",
        "live_statement_imported",
        "User imported real statement rows into live mode.",
        after_data={
            "source": source,
            "read": len(rows),
            "inserted": inserted,
            "skipped_existing": skipped,
            "needs_review": review,
            "unreadable": unreadable,
        },
        clock=now,
    )
    matched = reconcile(conn, user_id, clock)
    return ImportSummary(
        source=source,
        read=len(rows),
        inserted=inserted,
        skipped_existing=skipped,
        needs_review=review,
        unreadable=unreadable,
        unreadable_examples=[f"line {n}: {why}" for n, why in (parsed.rejected if parsed else [])],
        verified_alerts=matched.verified,
        still_provisional=matched.still_provisional,
    )


AI_BUDGET_S = 240.0  # a long statement may need several model calls


def queue_size(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND needs_review = 1", (user_id,)
    ).fetchone()[0]


def _applied_by_ai(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND needs_review = 0"
        " AND category_source IN ('llm', 'cache')",
        (user_id,),
    ).fetchone()[0]


def ai_categorize(
    state: ApiState, conn: sqlite3.Connection, summary: ImportSummary
) -> ImportSummary:
    """
    Let the model label merchants the rules did not know, then report what is left for the user.

    Goes through the same pipeline and `categorize_batch` tool as the demo, so confident answers
    are applied, unsure ones stay in the review queue with the AI's suggestion, and every change
    is audited. Merchant text is redacted before it leaves the machine, and each merchant is sent
    once however many rows it has. With no model, or if it fails, nothing breaks: the rows simply
    stay in the review queue.
    """
    llm = state.get_llm()
    if llm is None:
        summary.needs_review = queue_size(conn, state.user_id)
        summary.ai_note = (
            "No AI model is configured, so unknown merchants wait in the review queue."
        )
        return summary
    if hasattr(llm, "begin_request"):
        llm.begin_request(AI_BUDGET_S)
    register_all_tools()
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
    before = _applied_by_ai(conn, state.user_id)
    try:
        report = run_categorization_pipeline(
            state.context(conn, actor="agent"), llm, rules, aliases, "router", "v1", settings
        )
    except Exception:  # noqa: BLE001 - the import already succeeded; the model is optional
        conn.rollback()
        summary.needs_review = queue_size(conn, state.user_id)
        summary.ai_note = "The AI model failed; those rows wait in the review queue."
        return summary
    conn.commit()
    summary.ai_used = True
    summary.ai_calls = report.llm_calls
    summary.ai_failed_calls = report.llm_failures
    summary.ai_applied = _applied_by_ai(conn, state.user_id) - before
    summary.needs_review = queue_size(conn, state.user_id)
    if report.llm_failures and not summary.ai_applied:
        summary.ai_note = "The AI model could not be reached; those rows wait in the review queue."
    return summary
