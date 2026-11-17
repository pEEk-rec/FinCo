"""Running the monthly workflow and reading its review."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    load_and_register_connector,
    make_exec_ctx,
    open_db,
    save_trace,
)
from copilot.conversation.advice import format_inr
from copilot.review import build_monthly_review, render_html, render_markdown
from copilot.workflow.graph import build_agent_graph
from copilot.workflow.nodes import ensure_tools_registered
from copilot.workflow.state import AgentState
from copilot.workflow.trace import format_trace


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
    conn.commit()  # the graph's writes stay uncommitted until here
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
