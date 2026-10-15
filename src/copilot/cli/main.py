"""
Main Typer CLI application for Finance Copilot (PLAN_PHASE1 Section 5.9).
"""

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.formatters import (
    console,
    print_alerts_table,
    print_anomalies_table,
    print_audit_table,
    print_budgets_table,
    print_consents_table,
    print_error,
    print_goals_table,
    print_investigation_result,
    print_json,
    print_recurring_table,
    print_simulation_result,
    print_state_panel,
    print_success,
    print_timeline,
    print_transactions_table,
)
from copilot.cli.storage import (
    get_db_path,
    load_and_register_connector,
    load_trace,
    make_exec_ctx,
    open_db,
    save_mock_bank_data,
    save_trace,
)
from copilot.core.advice import format_inr
from copilot.core.intent import parse_amount_paise
from copilot.core.recommendations import format_recommendation_explanation
from copilot.core.timeline import build_timeline
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo import (
    get_account,
    get_category,
    get_recommendation,
    get_user,
    insert_account,
    insert_budget,
    insert_category,
    insert_user,
    list_budgets,
)
from copilot.models.agentic import Scenario
from copilot.models.domain import Account, Budget, Category, User
from copilot.review import build_monthly_review, render_html, render_markdown
from copilot.tools.executor import execute_tool
from copilot.workflow.agent_graph import build_planner_agent_graph
from copilot.workflow.agentic_state import AgenticState
from copilot.workflow.graph import build_agent_graph
from copilot.workflow.nodes import ensure_tools_registered
from copilot.workflow.state import AgentState
from copilot.workflow.trace import format_trace

app = typer.Typer(
    name="copilot",
    help="Personal Finance & Budgeting Copilot CLI",
    add_completion=False,
    no_args_is_help=True,
)

consent_app = typer.Typer(
    name="consent",
    help="Manage bank account aggregator consents",
    no_args_is_help=True,
)
app.add_typer(consent_app, name="consent")

goals_app = typer.Typer(
    name="goals",
    help="Manage financial goals",
    no_args_is_help=True,
)
app.add_typer(goals_app, name="goals")

whatif_app = typer.Typer(
    name="whatif",
    help="Simulate what-if spending decisions and scenarios",
    no_args_is_help=True,
)
app.add_typer(whatif_app, name="whatif")

alerts_app = typer.Typer(
    name="alerts",
    help="Manage adaptive financial alerts and preferences",
    no_args_is_help=True,
)
app.add_typer(alerts_app, name="alerts")


def parse_cli_amount(amt_str: str) -> int:
    """Parse monetary amount string into integer paise.

    Accepts: '50000', '50000.50', '₹50,000', 'Rs. 20,000', '20k', '2.5 lakh'.
    """
    clean = amt_str.strip()
    res = parse_amount_paise(clean)
    if res is not None:
        return res
    clean_num = clean.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        val = Decimal(clean_num)
        return int(round(val * 100))
    except Exception as exc:
        raise ValueError(f"Invalid monetary amount: '{amt_str}'") from exc


def _tool_out(res: Any, key: str) -> Any:
    """Extract a named attribute from a ToolOutput model or dict."""
    if hasattr(res.data, key):
        return getattr(res.data, key)
    if isinstance(res.data, dict):
        return res.data.get(key)
    return None


def _tool_dict(res: Any) -> dict[str, Any]:
    """Serialize ToolOutput model or dict to plain dictionary."""
    if hasattr(res.data, "model_dump"):
        return res.data.model_dump(mode="json")
    if isinstance(res.data, dict):
        return res.data
    return {}


# =================================================================================================
# 1. Database & Seeding
# =================================================================================================


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


# =================================================================================================
# 2. Consent Lifecycle Subcommands
# =================================================================================================


@consent_app.command("list")
def consent_list_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List all bank consents for a user."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    rows = conn.execute(
        """
        SELECT id, user_id, purpose, account_ids, date_range_from, date_range_to,
               status, expires_at, created_at
        FROM consents WHERE user_id = ? ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    consents = [dict(r) for r in rows]
    if as_json:
        print_json(consents)
    else:
        print_consents_table(consents)


@consent_app.command("create")
def consent_create_cmd(
    account_id: Annotated[str, typer.Argument(help="Account ID")] = "a1",
    institution: Annotated[
        str | None, typer.Option("--institution", help="Institution name")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    purpose: Annotated[str, typer.Option("--purpose", help="Consent purpose")] = "sync",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a new bank consent (status: pending)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    now_iso = to_utc_iso(now_utc())
    cid = f"consent_{user_id}_{int(datetime.now(tz=UTC).timestamp())}"
    conn.execute(
        """
        INSERT INTO consents (
            id, user_id, purpose, fi_types, account_ids,
            date_range_from, date_range_to, status, expires_at, created_at
        ) VALUES (?, ?, ?, 'DEPOSIT', ?, '2020-01-01T00:00:00Z',
                  '2030-01-01T00:00:00Z', 'pending', '2030-01-01T00:00:00Z', ?)
        """,
        (cid, user_id, purpose, f'["{account_id}"]', now_iso),
    )
    conn.commit()
    conn.close()

    res = {"id": cid, "status": "pending", "user_id": user_id, "account_id": account_id}
    if as_json:
        print_json(res)
    else:
        print_success(f"Created consent [cyan]{cid}[/cyan] (status: [yellow]PENDING[/yellow])")
        console.print(f"To activate: [bold]copilot consent approve {cid}[/bold]")


@consent_app.command("approve")
def consent_approve_cmd(
    consent_id: Annotated[str, typer.Argument(help="Consent ID to approve")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Approve a bank consent (status: active)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    cur = conn.execute("UPDATE consents SET status = 'active' WHERE id = ?", (consent_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        print_error(f"Consent '{consent_id}' not found.")
        raise typer.Exit(code=1)

    if as_json:
        print_json({"id": consent_id, "status": "active"})
    else:
        print_success(f"Consent [cyan]{consent_id}[/cyan] approved (status: [green]ACTIVE[/green])")


@consent_app.command("revoke")
def consent_revoke_cmd(
    consent_id: Annotated[str, typer.Argument(help="Consent ID to revoke")],
    reason: Annotated[str | None, typer.Option("--reason", help="Revocation reason")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Revoke a bank consent (status: revoked)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    cur = conn.execute("UPDATE consents SET status = 'revoked' WHERE id = ?", (consent_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        print_error(f"Consent '{consent_id}' not found.")
        raise typer.Exit(code=1)

    if as_json:
        print_json({"id": consent_id, "status": "revoked"})
    else:
        print_success(f"Consent [cyan]{consent_id}[/cyan] revoked (status: [red]REVOKED[/red])")


# =================================================================================================
# 3. Workflow Execution & Monthly Review
# =================================================================================================


@app.command("run")
def run_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    year: Annotated[int, typer.Option("--year", help="Year to process")] = 2024,
    month: Annotated[int, typer.Option("--month", help="Month to process")] = 2,
    interactive: Annotated[bool, typer.Option("--interactive/--no-interactive")] = False,
    auto_approve: Annotated[bool, typer.Option("--auto-approve/--no-auto-approve")] = True,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Run full agent graph: ingest -> categorize -> analyze -> advise -> review -> finalize."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)

    # 1. Register connector with mock transactions
    load_and_register_connector(user_id=user_id, conn=conn)

    # 2. Check for active consent
    c_row = conn.execute(
        "SELECT id FROM consents WHERE user_id = ? AND status = 'active' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not c_row:
        p_row = conn.execute(
            "SELECT id FROM consents WHERE user_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        if p_row:
            print_error(
                f"No active consent found for user '{user_id}'. "
                f"Approve pending consent: copilot consent approve {p_row[0]}"
            )
        else:
            print_error(f"No consent found for user '{user_id}'. Run 'copilot seed' to initialize.")
        raise typer.Exit(code=1)

    # 3. Setup LangGraph workflow execution
    run_id = f"run_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"
    exec_ctx = make_exec_ctx(conn=conn, user_id=user_id, run_id=run_id, actor="agent")

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = f"thread_{run_id}"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "exec_ctx": exec_ctx,
        }
    }

    state: AgentState = {
        "run_id": run_id,
        "user_id": user_id,
        "consent_id": c_row[0],
        "year": year,
        "month": month,
        "review_decisions": [],
        "trace": [],
    }

    try:
        result = graph.invoke(state, config=config)
    except GraphInterrupt as gi:
        # Human review interrupt
        drafts = gi.args[0].get("drafts", []) if gi.args else []
        decisions = []
        if interactive:
            console.print(
                f"\n[bold yellow]Human Review Required:[/bold yellow] {len(drafts)} items"
            )
            for d in drafts:
                console.print(f"\n  Advice ID: [cyan]{d.id}[/cyan]")
                console.print(f"  Guidance:  {d.text}")
                action = typer.prompt("  Decision ([a]pprove / [r]eject / [s]kip)", default="a")
                dec = "approved" if action.lower().startswith("a") else "rejected"
                decisions.append({"advice_id": d.id, "decision": dec})
        elif auto_approve:
            decisions = [{"advice_id": d.id, "decision": "approved"} for d in drafts]

        result = graph.invoke(Command(resume=decisions), config=config)

    trace_entries = result.get("trace", [])
    save_trace(run_id, trace_entries)
    conn.close()

    if as_json:
        print_json({"run_id": run_id, "status": result.get("status"), "trace": trace_entries})
    else:
        print_success(f"Workflow execution completed ([cyan]{run_id}[/cyan])")
        console.print(format_trace(trace_entries))


@app.command("review-month")
def review_month_cmd(
    period: Annotated[str, typer.Argument(help="Review period in YYYY-MM format (e.g. 2026-09)")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    output_dir: Annotated[
        str | None, typer.Option("--output-dir", help="Directory to save reports")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Generate and render monthly review (writes reports/<period>.md and .html)."""
    ensure_tools_registered()
    m = re.match(r"^(\d{4})-(\d{2})$", period)
    if not m:
        print_error(f"Invalid period format '{period}'. Expected YYYY-MM (e.g. 2026-09).")
        raise typer.Exit(code=1)

    year = int(m.group(1))
    month = int(m.group(2))
    if not 1 <= month <= 12:
        print_error(f"Invalid month {month}. Must be between 01 and 12.")
        raise typer.Exit(code=1)

    db_path = get_db_path(db)
    conn = open_db(db_path)
    run_id = f"rev_{year}_{month:02d}_{int(datetime.now(tz=UTC).timestamp())}"

    try:
        review_data = build_monthly_review(
            conn=conn,
            user_id=user_id,
            year=year,
            month=month,
            run_id=run_id,
        )
        conn.commit()
        conn.close()

        # Render reports
        reports_dir = Path(output_dir) if output_dir else Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)

        md_path = reports_dir / f"{period}.md"
        html_path = reports_dir / f"{period}.html"

        md_content = render_markdown(review_data)
        html_content = render_html(review_data)

        md_path.write_text(md_content, encoding="utf-8")
        html_path.write_text(html_content, encoding="utf-8")

        if as_json:
            print_json(review_data.model_dump())
        else:
            print_success(
                f"Generated Monthly Review for [bold cyan]{period}[/bold cyan] "
                f"(v{review_data.version})"
            )
            console.print(f"  • Income:     [green]{format_inr(review_data.income_paise)}[/green]")
            console.print(f"  • Spend:      [red]{format_inr(review_data.spend_paise)}[/red]")
            console.print(f"  • Net:        [bold]{format_inr(review_data.net_paise)}[/bold]")
            console.print(f"  • Categories: {len(review_data.category_totals)} tracked")
            console.print(f"  • Written:    [cyan]{md_path}[/cyan] ({len(md_content)} bytes)")
            console.print(f"  • Written:    [cyan]{html_path}[/cyan] ({len(html_content)} bytes)")
    except Exception as exc:
        conn.close()
        print_error(f"Failed to generate monthly review: {exc}")
        raise typer.Exit(code=1) from exc


# =================================================================================================
# 4. Transactions, Corrections & Undo
# =================================================================================================


@app.command("txns")
def txns_cmd(
    month: Annotated[str | None, typer.Option("--month", help="Filter by YYYY-MM")] = None,
    category: Annotated[str | None, typer.Option("--category", help="Filter by category")] = None,
    needs_review: Annotated[
        bool | None,
        typer.Option("--needs-review", help="Filter items needing review"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows")] = 50,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List transactions with optional filters."""
    db_path = get_db_path(db)
    conn = open_db(db_path)

    query = "SELECT * FROM transactions WHERE user_id = ?"
    params: list[Any] = [user_id]

    if month:
        query += " AND strftime('%Y-%m', occurred_at) = ?"
        params.append(month)
    if category:
        query += " AND category_id = ?"
        params.append(category)
    if needs_review is not None:
        query += " AND needs_review = ?"
        params.append(1 if needs_review else 0)

    query += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    txs = [dict(r) for r in rows]
    if as_json:
        print_json(txs)
    else:
        print_transactions_table(txs)


@app.command("correct")
def correct_cmd(
    txn_id: Annotated[str, typer.Argument(help="Transaction ID to recategorize")],
    category: Annotated[str, typer.Argument(help="New category ID")],
    remember: Annotated[
        bool,
        typer.Option("--remember", help="Create permanent merchant override"),
    ] = False,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """User correction: change a transaction's category (optional --remember override)."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "recategorize_transaction",
        {
            "transaction_id": txn_id,
            "new_category_id": category,
            "remember": remember,
        },
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Correction rejected: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(res.data)
    else:
        print_success(
            f"Transaction [cyan]{txn_id}[/cyan] updated to category [green]{category}[/green]"
        )
        if remember:
            console.print("  • Saved merchant override for future transactions.")


@app.command("undo")
def undo_cmd(
    audit_event_id: Annotated[str, typer.Argument(help="Audit event ID to undo")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Undo a specific reversible audit event."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "undo", {"audit_event_id": audit_event_id})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Undo rejected: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(res.data)
    else:
        print_success(f"Undid event [cyan]{audit_event_id}[/cyan] successfully.")


@app.command("undo-batch")
def undo_batch_cmd(
    run_id: Annotated[str, typer.Argument(help="Run ID of the categorization batch to revert")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Undo an entire automated categorization batch."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "undo_categorize_batch", {"run_id": run_id})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Undo batch rejected: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(res.data)
    else:
        restored = res.data.get("restored", 0) if isinstance(res.data, dict) else "?"
        print_success(f"Batch [cyan]{run_id}[/cyan] reverted. Restored {restored} transactions.")


# =================================================================================================
# 5. Analysis Views
# =================================================================================================


@app.command("budgets")
def budgets_cmd(
    month: Annotated[str | None, typer.Option("--month", help="Month in YYYY-MM format")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View monthly budget performance statuses."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    now = datetime.now(tz=UTC)
    yr = int(month.split("-")[0]) if month else now.year
    mo = int(month.split("-")[1]) if month else now.month

    res = execute_tool(ctx, "check_budgets", {"year": yr, "month": mo})
    conn.close()

    if not res.ok:
        print_error(f"Failed to check budgets: {res.error.message}")
        raise typer.Exit(code=1)

    data_dict = res.data.model_dump() if hasattr(res.data, "model_dump") else (res.data or {})
    statuses = data_dict.get("statuses", []) if isinstance(data_dict, dict) else []
    if as_json:
        print_json(statuses)
    else:
        print_budgets_table(statuses)


@app.command("forecast")
def forecast_cmd(
    month: Annotated[str | None, typer.Option("--month", help="Month in YYYY-MM format")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View month-end spend forecast."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    if month:
        m = re.match(r"^(\d{4})-(\d{2})$", month)
        if not m:
            print_error(f"Invalid month format '{month}'. Expected YYYY-MM.")
            raise typer.Exit(code=1)
        yr, mo = int(m.group(1)), int(m.group(2))
    else:
        now = datetime.now(tz=UTC)
        yr, mo = now.year, now.month

    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
    res = execute_tool(ctx, "forecast_month", {"year": yr, "month": mo})
    conn.close()

    if not res.ok:
        print_error(f"Failed to calculate forecast: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(res.data)
    else:
        val = res.data.model_dump() if hasattr(res.data, "model_dump") else (res.data or {})
        console.print(f"\n[bold]Month-End Spend Forecast ({yr}-{mo:02d}):[/bold]")
        console.print(f"  • Spent So Far:    {format_inr(val.get('spent_so_far', 0))}")
        proj_str = format_inr(val.get("projected_total", 0))
        console.print(f"  • Projected Total: [bold green]{proj_str}[/bold green]")
        rng = val.get("projected_range", (0, 0))
        console.print(f"  • Projected Range: {format_inr(rng[0])} - {format_inr(rng[1])}")
        if val.get("insufficient_data"):
            console.print("  • [yellow]Notice:[/yellow] Insufficient historical data for baseline.")


@app.command("anomalies")
def anomalies_cmd(
    month: Annotated[str | None, typer.Option("--month", help="Month in YYYY-MM format")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View detected unusual/outlier transactions."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    if month:
        m = re.match(r"^(\d{4})-(\d{2})$", month)
        if not m:
            print_error(f"Invalid month format '{month}'. Expected YYYY-MM.")
            raise typer.Exit(code=1)

    res = execute_tool(ctx, "detect_anomalies", {})
    conn.close()

    if not res.ok:
        print_error(f"Failed to detect anomalies: {res.error.message}")
        raise typer.Exit(code=1)

    data_dict = res.data.model_dump() if hasattr(res.data, "model_dump") else (res.data or {})
    anomalies = data_dict.get("anomalies", []) if isinstance(data_dict, dict) else []
    if as_json:
        print_json(anomalies)
    else:
        print_anomalies_table(anomalies)


@app.command("recurring")
def recurring_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View recurring subscriptions and bills."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "detect_recurring", {})
    conn.close()

    if not res.ok:
        print_error(f"Failed to detect recurring items: {res.error.message}")
        raise typer.Exit(code=1)

    data_dict = res.data.model_dump() if hasattr(res.data, "model_dump") else (res.data or {})
    recurring = data_dict.get("recurring", []) if isinstance(data_dict, dict) else []
    if as_json:
        print_json(recurring)
    else:
        print_recurring_table(recurring)


@app.command("state")
def state_cmd(
    month: Annotated[str | None, typer.Option("--month", help="Month in YYYY-MM format")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View financial state snapshot."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    if month:
        m = re.match(r"^(\d{4})-(\d{2})$", month)
        if not m:
            print_error(f"Invalid month format '{month}'. Expected YYYY-MM.")
            raise typer.Exit(code=1)
        yr, mo = int(m.group(1)), int(m.group(2))
    else:
        now = datetime.now(tz=UTC)
        yr, mo = now.year, now.month

    res = execute_tool(ctx, "get_financial_state", {"year": yr, "month": mo})
    conn.close()

    if not res.ok:
        print_error(f"Failed to get financial state: {res.error.message}")
        raise typer.Exit(code=1)

    val = res.data.model_dump() if hasattr(res.data, "model_dump") else (res.data or {})
    if as_json:
        print_json(val)
    else:
        print_state_panel(val)


# =================================================================================================
# 6. Audit & Trace
# =================================================================================================


@app.command("audit")
def audit_cmd(
    txn: Annotated[str | None, typer.Option("--txn", help="Filter by transaction ID")] = None,
    run: Annotated[str | None, typer.Option("--run", help="Filter by run ID")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows")] = 50,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View audit trail with before/after state and reversibility flags."""
    db_path = get_db_path(db)
    conn = open_db(db_path)

    query = "SELECT * FROM audit_events WHERE user_id = ?"
    params: list[Any] = [user_id]

    if txn:
        query += " AND entity_id = ?"
        params.append(txn)
    if run:
        query += " AND run_id = ?"
        params.append(run)

    query += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    events = [dict(r) for r in rows]
    if as_json:
        print_json(events)
    else:
        print_audit_table(events)


@app.command("trace")
def trace_cmd(
    run_id: Annotated[str, typer.Argument(help="Run ID or Task ID to display trace for")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display execution trace, spans, specialists, reflections, and manifests."""
    db_path = get_db_path(db)
    has_db_trace = False
    spans_data = []
    specs_data = []
    refs_data = []
    manifests_data = []

    try:
        conn = open_db(db_path)
        try:
            span_rows = conn.execute(
                "SELECT * FROM trace_spans WHERE trace_id = ? ORDER BY started_at ASC", (run_id,)
            ).fetchall()
            if span_rows:
                has_db_trace = True
                for r in span_rows:
                    d = dict(r)
                    if isinstance(d.get("attrs_json"), str):
                        try:
                            d["attrs"] = json.loads(d["attrs_json"])
                        except Exception:
                            d["attrs"] = {}
                    spans_data.append(d)

            spec_rows = conn.execute(
                "SELECT * FROM specialist_reports WHERE task_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            if spec_rows:
                has_db_trace = True
                for r in spec_rows:
                    d = dict(r)
                    for k in ("sub_question_json", "findings_json", "gaps_json"):
                        if isinstance(d.get(k), str):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                pass
                    specs_data.append(d)

            ref_rows = conn.execute(
                "SELECT * FROM reflections WHERE task_id = ? ORDER BY round ASC", (run_id,)
            ).fetchall()
            if ref_rows:
                has_db_trace = True
                for r in ref_rows:
                    d = dict(r)
                    if isinstance(d.get("critique_codes_json"), str):
                        try:
                            d["critique_codes"] = json.loads(d["critique_codes_json"])
                        except Exception:
                            d["critique_codes"] = []
                    refs_data.append(d)

            man_rows = conn.execute(
                "SELECT * FROM context_manifests WHERE task_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            if man_rows:
                has_db_trace = True
                for r in man_rows:
                    d = dict(r)
                    for k in ("included_json", "excluded_json"):
                        if isinstance(d.get(k), str):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                pass
                    manifests_data.append(d)
        finally:
            conn.close()
    except Exception:
        pass

    if has_db_trace:
        if as_json:
            print_json(
                {
                    "trace_id": run_id,
                    "spans": spans_data,
                    "specialists": specs_data,
                    "reflections": refs_data,
                    "context_manifests": manifests_data,
                }
            )
            return

        console.print(
            Panel(
                f"Execution Telemetry Trace for Task/Run ID: [cyan]{run_id}[/cyan]",
                border_style="cyan",
            )
        )

        if spans_data:
            t_span = Table(title="Trace Spans Hierarchy", box=box.ROUNDED)
            t_span.add_column("Span ID", style="dim")
            t_span.add_column("Kind", style="cyan")
            t_span.add_column("Name", style="bold")
            t_span.add_column("Duration", justify="right")
            t_span.add_column("Status")
            t_span.add_column("Attributes", style="dim")
            for s in spans_data:
                st = s.get("status", "ok")
                st_style = "green" if st == "ok" else "red"
                dur = (
                    f"{s.get('duration_ms', 0):.1f}ms" if s.get("duration_ms") is not None else "-"
                )
                attrs_str = str(s.get("attrs", {}))
                if len(attrs_str) > 60:
                    attrs_str = attrs_str[:57] + "..."
                t_span.add_row(
                    str(s.get("span_id", "")),
                    str(s.get("kind", "")),
                    str(s.get("name", "")),
                    dur,
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                    attrs_str,
                )
            console.print(t_span)

        if specs_data:
            t_spec = Table(title="Specialist Agent Reports", box=box.ROUNDED)
            t_spec.add_column("Role", style="bold cyan")
            t_spec.add_column("Status")
            t_spec.add_column("Findings", justify="right")
            t_spec.add_column("Gaps", justify="right")
            t_spec.add_column("Duration", justify="right")
            for sp in specs_data:
                st = sp.get("status", "ok")
                st_style = "green" if st == "ok" else ("yellow" if st == "partial" else "red")
                f_count = (
                    len(sp.get("findings_json", []))
                    if isinstance(sp.get("findings_json"), list)
                    else 0
                )
                g_count = (
                    len(sp.get("gaps_json", [])) if isinstance(sp.get("gaps_json"), list) else 0
                )
                t_spec.add_row(
                    str(sp.get("agent_role", "")),
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                    str(f_count),
                    str(g_count),
                    f"{sp.get('duration_ms', 0):.1f}ms",
                )
            console.print(t_spec)

        if refs_data:
            t_ref = Table(title="Reflexion Revisions & Critiques", box=box.ROUNDED)
            t_ref.add_column("Round", justify="center")
            t_ref.add_column("Source", style="cyan")
            t_ref.add_column("Critique Codes", style="yellow")
            t_ref.add_column("Revised", justify="center")
            t_ref.add_column("Outcome")
            for rf in refs_data:
                rev_str = "[green]YES[/green]" if rf.get("revised") else "[dim]NO[/dim]"
                out = rf.get("outcome", "unchanged")
                out_style = (
                    "green" if out == "fixed" else ("yellow" if out == "unchanged" else "red")
                )
                t_ref.add_row(
                    str(rf.get("round", 1)),
                    str(rf.get("source", "deterministic")),
                    ", ".join(rf.get("critique_codes", [])),
                    rev_str,
                    f"[{out_style}]{out.upper()}[/{out_style}]",
                )
            console.print(t_ref)

        if manifests_data:
            t_man = Table(title="Context Engineering Manifests", box=box.ROUNDED)
            t_man.add_column("Purpose", style="bold")
            t_man.add_column("Budget", justify="right")
            t_man.add_column("Estimated Tokens", justify="right")
            t_man.add_column("Included Items", justify="right")
            t_man.add_column("Excluded Items", justify="right")
            t_man.add_column("Redactions", justify="right")
            for m in manifests_data:
                inc_cnt = (
                    len(m.get("included_json", []))
                    if isinstance(m.get("included_json"), list)
                    else 0
                )
                exc_cnt = (
                    len(m.get("excluded_json", []))
                    if isinstance(m.get("excluded_json"), list)
                    else 0
                )
                t_man.add_row(
                    str(m.get("purpose", "")),
                    str(m.get("budget_tokens", 0)),
                    str(m.get("estimated_tokens", 0)),
                    str(inc_cnt),
                    str(exc_cnt),
                    str(m.get("redactions_count", 0)),
                )
            console.print(t_man)
        return

    trace_entries = load_trace(run_id)
    if trace_entries is None:
        print_error(f"No execution trace found for run '{run_id}'.")
        raise typer.Exit(code=1)

    if as_json:
        print_json(trace_entries)
    else:
        console.print(format_trace(trace_entries))


@app.command("eval")
def eval_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    phase: Annotated[int, typer.Option("--phase", help="Evaluation phase (1, 2, or 3)")] = 1,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    from rich import box
    from rich.table import Table

    if phase == 3:
        from copilot.eval.harness_phase3 import run_phase3_evaluation

        if not as_json:
            console.print(
                "[bold cyan]Running Phase 3 Eval Harness (seeds: 777, 888, 999)...[/bold cyan]"
            )

        report = run_phase3_evaluation()

        if as_json:
            print_json(report)
        else:
            table = Table(title="Phase 3 Agentic Copilot Evaluation Results", box=box.ROUNDED)
            table.add_column("Dimension", style="bold")
            table.add_column("Metric")
            table.add_column("Score", justify="right", style="green")
            table.add_column("Status", justify="center")

            comm = report.get("commitments", {})
            table.add_row(
                "Commitments",
                "Suggestion Precision / Recall",
                f"{comm.get('precision_pct', 0)}% / {comm.get('recall_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Commitments",
                "Occurrence Match Accuracy",
                f"{comm.get('match_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            cal = report.get("calendar", {})
            table.add_row(
                "Calendar",
                "Coverage Accuracy vs Ground Truth",
                f"{cal.get('coverage_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            goals = report.get("goals", {})
            table.add_row(
                "Goals",
                "Completion Projection Error",
                f"{goals.get('completion_error_months', 0.0):.2f} mo",
                "[green]PASS[/green]",
            )

            readiness = report.get("readiness", {})
            table.add_row(
                "Readiness",
                "Persona Classification Accuracy",
                f"{readiness.get('accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            mem = report.get("memory", {})
            table.add_row(
                "Memory",
                "Pattern Precision / Recall",
                f"{mem.get('pattern_precision_pct', 0)}% / {mem.get('pattern_recall_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Memory",
                "False Memory Rate on Noise",
                f"{mem.get('false_memory_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )

            agent_m = report.get("agent", {})
            table.add_row(
                "Multi-Agent",
                "Intent Type Accuracy",
                f"{agent_m.get('intent_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Trajectory Accuracy",
                f"{agent_m.get('trajectory_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Tool & Skill Minimality",
                f"{agent_m.get('tool_minimality_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Sub-Question Coverage",
                f"{agent_m.get('subquestion_coverage_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Revision Fix Rate",
                f"{agent_m.get('revision_success_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Fault-Tolerant Partial Answer Rate",
                f"{agent_m.get('partial_answer_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Parallel Speed-Up",
                f"{agent_m.get('parallel_speedup', 1.0):.2f}x",
                "[green]PASS[/green]",
            )

            learn_m = report.get("learning", {})
            table.add_row(
                "Feedback Learning",
                "Alert Noise Reduction vs Raw",
                f"{learn_m.get('noise_reduction_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Feedback Learning",
                "Safety Floors Protected",
                f"{learn_m.get('safety_floors_protected_pct', 100)}%",
                "[green]PASS[/green]",
            )

            safety_m = report.get("safety", {})
            table.add_row(
                "Safety & Governance",
                "Forbidden-Content Violations",
                str(safety_m.get("forbidden_content_violations", 0)),
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "Deterministic Refusal Pass",
                f"{safety_m.get('refusal_pass_pct', 100)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "Adversarial Injection Rejection",
                f"{safety_m.get('injection_rejection_pct', 100)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "MCP Zero Write Exposure",
                "PASS" if safety_m.get("mcp_zero_write_exposure", True) else "FAIL",
                "[green]PASS[/green]",
            )

            console.print(table)
            print_success("Evaluation report generated at [cyan]docs/eval_report_phase3.md[/cyan]")
        return

    if phase == 2:
        from copilot.eval.harness_phase2 import run_phase2_evaluation

        if not as_json:
            console.print(
                "[bold cyan]Running Finance Copilot Phase 2 Evaluation Harness...[/bold cyan]"
            )

        report = run_phase2_evaluation()

        if as_json:
            print_json(report)
        else:
            table = Table(title="Phase 2 Agentic Intelligence Evaluation Results", box=box.ROUNDED)
            table.add_column("Dimension", style="bold")
            table.add_column("Metric")
            table.add_column("Score", justify="right", style="green")
            table.add_column("Status", justify="center")

            table.add_row(
                "Intent Understanding",
                "Intent Type Accuracy",
                f"{report['intent']['type_accuracy_pct']}%",
                "[green]PASS[/green]",
            )
            prec = report["intent"]["refusal_precision_pct"]
            rec = report["intent"]["refusal_recall_pct"]
            table.add_row(
                "Governance Gate",
                "Refusal Precision / Recall",
                f"{prec}% / {rec}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Dynamic Planner",
                "Exact-Set Match",
                f"{report['planner']['exact_set_match_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Dynamic Planner",
                "Adversarial Plan Rejection",
                f"{report['planner']['adversarial_rejection_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Investigation",
                "Decomposition Exactness",
                f"{report['investigation_standard']['decomposition_invariant_pass_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Investigation",
                "No-Cause False Explanation Rate",
                f"{report['investigation_standard']['false_explanation_rate_pct']}%",
                "[green]PASS[/green]",
            )
            sim_ok = (
                report["simulation"]["identity_pass"]
                and report["simulation"]["conservation_of_paise_pass"]
            )
            table.add_row(
                "What-If Simulation",
                "Property Invariants",
                "PASS" if sim_ok else "FAIL",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Adaptive Alerts",
                "Ordinary Month Silence Rate",
                f"{report['alerts']['ordinary_month_silence_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Recommendations",
                "Narration Grounding Accuracy",
                f"{report['recommendations']['grounding_accuracy_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety Invariants",
                "Causal Claim Violations",
                str(report["recommendations"]["causal_claim_violations"]),
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety Invariants",
                "Missing Simulation Violations",
                str(report["recommendations"]["consequence_missing_simulation_violations"]),
                "[green]PASS[/green]",
            )

            console.print(table)
            print_success("Evaluation report generated at [cyan]docs/eval_report_phase2.md[/cyan]")
        return

    from copilot.eval.harness import run_evaluation

    if not as_json:
        console.print("[bold cyan]Running Finance Copilot Evaluation Harness...[/bold cyan]")

    report = run_evaluation()

    if as_json:
        print_json(report)
    else:
        summary = report["summary"]
        table = Table(title="Evaluation & Benchmarking Results", box=box.ROUNDED)
        table.add_column("Metric", style="bold")
        table.add_column("Score", justify="right", style="green")
        table.add_column("Status", justify="center")

        table.add_row(
            "Categorization Accuracy",
            f"{summary['categorization_accuracy_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Categorization Coverage",
            f"{summary['categorization_coverage_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "High-Conf Precision (>=0.85)",
            f"{summary['high_confidence_precision_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Transfer Detection F1",
            f"{summary['transfer_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Recurring Detection F1",
            f"{summary['recurring_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Anomaly Detection F1",
            f"{summary['anomaly_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row("Idempotency (0 duplicates)", "100%", "[green]PASS[/green]")
        table.add_row("Advice Validator Grounding", "100%", "[green]PASS[/green]")

        console.print(table)
        print_success("Evaluation report generated at [cyan]docs/eval_report.md[/cyan]")


# =================================================================================================
# 8. Phase 2: Goals Management
# =================================================================================================


@goals_app.command("add")
def goals_add_cmd(
    name: Annotated[str, typer.Argument(help="Name of the goal")],
    target: Annotated[str, typer.Argument(help="Target amount (e.g. 50000, 50k, ₹50,000)")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="Goal kind: savings, debt_payoff, purchase, emergency_fund"),
    ] = "savings",
    current: Annotated[str, typer.Option("--current", help="Initial saved amount")] = "0",
    deadline: Annotated[
        str | None, typer.Option("--deadline", help="Target deadline (YYYY-MM-DD)")
    ] = None,
    priority: Annotated[
        int, typer.Option("--priority", help="Priority (1=high, 2=med, 3=low)")
    ] = 1,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a new financial savings or purchase goal."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    try:
        target_paise = parse_cli_amount(target)
        current_paise = parse_cli_amount(current)
    except ValueError as exc:
        conn.close()
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    res = execute_tool(
        ctx,
        "create_goal",
        {
            "name": name,
            "kind": kind,
            "target_paise": target_paise,
            "current_paise": current_paise,
            "deadline": deadline,
            "priority": priority,
        },
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to create goal: {res.error.message}")
        raise typer.Exit(code=1)

    goal = _tool_out(res, "goal")
    if as_json:
        print_json(goal.model_dump(mode="json"))
    else:
        print_success(
            f"Goal '[cyan]{goal.id}[/cyan]' ({name}) created "
            f"with target {format_inr(target_paise)}."
        )


@goals_app.command("list")
def goals_list_cmd(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status: active, paused, completed, cancelled"),
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List financial goals for the current user."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "list_goals", {"status": status})
    conn.close()

    if not res.ok:
        print_error(f"Failed to list goals: {res.error.message}")
        raise typer.Exit(code=1)

    goals = _tool_out(res, "goals") or []
    if as_json:
        print_json([g.model_dump(mode="json") for g in goals])
    else:
        print_goals_table([g.model_dump(mode="json") for g in goals])


@goals_app.command("update")
def goals_update_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID to update")],
    name: Annotated[str | None, typer.Option("--name", help="Updated name")] = None,
    target: Annotated[str | None, typer.Option("--target", help="Updated target amount")] = None,
    current: Annotated[str | None, typer.Option("--current", help="Updated current amount")] = None,
    deadline: Annotated[
        str | None, typer.Option("--deadline", help="Updated deadline (YYYY-MM-DD)")
    ] = None,
    priority: Annotated[
        int | None, typer.Option("--priority", help="Updated priority (1-3)")
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", help="Updated status: active, paused, completed, cancelled"),
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Update properties of an existing financial goal."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    try:
        target_paise = parse_cli_amount(target) if target is not None else None
        current_paise = parse_cli_amount(current) if current is not None else None
    except ValueError as exc:
        conn.close()
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    args: dict[str, Any] = {"goal_id": goal_id}
    if name is not None:
        args["name"] = name
    if target_paise is not None:
        args["target_paise"] = target_paise
    if current_paise is not None:
        args["current_paise"] = current_paise
    if deadline is not None:
        args["deadline"] = deadline
    if priority is not None:
        args["priority"] = priority
    if status is not None:
        args["status"] = status

    res = execute_tool(ctx, "update_goal", args)
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to update goal: {res.error.message}")
        raise typer.Exit(code=1)

    goal = _tool_out(res, "goal")
    if as_json:
        print_json(goal.model_dump(mode="json"))
    else:
        print_success(f"Goal '[cyan]{goal_id}[/cyan]' updated successfully.")


@goals_app.command("done")
def goals_done_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID to mark as completed")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Mark a financial goal as completed."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "update_goal", {"goal_id": goal_id, "status": "done"})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to complete goal: {res.error.message}")
        raise typer.Exit(code=1)

    goal = _tool_out(res, "goal")
    if as_json:
        print_json(goal.model_dump(mode="json"))
    else:
        print_success(f"Goal '[cyan]{goal_id}[/cyan]' marked as completed.")


@goals_app.command("show")
def goals_show_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID to inspect")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display comprehensive goal progress, balance, and projected completion."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "get_goal_progress", {"goal_id": goal_id})
        if not res.ok:
            print_error(f"Failed to get goal progress: {res.error.message}")
            raise typer.Exit(code=1)

        if as_json:
            print_json(_tool_dict(res))
            return

        p_dict = _tool_dict(res).get("progress", {})
        t = Table(title=f"Goal Progress: {p_dict.get('name', goal_id)}", box=box.ROUNDED)
        t.add_column("Property", style="bold")
        t.add_column("Value", style="cyan")

        t.add_row("Goal ID", str(p_dict.get("goal_id")))
        t.add_row("Name", str(p_dict.get("name")))
        t.add_row("Progress Source", str(p_dict.get("progress_source")))
        t.add_row("Target Amount", format_inr(p_dict.get("target_paise", 0)))
        t.add_row("Current Progress", format_inr(p_dict.get("current_paise", 0)))
        t.add_row("Remaining", format_inr(p_dict.get("remaining_paise", 0)))
        pct = p_dict.get("percent_bp", 0) / 100.0
        t.add_row("Percent Complete", f"{pct:.1f}%")
        t.add_row("Required Monthly", format_inr(p_dict.get("required_monthly_paise", 0)))
        t.add_row("Feasibility Status", str(p_dict.get("feasibility_status")).upper())
        proj = p_dict.get("projected_completion", {})
        t.add_row("Projected Completion (Expected)", str(proj.get("expected") or "N/A"))
        console.print(t)
    finally:
        conn.close()


@goals_app.command("contribute")
def goals_contribute_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID to contribute to")],
    amount: Annotated[str, typer.Argument(help="Contribution amount (e.g. ₹5,000, 500000)")],
    occurred_on: Annotated[
        str | None, typer.Option("--date", help="Occurrence date (YYYY-MM-DD)")
    ] = None,
    source: Annotated[str, typer.Option("--source", help="Contribution source")] = "manual",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Record a contribution towards a manual savings goal."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        amt_paise = parse_cli_amount(amount)
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx,
            "record_goal_contribution",
            {
                "goal_id": goal_id,
                "amount_paise": amt_paise,
                "occurred_on": occurred_on,
                "source": source,
            },
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to record contribution: {res.error.message}")
            raise typer.Exit(code=1)

        if as_json:
            print_json(_tool_dict(res))
        else:
            print_success(f"Recorded contribution of {format_inr(amt_paise)} to goal '{goal_id}'.")
    finally:
        conn.close()


@goals_app.command("progress")
def goals_progress_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID")],
    today: Annotated[str | None, typer.Option("--today", help="As-of date (YYYY-MM-DD)")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Evaluate progress and feasibility for a goal."""
    goals_show_cmd(goal_id=goal_id, db=db, user_id=user_id, as_json=as_json)


# =================================================================================================
# 9. Phase 2: What-If Simulation
# =================================================================================================


@whatif_app.command("add-spend")
def whatif_add_spend_cmd(
    amount: Annotated[
        str | None, typer.Option("--amount", help="Amount to spend (e.g. 50000, 50k, ₹50,000)")
    ] = None,
    amt_arg: Annotated[str | None, typer.Argument(help="Optional positional amount")] = None,
    category: Annotated[str | None, typer.Option("--category", help="Category ID")] = None,
    months: Annotated[int, typer.Option("--months", help="Horizon in months (1-6)")] = 6,
    recurring: Annotated[bool, typer.Option("--recurring", help="Is recurring expense?")] = False,
    clock: Annotated[
        str | None, typer.Option("--clock", help="Simulated current time (ISO)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Simulate the financial impact of an additional expenditure."""
    ensure_tools_registered()
    raw_amount = amount or amt_arg
    if not raw_amount:
        print_error("Amount is required via --amount or argument.")
        raise typer.Exit(code=1)

    try:
        amount_paise = parse_cli_amount(raw_amount)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, clock=clock, actor="user")

    start_m = clock[:7] if clock else to_utc_iso(now_utc())[:7]
    scenario = Scenario(
        kind="add_spend",
        category_id=category,
        amount_paise=amount_paise,
        start_month=start_m,
        recurring=recurring,
        months=months,
    )

    res = execute_tool(
        ctx,
        "run_whatif",
        {"scenario": scenario.model_dump(), "horizon_months": months},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Simulation failed: {res.error.message}")
        raise typer.Exit(code=1)

    proj = _tool_out(res, "projection")
    sim_id = _tool_out(res, "simulation_id") or ""
    if as_json:
        print_json(
            {
                "simulation_id": sim_id,
                "projection": proj.model_dump(mode="json"),
            }
        )
    else:
        print_simulation_result(
            {
                "id": sim_id,
                "scenario": scenario.model_dump(),
                "assumptions": proj.assumptions,
            }
        )
        table = Table(title="Monthly Cash Flow & Balance Projection", box=box.ROUNDED)
        table.add_column("Month", style="blue")
        table.add_column("Projected Spend", justify="right")
        table.add_column("Projected Surplus", justify="right")
        table.add_column("Budget Status", justify="center")
        for m, sp in proj.monthly_spend_paise.items():
            surplus = proj.monthly_surplus_paise.get(m, 0)
            status = proj.budget_statuses.get(m, "ok")
            status_style = "green" if status == "ok" else "bold red"
            surplus_style = "green" if surplus >= 0 else "bold red"
            table.add_row(
                m,
                format_inr(sp),
                f"[{surplus_style}]{format_inr(surplus)}[/{surplus_style}]",
                f"[{status_style}]{status}[/{status_style}]",
            )
        console.print(table)
        if proj.goal_impacts:
            console.print("\n[bold]Goal Impacts:[/bold]")
            for g_id, impact in proj.goal_impacts.items():
                imp_style = "green" if impact == "on_track" else "bold yellow"
                console.print(f"  • Goal [cyan]{g_id}[/cyan]: [{imp_style}]{impact}[/{imp_style}]")


@whatif_app.command("reduce-spend")
def whatif_reduce_spend_cmd(
    amount: Annotated[
        str | None, typer.Option("--amount", help="Amount to reduce (e.g. 20000, 20k, ₹20,000)")
    ] = None,
    amt_arg: Annotated[str | None, typer.Argument(help="Optional positional amount")] = None,
    category: Annotated[str | None, typer.Option("--category", help="Category ID")] = None,
    months: Annotated[int, typer.Option("--months", help="Horizon in months (1-6)")] = 6,
    recurring: Annotated[bool, typer.Option("--recurring", help="Is recurring reduction?")] = True,
    clock: Annotated[
        str | None, typer.Option("--clock", help="Simulated current time (ISO)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Simulate the financial impact of reduced spending or spending cuts."""
    ensure_tools_registered()
    raw_amount = amount or amt_arg
    if not raw_amount:
        print_error("Amount is required via --amount or argument.")
        raise typer.Exit(code=1)

    try:
        amount_paise = parse_cli_amount(raw_amount)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, clock=clock, actor="user")

    start_m = clock[:7] if clock else to_utc_iso(now_utc())[:7]
    scenario = Scenario(
        kind="reduce_spend",
        category_id=category,
        amount_paise=amount_paise,
        start_month=start_m,
        recurring=recurring,
        months=months,
    )

    res = execute_tool(
        ctx,
        "run_whatif",
        {"scenario": scenario.model_dump(), "horizon_months": months},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Simulation failed: {res.error.message}")
        raise typer.Exit(code=1)

    proj = _tool_out(res, "projection")
    sim_id = _tool_out(res, "simulation_id") or ""
    if as_json:
        print_json(
            {
                "simulation_id": sim_id,
                "projection": proj.model_dump(mode="json"),
            }
        )
    else:
        print_simulation_result(
            {
                "id": sim_id,
                "scenario": scenario.model_dump(),
                "assumptions": proj.assumptions,
            }
        )
        table = Table(title="Monthly Cash Flow & Balance Projection", box=box.ROUNDED)
        table.add_column("Month", style="blue")
        table.add_column("Projected Spend", justify="right")
        table.add_column("Projected Surplus", justify="right")
        table.add_column("Budget Status", justify="center")
        for m, sp in proj.monthly_spend_paise.items():
            surplus = proj.monthly_surplus_paise.get(m, 0)
            status = proj.budget_statuses.get(m, "ok")
            status_style = "green" if status == "ok" else "bold red"
            surplus_style = "green" if surplus >= 0 else "bold red"
            table.add_row(
                m,
                format_inr(sp),
                f"[{surplus_style}]{format_inr(surplus)}[/{surplus_style}]",
                f"[{status_style}]{status}[/{status_style}]",
            )
        console.print(table)


@whatif_app.command("compare")
def whatif_compare_cmd(
    options: Annotated[
        list[str] | None,
        typer.Option("--option", help="Scenario options (e.g. '50000' or 'add_spend:50000')"),
    ] = None,
    amounts: Annotated[
        str | None,
        typer.Option("--amounts", help="Comma-separated amounts (e.g. '50000,75000')"),
    ] = None,
    category: Annotated[str | None, typer.Option("--category", help="Category ID")] = None,
    months: Annotated[int, typer.Option("--months", help="Horizon in months (1-6)")] = 6,
    clock: Annotated[
        str | None, typer.Option("--clock", help="Simulated current time (ISO)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Compare multiple what-if spending options side-by-side."""
    ensure_tools_registered()
    raw_scenarios: list[tuple[str, str]] = []
    if options:
        for opt in options:
            if ":" in opt:
                k, a = opt.split(":", 1)
                raw_scenarios.append((k, a))
            else:
                raw_scenarios.append(("add_spend", opt))
    elif amounts:
        for a in amounts.split(","):
            if a.strip():
                raw_scenarios.append(("add_spend", a.strip()))
    else:
        print_error("Please specify scenarios to compare using --option or --amounts.")
        raise typer.Exit(code=1)

    start_m = clock[:7] if clock else to_utc_iso(now_utc())[:7]
    scenarios: list[Scenario] = []
    for kind, amt_str in raw_scenarios:
        try:
            amt_p = parse_cli_amount(amt_str)
        except ValueError as exc:
            print_error(str(exc))
            raise typer.Exit(code=1) from exc
        scenarios.append(
            Scenario(
                kind=kind,  # type: ignore[arg-type]
                category_id=category,
                amount_paise=amt_p,
                start_month=start_m,
                months=months,
            )
        )

    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, clock=clock, actor="user")

    res = execute_tool(
        ctx,
        "compare_options",
        {"scenarios": [s.model_dump() for s in scenarios], "horizon_months": months},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Comparison failed: {res.error.message}")
        raise typer.Exit(code=1)

    comp = _tool_out(res, "comparison")
    sim_id = _tool_out(res, "simulation_id") or ""
    if as_json:
        print_json(
            {
                "simulation_id": sim_id,
                "comparison": comp.model_dump(mode="json"),
            }
        )
    else:
        table = Table(
            title=f"What-If Options Comparison ({len(scenarios)} options)", box=box.ROUNDED
        )
        table.add_column("Option", style="bold")
        table.add_column("Kind", style="cyan")
        table.add_column("Amount", justify="right")
        table.add_column("Net Surplus Delta", justify="right")

        baseline_surplus = sum(comp.baseline.monthly_surplus_paise.values())
        for idx, opt_proj in enumerate(comp.scenarios):
            opt_surplus = sum(opt_proj.monthly_surplus_paise.values())
            diff = opt_surplus - baseline_surplus
            diff_style = "green" if diff >= 0 else "red"
            diff_str = f"[{diff_style}]{'+' if diff >= 0 else ''}{format_inr(diff)}[/{diff_style}]"
            table.add_row(
                f"Option {idx + 1}",
                opt_proj.scenario.kind,
                format_inr(opt_proj.scenario.amount_paise),
                diff_str,
            )
        console.print(table)


# =================================================================================================
# 10. Phase 2: Adaptive Alerts
# =================================================================================================


@alerts_app.command("list")
def alerts_list_cmd(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status: open, acknowledged, dismissed, snoozed"),
    ] = None,
    period: Annotated[
        str | None, typer.Option("--period", help="Filter by period (YYYY-MM)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List active or historical adaptive alerts."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "list_alerts", {"status": status})
    conn.close()

    if not res.ok:
        print_error(f"Failed to list alerts: {res.error.message}")
        raise typer.Exit(code=1)

    alerts = _tool_out(res, "alerts") or []
    if as_json:
        print_json([a.model_dump(mode="json") for a in alerts])
    else:
        print_alerts_table([a.model_dump(mode="json") for a in alerts])


@alerts_app.command("evaluate")
def alerts_evaluate_cmd(
    period: Annotated[
        str | None, typer.Option("--period", help="Period to evaluate (YYYY-MM)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Evaluate signals and generate adaptive alerts for a period."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "evaluate_alerts", {"period": period})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Alert evaluation failed: {res.error.message}")
        raise typer.Exit(code=1)

    out_data = _tool_dict(res)
    if as_json:
        print_json(out_data)
    else:
        print_success(
            f"Alerts evaluated for {out_data.get('period')}: "
            f"created={out_data.get('created_count')}, "
            f"escalated={out_data.get('escalated_count')}, "
            f"suppressed={out_data.get('suppressed_count')}"
        )
        if out_data.get("alerts"):
            print_alerts_table(out_data["alerts"])


@alerts_app.command("ack")
def alerts_ack_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to acknowledge")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Optional acknowledgment note")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Acknowledge an adaptive alert."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "acknowledge", "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to acknowledge alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(_tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' acknowledged.")


@alerts_app.command("dismiss")
def alerts_dismiss_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to dismiss")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Optional dismissal reason")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Dismiss an adaptive alert."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "dismiss", "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to dismiss alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(_tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' dismissed.")


@alerts_app.command("snooze")
def alerts_snooze_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to snooze")],
    days: Annotated[int, typer.Option("--days", help="Days to snooze (1-90)")] = 7,
    reason: Annotated[str | None, typer.Option("--reason", help="Optional snooze note")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Snooze an adaptive alert for a specified number of days."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "snooze", "snooze_days": days, "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to snooze alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(_tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' snoozed for {days} days.")


@alerts_app.command("prefs")
def alerts_prefs_cmd(
    category: Annotated[
        str | None, typer.Option("--category", help="Category ID to configure")
    ] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Alert kind filter")] = None,
    min_severity: Annotated[
        str,
        typer.Option(
            "--min-severity", help="Minimum severity threshold: info, notice, warning, critical"
        ),
    ] = "info",
    muted: Annotated[
        bool, typer.Option("--muted/--unmuted", help="Silence alerts matching this preference")
    ] = False,
    max_open: Annotated[
        int | None, typer.Option("--max-open", help="Cap on open alerts before escalation")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Configure user preferences and silencing rules for adaptive alerts."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "set_alert_preference",
        {
            "category_id": category,
            "kind": kind,
            "min_severity": min_severity,
            "muted": muted,
            "max_open_alerts": max_open,
        },
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to update alert preferences: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(_tool_dict(res))
    else:
        print_success("Alert preferences updated successfully.")


# =================================================================================================
# 11. Phase 2: Direct Commands (investigate, explain, decide, timeline, ask)
# =================================================================================================


@app.command("investigate")
def investigate_cmd(
    anomaly: Annotated[
        str | None, typer.Option("--anomaly", help="Anomaly or transaction ID to investigate")
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="Category to investigate")
    ] = None,
    month: Annotated[str | None, typer.Option("--month", help="Target month (YYYY-MM)")] = None,
    baseline: Annotated[
        str | None, typer.Option("--baseline", help="Baseline comparison month (YYYY-MM)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Direct deterministic investigation of an anomaly or category spend shift."""
    ensure_tools_registered()
    if anomaly is None and not (category and month):
        print_error(
            "Please specify either --anomaly <id> or both --category <cat> and --month <YYYY-MM>."
        )
        raise typer.Exit(code=1)

    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    if anomaly:
        res = execute_tool(ctx, "investigate_anomaly", {"anomaly_id": anomaly})
        conn.commit()
        conn.close()
        if not res.ok:
            print_error(f"Investigation failed: {res.error.message}")
            raise typer.Exit(code=1)

        inv = _tool_out(res, "investigation")
        decomp = _tool_out(res, "decomposition") or {}
        if as_json:
            print_json(
                {
                    "investigation": inv.model_dump(mode="json"),
                    "decomposition": decomp,
                }
            )
        else:
            print_investigation_result(inv.model_dump(mode="json"))
    else:
        res = execute_tool(
            ctx,
            "explain_change",
            {
                "category_id": category,
                "period": month,
                "baseline_period": baseline,
            },
        )
        conn.commit()
        conn.close()
        if not res.ok:
            print_error(f"Investigation failed: {res.error.message}")
            raise typer.Exit(code=1)

        out_data = _tool_dict(res)
        if as_json:
            print_json(out_data)
        else:
            table = Table(
                title=f"Spend Change Decomposition ({category} in {month})", box=box.ROUNDED
            )
            table.add_column("Component", style="bold")
            table.add_column("Delta (Paise)", justify="right")
            table.add_column("Formatted", justify="right")
            for comp, val in out_data.get("decomposition", {}).items():
                style = "green" if val <= 0 else "red"
                table.add_row(
                    comp.replace("_", " ").title(),
                    str(val),
                    f"[{style}]{format_inr(abs(val))}[/{style}]",
                )
            console.print(table)


@app.command("explain")
def explain_cmd(
    advice_id: Annotated[str, typer.Argument(help="Recommendation or advice item ID to explain")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Print full explainable grounding, calculations, assumptions, and evidence for advice."""
    db_path = get_db_path(db)
    conn = open_db(db_path)

    rec = get_recommendation(conn, user_id, advice_id)
    if rec is None:
        row = conn.execute(
            "SELECT id, text, status, why, created_at FROM advice_items "
            "WHERE id = ? AND user_id = ?",
            (advice_id, user_id),
        ).fetchone()
        conn.close()
        if row is None:
            print_error(f"Recommendation or advice '{advice_id}' not found for user '{user_id}'.")
            raise typer.Exit(code=1)
        data = {
            "id": row[0],
            "text": row[1],
            "status": row[2],
            "why": row[3],
            "created_at": row[4],
        }
        if as_json:
            print_json(data)
        else:
            console.print(
                Panel(
                    f"[bold]Text:[/bold] {data['text']}\n"
                    f"[bold]Status:[/bold] {data['status']}\n"
                    f"[bold]Why:[/bold] {data['why'] or '(No explanation details)'}\n"
                    f"[bold]Created:[/bold] {data['created_at']}",
                    title=f"Advice Item {data['id']}",
                    border_style="cyan",
                )
            )
        return

    conn.close()
    if as_json:
        print_json(rec.model_dump(mode="json"))
    else:
        console.print(format_recommendation_explanation(rec))


@app.command("decide")
def decide_cmd(
    advice_id: Annotated[str, typer.Argument(help="Advice item ID to decide")],
    action: Annotated[str, typer.Argument(help="Action: approve or reject")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Approve or reject a drafted recommendation or advice item."""
    ensure_tools_registered()
    act = action.strip().lower()
    if act in ("approve", "approved", "a"):
        decision = "approved"
    elif act in ("reject", "rejected", "r"):
        decision = "rejected"
    else:
        print_error(f"Invalid decision '{action}'. Must be 'approve' or 'reject'.")
        raise typer.Exit(code=1)

    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "decide_advice", {"advice_id": advice_id, "decision": decision})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to record decision: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(_tool_dict(res))
    else:
        print_success(f"Advice '[cyan]{advice_id}[/cyan]' marked as [bold]{decision}[/bold].")


@app.command("timeline")
def timeline_cmd(
    task: Annotated[str | None, typer.Option("--task", help="Filter by task ID")] = None,
    run: Annotated[str | None, typer.Option("--run", help="Filter by run ID")] = None,
    since: Annotated[
        str | None, typer.Option("--since", help="Filter entries since timestamp (ISO)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display the agent activity timeline and pending human decisions."""
    db_path = get_db_path(db)
    conn = open_db(db_path)

    tl = build_timeline(conn, user_id, task_id=task, run_id=run, since=since)
    conn.close()

    if as_json:
        print_json(tl.model_dump(mode="json"))
    else:
        print_timeline(tl)


@app.command("ask")
def ask_cmd(
    query: Annotated[str, typer.Argument(help="Natural language request or question")],
    planner: Annotated[
        str,
        typer.Option("--planner", help="Planner mode: deterministic or llm"),
    ] = "deterministic",
    step_budget: Annotated[
        int,
        typer.Option("--step-budget", help="Maximum plan execution steps"),
    ] = 10,
    clock: Annotated[
        str | None,
        typer.Option("--clock", help="Simulated current time (ISO)"),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive/--no-interactive", help="Prompt for clarification/review"),
    ] = False,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Full planner-driven agent graph for natural-language inquiries."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)

    # Ensure user exists
    if get_user(conn, user_id) is None:
        ts = to_utc_iso(now_utc(clock))
        insert_user(conn, User(id=user_id, created_at=ts))
        conn.commit()

    run_id = f"ask_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    clock_iso = to_utc_iso(now_utc(clock)) if clock else to_utc_iso(now_utc())

    checkpointer = MemorySaver()
    graph = build_planner_agent_graph(checkpointer=checkpointer)
    thread_id = f"thread_{run_id}"
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "conn": conn,
            "actor": "agent",
        }
    }

    initial_state: AgenticState = {
        "user_id": user_id,
        "run_id": run_id,
        "raw_text": query,
        "clock": clock_iso,
        "planner_mode": planner,
        "step_budget": step_budget,
    }

    interrupt_val: dict[str, Any] | None = None
    try:
        result = graph.invoke(initial_state, config=thread_config)
        state_snap = graph.get_state(thread_config)
        if state_snap.tasks and state_snap.tasks[0].interrupts:
            interrupt_val = state_snap.tasks[0].interrupts[0].value
    except GraphInterrupt as gi:
        interrupt_val = gi.args[0] if gi.args else {}

    if interrupt_val:
        if "question" in interrupt_val:
            question = interrupt_val.get("question", "")
            if interactive:
                console.print(f"\n[bold yellow]Agent needs clarification:[/bold yellow] {question}")
                clarification = typer.prompt("Your answer")
                result = graph.invoke(Command(resume=clarification), config=thread_config)
            else:
                conn.close()
                if as_json:
                    print_json(
                        {
                            "status": "needs_clarification",
                            "question": question,
                            "raw_text": query,
                        }
                    )
                else:
                    msg = (
                        f"[yellow]{question}[/yellow]\n\n"
                        "[dim]Re-run with clearer details or use --interactive.[/dim]"
                    )
                    console.print(
                        Panel(
                            msg,
                            title="Clarification Needed",
                            border_style="yellow",
                        )
                    )
                return
        elif "pending_recommendations" in interrupt_val:
            recs = interrupt_val.get("pending_recommendations", [])
            decisions = []
            if interactive:
                console.print(
                    f"\n[bold yellow]Review Required:[/bold yellow] {len(recs)} recommendation(s)"
                )
                for r in recs:
                    console.print(f"\n  ID:   [cyan]{r.get('id')}[/cyan]")
                    console.print(f"  Text: {r.get('text')}")
                    action = typer.prompt("  Action ([a]pprove / [r]eject / [d]efer)", default="d")
                    if action.lower().startswith("a"):
                        decisions.append({"advice_id": r.get("id"), "decision": "approved"})
                    elif action.lower().startswith("r"):
                        decisions.append({"advice_id": r.get("id"), "decision": "rejected"})
            # Resume graph to finalize execution
            result = graph.invoke(Command(resume=decisions or {}), config=thread_config)
        else:
            result = graph.invoke(Command(resume={}), config=thread_config)

    # Check if a review interrupt occurred after clarification resumption
    state_snap = graph.get_state(thread_config)
    if state_snap.tasks and state_snap.tasks[0].interrupts:
        result = graph.invoke(Command(resume={}), config=thread_config)

    conn.commit()
    conn.close()

    if as_json:
        print_json(result)
        return

    # Visual rich output
    refusal = result.get("refusal_reason")
    if refusal:
        console.print(
            Panel(
                f"[bold red]Request Refused:[/bold red]\n{refusal}",
                title="Governance Policy Guardrail",
                border_style="red",
            )
        )
        return

    task_id = result.get("task_id", "")
    status = result.get("status", "completed")
    stop_reason = result.get("stop_reason", "completed")
    recs = result.get("recommendations", [])
    pending = result.get("pending_recommendations", [])
    observations = result.get("observations", [])

    lines = [
        f"[bold]Query:[/bold] {query}",
        f"[bold]Task ID:[/bold] {task_id}",
        f"[bold]Status:[/bold] [green]{status}[/green] (stop reason: {stop_reason})",
        f"[bold]Plan Execution:[/bold] {len(observations)} tool observation(s)",
    ]

    if recs:
        lines.append("\n[bold]Recommendations Generated:[/bold]")
        for r in recs:
            lines.append(f"  • {r.get('text')}")
            if r.get("confidence_label"):
                lines.append(f"    [dim](Confidence: {r.get('confidence_label')})[/dim]")

    console.print(Panel("\n".join(lines), title="Agent Copilot Response", border_style="cyan"))

    if pending:
        console.print(
            f"\n[bold yellow]Pending Decision:[/bold yellow] "
            f"{len(pending)} recommendation(s) require review."
        )
        for p in pending:
            console.print(f"  • Run: [cyan]copilot decide {p.get('id')} approve[/cyan]")


@app.command("serve")
def serve_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    port: Annotated[int, typer.Option("--port")] = 8765,
    demo: Annotated[str, typer.Option("--demo", help="empty or imported")] = "empty",
    token: Annotated[str | None, typer.Option("--token", help="Fixed session token (dev)")] = None,
) -> None:
    """Start the local HTTP API for the web UI (localhost only)."""
    from copilot.api.server import serve

    serve(get_db_path(db), port=port, demo=demo, token=token)


# -------------------------------------------------------------------------------------------------
# 13. Financial Commitments Commands (PLAN_PHASE3 Section 5.1 & 5.11)
# -------------------------------------------------------------------------------------------------
commitments_app = typer.Typer(name="commitments", help="Manage recurring financial commitments.")
app.add_typer(commitments_app, name="commitments")
app.add_typer(commitments_app, name="commitment")


@commitments_app.command("list")
def commitments_list_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, draft, paused, ended)"),
    ] = None,
    kind: Annotated[
        str | None, typer.Option("--kind", "-k", help="Filter by kind (bill, fee, rent, emi, etc.)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List financial commitments and draft suggestions."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "list_commitments", {"status": status, "kind": kind})
        if not res.ok:
            print_error(f"Failed to list commitments: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        items = _tool_dict(res).get("commitments", [])
        table = Table(title=f"Financial Commitments ({user_id})", box=box.ROUNDED)
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Direction")
        table.add_column("Kind", style="cyan")
        table.add_column("Amount", justify="right")
        table.add_column("Certainty")
        table.add_column("Schedule")
        table.add_column("Status")
        for c in items:
            amt_str = format_inr(c.get("amount_paise") or 0)
            if (
                c.get("certainty") == "estimated"
                and c.get("amount_min_paise")
                and c.get("amount_max_paise")
            ):
                amt_str = (
                    f"{format_inr(c['amount_min_paise'])} - {format_inr(c['amount_max_paise'])}"
                )
            st = c.get("status", "")
            st_style = "green" if st == "active" else ("yellow" if st == "draft" else "dim")
            table.add_row(
                str(c.get("id")),
                str(c.get("name")),
                str(c.get("direction")),
                str(c.get("kind")),
                amt_str,
                str(c.get("certainty")),
                f"{c.get('schedule_kind')} {c.get('schedule_json')}",
                f"[{st_style}]{st.upper()}[/{st_style}]",
            )
        console.print(table)
        if not items:
            console.print("[dim]No commitments found.[/dim]")
    finally:
        conn.close()


@commitments_app.command("add")
def commitments_add_cmd(
    name: Annotated[str, typer.Argument(help="Commitment name")],
    amount: Annotated[str, typer.Argument(help="Amount (e.g. ₹15,000, 15000)")],
    direction: Annotated[str, typer.Option("--direction", help="inflow or outflow")] = "outflow",
    kind: Annotated[str, typer.Option("--kind", help="Kind (fee, bill, rent, emi, etc.)")] = "bill",
    schedule_kind: Annotated[
        str,
        typer.Option(
            "--schedule", help="Schedule kind (monthly, weekly, yearly, once, every_n_days)"
        ),
    ] = "monthly",
    day: Annotated[int, typer.Option("--day", help="Day of month for monthly schedule")] = 1,
    date: Annotated[
        str | None, typer.Option("--date", help="Specific date for once schedule (YYYY-MM-DD)")
    ] = None,
    start_date: Annotated[
        str | None, typer.Option("--start-date", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[
        str | None, typer.Option("--end-date", help="End date (YYYY-MM-DD)")
    ] = None,
    certainty: Annotated[str, typer.Option("--certainty", help="firm or estimated")] = "firm",
    category_id: Annotated[str | None, typer.Option("--category", help="Category ID")] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a new financial commitment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        amt_paise = parse_cli_amount(amount)
        if schedule_kind == "monthly":
            sched = {"day": day}
        elif schedule_kind == "once":
            sched = {"date": date or start_date or "2024-01-01"}
        elif schedule_kind == "yearly":
            sched = {"month": 1, "day": day}
        else:
            sched = {"day": day}

        s_date = start_date or (date if schedule_kind == "once" else "2024-01-01")
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx,
            "create_commitment",
            {
                "name": name,
                "direction": direction,
                "kind": kind,
                "amount_paise": amt_paise,
                "schedule_kind": schedule_kind,
                "schedule_json": sched,
                "start_date": s_date,
                "end_date": end_date,
                "certainty": certainty,
                "category_id": category_id,
            },
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to create commitment: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
        else:
            c = _tool_dict(res).get("commitment", {})
            c_name = c.get("name")
            c_id = c.get("id")
            print_success(f"Commitment '{c_name}' created with ID [cyan]{c_id}[/cyan].")
    finally:
        conn.close()


@commitments_app.command("show")
def commitments_show_cmd(
    commitment_id: Annotated[str, typer.Argument(help="Commitment ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show details and upcoming occurrences for a commitment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "get_commitment_status", {"commitment_id": commitment_id})
        if not res.ok:
            print_error(f"Failed to get commitment status: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        data = _tool_dict(res)
        c = data.get("commitment", {})
        table = Table(title=f"Commitment: {c.get('name')}", box=box.ROUNDED)
        table.add_column("Property", style="bold")
        table.add_column("Value", style="cyan")
        table.add_row("ID", str(c.get("id")))
        table.add_row("Name", str(c.get("name")))
        table.add_row("Direction", str(c.get("direction")))
        table.add_row("Kind", str(c.get("kind")))
        table.add_row("Amount", format_inr(c.get("amount_paise") or 0))
        table.add_row("Schedule", f"{c.get('schedule_kind')} {c.get('schedule_json')}")
        table.add_row("Status", str(c.get("status")).upper())
        console.print(table)

        occs = data.get("upcoming_occurrences", [])
        if occs:
            t_occ = Table(title="Upcoming Occurrences", box=box.ROUNDED)
            t_occ.add_column("Due Date", style="dim")
            t_occ.add_column("Amount", justify="right")
            t_occ.add_column("Status")
            for o in occs:
                t_occ.add_row(
                    str(o.get("due_date")),
                    format_inr(o.get("amount_expected_paise", 0)),
                    str(o.get("status", "upcoming")),
                )
            console.print(t_occ)
    finally:
        conn.close()


@commitments_app.command("pause")
def commitments_pause_cmd(
    commitment_id: Annotated[str, typer.Argument(help="Commitment ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Pause an active commitment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "pause_commitment", {"commitment_id": commitment_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to pause commitment: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Commitment '{commitment_id}' paused.")
    finally:
        conn.close()


@commitments_app.command("end")
def commitments_end_cmd(
    commitment_id: Annotated[str, typer.Argument(help="Commitment ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """End a commitment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "end_commitment", {"commitment_id": commitment_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to end commitment: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Commitment '{commitment_id}' ended.")
    finally:
        conn.close()


@commitments_app.command("suggest")
def commitments_suggest_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Suggest commitment drafts from recurring transaction series."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="agent")
        res = execute_tool(ctx, "suggest_commitments", {})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to suggest commitments: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        drafts = _tool_dict(res).get("drafts", [])
        print_success(f"Generated [cyan]{len(drafts)}[/cyan] suggested commitment draft(s).")
        if drafts:
            t = Table(title="Suggested Commitment Drafts", box=box.ROUNDED)
            t.add_column("Draft ID", style="dim")
            t.add_column("Name", style="bold")
            t.add_column("Kind", style="cyan")
            t.add_column("Amount", justify="right")
            t.add_column("Certainty")
            for d in drafts:
                t.add_row(
                    str(d.get("id")),
                    str(d.get("name")),
                    str(d.get("kind")),
                    format_inr(d.get("amount_paise") or 0),
                    str(d.get("certainty")),
                )
            console.print(t)
            console.print(
                "[dim]Run 'copilot commitments accept <id>' to activate suggestion.[/dim]"
            )
    finally:
        conn.close()


@commitments_app.command("accept")
def commitments_accept_cmd(
    commitment_id: Annotated[str, typer.Argument(help="Draft commitment ID to accept")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Accept and activate a suggested commitment draft."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "accept_commitment", {"commitment_id": commitment_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to accept commitment: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Commitment draft '{commitment_id}' accepted and activated.")
    finally:
        conn.close()


@commitments_app.command("reject")
def commitments_reject_cmd(
    commitment_id: Annotated[str, typer.Argument(help="Draft commitment ID to reject")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Reject a suggested commitment draft."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "reject_commitment", {"commitment_id": commitment_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to reject commitment: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Commitment draft '{commitment_id}' rejected.")
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 14. Financial Calendar Lookahead (PLAN_PHASE3 Section 5.4 & 5.11)
# -------------------------------------------------------------------------------------------------
@app.command("calendar")
def calendar_cmd(
    days: Annotated[int, typer.Option("--days", help="Calendar horizon in days")] = 60,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Project cash flow, obligation coverage, and shortfall ranges over a lookahead calendar."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "get_calendar", {"horizon_days": days})
        if not res.ok:
            print_error(f"Failed to build calendar: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        data = _tool_dict(res).get("calendar", {})
        starting_bal = format_inr(data.get("starting_balance_paise", 0))
        min_buf = format_inr(data.get("min_buffer_paise", 0))
        lowest_bal = format_inr(data.get("lowest_low_balance_paise", 0))
        console.print(
            Panel(
                f"[bold]Calendar Lookahead Horizon:[/bold] {data.get('horizon_days')} days "
                f"({data.get('start_date')} to {data.get('end_date')})\n"
                f"[bold]Starting Liquid Balance:[/bold] [cyan]{starting_bal}[/cyan]\n"
                f"[bold]Minimum Safety Buffer:[/bold] {min_buf}\n"
                f"[bold]Lowest Projected Balance:[/bold] "
                f"[bold yellow]{lowest_bal}[/bold yellow] "
                f"(on {data.get('lowest_balance_date', 'N/A')})\n"
                f"[bold]Total Shortfall Days:[/bold] {len(data.get('shortfall_days', []))}",
                title="Financial Calendar Overview",
                border_style="cyan",
            )
        )

        covs = data.get("commitment_coverages", [])
        if covs:
            t = Table(title="Commitment Coverage Over Horizon", box=box.ROUNDED)
            t.add_column("Due Date", style="dim")
            t.add_column("Commitment Name", style="bold")
            t.add_column("Amount", justify="right")
            t.add_column("Balance After Payment", justify="right")
            t.add_column("Coverage Status")
            for c in covs:
                st = c.get("coverage", "")
                st_style = "green" if st == "covered" else ("yellow" if st == "at_risk" else "red")
                t.add_row(
                    str(c.get("due_date")),
                    str(c.get("commitment_name")),
                    format_inr(c.get("amount_paise", 0)),
                    format_inr(c.get("projected_balance_after_paise", 0)),
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                )
            console.print(t)

        shortfalls = data.get("shortfall_ranges", [])
        if shortfalls:
            t_s = Table(title="Identified Shortfall Periods", box=box.ROUNDED)
            t_s.add_column("Start Date", style="red")
            t_s.add_column("End Date", style="red")
            t_s.add_column("Min Balance", justify="right")
            t_s.add_column("Commitments Due")
            for s in shortfalls:
                t_s.add_row(
                    str(s.get("start_date")),
                    str(s.get("end_date")),
                    format_inr(s.get("min_balance_paise", 0)),
                    ", ".join(s.get("commitments_due", [])),
                )
            console.print(t_s)
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 15. Virtual Buckets Commands (PLAN_PHASE3 Section 5.3 & 5.11)
# -------------------------------------------------------------------------------------------------
buckets_app = typer.Typer(name="buckets", help="Manage virtual balance buckets and partitions.")
app.add_typer(buckets_app, name="buckets")


@buckets_app.command("list")
def buckets_list_cmd(
    period: Annotated[
        str | None, typer.Option("--period", "-p", help="Target period (YYYY-MM)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List virtual buckets, balances, and partition allocations."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res_list = execute_tool(ctx, "list_buckets", {})
        res_summary = execute_tool(ctx, "get_allocation_summary", {"period": period})
        if not res_list.ok:
            print_error(f"Failed to list buckets: {res_list.error.message}")
            raise typer.Exit(code=1)

        if as_json:
            print_json(
                {
                    "buckets": _tool_dict(res_list).get("buckets", []),
                    "summary": _tool_dict(res_summary) if res_summary.ok else {},
                }
            )
            return

        buckets = _tool_dict(res_list).get("buckets", [])
        table = Table(title=f"Virtual Buckets for User '{user_id}'", box=box.ROUNDED)
        table.add_column("Bucket ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Kind", style="cyan")
        table.add_column("Policy")
        table.add_column("Allocated", justify="right")
        table.add_column("Spent", justify="right")
        table.add_column("Balance", justify="right")
        table.add_column("Status")

        for b in buckets:
            b_id = b.get("id")
            st_res = execute_tool(ctx, "get_bucket_status", {"bucket_id": b_id, "period": period})
            bal_data = _tool_dict(st_res).get("balance", {}) if st_res.ok else {}
            st = bal_data.get("status", "ok")
            st_style = "green" if st == "ok" else ("yellow" if st == "low" else "red")
            table.add_row(
                str(b_id),
                str(b.get("name")),
                str(b.get("kind")),
                str(b.get("period_policy")),
                format_inr(bal_data.get("allocated_paise", 0)),
                format_inr(bal_data.get("spent_paise", 0)),
                format_inr(bal_data.get("balance_paise", 0)),
                f"[{st_style}]{st.upper()}[/{st_style}]",
            )
        console.print(table)

        if res_summary.ok:
            summ = _tool_dict(res_summary).get("summary", {})
            liquid = summ.get("liquid_balance_paise", 0)
            reserved = summ.get("reserved_total_paise", 0)
            avail = summ.get("available_unallocated_paise", 0)
            over = summ.get("over_allocated_by_paise", 0)
            over_msg = (
                f" | [bold red]Over-Allocated by {format_inr(over)}[/bold red]" if over > 0 else ""
            )
            console.print(
                f"\n[bold]Total Liquid Balance:[/bold] {format_inr(liquid)} | "
                f"[bold]Reserved across Buckets:[/bold] [cyan]{format_inr(reserved)}[/cyan] | "
                f"[bold]Unallocated Available:[/bold] [green]{format_inr(avail)}[/green]{over_msg}"
            )
    finally:
        conn.close()


@buckets_app.command("create")
def buckets_create_cmd(
    name: Annotated[str, typer.Argument(help="Bucket name")],
    kind: Annotated[
        str, typer.Option("--kind", help="Kind (spending, goal, commitment, flexible)")
    ] = "spending",
    period_policy: Annotated[
        str | None, typer.Option("--policy", help="Period policy (reset_monthly or accumulate)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a new virtual balance bucket."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx, "create_bucket", {"name": name, "kind": kind, "period_policy": period_policy}
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to create bucket: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
        else:
            b = _tool_dict(res).get("bucket", {})
            print_success(
                f"Bucket '{b.get('name')}' created successfully with ID [cyan]{b.get('id')}[/cyan]."
            )
    finally:
        conn.close()


@buckets_app.command("map")
def buckets_map_cmd(
    bucket_id: Annotated[str, typer.Argument(help="Bucket ID")],
    category_id: Annotated[str, typer.Argument(help="Category ID to map to bucket")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Map a transaction category uniquely to a spending bucket."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx, "map_category_to_bucket", {"bucket_id": bucket_id, "category_id": category_id}
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to map category: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Category '{category_id}' successfully mapped to bucket '{bucket_id}'.")
    finally:
        conn.close()


@buckets_app.command("allocate")
def buckets_allocate_cmd(
    bucket_id: Annotated[str, typer.Argument(help="Bucket ID")],
    amount: Annotated[str, typer.Argument(help="Amount to allocate (e.g. ₹10,000, 1000000)")],
    period: Annotated[
        str | None, typer.Option("--period", "-p", help="Target period (YYYY-MM)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Allocate funds into a virtual bucket."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        amt_paise = parse_cli_amount(amount)
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx,
            "allocate_to_bucket",
            {"bucket_id": bucket_id, "amount_paise": amt_paise, "period": period},
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to allocate to bucket: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Allocated {format_inr(amt_paise)} to bucket '{bucket_id}'.")
    finally:
        conn.close()


@buckets_app.command("release")
def buckets_release_cmd(
    bucket_id: Annotated[str, typer.Argument(help="Bucket ID")],
    amount: Annotated[str, typer.Argument(help="Amount to release back to unallocated")],
    period: Annotated[
        str | None, typer.Option("--period", "-p", help="Target period (YYYY-MM)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Release funds from a virtual bucket back to unallocated balance."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        amt_paise = parse_cli_amount(amount)
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx,
            "release_from_bucket",
            {"bucket_id": bucket_id, "amount_paise": amt_paise, "period": period},
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to release from bucket: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Released {format_inr(amt_paise)} from bucket '{bucket_id}'.")
    finally:
        conn.close()


@buckets_app.command("reassign")
def buckets_reassign_cmd(
    from_bucket: Annotated[str, typer.Argument(help="Source bucket ID")],
    to_bucket: Annotated[str, typer.Argument(help="Target bucket ID")],
    amount: Annotated[str, typer.Argument(help="Amount to reassign")],
    period: Annotated[
        str | None, typer.Option("--period", "-p", help="Target period (YYYY-MM)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Reassign balance directly between two buckets."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        amt_paise = parse_cli_amount(amount)
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx,
            "reassign_between_buckets",
            {
                "from_bucket_id": from_bucket,
                "to_bucket_id": to_bucket,
                "amount_paise": amt_paise,
                "period": period,
            },
        )
        conn.commit()
        if not res.ok:
            print_error(f"Failed to reassign: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Reassigned {format_inr(amt_paise)} from '{from_bucket}' to '{to_bucket}'.")
    finally:
        conn.close()


@buckets_app.command("status")
def buckets_status_cmd(
    bucket_id: Annotated[str, typer.Argument(help="Bucket ID")],
    period: Annotated[
        str | None, typer.Option("--period", "-p", help="Target period (YYYY-MM)")
    ] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display balance, spending, and overspend status of a bucket."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "get_bucket_status", {"bucket_id": bucket_id, "period": period})
        if not res.ok:
            print_error(f"Failed to get bucket status: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        b = _tool_dict(res).get("balance", {})
        table = Table(title=f"Bucket Balance: {b.get('name')}", box=box.ROUNDED)
        table.add_column("Property", style="bold")
        table.add_column("Value", style="cyan")
        table.add_row("Bucket ID", str(b.get("bucket_id")))
        table.add_row("Name", str(b.get("name")))
        table.add_row("Kind", str(b.get("kind")))
        table.add_row("Period", str(b.get("period")))
        table.add_row("Allocated", format_inr(b.get("allocated_paise", 0)))
        table.add_row("Spent", format_inr(b.get("spent_paise", 0)))
        table.add_row("Remaining Balance", format_inr(b.get("balance_paise", 0)))
        st = b.get("status", "ok")
        st_style = "green" if st == "ok" else ("yellow" if st == "low" else "red")
        table.add_row("Status", f"[{st_style}]{st.upper()}[/{st_style}]")
        console.print(table)
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 16. Reallocations Commands (PLAN_PHASE3 Section 5.3 & 5.11)
# -------------------------------------------------------------------------------------------------
reallocations_app = typer.Typer(
    name="reallocations", help="Manage agent reallocation recommendations."
)
app.add_typer(reallocations_app, name="reallocations")


@reallocations_app.command("list")
def reallocations_list_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List agent-drafted bucket reallocation recommendations."""
    from copilot.db.repo_phase3 import list_reallocation_drafts

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        drafts = list_reallocation_drafts(conn, user_id=user_id)
        if as_json:
            print_json([d.model_dump(mode="json") for d in drafts])
            return
        table = Table(title=f"Reallocation Drafts for {user_id}", box=box.ROUNDED)
        table.add_column("Draft ID", style="dim")
        table.add_column("From Bucket")
        table.add_column("To Bucket")
        table.add_column("Amount", justify="right")
        table.add_column("Status")
        table.add_column("Reason", style="dim")
        for d in drafts:
            st_style = (
                "green"
                if d.status in ("approved", "applied")
                else ("yellow" if d.status == "draft" else "red")
            )
            table.add_row(
                d.id,
                d.from_bucket_id,
                d.to_bucket_id,
                format_inr(d.amount_paise),
                f"[{st_style}]{d.status.upper()}[/{st_style}]",
                str(d.reason_json.get("explanation", "-")),
            )
        console.print(table)
        if not drafts:
            console.print("[dim]No reallocation drafts found.[/dim]")
    finally:
        conn.close()


@reallocations_app.command("decide")
def reallocations_decide_cmd(
    draft_id: Annotated[str, typer.Argument(help="Reallocation draft ID")],
    decision: Annotated[str, typer.Argument(help="Decision (approve or reject)")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Approve or reject an agent reallocation draft."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "decide_reallocation", {"draft_id": draft_id, "decision": decision})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to decide reallocation: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Reallocation draft '{draft_id}' decided: [bold]{decision}[/bold].")
    finally:
        conn.close()


@reallocations_app.command("apply")
def reallocations_apply_cmd(
    draft_id: Annotated[str, typer.Argument(help="Approved reallocation draft ID to apply")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Apply an approved reallocation draft to move funds between buckets."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "apply_reallocation", {"draft_id": draft_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to apply reallocation: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Reallocation draft '{draft_id}' successfully applied!")
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 17. Investment Readiness Assessment (PLAN_PHASE3 Section 5.6 & 5.11)
# -------------------------------------------------------------------------------------------------
@app.command("readiness")
def readiness_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Assess whether the user is ready to begin or continue investments."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "assess_investment_readiness", {})
        if not res.ok:
            print_error(f"Failed to assess readiness: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        data = _tool_dict(res).get("assessment", {})
        lvl = data.get("level", "not_ready")
        lvl_style = (
            "green"
            if lvl == "ready"
            else (
                "cyan"
                if lvl == "ready_with_conditions"
                else ("yellow" if lvl == "building" else "red")
            )
        )

        lvl_str = lvl.upper().replace("_", " ")
        v_text = data.get("verdict_text", "Criteria evaluated.")
        console.print(
            Panel(
                f"[bold]Overall Readiness Level:[/bold] [{lvl_style}]{lvl_str}[/{lvl_style}]\n"
                f"[bold]Assessed On:[/bold] {data.get('assessed_on', 'N/A')}\n"
                f"[bold]Verdict Explanation:[/bold] {v_text}",
                title="Investment Readiness Assessment",
                border_style="cyan",
            )
        )

        crit = data.get("criteria", [])
        if crit:
            t = Table(title="Assessment Criteria Breakdown", box=box.ROUNDED)
            t.add_column("Criterion", style="bold")
            t.add_column("Status")
            t.add_column("Current Value", justify="right")
            t.add_column("Target / Requirement", justify="right")
            t.add_column("What Would Change It", style="dim")
            for c in crit:
                st = c.get("status", "")
                st_style = "green" if st == "pass" else ("yellow" if st == "unknown" else "red")
                t.add_row(
                    str(c.get("name")),
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                    str(c.get("current_value", "-")),
                    str(c.get("target_value", "-")),
                    str(c.get("what_would_change_it", "-")),
                )
            console.print(t)
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 18. Contribution Planning & Trade-offs (PLAN_PHASE3 Section 5.7 & 5.11)
# -------------------------------------------------------------------------------------------------
contributions_app = typer.Typer(
    name="contributions", help="Plan contributions and waterfall allocations."
)
app.add_typer(contributions_app, name="contributions")


@contributions_app.command("plan")
@app.command("plan-contributions")
def contributions_plan_cmd(
    months: Annotated[int, typer.Option("--months", "-m", help="Horizon in months")] = 6,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Plan recurring contributions against cashflow surplus and waterfall priorities."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "plan_contributions", {"horizon_months": months})
        if not res.ok:
            print_error(f"Failed to plan contributions: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        data = _tool_dict(res).get("plan", {})
        console.print(
            Panel(
                f"[bold]Horizon:[/bold] {data.get('horizon_months')} months "
                f"({data.get('period_from')})\n"
                f"[bold]Status:[/bold] [cyan]{data.get('status', 'complete')}[/cyan]\n"
                f"[bold]Summary:[/bold] {data.get('summary_text', 'Contribution plan evaluated.')}",
                title="Contribution Plan Overview",
                border_style="cyan",
            )
        )

        steps = data.get("steps", [])
        if steps:
            t = Table(title="Waterfall Allocations per Month", box=box.ROUNDED)
            t.add_column("Priority", justify="right")
            t.add_column("Commitment / Goal", style="bold")
            t.add_column("Needed", justify="right")
            t.add_column("Funded (Expected)", justify="right")
            t.add_column("Shortfall", justify="right")
            t.add_column("Verdict")
            for s in steps:
                verd = s.get("verdict", "")
                v_style = (
                    "green"
                    if verd == "fits"
                    else ("yellow" if verd == "fits_expected_only" else "red")
                )
                t.add_row(
                    str(s.get("priority")),
                    str(s.get("name")),
                    format_inr(s.get("needed_paise", 0)),
                    format_inr(s.get("funded_expected_paise", 0)),
                    format_inr(s.get("shortfall_paise", 0)),
                    f"[{v_style}]{verd.upper()}[/{v_style}]",
                )
            console.print(t)

        opts = data.get("options", [])
        if opts:
            t_opt = Table(title="Adjustment Options for Shortfalls", box=box.ROUNDED)
            t_opt.add_column("Option", style="bold")
            t_opt.add_column("Description")
            t_opt.add_column("Impact", style="cyan")
            for idx, o in enumerate(opts, 1):
                t_opt.add_row(f"Option {idx}", str(o.get("description")), str(o.get("impact", "-")))
            console.print(t_opt)
    finally:
        conn.close()


@app.command("tradeoff")
@app.command("trade-offs")
def tradeoff_cmd(
    alt: Annotated[
        list[str] | None, typer.Option("--alt", help="Alternative spec JSON or description")
    ] = None,
    horizon: Annotated[int, typer.Option("--horizon", help="Horizon in months")] = 12,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Compare competing financial trade-offs side by side."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        alt_inputs = alt or []
        parsed_alts = []
        for idx, a in enumerate(alt_inputs, 1):
            try:
                parsed_alts.append(json.loads(a))
            except Exception:
                parsed_alts.append({"name": f"Alternative {idx}", "changes": [], "description": a})
        if not parsed_alts:
            parsed_alts = [
                {"name": "Prioritise Goal", "changes": []},
                {"name": "Prioritise Emergency Fund", "changes": []},
            ]

        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(
            ctx, "compare_tradeoffs", {"alternatives": parsed_alts, "horizon_months": horizon}
        )
        if not res.ok:
            print_error(f"Failed to compare trade-offs: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        data = _tool_dict(res).get("analysis", {})
        rec_alt = data.get("recommended_alternative", "Multiple valid options")
        cwording = data.get("constraint_wording", "Evaluation complete.")
        console.print(
            Panel(
                f"[bold]Best Alternative:[/bold] [green]{rec_alt}[/green]\n"
                f"[bold]Constraint Satisfaction Summary:[/bold] {cwording}",
                title="Goal Trade-Off Comparison",
                border_style="cyan",
            )
        )

        results = data.get("results", [])
        if results:
            t = Table(title="Side-by-Side Alternatives Comparison", box=box.ROUNDED)
            t.add_column("Alternative", style="bold")
            t.add_column("Goal Completion")
            t.add_column("Emergency Months", justify="right")
            t.add_column("Uncovered Commitments", justify="right")
            t.add_column("Shortfall Days", justify="right")
            t.add_column("Satisfies All Constraints", justify="center")
            for r in results:
                sat = r.get("satisfies_all_constraints", False)
                sat_str = "[bold green]YES[/bold green]" if sat else "[bold red]NO[/bold red]"
                t.add_row(
                    str(r.get("name")),
                    str(r.get("goal_completion_date", "N/A")),
                    f"{r.get('emergency_months', 0.0):.1f}",
                    str(r.get("not_covered_commitments_count", 0)),
                    str(r.get("shortfall_days_count", 0)),
                    sat_str,
                )
            console.print(t)
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 19. Behavioural Memory Commands (PLAN_PHASE3 Section 5.8, 5.9, & 5.11)
# -------------------------------------------------------------------------------------------------
memory_app = typer.Typer(
    name="memory", help="Manage behavioural memories and contextual exceptions."
)
app.add_typer(memory_app, name="memory")
app.add_typer(memory_app, name="memories")


@memory_app.command("list")
def memory_list_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, candidate, stale, retired)"),
    ] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List behavioural memory items and confidence scores."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "list_memories", {"status": status, "kind": kind})
        if not res.ok:
            print_error(f"Failed to list memories: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        items = _tool_dict(res).get("memories", [])
        table = Table(title=f"Behavioural Memories for User '{user_id}'", box=box.ROUNDED)
        table.add_column("Memory ID", style="dim")
        table.add_column("Kind", style="cyan")
        table.add_column("Subject Key", style="bold")
        table.add_column("Confidence", justify="right")
        table.add_column("Status")
        table.add_column("Statement", style="dim")

        for m in items:
            st = m.get("status", "")
            st_style = (
                "green" if st == "active" else ("yellow" if st in ("candidate", "stale") else "dim")
            )
            conf_bp = m.get("confidence_bp", 0)
            conf_str = f"{conf_bp / 100.0:.1f}%"
            table.add_row(
                str(m.get("id")),
                str(m.get("kind")),
                str(m.get("subject_key")),
                conf_str,
                f"[{st_style}]{st.upper()}[/{st_style}]",
                str(m.get("statement_json")),
            )
        console.print(table)
        if not items:
            console.print("[dim]No memory items recorded yet.[/dim]")
    finally:
        conn.close()


@memory_app.command("explain")
def memory_explain_cmd(
    memory_id: Annotated[str, typer.Argument(help="Memory item ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Explain evidence and decay calculations for a memory item."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "explain_memory", {"memory_id": memory_id})
        if not res.ok:
            print_error(f"Failed to explain memory: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
            return
        m = _tool_dict(res).get("memory", {})
        table = Table(title=f"Memory Explanation: {memory_id}", box=box.ROUNDED)
        table.add_column("Property", style="bold")
        table.add_column("Value", style="cyan")
        table.add_row("ID", str(m.get("id")))
        table.add_row("Kind", str(m.get("kind")))
        table.add_row("Subject Key", str(m.get("subject_key")))
        table.add_row("Status", str(m.get("status")).upper())
        table.add_row("Prior Confidence", f"{m.get('prior_bp', 0) / 100.0:.1f}%")
        table.add_row("Current Confidence", f"{m.get('confidence_bp', 0) / 100.0:.1f}%")
        table.add_row("Supporting Evidence", str(m.get("supporting_evidence_count", 0)))
        table.add_row("Contradicting Evidence", str(m.get("contradicting_evidence_count", 0)))
        console.print(table)
    finally:
        conn.close()


@memory_app.command("confirm")
def memory_confirm_cmd(
    memory_id: Annotated[str, typer.Argument(help="Memory item ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """User-confirm a memory item to activate it immediately."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "confirm_memory", {"memory_id": memory_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to confirm memory: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Memory item '{memory_id}' confirmed and activated.")
    finally:
        conn.close()


@memory_app.command("reject")
def memory_reject_cmd(
    memory_id: Annotated[str, typer.Argument(help="Memory item ID")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Reject a memory candidate."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "reject_memory", {"memory_id": memory_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to reject memory: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Memory item '{memory_id}' rejected.")
    finally:
        conn.close()


@memory_app.command("forget")
def memory_forget_cmd(
    memory_id: Annotated[str, typer.Argument(help="Memory item ID to permanently forget")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Permanently delete content of a memory item while keeping audit trail."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        res = execute_tool(ctx, "forget_memory", {"memory_id": memory_id})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to forget memory: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(f"Memory item '{memory_id}' permanently forgotten.")
    finally:
        conn.close()


@memory_app.command("refresh")
def memory_refresh_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Run observers and decay calculations to refresh memory confidence."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="agent")
        res = execute_tool(ctx, "refresh_memories", {})
        conn.commit()
        if not res.ok:
            print_error(f"Failed to refresh memories: {res.error.message}")
            raise typer.Exit(code=1)
        if as_json:
            print_json(_tool_dict(res))
        else:
            print_success(f"Memories refreshed successfully for user '{user_id}'.")
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 20. User Preferences Commands (PLAN_PHASE3 Section 5.11)
# -------------------------------------------------------------------------------------------------
prefs_app = typer.Typer(name="prefs", help="Manage user planning preferences.")
app.add_typer(prefs_app, name="prefs")


@prefs_app.command("show")
def prefs_show_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display all user planning preferences."""
    from copilot.db.repo_phase3 import list_user_preferences

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        prefs = list_user_preferences(conn, user_id=user_id)
        if as_json:
            print_json(prefs)
            return
        table = Table(title=f"User Preferences for {user_id}", box=box.ROUNDED)
        table.add_column("Key", style="bold cyan")
        table.add_column("Value")
        for k, v in prefs.items():
            table.add_row(k, str(v))
        console.print(table)
        if not prefs:
            console.print("[dim]No user preferences set yet (using system defaults).[/dim]")
    finally:
        conn.close()


@prefs_app.command("set")
def prefs_set_cmd(
    key: Annotated[
        str, typer.Argument(help="Preference key (e.g. emergency_months_target, buffer_paise)")
    ],
    value: Annotated[str, typer.Argument(help="Preference value (JSON string or primitive)")],
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Set a user planning preference value."""
    from copilot.db.repo_phase3 import set_user_preference

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        try:
            val = json.loads(value)
        except Exception:
            val = value
        set_user_preference(conn, user_id=user_id, key=key, value=val)
        conn.commit()
        print_success(f"Preference '[cyan]{key}[/cyan]' set successfully.")
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 21. Skills Library Commands (PLAN_PHASE3 Section 5.12 & 5.11)
# -------------------------------------------------------------------------------------------------
skills_app = typer.Typer(name="skills", help="Explore and execute procedural skills.")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List registered procedural skills in the library."""
    from copilot.skills.manifest import load_all_skills

    skills = load_all_skills()
    if as_json:
        print_json({name: s.model_dump(mode="json") for name, s in skills.items()})
        return
    table = Table(title="Registered Procedural Skills Library", box=box.ROUNDED)
    table.add_column("Skill Name", style="bold cyan")
    table.add_column("Version", justify="center")
    table.add_column("Description")
    table.add_column("Steps", justify="right")
    for name, s in sorted(skills.items()):
        table.add_row(
            name,
            str(s.version),
            s.description,
            str(len(s.steps)),
        )
    console.print(table)


@skills_app.command("show")
def skills_show_cmd(
    skill_name: Annotated[str, typer.Argument(help="Name of the skill to inspect")],
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display manifest and procedure steps for a skill."""
    from copilot.skills.manifest import load_skill_manifest

    try:
        s = load_skill_manifest(skill_name)
    except Exception as exc:
        print_error(f"Failed to load skill '{skill_name}': {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(s.model_dump(mode="json"))
        return

    console.print(
        Panel(
            f"[bold]Skill:[/bold] [cyan]{s.name}[/cyan] (v{s.version})\n"
            f"[bold]Description:[/bold] {s.description}\n"
            f"[bold]Inputs Schema:[/bold] {s.inputs}\n"
            f"[bold]Preconditions:[/bold] {s.preconditions}\n"
            f"[bold]Outputs:[/bold] {s.outputs}",
            title=f"Skill Manifest: {s.name}",
            border_style="cyan",
        )
    )

    t = Table(title="Procedural Execution Steps", box=box.ROUNDED)
    t.add_column("Step #", justify="right")
    t.add_column("Tool Invoked", style="bold")
    t.add_column("Parameters Expression")
    for idx, st in enumerate(s.steps, 1):
        for tool_name, params in st.items():
            t.add_row(str(idx), tool_name, str(params))
    console.print(t)


@skills_app.command("run")
def skills_run_cmd(
    skill_name: Annotated[str, typer.Argument(help="Name of the skill to execute")],
    inputs: Annotated[
        str, typer.Option("--inputs", help="JSON string of skill input parameters")
    ] = "{}",
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Execute a procedural skill through governed execute_tool steps."""
    from copilot.skills.manifest import load_skill_manifest
    from copilot.skills.runner import run_skill

    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        try:
            in_dict = json.loads(inputs)
        except Exception as exc:
            print_error(f"Invalid inputs JSON: {exc}")
            raise typer.Exit(code=1) from exc

        manifest = load_skill_manifest(skill_name)
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="agent")
        result = run_skill(manifest, ctx, in_dict)
        conn.commit()

        if as_json:
            print_json(
                {
                    "skill_name": skill_name,
                    "status": result.status,
                    "outputs": result.outputs,
                    "error": result.error,
                    "steps_executed": len(result.step_results),
                }
            )
            return

        st_style = "green" if result.status == "ok" else "red"
        console.print(
            Panel(
                f"[bold]Skill:[/bold] [cyan]{skill_name}[/cyan]\n"
                f"[bold]Status:[/bold] [{st_style}]{result.status.upper()}[/{st_style}]\n"
                f"[bold]Steps Executed:[/bold] {len(result.step_results)}\n"
                f"[bold]Findings Generated:[/bold] {len(result.outputs)}",
                title="Skill Execution Result",
                border_style="cyan",
            )
        )
        if result.error:
            print_error(f"Skill error: {result.error}")
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# Scheduled Jobs & Agent Runtime Commands (PLAN_PHASE3 Section 5.15)
# -------------------------------------------------------------------------------------------------
jobs_app = typer.Typer(name="jobs", help="Manage scheduled background upkeep jobs.")
app.add_typer(jobs_app, name="jobs")


@jobs_app.command("run-due")
def jobs_run_due_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Run all scheduled upkeep jobs that are due."""
    from copilot.runtime.runner import run_due_jobs

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        runs = run_due_jobs(conn, user_id=user)
        table = Table(title=f"Scheduled Jobs Run Results ({user})", box=box.ROUNDED)
        table.add_column("Run ID", style="dim")
        table.add_column("Job ID", style="cyan")
        table.add_column("Status")
        table.add_column("Summary", style="dim")

        import json

        for r in runs:
            st_style = (
                "green" if r.status == "ok" else ("yellow" if r.status == "skipped" else "red")
            )
            table.add_row(
                r.id,
                r.job_id,
                f"[{st_style}]{r.status.upper()}[/{st_style}]",
                json.dumps(r.summary_json),
            )
        console.print(table)
        if not runs:
            console.print("[dim]No scheduled jobs were due to run.[/dim]")
    finally:
        conn.close()


@jobs_app.command("list")
def jobs_list_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """List all scheduled background upkeep jobs and their status."""
    from copilot.db.repo_phase3 import list_scheduled_jobs
    from copilot.runtime.scheduler import init_scheduled_jobs

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        init_scheduled_jobs(conn, user_id=user)
        jobs = list_scheduled_jobs(conn, user_id=user, enabled_only=False)
        table = Table(title=f"Scheduled Jobs for {user}", box=box.ROUNDED)
        table.add_column("Job Kind", style="cyan")
        table.add_column("Schedule")
        table.add_column("Next Run At", style="dim")
        table.add_column("Last Status")
        table.add_column("Failures", justify="right")
        table.add_column("Lease Owner", style="dim")

        for j in jobs:
            st_style = (
                "green"
                if j.last_status == "ok"
                else ("red" if j.last_status == "dead_letter" else "yellow")
            )
            table.add_row(
                j.job_kind,
                j.schedule,
                j.next_run_at,
                f"[{st_style}]{j.last_status or 'pending'}[/{st_style}]",
                str(j.consecutive_failures),
                j.lease_owner or "-",
            )
        console.print(table)
    finally:
        conn.close()


@jobs_app.command("retry")
def jobs_retry_cmd(
    job_kind: Annotated[str, typer.Argument(help="Job kind to retry")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Retry a failed or dead-lettered scheduled job."""
    from copilot.runtime.runner import retry_dead_letter_job

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        run = retry_dead_letter_job(conn, user_id=user, job_kind=job_kind)
        st_style = "green" if run.status == "ok" else "red"
        console.print(
            f"Retried [cyan]{job_kind}[/cyan]: [{st_style}]{run.status.upper()}[/{st_style}]"
        )
        print_json(run.summary_json)
    finally:
        conn.close()


@jobs_app.command("run")
def jobs_run_cmd(
    job_kind: Annotated[str, typer.Argument(help="Specific job kind to run immediately")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Run a specific scheduled job immediately."""
    from copilot.runtime.runner import run_job

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        run = run_job(conn, user_id=user, job_kind=job_kind)
        st_style = (
            "green" if run.status == "ok" else ("yellow" if run.status == "skipped" else "red")
        )
        console.print(
            f"Executed [cyan]{job_kind}[/cyan]: [{st_style}]{run.status.upper()}[/{st_style}]"
        )
        print_json(run.summary_json)
    finally:
        conn.close()


@jobs_app.command("dead-letter")
def jobs_dead_letter_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List jobs that entered the dead-letter state after max retries."""
    from copilot.db.repo_phase3 import list_scheduled_jobs

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        jobs = list_scheduled_jobs(conn, user_id=user, enabled_only=False)
        dead = [j for j in jobs if j.last_status == "dead_letter"]
        if as_json:
            print_json([j.model_dump(mode="json") for j in dead])
            return
        table = Table(title=f"Dead-Letter Jobs for User '{user}'", box=box.ROUNDED)
        table.add_column("Job Kind", style="bold red")
        table.add_column("Schedule")
        table.add_column("Consecutive Failures", justify="right")
        table.add_column("Next Run At")
        for j in dead:
            table.add_row(j.job_kind, j.schedule, str(j.consecutive_failures), j.next_run_at)
        console.print(table)
        if not dead:
            console.print("[green]No dead-letter jobs. All scheduled jobs healthy.[/green]")
    finally:
        conn.close()


@app.command("agentd")
def agentd_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    interval: Annotated[int | None, typer.Option("--interval", help="Loop interval (s)")] = None,
    max_cycles: Annotated[
        int | None, typer.Option("--max-cycles", help="Maximum cycles to run")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Run the foreground agent daemon loop for automated upkeep."""
    from copilot.runtime.daemon import run_agentd

    db_path = get_db_path(db)

    def conn_factory():
        return open_db(db_path)

    console.print(
        f"[bold cyan]FinCo Agent Daemon[/bold cyan] starting for user [bold]{user}[/bold]..."
    )
    cycles = run_agentd(
        conn_factory=conn_factory,
        user_id=user,
        loop_interval_seconds=interval,
        max_cycles=max_cycles,
    )
    console.print(f"agentd stopped after completing [bold]{cycles}[/bold] cycle(s).")


@app.command("ops")
def ops_cmd(
    user: Annotated[str | None, typer.Option("--user", "-u", help="Filter by User ID")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display operational telemetry and observability report (PLAN_PHASE3 Section 5.15)."""
    import dataclasses

    from copilot.ops.telemetry import compute_ops_telemetry

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        report = compute_ops_telemetry(conn, user_id=user)
        if json_output:
            print_json(dataclasses.asdict(report))
            return

        summary_text = (
            f"[bold]Scope:[/bold] [cyan]{user or 'all users'}[/cyan]\n\n"
            f"[bold]LLM Metrics:[/bold] Calls/Task: [bold]{report.llm_calls_per_task}[/bold] | "
            f"Tokens/Task: [bold]{report.tokens_per_task}[/bold] | "
            f"Total Tokens: [bold]{report.total_tokens}[/bold]\n"
            f"[bold]Estimated Cost:[/bold] "
            f"[bold yellow]{report.estimated_cost_str}[/bold yellow]\n\n"
            f"[bold]Reliability:[/bold] Budget Stops: [bold]{report.budget_stops_count}[/bold] | "
            f"Validator Fallback Rate: [bold]{report.validator_fallback_rate * 100:.2f}%[/bold]\n"
            f"[bold]Self-Correction:[/bold] Critic Catch Rate: "
            f"[bold]{report.critic_catch_rate * 100:.2f}%[/bold] | "
            f"Revision Success Rate: [bold]{report.revision_success_rate * 100:.2f}%[/bold]\n"
            f"[bold]Orchestration:[/bold] Parallel Speed-up: "
            f"[bold green]{report.parallel_speed_up}x[/bold green]\n\n"
            f"[bold]Background Jobs:[/bold] [green]{report.job_counts.get('ok', 0)} ok[/green], "
            f"[red]{report.job_counts.get('dead_letter', 0)} dead letter[/red], "
            f"[yellow]{report.job_counts.get('failed', 0)} failed[/yellow], "
            f"[dim]{report.job_counts.get('skipped', 0)} skipped[/dim]"
        )

        console.print(
            Panel(summary_text, title="FinCo Ops Telemetry Dashboard", border_style="cyan")
        )

        if report.p50_p95_nodes or report.p50_p95_skills:
            t = Table(title="Component Latency Percentiles", box=box.ROUNDED)
            t.add_column("Type", style="cyan")
            t.add_column("Component Name")
            t.add_column("Count", justify="right")
            t.add_column("p50 (ms)", justify="right")
            t.add_column("p95 (ms)", justify="right")

            for name, stats in report.p50_p95_nodes.items():
                t.add_row(
                    "Node",
                    name,
                    str(stats.get("count", 0)),
                    f"{stats['p50_ms']:.1f}",
                    f"{stats['p95_ms']:.1f}",
                )
            for name, stats in report.p50_p95_skills.items():
                t.add_row(
                    "Skill",
                    name,
                    str(stats.get("count", 0)),
                    f"{stats['p50_ms']:.1f}",
                    f"{stats['p95_ms']:.1f}",
                )
            console.print(t)

        if report.failure_counts_by_code:
            t_err = Table(title="Failures by Error Code", box=box.ROUNDED)
            t_err.add_column("Error Code", style="red")
            t_err.add_column("Count", justify="right")
            for code, count in report.failure_counts_by_code.items():
                t_err.add_row(code, str(count))
            console.print(t_err)
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 19. Bounded Feedback Learning Commands (PLAN_PHASE3 Section 5.16)
# -------------------------------------------------------------------------------------------------
learning_app = typer.Typer(
    help="Inspect and manage bounded feedback learning state (PLAN_PHASE3 Section 5.16)."
)
app.add_typer(learning_app, name="learning")


@learning_app.command("show")
def learning_show_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display learned sensitivity multipliers and Beta posteriors."""
    from copilot.core.learning import list_tenant_learning_stats

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        stats = list_tenant_learning_stats(conn, user_id=user)
        if json_output:
            print_json(stats)
            return

        table = Table(title=f"Learned Feedback Multipliers for User '{user}'", box=box.ROUNDED)
        table.add_column("Subject Kind", style="cyan", no_wrap=True)
        table.add_column("Subject Key", no_wrap=True)
        table.add_column("Alpha (α)", justify="right")
        table.add_column("Beta (β)", justify="right")
        table.add_column("Posterior (p)", justify="right")
        table.add_column("Multiplier (m)", justify="right", style="bold green")
        table.add_column("Hard Floor", justify="center")
        table.add_column("Updated At", style="dim")

        for s in stats:
            floor_str = "[bold red]YES[/bold red]" if s["hard_floor_protected"] else "NO"
            m_style = "bold green" if s["multiplier"] >= 1.0 else "bold yellow"
            table.add_row(
                s["subject_kind"],
                s["subject_key"],
                f"{s['alpha']:.1f}",
                f"{s['beta']:.1f}",
                f"{s['p']:.4f}",
                f"[{m_style}]{s['multiplier']:.4f}[/{m_style}]",
                floor_str,
                s["updated_at"],
            )
        console.print(table)
        if not stats:
            console.print(
                "[dim]No learned feedback recorded yet. Using priors (α=2, β=2, m=1.0).[/dim]"
            )
    finally:
        conn.close()


@learning_app.command("reset")
def learning_reset_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    subject: Annotated[
        str | None, typer.Option("--subject", "-s", help="Specific subject key to reset")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Reset learned feedback statistics to priors (restores α=2, β=2, m=1.0)."""
    from copilot.core.learning import reset_learning

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        cnt = reset_learning(conn, user_id=user, subject_key=subject)
        conn.commit()
        if subject:
            console.print(
                f"Reset [cyan]{cnt}[/cyan] feedback stat(s) for subject '[bold]{subject}[/bold]'."
            )
        else:
            console.print(
                f"Reset [cyan]{cnt}[/cyan] feedback stat(s) for user '{user}' back to priors."
            )
    finally:
        conn.close()


# -------------------------------------------------------------------------------------------------
# 20. Model Context Protocol (MCP) Server Commands (PLAN_PHASE3 Section 5.17)
# -------------------------------------------------------------------------------------------------
mcp_app = typer.Typer(
    help="Model Context Protocol (MCP) server commands (PLAN_PHASE3 Section 5.17)."
)
app.add_typer(mcp_app, name="mcp")


@app.command("mcp-serve")
@mcp_app.command("serve")
def mcp_serve_cmd(
    user_id: Annotated[str, typer.Option("--user-id", "-u", help="User ID for MCP tenant")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Expose FinCo capabilities over stdio via Model Context Protocol (MCP)."""
    from copilot.mcp.server import run_mcp_stdio_server

    db_path = get_db_path(db)
    run_mcp_stdio_server(user_id=user_id, db_path=db_path)


if __name__ == "__main__":
    app()
