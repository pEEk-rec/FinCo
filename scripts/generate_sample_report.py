"""
Generate a sample Monthly Financial Review for September 2026 (PLAN_PHASE1 Stage 1.10).

Creates:
- reports/2026-09.md
- reports/2026-09.html
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.review import (
    build_monthly_review,
    extract_all_review_numbers,
    extract_numbers_from_rendered_text,
    render_html,
    render_markdown,
)


def seed_data(conn: sqlite3.Connection) -> None:
    t0 = "2026-01-01T00:00:00Z"
    user_id = "user_demo"
    insert_user(conn, User(id=user_id, created_at=t0))
    insert_account(
        conn,
        Account(
            id="acc_main",
            user_id=user_id,
            name="HDFC Salary Account",
            opening_balance_paise=25000000,
            created_at=t0,
        ),
    )

    cats = [
        ("cat_groceries", "Groceries"),
        ("cat_dining", "Dining"),
        ("cat_utilities", "Utilities"),
        ("cat_shopping", "Shopping"),
        ("cat_subscriptions", "Subscriptions"),
        ("cat_travel", "Travel"),
    ]
    for cid, cname in cats:
        insert_category(conn, Category(id=cid, user_id=user_id, name=cname, created_at=t0))

    # Budgets
    insert_budget(
        conn,
        Budget(
            id="b_groc",
            user_id=user_id,
            category_id="cat_groceries",
            limit_paise=1500000,  # ₹15,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    insert_budget(
        conn,
        Budget(
            id="b_dine",
            user_id=user_id,
            category_id="cat_dining",
            limit_paise=600000,  # ₹6,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )
    insert_budget(
        conn,
        Budget(
            id="b_shop",
            user_id=user_id,
            category_id="cat_shopping",
            limit_paise=800000,  # ₹8,000
            warn_threshold_pct=80,
            forecast_warn=True,
        ),
    )

    # August 2026 (prior month baseline)
    aug_txs = [
        (
            "tx_aug_inc",
            "2026-08-01T09:00:00Z",
            -12000000,
            "credit",
            None,
            "rule",
            1.0,
            "SALARY",
            "TECH CORP SALARY",
            "Monthly salary",
        ),
        (
            "tx_aug_1",
            "2026-08-05T12:00:00Z",
            620000,
            "debit",
            "cat_groceries",
            "rule",
            0.95,
            "BIGBASKET",
            "BIGBASKET",
            "Groceries",
        ),
        (
            "tx_aug_2",
            "2026-08-12T19:30:00Z",
            410000,
            "debit",
            "cat_dining",
            "rule",
            0.90,
            "SWIGGY",
            "SWIGGY",
            "Dinner Swiggy",
        ),
        (
            "tx_aug_3",
            "2026-08-15T10:00:00Z",
            150000,
            "debit",
            "cat_utilities",
            "rule",
            0.99,
            "BESCOM",
            "BESCOM ELECTRICITY",
            "Power bill",
        ),
        (
            "tx_aug_4",
            "2026-08-20T16:00:00Z",
            350000,
            "debit",
            "cat_shopping",
            "rule",
            0.88,
            "AMAZON",
            "AMAZON INDIA",
            "Online shopping",
        ),
    ]
    for tid, ts, amt, direction, cat, csrc, cconf, mnorm, mraw, desc in aug_txs:
        insert_transaction(
            conn,
            Transaction(
                id=tid,
                account_id="acc_main",
                user_id=user_id,
                occurred_at=ts,
                amount_paise=amt,
                merchant_raw=mraw,
                merchant_normalized=mnorm,
                description=desc,
                direction=direction,
                category_id=cat,
                category_source=csrc,
                category_confidence=cconf,
                created_at=ts,
            ),
        )

    # September 2026 transactions
    sep_txs = [
        (
            "tx_sep_inc",
            "2026-09-01T09:00:00Z",
            -12000000,
            "credit",
            None,
            "none",
            1.0,
            "SALARY",
            "TECH CORP SALARY",
            "Monthly salary",
        ),
        (
            "tx_sep_g1",
            "2026-09-04T11:00:00Z",
            450000,
            "debit",
            "cat_groceries",
            "rule",
            0.95,
            "BIGBASKET",
            "BIGBASKET",
            "Grocery staples",
        ),
        (
            "tx_sep_g2",
            "2026-09-18T17:00:00Z",
            300000,
            "debit",
            "cat_groceries",
            "rule",
            0.92,
            "ZEPTO",
            "ZEPTO QUICK",
            "Quick groceries",
        ),
        (
            "tx_sep_d1",
            "2026-09-08T13:30:00Z",
            280000,
            "debit",
            "cat_dining",
            "rule",
            0.90,
            "SWIGGY",
            "SWIGGY",
            "Weekend dining",
        ),
        (
            "tx_sep_d2",
            "2026-09-22T20:00:00Z",
            240000,
            "debit",
            "cat_dining",
            "rule",
            0.89,
            "ZOMATO",
            "ZOMATO RESTAURANT",
            "Dinner with friends",
        ),
        (
            "tx_sep_u1",
            "2026-09-15T10:00:00Z",
            150000,
            "debit",
            "cat_utilities",
            "rule",
            0.99,
            "BESCOM",
            "BESCOM ELECTRICITY",
            "Electricity bill",
        ),
        (
            "tx_sep_s1",
            "2026-09-10T02:00:00Z",
            64900,
            "debit",
            "cat_subscriptions",
            "rule",
            0.98,
            "NETFLIX",
            "NETFLIX ENTERTAINMENT",
            "Monthly subscription",
        ),
        (
            "tx_sep_s2",
            "2026-09-16T08:00:00Z",
            99900,
            "debit",
            "cat_subscriptions",
            "rule",
            0.97,
            "AIRTEL",
            "AIRTEL BROADBAND",
            "Fiber internet bill",
        ),
        (
            "tx_sep_sh1",
            "2026-09-12T15:00:00Z",
            420000,
            "debit",
            "cat_shopping",
            "rule",
            0.85,
            "MYNTRA",
            "MYNTRA FASHION",
            "Apparel sale",
        ),
        (
            "tx_sep_tr1",
            "2026-09-25T14:15:00Z",
            2250000,
            "debit",
            "cat_travel",
            "rule",
            0.90,
            "INDIGO",
            "INDIGO AIRLINES",
            "Domestic flight tickets",
        ),
    ]
    for tid, ts, amt, direction, cat, csrc, cconf, mnorm, mraw, desc in sep_txs:
        insert_transaction(
            conn,
            Transaction(
                id=tid,
                account_id="acc_main",
                user_id=user_id,
                occurred_at=ts,
                amount_paise=amt,
                merchant_raw=mraw,
                merchant_normalized=mnorm,
                description=desc,
                direction=direction,
                category_id=cat,
                category_source=csrc,
                category_confidence=cconf,
                created_at=ts,
            ),
        )

    # Recurring series
    conn.execute(
        """
        INSERT INTO recurring_series (
            id, user_id, merchant_normalized, typical_amount_paise, cadence_days,
            last_seen, next_expected, confidence, kind
        ) VALUES
        ('rec_bescom', 'user_demo', 'BESCOM', 150000, 30,
         '2026-09-15T10:00:00Z', '2026-10-15T10:00:00Z', 0.99, 'bill'),
        ('rec_netflix', 'user_demo', 'NETFLIX', 64900, 30,
         '2026-09-10T02:00:00Z', '2026-10-10T02:00:00Z', 0.98, 'subscription'),
        ('rec_airtel', 'user_demo', 'AIRTEL', 99900, 30,
         '2026-09-16T08:00:00Z', '2026-10-16T08:00:00Z', 0.97, 'bill')
        """
    )

    # Advice
    advice_text = (
        "Dining spend reached 87% of your monthly limit of ₹6,000. "
        "Consider pacing weekend restaurant orders."
    )
    conn.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text, evidence_json,
            assumptions_json, status, created_at
        ) VALUES (
            'adv_202609_1',
            'user_demo',
            'run_seed',
            '[]',
            ?,
            '{}',
            '["Dining limit remains ₹6,000", "No additional unrecorded restaurant charges"]',
            'approved',
            '2026-09-28T18:00:00Z'
        )
        """,
        (advice_text,),
    )
    conn.commit()


def main() -> None:
    conn = get_connection(":memory:")
    init_db(conn)
    seed_data(conn)

    # Clock right after September concludes
    clock = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    review = build_monthly_review(
        conn,
        user_id="user_demo",
        year=2026,
        month=9,
        run_id="run_sample_202609",
        clock=clock,
    )

    # Render Markdown and HTML
    md_text = render_markdown(review)
    html_text = render_html(review)

    # Validate number safety invariant
    valid_numbers = extract_all_review_numbers(review)
    md_numbers = extract_numbers_from_rendered_text(md_text)
    html_numbers = extract_numbers_from_rendered_text(html_text)

    diff_md = md_numbers - valid_numbers
    diff_html = html_numbers - valid_numbers
    if diff_md:
        raise ValueError(f"Invented numbers in Markdown: {diff_md}")
    if diff_html:
        raise ValueError(f"Invented numbers in HTML: {diff_html}")

    # Write output to reports/ directory
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    md_path = reports_dir / "2026-09.md"
    html_path = reports_dir / "2026-09.html"

    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    print(f"Successfully generated {md_path} ({len(md_text)} bytes)")
    print(f"Successfully generated {html_path} ({len(html_text)} bytes)")


if __name__ == "__main__":
    main()
