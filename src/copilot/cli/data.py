"""Setting up: create the database and load demo data."""

from typing import Annotated

import typer

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    open_db,
    save_mock_bank_data,
)
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
from copilot.models.domain import Account, Budget, Category, User


@app.command("init-db")
def init_db_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Initialize database and apply all schema migrations."""
    db_path = get_db_path(db)
    try:
        conn = open_db(db_path)
        conn.close()
        if as_json:
            print_json({"status": "ok", "message": "Database initialized", "db": db_path})
        else:
            print_success(f"Database initialized successfully at [cyan]{db_path}[/cyan]")
    except Exception as exc:
        print_error(f"Failed to initialize database: {exc}")
        raise typer.Exit(code=1) from exc


@app.command("seed")
def seed_cmd(
    seed: Annotated[int, typer.Option("--seed", help="Random seed")] = 42,
    months: Annotated[int, typer.Option("--months", help="Months of history to generate")] = 3,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="Demo user ID")] = "u1",
    account_id: Annotated[str, typer.Option("--account-id", help="Default account ID")] = "a1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Seed demo user, accounts, categories, budgets, and synthetic bank data."""
    db_path = get_db_path(db)
    try:
        conn = open_db(db_path)
        t0 = "2024-01-01T00:00:00Z"

        # 1. User
        if not get_user(conn, user_id):
            insert_user(conn, User(id=user_id, created_at=t0))

        # 2. Account
        if not get_account(conn, user_id, account_id):
            insert_account(
                conn,
                Account(
                    id=account_id,
                    user_id=user_id,
                    name="Checking Account",
                    opening_balance_paise=25000000,
                    created_at=t0,
                ),
            )

        # 3. Standard Categories
        cats = [
            ("food", "Food & Dining"),
            ("travel", "Travel & Commute"),
            ("groceries", "Groceries"),
            ("shopping", "Shopping"),
            ("utilities", "Utilities & Bills"),
            ("subscriptions", "Subscriptions"),
            ("entertainment", "Entertainment & Media"),
            ("bills", "Bills & Recharge"),
            ("housing", "Housing & Rent"),
            ("rent", "Rent & Housing"),
            ("income", "Salary & Income"),
            ("cat_groceries", "Groceries (Legacy)"),
            ("cat_dining", "Dining (Legacy)"),
            ("cat_shopping", "Shopping (Legacy)"),
            ("cat_utilities", "Utilities (Legacy)"),
            ("cat_subscriptions", "Subscriptions (Legacy)"),
            ("cat_travel", "Travel (Legacy)"),
        ]
        for cid, cname in cats:
            if not get_category(conn, user_id, cid):
                insert_category(
                    conn,
                    Category(id=cid, user_id=user_id, name=cname, created_at=t0),
                )

        # 4. Standard Budgets
        existing_b_cats = {b.category_id for b in list_budgets(conn, user_id)}
        if "food" not in existing_b_cats:
            insert_budget(
                conn,
                Budget(
                    id="b_food",
                    user_id=user_id,
                    category_id="food",
                    limit_paise=1500000,
                    warn_threshold_pct=80,
                    forecast_warn=True,
                ),
            )
        if "cat_groceries" not in existing_b_cats:
            insert_budget(
                conn,
                Budget(
                    id="b_groceries",
                    user_id=user_id,
                    category_id="cat_groceries",
                    limit_paise=1500000,
                    warn_threshold_pct=80,
                    forecast_warn=True,
                ),
            )
        if "cat_dining" not in existing_b_cats:
            insert_budget(
                conn,
                Budget(
                    id="b_dining",
                    user_id=user_id,
                    category_id="cat_dining",
                    limit_paise=600000,
                    warn_threshold_pct=80,
                    forecast_warn=True,
                ),
            )

        # 5. Persist synthetic bank data
        tx_count = save_mock_bank_data(
            user_id=user_id,
            seed=seed,
            months=months,
            account_id=account_id,
        )

        # 6. Default consent in database
        cid = f"consent_seed_{user_id}_{seed}"
        conn.execute(
            """
            INSERT OR REPLACE INTO consents (
                id, user_id, purpose, fi_types, account_ids,
                date_range_from, date_range_to, status, expires_at, created_at
            ) VALUES (?, ?, 'sync', 'DEPOSIT', ?, '2020-01-01T00:00:00Z',
                      '2030-01-01T00:00:00Z', 'pending', '2030-01-01T00:00:00Z', ?)
            """,
            (cid, user_id, f'["{account_id}"]', t0),
        )
        conn.commit()
        conn.close()

        res_data = {
            "status": "ok",
            "user_id": user_id,
            "account_id": account_id,
            "seed": seed,
            "months": months,
            "synthetic_transactions": tx_count,
            "consent_id": cid,
        }
        if as_json:
            print_json(res_data)
        else:
            print_success(f"Seeded environment for user [cyan]{user_id}[/cyan]:")
            console.print(f"  • Accounts: [green]{account_id}[/green] (Checking)")
            console.print("  • Categories & Budgets configured")
            console.print(f"  • Generated: [bold]{tx_count}[/bold] synthetic bank records")
            console.print(
                f"  • Consent created: [yellow]{cid}[/yellow] "
                "(Approve with 'copilot consent approve <id>')"
            )
    except Exception as exc:
        print_error(f"Failed to seed demo data: {exc}")
        raise typer.Exit(code=1) from exc
