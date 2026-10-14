"""
Read models: exactly what each screen needs, with every derived number computed here.

The frontend never computes financial values (PLAN_UI 0.2). It receives integer paise,
API-rounded percents and display-ready statuses from these functions. Reads do not go through
the executor (they change nothing); all writes do (see routes.py).
"""

import calendar
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from copilot.core.forecast import Series, forecast_month
from copilot.core.timeutil import IST, from_utc_iso, month_bounds, now_utc, to_utc_iso
from copilot.db.repo import (
    get_transaction,
    list_accounts,
    list_alerts,
    list_budgets,
    list_categories,
    list_transactions,
)
from copilot.models.domain import Transaction
from copilot.tools.financial import (
    budget_status,
    days_elapsed_in_month,
    net_spend_by_category,
    run_rate_forecast,
)

FORECAST_MIN_DAYS = 3  # matches copilot.core.forecast.forecast_month's insufficient_data rule
UPCOMING_DAYS = 14
UNDOABLE_EVENTS = ("transaction_recategorized", "override_applied")

# ---------------------------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------------------------


class Period(BaseModel):
    """A calendar month in IST."""

    key: str
    year: int
    month: int
    days_in_month: int
    days_elapsed: int
    is_current: bool


def current_period(clock: datetime | None, period: str | None = None) -> Period:
    """The requested period (YYYY-MM), defaulting to the clock's IST month."""
    now = now_utc(clock).astimezone(IST)
    if period:
        year, month = (int(p) for p in period.split("-"))
    else:
        year, month = now.year, now.month
    dim = calendar.monthrange(year, month)[1]
    return Period(
        key=f"{year:04d}-{month:02d}",
        year=year,
        month=month,
        days_in_month=dim,
        days_elapsed=days_elapsed_in_month(year, month, now_utc(clock)),
        is_current=(now.year, now.month) == (year, month),
    )


def ist_day(utc_iso: str) -> int:
    """Day of month in IST for a stored UTC timestamp."""
    return from_utc_iso(utc_iso).astimezone(IST).day


def category_names(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    """Category id -> display name."""
    return {c.id: c.name for c in list_categories(conn, user_id)}


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half up (non-negative inputs)."""
    return (2 * numerator + denominator) // (2 * denominator)


# ---------------------------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------------------------


class PacePoint(BaseModel):
    """Cumulative paise at the end of an IST day of the month."""

    day: int
    paise: int


class ForecastBand(BaseModel):
    """Run-rate forecast of budgeted spend with a low/high range."""

    status: Literal["ok", "insufficient_data"]
    projected_paise: int | None
    low: list[PacePoint]
    high: list[PacePoint]
    basis: str
    has_days: int
    needs_days: int


class BudgetPace(BaseModel):
    """The budget pace card: hero figure, lines and callout."""

    total_limit_paise: int
    spent_paise: int
    left_to_spend_paise: int
    ideal_today_paise: int
    pace_delta_paise: int
    pace: Literal["under", "on", "over"]
    over_budget: bool
    actual: list[PacePoint]
    ideal: list[PacePoint]
    forecast: ForecastBand


class CategoryRow(BaseModel):
    """One category with spend and (if budgeted) its limit and status."""

    category_id: str | None
    name: str | None
    spent_paise: int
    limit_paise: int | None
    pct_used: int | None
    status: Literal["ok", "warning", "exceeded", "projected_exceed", "none"]


class ReviewPreviewItem(BaseModel):
    """A transaction waiting in the review queue."""

    id: str
    merchant: str
    occurred_at: str
    amount_paise: int


class UpcomingItem(BaseModel):
    """An expected recurring payment."""

    merchant: str
    expected_on: str
    amount_paise: int
    cadence_days: int | None
    kind: str


class AlertItem(BaseModel):
    """An open alert with its one-line reason."""

    id: str
    kind: str
    severity: Literal["info", "notice", "warning", "critical"]
    why_text: str
    status: str
    created_at: str


class Headline(BaseModel):
    """Number-free headline built from the pace finding; `emphasis` is italicised."""

    before: str
    emphasis: str
    after: str


class Dashboard(BaseModel):
    """Everything on the dashboard."""

    as_of: str
    period: Period
    data_source: Literal["synthetic_demo", "connected"]
    has_transactions: bool
    headline: Headline | None
    budget_pace: BudgetPace | None
    review_count: int
    review_preview: list[ReviewPreviewItem]
    upcoming: list[UpcomingItem]
    top_categories: list[CategoryRow]
    alerts: list[AlertItem]


def _cumulative_by_day(txs: list[Transaction], categories: set[str], days: int) -> list[PacePoint]:
    """Cumulative net spend in `categories`, floored at 0 per category (matches budgets)."""
    per_cat_day: dict[str, list[int]] = {c: [0] * (days + 1) for c in categories}
    for tx in txs:
        if tx.category_id in per_cat_day:
            day = ist_day(tx.occurred_at)
            if 1 <= day <= days:
                per_cat_day[tx.category_id][day] += tx.amount_paise
    running = {c: 0 for c in categories}
    points = []
    for day in range(1, days + 1):
        total = 0
        for c in categories:
            running[c] += per_cat_day[c][day]
            total += max(0, running[c])
        points.append(PacePoint(day=day, paise=total))
    return points


def _recurring_rows(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM recurring_series WHERE user_id = ? ORDER BY next_expected", (user_id,)
    ).fetchall()


def build_budget_pace(
    conn: sqlite3.Connection, user_id: str, period: Period, txs: list[Transaction]
) -> BudgetPace | None:
    """Pace of spend in budgeted categories against the sum of their limits."""
    budgets = list_budgets(conn, user_id)
    if not budgets:
        return None
    categories = {b.category_id for b in budgets}
    total_limit = sum(b.limit_paise for b in budgets)
    dim = period.days_in_month
    elapsed = period.days_elapsed
    actual = _cumulative_by_day(txs, categories, max(elapsed, 0))
    spent = actual[-1].paise if actual else 0
    ideal = [
        PacePoint(day=d, paise=round_half_up_div(total_limit * d, dim)) for d in range(1, dim + 1)
    ]
    ideal_today = ideal[elapsed - 1].paise if elapsed >= 1 else 0
    delta = ideal_today - spent
    # "On pace" when within 2% of the budget, so a few rupees do not flip the headline.
    tolerance = total_limit // 50
    pace: Literal["under", "on", "over"] = (
        "on" if abs(delta) <= tolerance else ("under" if delta > 0 else "over")
    )

    budget_txs = [t for t in txs if t.category_id in categories]
    fc = forecast_month(
        budget_txs,
        [
            Series(r["merchant_normalized"], r["typical_amount_paise"])
            for r in _recurring_rows(conn, user_id)
            if r["kind"] != "income"
        ],
        max(elapsed, 0),
        dim,
    )
    if elapsed < FORECAST_MIN_DAYS or fc["insufficient_data"] or not period.is_current:
        band = ForecastBand(
            status="insufficient_data",
            projected_paise=None,
            low=[],
            high=[],
            basis="",
            has_days=max(elapsed, 0),
            needs_days=FORECAST_MIN_DAYS,
        )
    else:
        low_end, high_end = fc["projected_range"]
        band = ForecastBand(
            status="ok",
            projected_paise=fc["projected_total"],
            low=[
                PacePoint(day=elapsed, paise=spent),
                PacePoint(day=dim, paise=max(spent, low_end)),
            ],
            high=[
                PacePoint(day=elapsed, paise=spent),
                PacePoint(day=dim, paise=max(spent, high_end)),
            ],
            basis="Fixed payments still due, plus variable spend at its current daily rate, ±20%.",
            has_days=elapsed,
            needs_days=FORECAST_MIN_DAYS,
        )
    return BudgetPace(
        total_limit_paise=total_limit,
        spent_paise=spent,
        left_to_spend_paise=total_limit - spent,
        ideal_today_paise=ideal_today,
        pace_delta_paise=delta,
        pace=pace,
        over_budget=spent > total_limit,
        actual=actual,
        ideal=ideal,
        forecast=band,
    )


def _headline(period: Period, pace: BudgetPace | None) -> Headline | None:
    month = calendar.month_name[period.month]
    if pace is None:
        return None
    if pace.over_budget:
        return Headline(before=f"{month} is ", emphasis="over", after=" budget")
    word = {"under": "under", "on": "on", "over": "over"}[pace.pace]
    verb = "is running " if period.is_current else "finished "
    return Headline(before=f"{month} {verb}", emphasis=word, after=" pace")


def build_category_rows(
    conn: sqlite3.Connection, user_id: str, period: Period, txs: list[Transaction], limit: int
) -> list[CategoryRow]:
    """Categories by net spend, largest first, with budget status where one exists."""
    names = category_names(conn, user_id)
    budgets = {b.category_id: b for b in list_budgets(conn, user_id)}
    spend = net_spend_by_category(txs)
    rows = []
    for cat, spent in sorted(spend.items(), key=lambda kv: (-kv[1], kv[0] or "")):
        budget = budgets.get(cat) if cat else None
        if budget:
            projected = run_rate_forecast(spent, max(period.days_elapsed, 0), period.days_in_month)
            pct, status = budget_status(
                spent,
                budget.limit_paise,
                budget.warn_threshold_pct,
                projected,
                budget.forecast_warn,
            )
            rows.append(
                CategoryRow(
                    category_id=cat,
                    name=names.get(cat),
                    spent_paise=spent,
                    limit_paise=budget.limit_paise,
                    pct_used=pct,
                    status=status,
                )
            )
        else:
            rows.append(
                CategoryRow(
                    category_id=cat,
                    name=names.get(cat) if cat else None,
                    spent_paise=spent,
                    limit_paise=None,
                    pct_used=None,
                    status="none",
                )
            )
    return rows[:limit]


def review_queue_rows(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    """Transactions waiting for the user, newest first."""
    return conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND needs_review = 1 "
        "ORDER BY occurred_at DESC, id",
        (user_id,),
    ).fetchall()


def display_merchant(row: sqlite3.Row | Transaction) -> str:
    """Normalised merchant when known, else the raw narration."""
    norm = row["merchant_normalized"] if isinstance(row, sqlite3.Row) else row.merchant_normalized
    raw = row["merchant_raw"] if isinstance(row, sqlite3.Row) else row.merchant_raw
    return (norm or raw).strip()


def build_dashboard(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None,
    data_source: Literal["synthetic_demo", "connected"],
    period_key: str | None = None,
) -> Dashboard:
    """The dashboard read model."""
    period = current_period(clock, period_key)
    as_of = to_utc_iso(now_utc(clock))
    start, end = month_bounds(period.year, period.month)
    end = min(end, as_of) if period.is_current else end
    txs = list_transactions(conn, user_id, start, end)
    has_any = (
        conn.execute("SELECT 1 FROM transactions WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
        is not None
    )

    pace = build_budget_pace(conn, user_id, period, txs) if has_any else None
    queue = review_queue_rows(conn, user_id)
    today = now_utc(clock).astimezone(IST).date()
    horizon = today + timedelta(days=UPCOMING_DAYS)
    upcoming = []
    for r in _recurring_rows(conn, user_id):
        if r["kind"] == "income" or not r["next_expected"]:
            continue
        expected = (
            from_utc_iso(r["next_expected"]).astimezone(IST).date()
            if "T" in r["next_expected"]
            else datetime.fromisoformat(r["next_expected"]).date()
        )
        if today <= expected <= horizon:
            upcoming.append(
                UpcomingItem(
                    merchant=r["merchant_normalized"],
                    expected_on=expected.isoformat(),
                    amount_paise=r["typical_amount_paise"],
                    cadence_days=r["cadence_days"],
                    kind=r["kind"],
                )
            )
    alerts = [
        AlertItem(
            id=a.id,
            kind=a.kind,
            severity=a.severity,
            why_text=a.why_text,
            status=a.status,
            created_at=a.created_at,
        )
        for a in list_alerts(conn, user_id, status="open")[:5]
    ]
    return Dashboard(
        as_of=as_of,
        period=period,
        data_source=data_source,
        has_transactions=has_any,
        headline=_headline(period, pace),
        budget_pace=pace,
        review_count=len(queue),
        review_preview=[
            ReviewPreviewItem(
                id=r["id"],
                merchant=display_merchant(r),
                occurred_at=r["occurred_at"],
                amount_paise=r["amount_paise"],
            )
            for r in queue[:4]
        ],
        upcoming=upcoming[:6],
        top_categories=build_category_rows(conn, user_id, period, txs, 6),
        alerts=alerts,
    )


# ---------------------------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------------------------


class TransactionRow(BaseModel):
    """A transaction as listed."""

    id: str
    occurred_at: str
    merchant: str
    merchant_raw: str
    account_id: str
    account_name: str
    amount_paise: int
    direction: Literal["debit", "credit"]
    category_id: str | None
    category_name: str | None
    category_source: str
    category_confidence: float | None
    needs_review: bool
    is_duplicate: bool
    is_transfer: bool


class TransactionPage(BaseModel):
    """A page of transactions, newest first."""

    items: list[TransactionRow]
    total: int
    offset: int
    limit: int


def _transfer_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT debit_txn_id, credit_txn_id FROM transfer_links WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {r[0] for r in rows} | {r[1] for r in rows}


def to_row(
    tx: sqlite3.Row,
    names: dict[str, str],
    accounts: dict[str, str],
    transfers: set[str],
) -> TransactionRow:
    """Map a DB row to the list shape."""
    return TransactionRow(
        id=tx["id"],
        occurred_at=tx["occurred_at"],
        merchant=display_merchant(tx),
        merchant_raw=tx["merchant_raw"],
        account_id=tx["account_id"],
        account_name=accounts.get(tx["account_id"], tx["account_id"]),
        amount_paise=tx["amount_paise"],
        direction=tx["direction"],
        category_id=tx["category_id"],
        category_name=names.get(tx["category_id"]) if tx["category_id"] else None,
        category_source=tx["category_source"],
        category_confidence=tx["category_confidence"],
        needs_review=bool(tx["needs_review"]),
        is_duplicate=tx["is_duplicate_of"] is not None,
        is_transfer=tx["id"] in transfers,
    )


def list_transaction_page(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    period: str | None,
    category_id: str | None,
    uncategorised: bool,
    needs_review: bool | None,
    source: str | None,
    q: str | None,
    offset: int,
    limit: int,
) -> TransactionPage:
    """Filtered, paginated transactions. All filters are parameterised SQL."""
    where = ["user_id = ?"]
    params: list[str | int] = [user_id]
    if period:
        year, month = (int(p) for p in period.split("-"))
        start, end = month_bounds(year, month)
        where += ["occurred_at >= ?", "occurred_at < ?"]
        params += [start, end]
    if uncategorised:
        where.append("category_id IS NULL")
    elif category_id:
        where.append("category_id = ?")
        params.append(category_id)
    if needs_review is not None:
        where.append("needs_review = ?")
        params.append(1 if needs_review else 0)
    if source:
        where.append("category_source = ?")
        params.append(source)
    if q:
        where.append(
            "(LOWER(merchant_raw) LIKE ? OR LOWER(COALESCE(merchant_normalized, '')) LIKE ? "
            "OR LOWER(description) LIKE ?)"
        )
        like = f"%{q.lower()}%"
        params += [like, like, like]
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {clause}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM transactions WHERE {clause} ORDER BY occurred_at DESC, id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    names = category_names(conn, user_id)
    accounts = {a.id: a.name for a in list_accounts(conn, user_id)}
    transfers = _transfer_ids(conn, user_id)
    return TransactionPage(
        items=[to_row(r, names, accounts, transfers) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


class HistoryEntry(BaseModel):
    """One audited change to a transaction."""

    audit_event_id: str
    occurred_at: str
    actor: str
    event_type: str
    summary: str
    before_category_id: str | None
    after_category_id: str | None
    undoable: bool


class TransactionDetail(BaseModel):
    """Everything the detail panel shows."""

    transaction: TransactionRow
    description: str
    recurring: UpcomingItem | None
    duplicate_of: str | None
    history: list[HistoryEntry]


def _undone_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT json_extract(metadata_json, '$.undone_event_id') FROM audit_events "
        "WHERE user_id = ? AND event_type = 'undo'",
        (user_id,),
    ).fetchall()
    return {r[0] for r in rows if r[0]}


def build_transaction_detail(
    conn: sqlite3.Connection, user_id: str, tx_id: str
) -> TransactionDetail | None:
    """Detail with audited history, newest first."""
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
    ).fetchone()
    if row is None:
        return None
    names = category_names(conn, user_id)
    accounts = {a.id: a.name for a in list_accounts(conn, user_id)}
    undone = _undone_ids(conn, user_id)
    events = conn.execute(
        "SELECT * FROM audit_events WHERE user_id = ? AND entity_id = ? "
        "AND event_type IN ('transaction_recategorized', 'override_applied', 'undo') "
        "ORDER BY occurred_at DESC, rowid DESC",
        (user_id, tx_id),
    ).fetchall()
    history = []
    for e in events:
        before = json.loads(e["before_json"]) if e["before_json"] else {}
        after = json.loads(e["after_json"]) if e["after_json"] else {}
        b_cat = (before or {}).get("category_id") if isinstance(before, dict) else None
        a_cat = (after or {}).get("category_id") if isinstance(after, dict) else None
        history.append(
            HistoryEntry(
                audit_event_id=e["id"],
                occurred_at=e["occurred_at"],
                actor=e["actor"],
                event_type=e["event_type"],
                summary=e["reason"],
                before_category_id=b_cat,
                after_category_id=a_cat,
                undoable=e["event_type"] in UNDOABLE_EVENTS and e["id"] not in undone,
            )
        )
    recurring = None
    if row["merchant_normalized"]:
        r = conn.execute(
            "SELECT * FROM recurring_series WHERE user_id = ? AND merchant_normalized = ?",
            (user_id, row["merchant_normalized"]),
        ).fetchone()
        if r:
            recurring = UpcomingItem(
                merchant=r["merchant_normalized"],
                expected_on=(r["next_expected"] or "")[:10],
                amount_paise=r["typical_amount_paise"],
                cadence_days=r["cadence_days"],
                kind=r["kind"],
            )
    return TransactionDetail(
        transaction=to_row(row, names, accounts, _transfer_ids(conn, user_id)),
        description=row["description"],
        recurring=recurring,
        duplicate_of=row["is_duplicate_of"],
        history=history,
    )


# ---------------------------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------------------------


class SimilarItem(BaseModel):
    """A past transaction from the same merchant and how it was categorised."""

    id: str
    occurred_at: str
    amount_paise: int
    category_id: str | None
    category_name: str | None


class Suggestion(BaseModel):
    """A category the user can pick with one key."""

    category_id: str
    name: str
    reason: Literal["ai_suggestion", "past_choice", "frequent"]


class ReviewItem(BaseModel):
    """One uncertain transaction with the context needed to decide."""

    transaction: TransactionRow
    why: str
    similar: list[SimilarItem]
    suggestions: list[Suggestion]


class ReviewQueue(BaseModel):
    """The whole queue."""

    total: int
    items: list[ReviewItem]


def _suggestions(
    candidates: list[tuple[str | None, Literal["ai_suggestion", "past_choice", "frequent"]]],
    names: dict[str, str],
) -> list[Suggestion]:
    """First five distinct known categories, in priority order."""
    out: list[Suggestion] = []
    seen: set[str] = set()
    for cat, reason in candidates:
        if cat and cat in names and cat not in seen and len(out) < 5:
            seen.add(cat)
            out.append(Suggestion(category_id=cat, name=names[cat], reason=reason))
    return out


def _why(tx: sqlite3.Row) -> str:
    source = tx["category_source"]
    conf = tx["category_confidence"]
    if source == "llm" and conf is not None:
        return f"AI suggestion with confidence {conf:.2f}, below the auto-accept threshold."
    if source == "none":
        return "No rule matched this merchant and no AI suggestion was available."
    return "Flagged for review by the categoriser."


def build_review_queue(conn: sqlite3.Connection, user_id: str, limit: int = 50) -> ReviewQueue:
    """Review queue with similar past items and suggested categories."""
    names = category_names(conn, user_id)
    accounts = {a.id: a.name for a in list_accounts(conn, user_id)}
    transfers = _transfer_ids(conn, user_id)
    frequent = [
        r[0]
        for r in conn.execute(
            "SELECT category_id FROM transactions WHERE user_id = ? AND category_id IS NOT NULL "
            "GROUP BY category_id ORDER BY COUNT(*) DESC LIMIT 6",
            (user_id,),
        ).fetchall()
    ]
    rows = review_queue_rows(conn, user_id)
    items = []
    for tx in rows[:limit]:
        similar_rows = (
            conn.execute(
                "SELECT id, occurred_at, amount_paise, category_id FROM transactions "
                "WHERE user_id = ? AND merchant_normalized = ? AND id != ? "
                "AND category_id IS NOT NULL ORDER BY occurred_at DESC LIMIT 3",
                (user_id, tx["merchant_normalized"], tx["id"]),
            ).fetchall()
            if tx["merchant_normalized"]
            else []
        )
        candidates: list[
            tuple[str | None, Literal["ai_suggestion", "past_choice", "frequent"]]
        ] = []
        if tx["category_source"] == "llm":
            candidates.append((tx["category_id"], "ai_suggestion"))
        candidates += [(s["category_id"], "past_choice") for s in similar_rows]
        candidates += [
            (cat, "frequent")
            for cat in frequent
            if not (cat == "income" and tx["direction"] == "debit")  # a payment is not income
        ]
        suggestions = _suggestions(candidates, names)
        items.append(
            ReviewItem(
                transaction=to_row(tx, names, accounts, transfers),
                why=_why(tx),
                similar=[
                    SimilarItem(
                        id=s["id"],
                        occurred_at=s["occurred_at"],
                        amount_paise=s["amount_paise"],
                        category_id=s["category_id"],
                        category_name=names.get(s["category_id"]),
                    )
                    for s in similar_rows
                ],
                suggestions=suggestions,
            )
        )
    return ReviewQueue(total=len(rows), items=items)


# ---------------------------------------------------------------------------------------------
# Consents and imports
# ---------------------------------------------------------------------------------------------


class ConsentView(BaseModel):
    """A consent as the user sees it (expiry applied at read time)."""

    id: str
    purpose: str
    account_ids: list[str]
    account_names: list[str]
    range_from: str
    range_to: str
    status: Literal["pending", "active", "expired", "revoked"]
    expires_at: str | None
    created_at: str


class ImportBatchView(BaseModel):
    """One ingestion batch."""

    id: str
    consent_id: str | None
    status: str
    fetched: int
    inserted: int
    duplicates: int
    error_code: str | None
    started_at: str | None
    finished_at: str | None


def list_consent_views(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None
) -> list[ConsentView]:
    """Consents newest first; an active consent past its expiry reads as expired."""
    now = to_utc_iso(now_utc(clock))
    accounts = {a.id: a.name for a in list_accounts(conn, user_id)}
    views = []
    for r in conn.execute(
        "SELECT * FROM consents WHERE user_id = ? ORDER BY created_at DESC, id", (user_id,)
    ).fetchall():
        ids = json.loads(r["account_ids"]) if r["account_ids"] else []
        status = r["status"]
        if status == "active" and r["expires_at"] and r["expires_at"] <= now:
            status = "expired"
        views.append(
            ConsentView(
                id=r["id"],
                purpose=r["purpose"],
                account_ids=ids,
                account_names=[accounts.get(i, i) for i in ids],
                range_from=r["date_range_from"],
                range_to=r["date_range_to"],
                status=status,
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
        )
    return views


def list_import_batches(conn: sqlite3.Connection, user_id: str) -> list[ImportBatchView]:
    """Ingestion batches, newest first."""
    return [
        ImportBatchView(
            id=r["id"],
            consent_id=r["consent_id"],
            status=r["status"],
            fetched=r["fetched_count"] or 0,
            inserted=r["inserted_count"] or 0,
            duplicates=r["duplicate_count"] or 0,
            error_code=r["error_code"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
        )
        for r in conn.execute(
            "SELECT * FROM ingestion_batches WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,),
        ).fetchall()
    ]


class CategorisationEvent(BaseModel):
    """How one imported transaction was categorised (drives the constellation)."""

    transaction_id: str
    category_id: str | None
    category_name: str | None
    source: str
    needs_review: bool


class ImportResult(BaseModel):
    """Outcome of one import: counts plus per-transaction categorisation events."""

    batch_id: str | None
    fetched: int
    inserted: int
    skipped_existing: int
    duplicates_flagged: int
    by_rule: int
    by_ai: int
    needs_review: int
    other: int
    events: list[CategorisationEvent]


def categorisation_events(
    conn: sqlite3.Connection, user_id: str, batch_id: str | None
) -> list[CategorisationEvent]:
    """Per-transaction results for a batch, in the order the transactions occurred."""
    if batch_id is None:
        return []
    names = category_names(conn, user_id)
    return [
        CategorisationEvent(
            transaction_id=r["id"],
            category_id=r["category_id"],
            category_name=names.get(r["category_id"]) if r["category_id"] else None,
            source=r["category_source"],
            needs_review=bool(r["needs_review"]),
        )
        for r in conn.execute(
            "SELECT id, category_id, category_source, needs_review FROM transactions "
            "WHERE user_id = ? AND batch_id = ? ORDER BY occurred_at, id",
            (user_id, batch_id),
        ).fetchall()
    ]


def tx_exists(conn: sqlite3.Connection, user_id: str, tx_id: str) -> bool:
    """True when the transaction belongs to the user."""
    return get_transaction(conn, user_id, tx_id) is not None
