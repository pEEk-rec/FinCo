# ruff: noqa: E501  (prose and SQL lines)
"""
The owner's gold set (PLAN_AGENTIC_V2, A0 and open question O-1).

Measure categorisation on your own real transactions without ever showing them to anyone:

1. `prepare_sheet` reads the payments already in your local database and writes a CSV with only a
   row number, the date, the *cleaned* name, the amount in rupees and an empty category column. No
   account numbers, balances, references or raw narrations.
2. You fill in the category column in a spreadsheet, on your own computer.
3. `evaluate_sheet` replays your labelled rows week by week through the cascade (no model, no
   network): the system decides what it can, asks about the rest, and is "answered" by your
   labels. It returns totals only, so the result is safe to paste into a chat.

The sheet lives under `data/gold/`, which is git-ignored.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.settings import load_settings
from copilot.common.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.models.domain import Account, Category, Transaction, User
from copilot.understand import learn
from copilot.understand.cascade import Cascade, Item
from copilot.understand.descriptor import parse_descriptor
from copilot.understand.rules import load_aliases, load_rules

GOLD_DIR = Path(__file__).resolve().parents[3] / "data" / "gold"
COLUMNS = ("row", "date", "name", "amount_rupees", "category")


def prepare_sheet(
    conn: sqlite3.Connection, user_id: str, out: Path | None = None, limit: int = 150
) -> tuple[Path, int]:
    """Write the labelling sheet from the user's own ledger. Returns (path, rows)."""
    out = out or GOLD_DIR / "sheet.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT occurred_at, merchant_raw, amount_paise FROM transactions WHERE user_id = ?"
        " AND direction = 'debit' AND is_duplicate_of IS NULL ORDER BY occurred_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for i, (when, raw, paise) in enumerate(reversed(rows), start=1):
            name = parse_descriptor(raw).name
            w.writerow([i, when[:10], name, f"{abs(paise) // 100}.{abs(paise) % 100:02d}", ""])
    return out, len(rows)


@dataclass
class GoldResult:
    rows: int
    categories: int
    applied: int
    accuracy: float
    coverage: float
    questions_per_100: float
    weeks: int


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_") or "other"


def evaluate_sheet(path: Path) -> GoldResult:
    """Replay a filled-in sheet. Totals only: no name or amount leaves this function."""
    with path.open(newline="", encoding="utf-8") as f:
        raw = [r for r in csv.DictReader(f) if (r.get("category") or "").strip()]
    if len(raw) < 20:
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Label at least 20 rows before evaluating.")
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    t0 = "2026-01-01T00:00:00Z"
    insert_user(conn, User(id="gold", created_at=t0))
    insert_account(
        conn, Account(id="a", user_id="gold", name="G", opening_balance_paise=0, created_at=t0)
    )
    cats = {_slug(r["category"]): r["category"].strip() for r in raw}
    for cid, name in cats.items():
        insert_category(conn, Category(id=cid, user_id="gold", name=name, created_at=t0))
    items: list[tuple[int, Item, str]] = []
    first = datetime.fromisoformat(min(r["date"] for r in raw)).replace(tzinfo=IST, hour=12)
    for i, r in enumerate(sorted(raw, key=lambda r: (r["date"], int(r["row"])))):
        when = datetime.fromisoformat(r["date"]).replace(tzinfo=IST, hour=12)
        paise = round(float(r["amount_rupees"]) * 100)
        insert_transaction(
            conn,
            Transaction(
                id=f"g{i}", user_id="gold", account_id="a", occurred_at=to_utc_iso(when),
                amount_paise=paise, direction="debit", merchant_raw=r["name"], description="",
                created_at=to_utc_iso(when),
            ),
        )  # fmt: skip
        week = (when - first).days // 7
        items.append((week, Item(f"g{i}", r["name"], paise, "debit"), _slug(r["category"])))
    settings = load_settings()
    cas = Cascade(
        conn, "gold", categories=cats, rules=load_rules(settings.categorization_rules_path),
        aliases=load_aliases(settings.merchant_aliases_path), clock=first,
    )  # fmt: skip
    truth = {it.tx_id: cat for _w, it, cat in items}
    by_week: dict[int, list[Item]] = defaultdict(list)
    for w, it, _c in items:
        by_week[w].append(it)
    applied = right = questions = 0
    for week in sorted(by_week):
        decisions = cas.run(by_week[week])
        applied += sum(d.applied for d in decisions)
        right += sum(d.applied and d.category_id == truth[d.tx_id] for d in decisions)
        when = first + timedelta(days=week * 7 + 7)
        for q in learn.rank_questions(conn, "gold", clock=when):
            if q.kind == "person":
                for tid in q.tx_ids:
                    learn.answer_transaction(conn, "gold", tid, truth[tid])
                    questions += 1
            else:
                learn.answer_entity(conn, "gold", q.entity_id, truth[q.tx_ids[0]])
                questions += 1
    n = len(items)
    return GoldResult(
        rows=n, categories=len(cats), applied=applied,
        accuracy=right / applied if applied else 1.0, coverage=applied / n,
        questions_per_100=100 * questions / n, weeks=len(by_week),
    )  # fmt: skip
