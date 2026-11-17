"""What FinCo remembers about you, and your planning preferences."""

import json
from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.common import tool_dict
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
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

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
            print_json(tool_dict(res))
            return
        items = tool_dict(res).get("memories", [])
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
            print_json(tool_dict(res))
            return
        m = tool_dict(res).get("memory", {})
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


@memory_app.command("exception")
def memory_exception_cmd(
    category: Annotated[str, typer.Option("--category", help="Category name or id")],
    reason: Annotated[str, typer.Option("--reason", help="festival, travel, medical, ...")],
    from_date: Annotated[str | None, typer.Option("--from", help="First day, YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option("--to", help="Last day, YYYY-MM-DD")] = None,
    period: Annotated[str | None, typer.Option("--period", help="Whole month, YYYY-MM")] = None,
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Declare a one-off stretch (a trip, a festival) so challenges and baselines allow for it."""
    ensure_tools_registered()
    conn = open_db(get_db_path(db))
    try:
        ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")
        args = {
            "category": category,
            "reason": reason,
            "period": period,
            "from_date": from_date,
            "to_date": to_date,
        }
        res = execute_tool(ctx, "record_contextual_exception", args)
        conn.commit()
        if not res.ok:
            print_error(f"Could not record the exception: {res.error.message}")
            raise typer.Exit(code=1)
        print_success(
            f"Noted: {category} ({reason}) {from_date or period}"
            + (f" to {to_date}" if to_date else "")
            + "."
        )
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
            print_json(tool_dict(res))
        else:
            print_success(f"Memories refreshed successfully for user '{user_id}'.")
    finally:
        conn.close()


prefs_app = typer.Typer(name="prefs", help="Manage user planning preferences.")
app.add_typer(prefs_app, name="prefs")


@prefs_app.command("show")
def prefs_show_cmd(
    user_id: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display all user planning preferences."""
    from copilot.db.repo_memory import list_user_preferences

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
    from copilot.db.repo_memory import set_user_preference

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
