"""The agent runtime: skills, scheduled jobs and the MCP server."""

import json
from typing import Annotated

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_error,
    print_json,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.workflow.nodes import ensure_tools_registered

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
    from copilot.db.repo_agent_runtime import list_scheduled_jobs
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
    from copilot.db.repo_agent_runtime import list_scheduled_jobs

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
