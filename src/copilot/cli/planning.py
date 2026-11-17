"""Planning money: buckets, reallocations, readiness to invest and contributions."""

import json
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
                    "buckets": tool_dict(res_list).get("buckets", []),
                    "summary": tool_dict(res_summary) if res_summary.ok else {},
                }
            )
            return

        buckets = tool_dict(res_list).get("buckets", [])
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
            bal_data = tool_dict(st_res).get("balance", {}) if st_res.ok else {}
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
            summ = tool_dict(res_summary).get("summary", {})
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
            print_json(tool_dict(res))
        else:
            b = tool_dict(res).get("bucket", {})
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
            print_json(tool_dict(res))
            return
        b = tool_dict(res).get("balance", {})
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
    from copilot.db.repo_agent_runtime import list_reallocation_drafts

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
            print_json(tool_dict(res))
            return
        data = tool_dict(res).get("assessment", {})
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
            print_json(tool_dict(res))
            return
        data = tool_dict(res).get("plan", {})
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
            print_json(tool_dict(res))
            return
        data = tool_dict(res).get("analysis", {})
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
