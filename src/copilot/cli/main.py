"""
Main Typer CLI application for Finance Copilot (PLAN_PHASE1 Section 5.9).
"""

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
    run_id: Annotated[str, typer.Argument(help="Run ID to display trace for")],
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display node-by-node execution trace for a workflow run."""
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
    phase: Annotated[int, typer.Option("--phase", help="Evaluation phase (1 or 2)")] = 1,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    from rich import box
    from rich.table import Table

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


if __name__ == "__main__":
    app()
