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

from copilot.api.services import DEMO_CATEGORIES, T0
from copilot.api.state import ApiState
from copilot.audit.events import record_event
from copilot.core.categorisation import load_aliases, normalize_merchant
from copilot.core.config import load_settings
from copilot.core.money import rupees_to_paise
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
    for cid, name in DEMO_CATEGORIES:
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
        category, source_tag = categorize(row.narration, row.amount_paise, row.direction)
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
                category_confidence=0.9 if category else None,
                category_source="rule" if category else "none",
                created_at=to_utc_iso(now),
                fingerprint=fingerprint,
                merchant_normalized=normalize_merchant(row.narration, aliases),
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
