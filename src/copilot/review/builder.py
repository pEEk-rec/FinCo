"""
Monthly review builder and versioning logic (PLAN_PHASE1 Section 5.8).

Combines deterministic financial aggregations, budget tracking, recurring payments,
anomalies, forecasts, and advice into a versioned MonthlyReview document.
"""

import calendar
import json
import sqlite3
from datetime import UTC, datetime

from copilot.core.anomalies import detect_anomalies
from copilot.core.forecast import Series, forecast_month
from copilot.core.timeutil import IST, month_bounds, to_utc_iso
from copilot.db.repo import insert_monthly_review, list_budgets, list_categories, list_transactions
from copilot.models.domain import MonthlyReview
from copilot.review.models import (
    CategoryTotal,
    DataQualityNotes,
    MonthlyReviewData,
    ReviewAdviceItem,
    ReviewAnomalyItem,
    ReviewBudgetStatus,
    ReviewForecast,
    ReviewRecurringItem,
)
from copilot.tools.financial import (
    budget_status,
    days_elapsed_in_month,
    net_spend_by_category,
    run_rate_forecast,
)


def build_monthly_review(
    conn: sqlite3.Connection,
    user_id: str,
    year: int,
    month: int,
    run_id: str,
    clock: datetime | None = None,
) -> MonthlyReviewData:
    """
    Build and persist a new version of the MonthlyReview for (user_id, year, month).

    Deterministic and idempotent:
    - Queries transactions and derived state for the period.
    - Computes previous-month delta for category expenditures.
    - Increments the version counter (v1 -> v2) if a review already exists.
    - Persists the record to `monthly_reviews`.
    """
    now_dt = clock or datetime.now(tz=UTC)
    now_iso = to_utc_iso(now_dt)
    period = f"{year:04d}-{month:02d}"

    # 1. Date ranges
    start_utc, end_utc = month_bounds(year, month)
    end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    effective_end_utc = to_utc_iso(now_dt) if now_dt < end_dt else end_utc

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_start_utc, prev_end_utc = month_bounds(prev_year, prev_month)
    prev_period = f"{prev_year:04d}-{prev_month:02d}"

    # 2. Current month transactions & spend
    txs = list_transactions(conn, user_id, start_utc, effective_end_utc)
    curr_spend = net_spend_by_category(txs)

    income_paise = sum(
        -tx.amount_paise for tx in txs if tx.direction == "credit" and not tx.excluded_from_spend
    )
    spend_paise = sum(curr_spend.values())
    net_paise = income_paise - spend_paise

    # 3. Previous month comparison
    prev_txs = list_transactions(conn, user_id, prev_start_utc, prev_end_utc)
    prev_spend = net_spend_by_category(prev_txs)
    has_prev = len(prev_txs) > 0

    prev_income_paise = (
        sum(
            -tx.amount_paise
            for tx in prev_txs
            if tx.direction == "credit" and not tx.excluded_from_spend
        )
        if has_prev
        else None
    )
    prev_spend_paise = sum(prev_spend.values()) if has_prev else None
    prev_net_paise = (
        (prev_income_paise - prev_spend_paise)
        if (prev_income_paise is not None and prev_spend_paise is not None)
        else None
    )

    # 4. Categories & Category Totals
    cats = {c.id: c.name for c in list_categories(conn, user_id)}
    all_cat_ids = sorted(
        set(list(curr_spend.keys()) + list(prev_spend.keys())),
        key=lambda cat: (cat is None, cat or ""),
    )

    category_totals: list[CategoryTotal] = []
    for cat_id in all_cat_ids:
        if cat_id is None:
            c_name = "Uncategorised"
            c_id_str = "uncategorised"
        else:
            c_name = cats.get(cat_id, cat_id)
            c_id_str = cat_id

        c_spend = curr_spend.get(cat_id, 0)
        p_spend = prev_spend.get(cat_id, 0) if has_prev else None

        chg_paise = (c_spend - p_spend) if p_spend is not None else None
        chg_pct = (
            round((chg_paise * 100.0 / p_spend), 1)
            if (p_spend is not None and p_spend > 0 and chg_paise is not None)
            else None
        )

        category_totals.append(
            CategoryTotal(
                category_id=c_id_str,
                category_name=c_name,
                current_spend_paise=c_spend,
                previous_spend_paise=p_spend,
                change_paise=chg_paise,
                change_pct=chg_pct,
            )
        )

    # Sort descending by current spend
    category_totals.sort(key=lambda x: x.current_spend_paise, reverse=True)

    # 5. Budget Status
    days_in_month = calendar.monthrange(year, month)[1]
    elapsed = days_elapsed_in_month(year, month, now_dt)

    budget_statuses: list[ReviewBudgetStatus] = []
    for b in list_budgets(conn, user_id):
        b_spent = curr_spend.get(b.category_id, 0)
        proj = run_rate_forecast(b_spent, elapsed, days_in_month)
        pct_used, b_stat = budget_status(
            b_spent, b.limit_paise, b.warn_threshold_pct, proj, b.forecast_warn
        )
        c_name = cats.get(b.category_id, b.category_id)
        budget_statuses.append(
            ReviewBudgetStatus(
                category_id=b.category_id,
                category_name=c_name,
                spent_paise=b_spent,
                limit_paise=b.limit_paise,
                pct_used=pct_used,
                status=b_stat,
            )
        )

    # 6. Recurring payments
    rec_rows = conn.execute(
        """
        SELECT merchant_normalized, typical_amount_paise, cadence_days, confidence
        FROM recurring_series
        WHERE user_id = ?
        ORDER BY typical_amount_paise DESC
        """,
        (user_id,),
    ).fetchall()

    recurring_payments = [
        ReviewRecurringItem(
            merchant=row[0],
            typical_amount_paise=row[1],
            cadence_days=row[2],
            confidence=row[3],
        )
        for row in rec_rows
    ]

    # 7. Anomalies
    anomaly_dicts = detect_anomalies(txs)
    tx_by_id = {t.id: t for t in txs}
    anomalies: list[ReviewAnomalyItem] = []
    for a in anomaly_dicts:
        tx_ids = a.get("transaction_ids", ())
        if not tx_ids:
            continue
        primary_id = tx_ids[0]
        matched_tx = tx_by_id.get(primary_id)
        if matched_tx:
            anomalies.append(
                ReviewAnomalyItem(
                    transaction_id=matched_tx.id,
                    merchant=matched_tx.merchant_normalized or matched_tx.merchant_raw,
                    amount_paise=matched_tx.amount_paise,
                    occurred_at=matched_tx.occurred_at,
                    reason=a.get("details", a.get("kind", "anomaly")),
                )
            )

    # 8. Forecast
    series_objs = [
        Series(merchant_normalized=r.merchant, typical_amount_paise=r.typical_amount_paise)
        for r in recurring_payments
    ]
    f_res = forecast_month(txs, series_objs, elapsed, days_in_month)
    forecast = ReviewForecast(
        spent_so_far_paise=f_res["spent_so_far"],
        projected_total_paise=f_res["projected_total"],
        projected_range_paise=f_res["projected_range"],
        insufficient_data=f_res["insufficient_data"],
    )

    # 9. Advice items
    advice_rows = conn.execute(
        """
        SELECT id, text, status, assumptions_json
        FROM advice_items
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    advice_items: list[ReviewAdviceItem] = []
    for a_row in advice_rows:
        try:
            assumptions = json.loads(a_row[3]) if a_row[3] else []
        except Exception:
            assumptions = []
        advice_items.append(
            ReviewAdviceItem(
                id=a_row[0],
                text=a_row[1],
                status=a_row[2],
                assumptions=assumptions,
            )
        )

    # 10. Data Quality Notes
    review_queue_size = conn.execute(
        """
        SELECT COUNT(*) FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ? AND needs_review = 1
        """,
        (user_id, start_utc, effective_end_utc),
    ).fetchone()[0]

    duplicates_flagged = conn.execute(
        """
        SELECT COUNT(*) FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
          AND is_duplicate_of IS NOT NULL
        """,
        (user_id, start_utc, effective_end_utc),
    ).fetchone()[0]

    # Distinct days recorded in IST
    tx_days = set()
    for tx in txs:
        tx_dt = datetime.fromisoformat(tx.occurred_at.replace("Z", "+00:00")).astimezone(IST)
        tx_days.add(tx_dt.day)

    now_ist = now_dt.astimezone(IST)
    is_partial = (now_ist.year == year and now_ist.month == month and now_ist.day < days_in_month)
    days_recorded = now_ist.day if is_partial else days_in_month
    missing_days = max(0, days_recorded - len(tx_days))

    data_quality = DataQualityNotes(
        review_queue_size=review_queue_size,
        duplicates_flagged=duplicates_flagged,
        missing_days=missing_days,
        days_recorded=len(tx_days),
        days_in_month=days_in_month,
        is_partial_month=is_partial,
    )

    # 11. Versioning & ID
    row_ver = conn.execute(
        """
        SELECT MAX(version) FROM monthly_reviews
        WHERE user_id = ? AND year = ? AND month = ?
        """,
        (user_id, year, month),
    ).fetchone()
    current_max_version = row_ver[0] if (row_ver and row_ver[0] is not None) else 0
    new_version = current_max_version + 1
    review_id = f"mr_{user_id}_{year}_{month:02d}_v{new_version}"

    review_data = MonthlyReviewData(
        id=review_id,
        user_id=user_id,
        period=period,
        year=year,
        month=month,
        version=new_version,
        run_id=run_id,
        generated_at=now_iso,
        income_paise=income_paise,
        spend_paise=spend_paise,
        net_paise=net_paise,
        previous_period=prev_period if has_prev else None,
        previous_income_paise=prev_income_paise,
        previous_spend_paise=prev_spend_paise,
        previous_net_paise=prev_net_paise,
        category_totals=category_totals,
        budget_statuses=budget_statuses,
        recurring_payments=recurring_payments,
        anomalies=anomalies,
        forecast=forecast,
        advice=advice_items,
        data_quality=data_quality,
    )

    # Persist to database
    db_review = MonthlyReview(
        id=review_id,
        user_id=user_id,
        year=year,
        month=month,
        version=new_version,
        run_id=run_id,
        review_json=review_data.model_dump_json(),
        created_at=now_iso,
    )
    insert_monthly_review(conn, db_review)

    return review_data
