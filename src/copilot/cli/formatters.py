"""
Rich terminal formatting helpers and JSON serialization for CLI commands.
"""

import json
from decimal import Decimal
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from copilot.core.advice import format_inr

console = Console()
error_console = Console(stderr=True)


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def print_json(data: Any) -> None:
    """Print data as formatted JSON to stdout."""
    import sys

    sys.stdout.write(json.dumps(data, indent=2, cls=_DecimalEncoder, default=str) + "\n")


def print_error(message: str) -> None:
    """Print a clean error message without traceback."""
    error_console.print(f"[bold red]Error:[/bold red] {message}")


def print_success(message: str) -> None:
    """Print a success confirmation message."""
    console.print(f"[bold green][OK][/bold green] {message}")


def print_transactions_table(txs: list[dict[str, Any]]) -> None:
    """Format transactions in a readable Rich table."""
    table = Table(title="Transactions", box=box.ROUNDED, expand=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Date", style="blue")
    table.add_column("Amount", justify="right")
    table.add_column("Type", style="magenta")
    table.add_column("Merchant", style="bold")
    table.add_column("Category", style="green")
    table.add_column("Source", style="dim")
    table.add_column("Review?", justify="center")

    for t in txs:
        direction = t.get("direction", "debit")
        amount_paise = t.get("amount_paise", 0)
        amt_str = format_inr(abs(amount_paise))
        amt_styled = (
            f"[green]+{amt_str}[/green]"
            if direction == "credit"
            else f"[red]-{amt_str}[/red]"
        )
        needs_rev = "[bold yellow]YES[/bold yellow]" if t.get("needs_review") else "[dim]no[/dim]"
        cat = t.get("category_id") or "[dim]uncategorised[/dim]"
        src = t.get("category_source", "none")

        table.add_row(
            str(t.get("id")),
            str(t.get("occurred_at", "")[:10]),
            amt_styled,
            str(direction),
            str(t.get("merchant_normalized") or t.get("merchant_raw")),
            str(cat),
            str(src),
            needs_rev,
        )

    console.print(table)


def print_budgets_table(budgets: list[dict[str, Any]]) -> None:
    """Format budget health statuses in a Rich table."""
    table = Table(title="Budget Performance", box=box.ROUNDED)
    table.add_column("Category", style="bold")
    table.add_column("Spent", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("Used %", justify="right")
    table.add_column("Status", justify="center")

    status_styles = {
        "ok": "[green]OK[/green]",
        "warning": "[bold yellow]WARNING[/bold yellow]",
        "exceeded": "[bold red]EXCEEDED[/bold red]",
        "projected_exceed": "[bold orange1]PROJ EXCEED[/bold orange1]",
    }

    for b in budgets:
        spent = format_inr(b.get("spent_paise", 0))
        limit = format_inr(b.get("limit_paise", 0))
        pct = f"{b.get('pct_used', 0)}%" if b.get("pct_used") is not None else "-"
        stat_raw = str(b.get("status", "ok"))
        stat_badge = status_styles.get(stat_raw, stat_raw)

        table.add_row(
            str(b.get("category_id") or b.get("category_name")),
            spent,
            limit,
            pct,
            stat_badge,
        )

    console.print(table)


def print_anomalies_table(anomalies: list[dict[str, Any]]) -> None:
    """Format detected anomalies in a Rich table."""
    if not anomalies:
        console.print("[dim]No anomalies flagged.[/dim]")
        return

    table = Table(title="Detected Anomalies", box=box.ROUNDED)
    table.add_column("Kind / Details", style="bold yellow")
    table.add_column("Transaction(s)", style="cyan")
    table.add_column("Score", justify="right", style="magenta")

    for a in anomalies:
        tx_ids = ", ".join(a.get("transaction_ids", ()))
        table.add_row(
            str(a.get("details") or a.get("kind")),
            tx_ids,
            f"{a.get('score', 0.0):.2f}",
        )

    console.print(table)


def print_recurring_table(recurring: list[dict[str, Any]]) -> None:
    """Format recurring commitments in a Rich table."""
    if not recurring:
        console.print("[dim]No recurring subscriptions or bills detected.[/dim]")
        return

    table = Table(title="Recurring Subscriptions & Bills", box=box.ROUNDED)
    table.add_column("Merchant", style="bold")
    table.add_column("Typical Amount", justify="right", style="green")
    table.add_column("Cadence", justify="right")
    table.add_column("Confidence", justify="right", style="cyan")
    table.add_column("Kind", style="magenta")

    for r in recurring:
        table.add_row(
            str(r.get("merchant_normalized")),
            format_inr(r.get("typical_amount_paise", 0)),
            f"{r.get('cadence_days', 30)} days",
            f"{r.get('confidence', 1.0):.2f}",
            str(r.get("kind", "bill")),
        )

    console.print(table)


def print_consents_table(consents: list[dict[str, Any]]) -> None:
    """Format consents in a Rich table."""
    table = Table(title="Bank Consents", box=box.ROUNDED)
    table.add_column("Consent ID", style="cyan")
    table.add_column("Accounts", style="blue")
    table.add_column("Range", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Expires", style="dim")

    status_styles = {
        "active": "[bold green]ACTIVE[/bold green]",
        "pending": "[bold yellow]PENDING[/bold yellow]",
        "revoked": "[bold red]REVOKED[/bold red]",
        "expired": "[dim]EXPIRED[/dim]",
    }

    for c in consents:
        stat_raw = str(c.get("status", "pending"))
        stat_badge = status_styles.get(stat_raw, stat_raw)
        rng = f"{c.get('date_range_from', '')[:10]} to {c.get('date_range_to', '')[:10]}"
        table.add_row(
            str(c.get("id")),
            str(c.get("account_ids")),
            rng,
            stat_badge,
            str(c.get("expires_at", "")[:10]),
        )

    console.print(table)


def print_audit_table(events: list[dict[str, Any]]) -> None:
    """Format audit events in a Rich table."""
    table = Table(title="Audit Trail", box=box.ROUNDED)
    table.add_column("Event ID", style="dim", no_wrap=True)
    table.add_column("Time", style="blue")
    table.add_column("Actor", style="magenta")
    table.add_column("Event Type", style="bold")
    table.add_column("Entity", style="cyan")
    table.add_column("Reason", style="white")
    table.add_column("Reversible", justify="center")

    for e in events:
        rev_str = "[green]YES[/green]" if e.get("reversible") else "[dim]NO[/dim]"
        entity = f"{e.get('entity_type')}:{e.get('entity_id')}" if e.get("entity_id") else "-"
        table.add_row(
            str(e.get("id"))[:8],
            str(e.get("occurred_at", "")[:19]),
            str(e.get("actor")),
            str(e.get("event_type")),
            entity,
            str(e.get("reason", "")),
            rev_str,
        )

    console.print(table)


def print_state_panel(state_data: dict[str, Any]) -> None:
    """Format high-level financial state in a summary Panel."""
    bal_paise = state_data.get("balance_paise", 0)
    lines = [
        f"[bold]Total Balance:[/bold] {format_inr(bal_paise)}",
        f"[bold]Review Queue Size:[/bold] {state_data.get('review_queue_size', 0)} items",
        f"[bold]Active Budgets:[/bold] {len(state_data.get('budgets', []))}",
        f"[bold]Tracked Categories:[/bold] {len(state_data.get('category_totals', {}))}",
    ]
    console.print(Panel("\n".join(lines), title="Financial State Snapshot", border_style="cyan"))


def print_timeline(timeline: Any) -> None:
    """Print the chronological activity timeline and pinned pending approvals."""
    # 1. Pinned Pending Approvals
    if timeline.pending_approvals:
        approval_lines = []
        for app in timeline.pending_approvals:
            rec_id = app.ref.get("recommendation_id", "unknown")
            approval_lines.append(
                f"[bold cyan]ID:[/bold cyan] {rec_id} | [bold yellow]{app.title}[/bold yellow]\n"
                f"[white]{app.detail}[/white]\n"
            )
        console.print(
            Panel(
                "\n".join(approval_lines),
                title="[bold yellow]Needs Your Decision[/bold yellow]",
                border_style="yellow",
            )
        )

    # 2. Activity Timeline Table
    table = Table(title="Agent Activity Timeline", box=box.ROUNDED)
    table.add_column("Time", style="blue", no_wrap=True)
    table.add_column("Kind", style="magenta")
    table.add_column("Status", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Details", style="white")

    for e in timeline.entries:
        ts = e.ts[:19].replace("T", " ") if e.ts else "-"
        status_style = "green" if e.status in ("done", "completed", "on_track") else "yellow"
        if e.status in ("failed", "rejected", "error", "refused"):
            status_style = "red"

        table.add_row(
            ts,
            str(e.kind),
            f"[{status_style}]{e.status}[/{status_style}]",
            str(e.title),
            str(e.detail),
        )

    console.print(table)


def print_goals_table(goals: list[dict[str, Any]]) -> None:
    """Format goals in a Rich table."""
    table = Table(title="Financial Goals", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold", min_width=20, no_wrap=False)
    table.add_column("Kind", style="magenta")
    table.add_column("Target", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Status", style="green")
    table.add_column("Deadline", style="blue")
    table.add_column("Priority", justify="center")

    for g in goals:
        status_color = "green" if g.get("status") == "active" else "dim"
        table.add_row(
            str(g.get("id"))[:12],
            str(g.get("name")),
            str(g.get("kind")),
            format_inr(g.get("target_paise", 0)),
            format_inr(g.get("current_paise", 0)),
            f"[{status_color}]{g.get('status')}[/{status_color}]",
            str(g.get("deadline") or "-"),
            str(g.get("priority", 1)),
        )

    console.print(table)


def print_alerts_table(alerts: list[dict[str, Any]]) -> None:
    """Format adaptive alerts in a Rich table."""
    table = Table(title="Adaptive Alerts", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Period", style="blue")
    table.add_column("Severity", style="bold")
    table.add_column("Kind", style="magenta")
    table.add_column("Status", style="yellow")
    table.add_column("Score", justify="right")
    table.add_column("Why", style="white")

    for a in alerts:
        sev = a.get("severity", "info").upper()
        sev_color = "red" if sev in ("CRITICAL", "WARNING") else "yellow"
        table.add_row(
            str(a.get("id"))[:8],
            str(a.get("period")),
            f"[{sev_color}]{sev}[/{sev_color}]",
            str(a.get("kind")),
            str(a.get("status")),
            f"{a.get('score_bp', 0) / 100:.1f}%",
            str(a.get("why_text", ""))[:70] + "...",
        )

    console.print(table)


def print_investigation_result(inv: dict[str, Any]) -> None:
    """Format investigation results in a Rich panel and table."""
    outcome = inv.get("outcome", "unknown")
    outcome_color = "green" if outcome == "explained" else "yellow"
    share = inv.get("explained_share_bp", 0) / 100.0

    lines = [
        f"[bold]Subject:[/bold] {inv.get('subject_kind')} ({inv.get('id', '')})",
        f"[bold]Outcome:[/bold] [{outcome_color}]{outcome}[/{outcome_color}] "
        f"({share:.1f}% explained)",
        f"[bold]Confidence:[/bold] {inv.get('confidence_label')}",
        f"[bold]Unexplained Spend:[/bold] {format_inr(inv.get('unexplained_paise', 0))}",
    ]
    console.print(Panel("\n".join(lines), title="Investigation Result", border_style="cyan"))

    hypotheses = inv.get("hypotheses", [])
    if hypotheses:
        table = Table(title="Evaluated Hypotheses", box=box.ROUNDED)
        table.add_column("Hypothesis", style="bold")
        table.add_column("Status", style="magenta")
        table.add_column("Score", justify="right")
        table.add_column("Contribution", justify="right")

        for h in hypotheses:
            table.add_row(
                str(h.get("code")),
                str(h.get("status")),
                f"{h.get('score_bp', 0) / 100:.1f}%",
                format_inr(h.get("contribution_paise", 0)),
            )
        console.print(table)


def print_simulation_result(sim: dict[str, Any]) -> None:
    """Format simulation projection in a Rich panel."""
    scenario = sim.get("scenario", {})
    kind = scenario.get("kind", "whatif")
    amt = scenario.get("amount_paise", 0)

    lines = [
        f"[bold]Simulation ID:[/bold] {sim.get('id')}",
        f"[bold]Scenario:[/bold] {kind} of {format_inr(amt)}",
        f"[bold]Horizon:[/bold] {scenario.get('months', 6)} months",
        f"[bold]Assumptions:[/bold] {', '.join(sim.get('assumptions', []))}",
    ]
    console.print(Panel("\n".join(lines), title="Simulation Summary", border_style="green"))
