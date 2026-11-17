"""The ledger: transactions, corrections and undo, and the analysis views over them."""

import re
from datetime import UTC, datetime
from typing import Annotated, Any

import typer

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_anomalies_table,
    print_budgets_table,
    print_error,
    print_json,
    print_recurring_table,
    print_state_panel,
    print_success,
    print_transactions_table,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.conversation.advice import format_inr
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered


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
