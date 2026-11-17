"""What-if: simulate a spending decision or compare scenarios before making it."""

from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.app import whatif_app
from copilot.cli.common import parse_cli_amount, tool_out
from copilot.cli.formatters import (
    console,
    print_error,
    print_json,
    print_simulation_result,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.conversation.advice import format_inr
from copilot.models.agentic import Scenario
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered


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

    proj = tool_out(res, "projection")
    sim_id = tool_out(res, "simulation_id") or ""
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

    proj = tool_out(res, "projection")
    sim_id = tool_out(res, "simulation_id") or ""
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

    comp = tool_out(res, "comparison")
    sim_id = tool_out(res, "simulation_id") or ""
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
