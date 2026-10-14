"""
The rails engine: live SMS alerts, receipt splits, reconciliation and budget pacing.

Statement (Account Aggregator) rows stay the source of truth. An SMS creates a *provisional*
payment the moment it arrives, so budgets react in seconds; when the statement later contains
the same payment, the provisional record is *verified* and linked, never counted twice.
Receipt splits are drafts: they change nothing until the user approves them.
All money is integer paise. Every state change writes an audit event.
"""

import hashlib
import json
import sqlite3
import uuid
from calendar import monthrange
from datetime import datetime, timedelta

from pydantic import BaseModel

from copilot.audit.events import record_event
from copilot.core.advice import format_inr
from copilot.core.categorisation import evaluate_rules, load_aliases, load_rules, normalize_merchant
from copilot.core.config import load_settings
from copilot.core.timeutil import IST, from_utc_iso, month_bounds, now_utc, to_utc_iso
from copilot.rails.receipts import (
    NotAReceipt,
    Receipt,
    parse_receipt,
    rails_config,
    split_by_category,
)
from copilot.rails.sms import NotAPayment, ParsedSms, parse_sms

SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    rail TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    received_at TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    merchant TEXT NOT NULL,
    reference TEXT,
    account_tail TEXT,
    category_id TEXT,
    category_source TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    matched_txn_id TEXT,
    parsed_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rail_splits (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    merchant TEXT,
    event_id TEXT,
    txn_id TEXT,
    category_id TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the rails tables (own tables; the core schema is untouched)."""
    conn.executescript(SCHEMA)


# ----------------------------------------------------------------------------- output models


class RailEventOut(BaseModel):
    id: str
    rail: str
    status: str
    direction: str
    amount: str
    amount_paise: int
    merchant: str
    occurred_at: str
    category_id: str | None
    category_name: str | None
    category_source: str
    needs_review: bool
    matched_txn_id: str | None
    reference: str | None


class IngestOut(BaseModel):
    outcome: str  # provisional | duplicate | refused
    reason: str | None = None
    event: RailEventOut | None = None


class SplitPart(BaseModel):
    id: str
    category_id: str
    category_name: str | None
    amount: str
    amount_paise: int
    status: str


class ReceiptOut(BaseModel):
    outcome: str  # suggested | unmatched | refused
    reason: str | None = None
    receipt_id: str | None = None
    merchant: str | None = None
    payment: RailEventOut | None = None
    parts: list[SplitPart] = []
    problems: list[str] = []


class ReconcileOut(BaseModel):
    verified: int
    still_provisional: int
    matches: list[dict[str, str]]


class PaceRow(BaseModel):
    category_id: str
    category_name: str
    limit: str
    limit_paise: int
    percent_settled: int
    percent_provisional: int
    settled: str
    provisional: str
    total: str
    percent_used: int
    projected: str
    projected_percent: int
    status: str  # ok | watch | projected_over | over
    message: str


class PacingOut(BaseModel):
    period: str
    day: int
    days_in_month: int
    rows: list[PaceRow]
    provisional_count: int
    headline: str


# ----------------------------------------------------------------------------- helpers


def _names(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    rows = conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,)).fetchall()
    return {r["id"]: r["name"] for r in rows}


def _out(row: sqlite3.Row, names: dict[str, str]) -> RailEventOut:
    return RailEventOut(
        id=row["id"],
        rail=row["rail"],
        status=row["status"],
        direction=row["direction"],
        amount=format_inr(row["amount_paise"]),
        amount_paise=row["amount_paise"],
        merchant=row["merchant"],
        occurred_at=row["occurred_at"],
        category_id=row["category_id"],
        category_name=names.get(row["category_id"] or ""),
        category_source=row["category_source"],
        needs_review=bool(row["needs_review"]),
        matched_txn_id=row["matched_txn_id"],
        reference=row["reference"],
    )


def _fingerprint(p: ParsedSms) -> str:
    key = p.reference or f"{p.occurred_at[:16]}|{p.merchant.lower()}"
    raw = f"{p.account_tail}|{p.direction}|{p.amount_paise}|{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def categorize(merchant: str, amount_paise: int, direction: str) -> tuple[str | None, str]:
    """(category_id, source): user-visible rules first, then bill-pay billers, else unknown."""
    settings = load_settings()
    normalized = normalize_merchant(merchant, load_aliases(settings.merchant_aliases_path))
    hit = evaluate_rules(
        normalized, amount_paise, direction, load_rules(settings.categorization_rules_path)
    )
    if hit:
        return hit[0], "rule"
    import re

    for biller in [*rails_config()["merchants"], *rails_config()["billers"]]:
        if re.search(biller["match"], normalized, re.I):
            return biller["category_id"], "biller"
    return None, "none"


# ----------------------------------------------------------------------------- SMS rail


def ingest_sms(
    conn: sqlite3.Connection, user_id: str, text: str, clock: datetime | None = None
) -> IngestOut:
    """Turn one alert into a provisional payment. Same alert twice is reported, not repeated."""
    ensure_schema(conn)
    now = now_utc(clock)
    try:
        parsed = parse_sms(text, now)
    except NotAPayment as exc:
        return IngestOut(outcome="refused", reason=str(exc))
    names = _names(conn, user_id)
    fp = _fingerprint(parsed)
    existing = conn.execute("SELECT * FROM rail_events WHERE fingerprint = ?", (fp,)).fetchone()
    if existing:
        return IngestOut(
            outcome="duplicate", reason="already received", event=_out(existing, names)
        )
    category, source = categorize(parsed.merchant, parsed.amount_paise, parsed.direction)
    if category not in names:  # a rule may name a category this profile does not have
        category, source = None, "none"
    review = category is None or (parsed.is_p2p and source == "none")
    event_id = f"rail_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO rail_events (id, user_id, rail, fingerprint, received_at, occurred_at,"
        " direction, amount_paise, merchant, reference, account_tail, category_id,"
        " category_source, needs_review, status, parsed_json)"
        " VALUES (?, ?, 'sms', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'provisional', ?)",
        (
            event_id,
            user_id,
            fp,
            to_utc_iso(now),
            parsed.occurred_at,
            parsed.direction,
            parsed.amount_paise,
            parsed.merchant,
            parsed.reference,
            parsed.account_tail,
            category,
            source,
            int(review),
            json.dumps({"bank": parsed.bank, "card": parsed.is_card, "p2p": parsed.is_p2p}),
        ),
    )
    record_event(
        conn,
        user_id,
        "system",
        "rail_sms_ingested",
        "Bank alert read and held as provisional until the statement confirms it.",
        entity_type="rail_event",
        entity_id=event_id,
        after_data={
            "amount_paise": parsed.amount_paise,
            "direction": parsed.direction,
            "category_id": category,
            "source": source,
        },
        clock=now,
    )
    row = conn.execute("SELECT * FROM rail_events WHERE id = ?", (event_id,)).fetchone()
    return IngestOut(outcome="provisional", event=_out(row, names))


def list_events(conn: sqlite3.Connection, user_id: str, limit: int = 100) -> list[RailEventOut]:
    ensure_schema(conn)
    names = _names(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM rail_events WHERE user_id = ? ORDER BY occurred_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_out(r, names) for r in rows]


# ----------------------------------------------------------------------------- reconcile


def reconcile(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> ReconcileOut:
    """Match provisional payments to statement rows: same amount and direction, close in time."""
    ensure_schema(conn)
    now = now_utc(clock)
    window = timedelta(hours=rails_config()["reconcile"]["window_hours"])
    taken = {
        r[0]
        for r in conn.execute(
            "SELECT matched_txn_id FROM rail_events WHERE matched_txn_id IS NOT NULL"
        )
    }
    matches: list[dict[str, str]] = []
    pending = conn.execute(
        "SELECT * FROM rail_events WHERE user_id = ? AND status = 'provisional'"
        " ORDER BY occurred_at",
        (user_id,),
    ).fetchall()
    for ev in pending:
        sign = ev["amount_paise"] if ev["direction"] == "debit" else -ev["amount_paise"]
        when = from_utc_iso(ev["occurred_at"])
        low, high = to_utc_iso(when - window), to_utc_iso(when + window)
        candidates = conn.execute(
            "SELECT id, occurred_at, merchant_raw FROM transactions WHERE user_id = ?"
            " AND amount_paise = ? AND occurred_at BETWEEN ? AND ?",
            (user_id, sign, low, high),
        ).fetchall()
        candidates = [c for c in candidates if c["id"] not in taken]
        if not candidates:
            continue
        ref = ev["reference"]

        def closeness(c: sqlite3.Row) -> tuple[int, float]:
            by_ref = 0 if ref and ref in c["merchant_raw"] else 1
            return by_ref, abs((from_utc_iso(c["occurred_at"]) - when).total_seconds())

        best = min(candidates, key=closeness)
        taken.add(best["id"])
        conn.execute(
            "UPDATE rail_events SET status = 'verified', matched_txn_id = ? WHERE id = ?",
            (best["id"], ev["id"]),
        )
        conn.execute(
            "UPDATE rail_splits SET txn_id = ?, event_id = NULL WHERE event_id = ?",
            (best["id"], ev["id"]),
        )
        record_event(
            conn,
            user_id,
            "system",
            "rail_event_verified",
            "Statement row confirmed the alert; the two are now one payment.",
            entity_type="rail_event",
            entity_id=ev["id"],
            before_data={"status": "provisional"},
            after_data={"status": "verified", "matched_txn_id": best["id"]},
            clock=now,
        )
        matches.append({"event_id": ev["id"], "txn_id": best["id"], "merchant": ev["merchant"]})
    left = conn.execute(
        "SELECT COUNT(*) FROM rail_events WHERE user_id = ? AND status = 'provisional'", (user_id,)
    ).fetchone()[0]
    return ReconcileOut(verified=len(matches), still_provisional=left, matches=matches)


# ----------------------------------------------------------------------------- receipts


def _find_payment(
    conn: sqlite3.Connection, user_id: str, receipt: Receipt, clock: datetime | None
) -> tuple[str, str, int, str, str | None] | None:
    """(kind, id, amount, merchant, category) of a payment equal to the receipt total."""
    total = receipt.total_paise or 0
    now = now_utc(clock)
    low = to_utc_iso(now - timedelta(days=rails_config()["reconcile"]["split_window_days"]))
    high = to_utc_iso(now + timedelta(days=1))
    words = {w for w in (receipt.merchant or "").lower().replace(".", " ").split() if len(w) > 3}

    def related(merchant: str) -> bool:
        low_m = merchant.lower()
        return not words or any(w in low_m for w in words)

    for ev in conn.execute(
        "SELECT * FROM rail_events WHERE user_id = ? AND direction = 'debit' AND amount_paise = ?"
        " AND occurred_at BETWEEN ? AND ? ORDER BY occurred_at DESC",
        (user_id, total, low, high),
    ):
        if related(ev["merchant"]):
            kind = "txn" if ev["matched_txn_id"] else "event"
            ident = ev["matched_txn_id"] or ev["id"]
            return kind, ident, total, ev["merchant"], ev["category_id"]
    for tx in conn.execute(
        "SELECT id, merchant_raw, category_id FROM transactions WHERE user_id = ?"
        " AND direction = 'debit' AND amount_paise = ? AND occurred_at BETWEEN ? AND ?"
        " ORDER BY occurred_at DESC",
        (user_id, total, low, high),
    ):
        if related(tx["merchant_raw"]):
            return "txn", tx["id"], total, tx["merchant_raw"], tx["category_id"]
    return None


def ingest_receipt(
    conn: sqlite3.Connection, user_id: str, text: str, clock: datetime | None = None
) -> ReceiptOut:
    """Read a receipt, find the payment it belongs to, and draft the category split."""
    ensure_schema(conn)
    now = now_utc(clock)
    names = _names(conn, user_id)
    try:
        receipt = parse_receipt(text)
    except NotAReceipt as exc:
        return ReceiptOut(outcome="refused", reason=str(exc))
    if (
        receipt.total_paise is None
        or receipt.problems
        and "do not add up" in " ".join(receipt.problems)
    ):
        return ReceiptOut(
            outcome="refused",
            reason="Receipt lines do not add up to its total.",
            merchant=receipt.merchant,
            problems=receipt.problems,
        )
    payment = _find_payment(conn, user_id, receipt, clock)
    if payment is None:
        return ReceiptOut(
            outcome="unmatched",
            reason="No payment of that amount from that merchant yet. Send it again after the alert.",
            merchant=receipt.merchant,
            problems=receipt.problems,
        )
    kind, ident, amount, merchant, cat = payment
    try:
        parts = split_by_category(receipt, amount, cat or "shopping")
    except ValueError as exc:
        return ReceiptOut(outcome="refused", reason=str(exc), merchant=receipt.merchant)
    # A newer receipt for the same payment replaces the older, still-undecided draft.
    column = "txn_id" if kind == "txn" else "event_id"
    conn.execute(
        f"DELETE FROM rail_splits WHERE user_id = ? AND {column} = ? AND status = 'suggested'",
        (user_id, ident),
    )
    receipt_id = f"rcpt_{uuid.uuid4().hex[:10]}"
    out_parts: list[SplitPart] = []
    for category, paise in parts:
        sid = f"split_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO rail_splits (id, user_id, receipt_id, merchant, event_id, txn_id,"
            " category_id, amount_paise, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?)",
            (
                sid,
                user_id,
                receipt_id,
                receipt.merchant,
                ident if kind == "event" else None,
                ident if kind == "txn" else None,
                category,
                paise,
                to_utc_iso(now),
            ),
        )
        out_parts.append(
            SplitPart(
                id=sid,
                category_id=category,
                category_name=names.get(category),
                amount=format_inr(paise),
                amount_paise=paise,
                status="suggested",
            )
        )
    record_event(
        conn,
        user_id,
        "system",
        "rail_split_suggested",
        "Receipt read; a category split is drafted and waits for the user.",
        entity_type="receipt",
        entity_id=receipt_id,
        after_data={"payment": ident, "parts": [{"category_id": c, "paise": p} for c, p in parts]},
        clock=now,
    )
    ev = conn.execute(
        "SELECT * FROM rail_events WHERE id = ? OR matched_txn_id = ? LIMIT 1", (ident, ident)
    ).fetchone()
    return ReceiptOut(
        outcome="suggested",
        receipt_id=receipt_id,
        merchant=receipt.merchant,
        payment=_out(ev, names) if ev else None,
        parts=out_parts,
        problems=receipt.problems,
    )


def decide_split(
    conn: sqlite3.Connection,
    user_id: str,
    receipt_id: str,
    decision: str,
    clock: datetime | None = None,
) -> int:
    """User approves or rejects a drafted split (all parts together). Returns parts changed."""
    ensure_schema(conn)
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    cur = conn.execute(
        "UPDATE rail_splits SET status = ? WHERE user_id = ? AND receipt_id = ?"
        " AND status = 'suggested'",
        (decision, user_id, receipt_id),
    )
    if cur.rowcount:
        record_event(
            conn,
            user_id,
            "user",
            f"rail_split_{decision}",
            "User decided on a drafted receipt split.",
            entity_type="receipt",
            entity_id=receipt_id,
            before_data={"status": "suggested"},
            after_data={"status": decision},
            clock=now_utc(clock),
        )
    return cur.rowcount


def list_splits(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    ensure_schema(conn)
    names = _names(conn, user_id)
    out = []
    for r in conn.execute(
        "SELECT * FROM rail_splits WHERE user_id = ? ORDER BY created_at DESC, id", (user_id,)
    ):
        out.append(
            {
                "id": r["id"],
                "receipt_id": r["receipt_id"],
                "merchant": r["merchant"],
                "category_id": r["category_id"],
                "category_name": names.get(r["category_id"]),
                "amount": format_inr(r["amount_paise"]),
                "amount_paise": r["amount_paise"],
                "status": r["status"],
            }
        )
    return out


# ----------------------------------------------------------------------------- pacing


def pacing(conn: sqlite3.Connection, user_id: str, clock: datetime | None = None) -> PacingOut:
    """
    Month-to-date spend per budget, counting statement rows plus provisional alerts.

    Verified alerts are not counted (the statement row already is). Approved receipt splits
    move part of a payment to another category. The projection is straight-line: spend so far
    divided by days elapsed, times days in the month.
    """
    ensure_schema(conn)
    now = now_utc(clock)
    ist = now.astimezone(IST)
    start, end = month_bounds(ist.year, ist.month)
    days = monthrange(ist.year, ist.month)[1]
    elapsed = max(1, ist.day)
    names = _names(conn, user_id)
    settled: dict[str, int] = {}
    provisional: dict[str, int] = {}
    for r in conn.execute(
        "SELECT category_id, SUM(amount_paise) s FROM transactions WHERE user_id = ?"
        " AND direction = 'debit' AND occurred_at >= ? AND occurred_at < ? GROUP BY category_id",
        (user_id, start, end),
    ):
        settled[r["category_id"] or ""] = r["s"]
    prov_count = 0
    prov_rows = conn.execute(
        "SELECT id, category_id, amount_paise FROM rail_events WHERE user_id = ?"
        " AND status = 'provisional' AND direction = 'debit' AND occurred_at >= ? AND occurred_at < ?",
        (user_id, start, end),
    ).fetchall()
    for r in prov_rows:
        provisional[r["category_id"] or ""] = (
            provisional.get(r["category_id"] or "", 0) + r["amount_paise"]
        )
        prov_count += 1
    # approved splits: take the payment out of its own category and add its parts
    groups: dict[str, list[sqlite3.Row]] = {}
    for s in conn.execute(
        "SELECT * FROM rail_splits WHERE user_id = ? AND status = 'approved'", (user_id,)
    ):
        groups.setdefault(s["receipt_id"], []).append(s)
    for parts in groups.values():
        first = parts[0]
        if first["txn_id"]:
            src = conn.execute(
                "SELECT category_id, amount_paise, occurred_at FROM transactions WHERE id = ?",
                (first["txn_id"],),
            ).fetchone()
            bucket = settled
        else:
            src = conn.execute(
                "SELECT category_id, amount_paise, occurred_at FROM rail_events WHERE id = ?",
                (first["event_id"],),
            ).fetchone()
            bucket = provisional
        if not src or not (start <= src["occurred_at"] < end):
            continue
        bucket[src["category_id"] or ""] = (
            bucket.get(src["category_id"] or "", 0) - src["amount_paise"]
        )
        for p in parts:
            bucket[p["category_id"]] = bucket.get(p["category_id"], 0) + p["amount_paise"]
    rows: list[PaceRow] = []
    watch_names: list[str] = []
    for b in conn.execute(
        "SELECT category_id, limit_paise, warn_threshold_pct FROM budgets WHERE user_id = ?"
        " ORDER BY category_id",
        (user_id,),
    ):
        cid, limit = b["category_id"], b["limit_paise"]
        s, p = settled.get(cid, 0), provisional.get(cid, 0)
        total = s + p
        projected = total * days // elapsed // 100 * 100  # whole rupees
        pct = total * 100 // limit if limit else 0
        proj_pct = projected * 100 // limit if limit else 0
        if total > limit:
            status, msg = "over", f"Over the limit by {format_inr(total - limit)}."
        elif proj_pct > 100:
            status = "projected_over"
            msg = f"On pace for {format_inr(projected)}, {format_inr(projected - limit)} over."
        elif pct >= b["warn_threshold_pct"]:
            status, msg = "watch", "Close to the limit; slow down for the rest of the month."
        else:
            status, msg = "ok", "On track."
        if status != "ok":
            watch_names.append(names.get(cid, cid))
        rows.append(
            PaceRow(
                category_id=cid,
                category_name=names.get(cid, cid),
                limit=format_inr(limit),
                limit_paise=limit,
                percent_settled=max(0, s) * 100 // limit if limit else 0,
                percent_provisional=max(0, p) * 100 // limit if limit else 0,
                settled=format_inr(s),
                provisional=format_inr(p),
                total=format_inr(total),
                percent_used=pct,
                projected=format_inr(projected),
                projected_percent=proj_pct,
                status=status,
                message=msg,
            )
        )
    rows.sort(key=lambda r: -r.projected_percent)
    headline = (
        f"{', '.join(watch_names)}: needs attention." if watch_names else "All budgets on track."
    )
    return PacingOut(
        period=f"{ist.year:04d}-{ist.month:02d}",
        day=elapsed,
        days_in_month=days,
        rows=rows,
        provisional_count=prov_count,
        headline=headline,
    )
