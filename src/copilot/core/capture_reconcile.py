"""
Reconciliation and coverage health (PLAN_CAPTURE Stage C4, ADR-0001 D8 and D9, ADR-0002).

A captured payment event is matched to a ledger transaction, in this order:
  1. the UTR/RRN found in the ledger narration, with the same amount and direction;
  2. the same amount and direction, on the same account (by its last four digits), within a
     short time window.
A rule only counts when it gives *exactly one* ledger transaction. Anything else is left
unmerged: ambiguity is never resolved by guessing. A matched user label becomes the ledger
transaction's category with `category_source = user`, linked to the event for audit.

Spend views must never count a payment twice. `combined_spend` therefore counts an unmatched
event as provisional spend only when the ledger has *no candidate at all* for it.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from copilot.audit.events import Actor, record_event
from copilot.config.capture import ReconcileConfig, load_reconcile_config
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST, from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo import update_transaction_category
from copilot.models.capture import PaymentEvent

_OPEN = ("posted", "orphaned")


# ---------------------------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------------------------
def set_account_last4(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    last4: str,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> None:
    if not (len(last4) == 4 and last4.isdigit()):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Give the last four digits.")
    if not conn.execute(
        "SELECT 1 FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id)
    ).fetchone():
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Account {account_id!r} not found.")
    now = to_utc_iso(now_utc(clock))
    conn.execute(
        "INSERT INTO account_last4_map (id, user_id, account_id, last4, created_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, last4) DO UPDATE SET account_id = excluded.account_id",
        (f"al4_{uuid.uuid4().hex[:10]}", user_id, account_id, last4, now),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="account_last4_set",
        reason=f"Account {account_id} ends {last4}", entity_type="account", entity_id=account_id,
        metadata={"last4": last4}, clock=clock,
    )  # fmt: skip


def _account_for(conn: sqlite3.Connection, user_id: str, last4: str | None) -> str | None:
    """The ledger account an alert belongs to. A user with one account needs no mapping."""
    if last4:
        row = conn.execute(
            "SELECT account_id FROM account_last4_map WHERE user_id = ? AND last4 = ?",
            (user_id, last4),
        ).fetchone()
        if row:
            return row[0]
    if not conn.execute(
        "SELECT 1 FROM account_last4_map WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone():
        only = conn.execute("SELECT id FROM accounts WHERE user_id = ?", (user_id,)).fetchall()
        if len(only) == 1:
            return only[0][0]
    return None


# ---------------------------------------------------------------------------------------------
# Finding candidates
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Candidates:
    by_utr: list[str]
    by_window: list[str]

    @property
    def any(self) -> bool:
        return bool(self.by_utr or self.by_window)

    def unique(self) -> tuple[str, str] | None:
        """(txn id, method) when a rule gives exactly one match, else None."""
        if len(self.by_utr) == 1:
            return self.by_utr[0], "utr"
        if not self.by_utr and len(self.by_window) == 1:
            return self.by_window[0], "amount_account_time"
        return None


def candidates_for(
    conn: sqlite3.Connection, user_id: str, ev: PaymentEvent, cfg: ReconcileConfig
) -> Candidates:
    free = "id NOT IN (SELECT txn_id FROM event_links WHERE user_id = ?)"
    base = (
        f"SELECT id FROM transactions WHERE user_id = ? AND direction = ? AND ABS(amount_paise) = ?"
        f" AND is_duplicate_of IS NULL AND {free}"
    )
    args = [user_id, ev.direction, ev.amount_paise, user_id]
    by_utr: list[str] = []
    if ev.utr and "utr" in cfg.match_order:
        like = f"%{ev.utr}%"
        by_utr = [
            r[0]
            for r in conn.execute(
                base + " AND (merchant_raw LIKE ? OR description LIKE ?) ORDER BY id",
                [*args, like, like],
            )
        ]
    by_window: list[str] = []
    if "amount_account_time" in cfg.match_order:
        account = _account_for(conn, user_id, ev.account_last4)
        if account:
            centre = from_utc_iso(ev.occurred_at)
            lo = to_utc_iso(centre - timedelta(minutes=cfg.time_window_minutes))
            hi = to_utc_iso(centre + timedelta(minutes=cfg.time_window_minutes))
            by_window = [
                r[0]
                for r in conn.execute(
                    base + " AND account_id = ? AND occurred_at BETWEEN ? AND ? ORDER BY id",
                    [*args, account, lo, hi],
                )
            ]
    return Candidates(by_utr, by_window)


# ---------------------------------------------------------------------------------------------
# Reconciling
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReconcileReport:
    matched: int
    ambiguous: int
    orphaned: int
    unchanged: int
    label_conflicts: int


def reconcile_events(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
    cfg: ReconcileConfig | None = None,
) -> ReconcileReport:
    cfg = cfg or load_reconcile_config()
    now = now_utc(clock)
    rows = conn.execute(
        "SELECT * FROM payment_events WHERE user_id = ? AND state IN ('posted', 'orphaned')"
        " AND counterparty_kind != 'self' ORDER BY occurred_at, id",
        (user_id,),
    ).fetchall()
    from copilot.core.capture import _row_to_event  # local: avoids an import cycle

    matched = ambiguous = orphaned = unchanged = conflicts = 0
    for row in rows:
        ev = _row_to_event(row)
        cand = candidates_for(conn, user_id, ev, cfg)
        hit = cand.unique()
        if hit:
            txn_id, method = hit
            conflicts += _link(conn, user_id, ev, txn_id, method, actor, run_id, now)
            matched += 1
        elif cand.any:
            ambiguous += 1  # several candidates: left as they are, never merged by guessing
        elif ev.state == "posted" and now - from_utc_iso(ev.occurred_at) >= timedelta(
            hours=cfg.orphan_after_hours
        ):
            conn.execute(
                "UPDATE payment_events SET state = 'orphaned' WHERE user_id = ? AND id = ?",
                (user_id, ev.id),
            )
            record_event(
                conn, user_id=user_id, actor=actor, event_type="payment_orphaned",
                reason="No ledger match within the window; shown as unverified", run_id=run_id,
                entity_type="payment_event", entity_id=ev.id, clock=now,
            )  # fmt: skip
            orphaned += 1
        else:
            unchanged += 1
    return ReconcileReport(matched, ambiguous, orphaned, unchanged, conflicts)


def _link(
    conn: sqlite3.Connection,
    user_id: str,
    ev: PaymentEvent,
    txn_id: str,
    method: str,
    actor: Actor,
    run_id: str | None,
    now: datetime,
) -> int:
    """Link an event to its transaction and carry a user's label across. Returns 1 on conflict."""
    conn.execute(
        "INSERT INTO event_links (id, user_id, event_id, txn_id, method, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (f"lnk_{uuid.uuid4().hex[:12]}", user_id, ev.id, txn_id, method, to_utc_iso(now)),
    )
    conn.execute(
        "UPDATE payment_events SET state = 'reconciled' WHERE user_id = ? AND id = ?",
        (user_id, ev.id),
    )
    txn = conn.execute(
        "SELECT category_id, category_source, category_confidence, needs_review"
        " FROM transactions WHERE user_id = ? AND id = ?",
        (user_id, txn_id),
    ).fetchone()
    before = {"category_id": txn["category_id"], "category_source": txn["category_source"]}
    carried, conflict = False, 0
    if ev.direction == "debit" and ev.category_source == "user" and ev.category_id:
        if txn["category_source"] == "user" and txn["category_id"] != ev.category_id:
            conflict = 1  # the ledger row already has a different choice of the user's: keep it
        elif txn["category_id"] != ev.category_id or txn["category_source"] != "user":
            update_transaction_category(
                conn, user_id, txn_id, ev.category_id, "user", 1.0, needs_review=False
            )
            carried = True
    record_event(
        conn, user_id=user_id, actor=actor, event_type="payment_reconciled",
        reason=f"Payment matched to ledger transaction by {method}", run_id=run_id,
        entity_type="payment_event", entity_id=ev.id,
        before_data=before,
        after_data=(
            {"category_id": ev.category_id, "category_source": "user"} if carried else before
        ),
        metadata={
            "txn_id": txn_id, "method": method, "label_carried": carried,
            "conflict": bool(conflict),
        },
        clock=now,
    )  # fmt: skip
    return conflict


# ---------------------------------------------------------------------------------------------
# Spend that never double counts
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CombinedSpend:
    ledger_paise: int
    provisional_paise: int
    unverified_events: int

    @property
    def total_paise(self) -> int:
        return self.ledger_paise + self.provisional_paise


def combined_spend(
    conn: sqlite3.Connection,
    user_id: str,
    start: str,
    end: str,
    *,
    include_simulated: bool = False,
    cfg: ReconcileConfig | None = None,
) -> CombinedSpend:
    """
    Spend in [start, end) (UTC ISO). The ledger is the truth. An event that is not yet in it adds
    provisional spend only when the ledger has no candidate for it, so a payment is never
    counted both ways, even when its match is ambiguous.
    """
    cfg = cfg or load_reconcile_config()
    ledger = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE user_id = ?"
        " AND direction = 'debit' AND excluded_from_spend = 0 AND is_duplicate_of IS NULL"
        " AND occurred_at >= ? AND occurred_at < ?",
        (user_id, start, end),
    ).fetchone()[0]
    sim = "" if include_simulated else " AND simulated = 0"
    rows = conn.execute(
        "SELECT * FROM payment_events WHERE user_id = ? AND direction = 'debit'"
        " AND state IN ('posted', 'orphaned') AND counterparty_kind != 'self'"
        f" AND occurred_at >= ? AND occurred_at < ?{sim}",
        (user_id, start, end),
    ).fetchall()
    from copilot.core.capture import _row_to_event

    provisional = count = 0
    for row in rows:
        ev = _row_to_event(row)
        if candidates_for(conn, user_id, ev, cfg).any:
            continue
        provisional += ev.amount_paise
        count += 1
    return CombinedSpend(int(ledger), provisional, count)


# ---------------------------------------------------------------------------------------------
# Coverage health
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CoverageRow:
    account_id: str | None
    ledger_txns: int
    alerts: int
    share_bp: int
    warn: bool
    message: str


def coverage_health(
    conn: sqlite3.Connection,
    user_id: str,
    now: datetime,
    cfg: ReconcileConfig | None = None,
) -> list[CoverageRow]:
    """Did the alerts keep up with the bank? Silent capture gaps become a visible state."""
    cfg = cfg or load_reconcile_config()
    cov = cfg.coverage
    since = to_utc_iso(now - timedelta(days=cov.window_days))
    until = to_utc_iso(now)
    rows = conn.execute(
        "SELECT a.id, a.name, (SELECT COUNT(*) FROM transactions t WHERE t.user_id = a.user_id"
        "   AND t.account_id = a.id AND t.is_duplicate_of IS NULL"
        "   AND t.occurred_at >= ? AND t.occurred_at <= ?) AS ledger"
        " FROM accounts a WHERE a.user_id = ? ORDER BY a.id",
        (since, until, user_id),
    ).fetchall()
    out: list[CoverageRow] = []
    for r in rows:
        alerts = conn.execute(
            "SELECT COUNT(*) FROM event_links l JOIN transactions t ON t.id = l.txn_id"
            " WHERE l.user_id = ? AND t.account_id = ?"
            " AND t.occurred_at >= ? AND t.occurred_at <= ?",
            (user_id, r["id"], since, until),
        ).fetchone()[0]
        ledger = r["ledger"]
        share = alerts * 10000 // ledger if ledger else 10000
        warn = ledger >= cov.min_ledger_txns and share < cov.warn_below_bp
        message = (
            f"Your bank shows {ledger} transactions on {r['name']} in the last {cov.window_days} "
            f"days but only {alerts} alerts reached FinCo. Is the bank SMS going to another phone?"
            if warn
            else f"Alerts are keeping up on {r['name']}."
            if ledger >= cov.min_ledger_txns
            else f"Not enough activity on {r['name']} yet to tell."
        )
        out.append(CoverageRow(r["id"], ledger, alerts, share, warn, message))
    return out


def local_day_bounds(day: str) -> tuple[str, str]:
    """UTC bounds of one IST calendar day, for 'today'."""
    start = datetime.fromisoformat(day).replace(tzinfo=IST)
    return to_utc_iso(start), to_utc_iso(start + timedelta(days=1))
