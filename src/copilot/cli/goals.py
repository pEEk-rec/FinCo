"""Goals: create, change, contribute to and track them."""

from datetime import UTC, datetime
from typing import Annotated, Any

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.app import goals_app
from copilot.cli.common import parse_cli_amount, tool_dict, tool_out
from copilot.cli.formatters import (
    console,
    print_error,
    print_goals_table,
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

    goal = tool_out(res, "goal")
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

    goals = tool_out(res, "goals") or []
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

    goal = tool_out(res, "goal")
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

    goal = tool_out(res, "goal")
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
            print_json(tool_dict(res))
            return

        p_dict = tool_dict(res).get("progress", {})
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
            print_json(tool_dict(res))
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


@goals_app.command("decompose")
def goals_decompose_cmd(
    goal_id: Annotated[str, typer.Argument(help="Goal ID to decompose")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Decompose a goal deficit into candidate behavioral experiments (PLAN_PHASE4)."""
    from copilot.common.timeutil import from_utc_iso
    from copilot.engagement.challenges import decompose_goal_gap

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = None
        if clock:
            try:
                clock_dt = from_utc_iso(clock)
            except Exception:
                clock_dt = datetime.fromisoformat(clock).replace(tzinfo=UTC)

        decomp = decompose_goal_gap(conn, user_id=user, goal_id=goal_id, clock=clock_dt)
        data = decomp.model_dump(mode="json")
        if as_json:
            print_json(data)
            return

        table = Table(
            title=f"Goal Gap Decomposition for Goal '{decomp.goal_name}' ({goal_id})",
            box=box.ROUNDED,
        )
        table.add_column("Template", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Difficulty", style="magenta")
        table.add_column("Expected Savings", justify="right", style="green")
        table.add_column("Goal Gap Share", justify="right")

        for c in decomp.candidate_experiments:
            table.add_row(
                c.template_code,
                c.title,
                c.difficulty,
                format_inr(c.expected_effect_paise),
                f"{c.gap_share_pct}%",
            )

        monthly_str = (
            format_inr(decomp.required_monthly_paise) if decomp.required_monthly_paise else "N/A"
        )  # noqa: E501
        console.print(
            Panel(
                f"[bold cyan]Deficit:[/bold cyan] {format_inr(decomp.deficit_paise)} | "
                f"[bold cyan]Monthly Gap:[/bold cyan] {monthly_str}\n"
                "[italic dim]Candidate experiments provide observational options without promising goal completion.[/italic dim]",  # noqa: E501
                title="Goal Gap Summary",
                box=box.ROUNDED,
            )
        )
        console.print(table)
        if not decomp.candidate_experiments:
            console.print(
                "[dim]No candidate experiments could be fitted for this goal deficit.[/dim]"
            )  # noqa: E501
    finally:
        conn.close()
