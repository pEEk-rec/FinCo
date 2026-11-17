"""Talking to the agent: ask, investigate, explain, decide, and the timeline."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import typer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.common import tool_dict, tool_out
from copilot.cli.formatters import (
    console,
    print_error,
    print_investigation_result,
    print_json,
    print_success,
    print_timeline,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.conversation.advice import format_inr
from copilot.db.repo import (
    get_recommendation,
    get_user,
    insert_user,
)
from copilot.engagement.recommendations import format_recommendation_explanation
from copilot.models.domain import User
from copilot.ops.timeline import build_timeline
from copilot.tools.executor import execute_tool
from copilot.workflow.agent_graph import build_planner_agent_graph
from copilot.workflow.agentic_state import AgenticState
from copilot.workflow.nodes import ensure_tools_registered


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

        inv = tool_out(res, "investigation")
        decomp = tool_out(res, "decomposition") or {}
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

        out_data = tool_dict(res)
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
        print_json(tool_dict(res))
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
    real_time: Annotated[
        bool, typer.Option("--real-time", help="Real clock, for live bank alerts")
    ] = False,
    lan: Annotated[
        bool, typer.Option("--lan", help="Listen on the local network (phone on Wi-Fi)")
    ] = False,
) -> None:
    """Start the local HTTP API for the web UI (localhost only unless --lan)."""
    from copilot.api.server import serve

    serve(get_db_path(db), port=port, demo=demo, token=token, real_time=real_time, lan=lan)
