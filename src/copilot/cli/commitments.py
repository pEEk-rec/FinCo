"""Commitments (rent, EMIs, subscriptions, SIPs) and the calendar they make."""

from typing import Annotated

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.common import parse_cli_amount, tool_dict
from copilot.cli.formatters import (
    console,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.conversation.advice import format_inr
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

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
            print_json(tool_dict(res))
            return
        items = tool_dict(res).get("commitments", [])
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
            print_json(tool_dict(res))
        else:
            c = tool_dict(res).get("commitment", {})
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
            print_json(tool_dict(res))
            return
        data = tool_dict(res)
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
            print_json(tool_dict(res))
            return
        drafts = tool_dict(res).get("drafts", [])
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
            print_json(tool_dict(res))
            return
        data = tool_dict(res).get("calendar", {})
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
