"""Bounded learning from your feedback: what it learned, and resetting it."""

from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_json,
)
from copilot.cli.storage import (
    get_db_path,
    open_db,
)

learning_app = typer.Typer(
    help="Inspect and manage bounded feedback learning state (PLAN_PHASE3 Section 5.16)."
)
app.add_typer(learning_app, name="learning")


@learning_app.command("show")
def learning_show_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    subject: Annotated[
        str | None, typer.Option("--subject", "-s", help="Filter by subject kind or key")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display learned sensitivity multipliers and Beta posteriors."""
    from copilot.learning.feedback import list_tenant_learning_stats

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        stats = list_tenant_learning_stats(conn, user_id=user)
        if subject:
            stats = [
                s
                for s in stats
                if s.get("subject_kind") == subject or s.get("subject_key") == subject
            ]
        from copilot.capture import learning as capture_learning
        from copilot.config.capture import load_capture_config

        capture_rows = capture_learning.summary(conn, user, load_capture_config())
        if json_output:
            print_json(capture_rows if subject == "capture" else stats)
            return

        cap = Table(
            title="How payment guesses are weighted (basis points of 10000)", box=box.ROUNDED
        )
        for col in ("Signal", "Configured", "Learned", "Multiplier", "p", "Labels seen"):
            cap.add_column(col, justify="left" if col == "Signal" else "right")
        for r in capture_rows:
            cap.add_row(
                r["signal"],
                str(r["base_bp"]),
                str(r["effective_bp"]),
                f"{r['multiplier']:.4f}",
                f"{r['p']:.4f}",
                str(r["evidence"]),
            )
        console.print(cap)

        table = Table(title=f"Learned Feedback Multipliers for User '{user}'", box=box.ROUNDED)
        table.add_column("Subject Kind", style="cyan", no_wrap=True)
        table.add_column("Subject Key", no_wrap=True)
        table.add_column("Alpha (α)", justify="right")
        table.add_column("Beta (β)", justify="right")
        table.add_column("Posterior (p)", justify="right")
        table.add_column("Multiplier (m)", justify="right", style="bold green")
        table.add_column("Hard Floor", justify="center")
        table.add_column("Updated At", style="dim")

        for s in stats:
            floor_str = "[bold red]YES[/bold red]" if s["hard_floor_protected"] else "NO"
            m_style = "bold green" if s["multiplier"] >= 1.0 else "bold yellow"
            table.add_row(
                s["subject_kind"],
                s["subject_key"],
                f"{s['alpha']:.1f}",
                f"{s['beta']:.1f}",
                f"{s['p']:.4f}",
                f"[{m_style}]{s['multiplier']:.4f}[/{m_style}]",
                floor_str,
                s["updated_at"],
            )
        console.print(table)
        if not stats:
            console.print(
                "[dim]No learned feedback recorded yet. Using priors (α=2, β=2, m=1.0).[/dim]"
            )
    finally:
        conn.close()


@learning_app.command("reset")
def learning_reset_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    subject: Annotated[
        str | None, typer.Option("--subject", "-s", help="Specific subject kind or key to reset")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
) -> None:
    """Reset learned feedback statistics to priors (restores α=2, β=2, m=1.0)."""
    from copilot.learning.feedback import reset_learning

    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        sub_kind = (
            subject
            if subject in ("challenge_template", "alert_type", "anomaly_type", "capture_signal")
            else None
        )
        sub_key = subject if sub_kind is None else None
        cnt = reset_learning(conn, user_id=user, subject_kind=sub_kind, subject_key=sub_key)
        conn.commit()
        if subject:
            console.print(
                f"Reset [cyan]{cnt}[/cyan] feedback stat(s) for subject '[bold]{subject}[/bold]'."
            )
        else:
            console.print(
                f"Reset [cyan]{cnt}[/cyan] feedback stat(s) for user '{user}' back to priors."
            )
    finally:
        conn.close()
