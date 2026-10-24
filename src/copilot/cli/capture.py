"""
Typer CLI for the Capture track (PLAN_CAPTURE).

    copilot capture simulate --bank hdfc --kind debit --amount 250 --to "ramesh@ybl"
    copilot capture inbox
    copilot capture label <event_id> --category food
    copilot capture undo <audit_event_id>

Every command goes through `execute_tool`, so each one is governed and audited.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.formatters import console, format_inr, print_error, print_json, print_success
from copilot.cli.storage import get_db_path, make_exec_ctx, open_db
from copilot.core.intent import parse_amount_paise
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

capture_app = typer.Typer(
    help="Tag payments at the moment they happen (PLAN_CAPTURE).", no_args_is_help=True
)

_DB = Annotated[str | None, typer.Option("--db", help="SQLite database path")]
_USER = Annotated[str, typer.Option("--user", "-u", help="User ID")]


def _run(db: str | None, user: str, tool: str, args: dict):
    ensure_tools_registered()
    conn = open_db(get_db_path(db))
    try:
        res = execute_tool(make_exec_ctx(conn=conn, user_id=user, actor="user"), tool, args)
        conn.commit()
    finally:
        conn.close()
    if not res.ok:
        print_error(res.error.message if res.error else "That did not work.")
        raise typer.Exit(code=1)
    return res.data


@capture_app.command("bridge-setup")
def bridge_setup_cmd(
    port: Annotated[int, typer.Option("--port", help="the port `copilot serve` uses")] = 8765,
    lan: Annotated[bool, typer.Option("--lan", help="Wi-Fi route instead of USB")] = False,
) -> None:
    """Print the exact rule to create on your phone, and create the webhook secret if needed."""
    import socket

    from copilot.config.capture import load_capture_config, load_sms_senders
    from copilot.core.capture_bridge import bridge_instructions
    from copilot.core.capture_secret import ensure_capture_secret

    secret, created = ensure_capture_secret()
    lan_host = None
    if lan:
        try:
            lan_host = socket.gethostbyname(socket.gethostname())
        except OSError:
            lan_host = "<this computer's address>"
    if created:
        console.print(
            "[green]Created a new bridge secret[/green] in data/capture_secret (git-ignored)."
        )
    console.print(
        bridge_instructions(
            load_sms_senders(),
            port=port,
            secret=secret,
            secret_header=load_capture_config().webhook.secret_header,
            lan_host=lan_host,
        ),
        markup=False,
        highlight=False,
    )


@capture_app.command("simulate")
def simulate_cmd(
    bank: Annotated[str, typer.Option("--bank", help="hdfc, sbi, icici, axis or kotak")] = "hdfc",
    kind: Annotated[
        str, typer.Option("--kind", help="debit, credit, card, atm, autopay or reversal")
    ] = "debit",
    amount: Annotated[
        str, typer.Option("--amount", help="in rupees, for example 250 or 1,299.50")
    ] = "",
    to: Annotated[str, typer.Option("--to", help="who it was to (or from)")] = "",
    vpa: Annotated[str | None, typer.Option("--vpa", help="a UPI handle")] = None,
    user: _USER = "u1",
    db: _DB = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Send a pretend bank alert through the real pipeline. Always marked as simulated."""
    paise = (parse_amount_paise(amount) or parse_amount_paise(f"Rs {amount}")) if amount else None
    if not paise:
        print_error("Give an amount, for example --amount 250.")
        raise typer.Exit(code=1)
    out = _run(
        db,
        user,
        "simulate_payment_event",
        {
            "bank": bank, "kind": kind, "amount_paise": paise, "counterparty": to,
            **({"vpa": vpa} if vpa else {}),
        },
    )  # fmt: skip
    if as_json:
        print_json(out.model_dump(mode="json"))
        return
    print_success(
        f"Simulated {kind} of {format_inr(out.event.amount_paise)} "
        f"({'new' if out.created else 'already seen'}). Decision: {out.decision} ({out.reason})."
    )
    console.print(f"[dim]Synthetic alert: {out.sample_text}[/dim]")
    console.print(f"Event [cyan]{out.event.id}[/cyan]. Guesses:")
    for i, g in enumerate(out.guesses, 1):
        console.print(f"  {i}. {g['label']}")


@capture_app.command("inbox")
def inbox_cmd(
    user: _USER = "u1", db: _DB = None, as_json: Annotated[bool, typer.Option("--json")] = False
) -> None:
    """Payments waiting for you to say what they were."""
    out = _run(db, user, "pending_prompts", {})
    if as_json:
        print_json(out.model_dump(mode="json"))
        return
    table = Table(title="Waiting for you", box=box.ROUNDED)
    for col in ("Event", "Payee", "Amount", "Why", "Guesses"):
        table.add_column(col)
    for p in out.prompts:
        e = p.event
        sign = "+" if e.direction == "credit" else ""
        table.add_row(
            e.id + ("  [SIMULATED]" if e.simulated else ""),
            e.display_name,
            sign + format_inr(e.amount_paise),
            p.reason.replace("_", " "),
            ", ".join(g.name for g in p.guesses),
        )
    console.print(table)
    if not out.prompts:
        console.print("[dim]All caught up.[/dim]")


@capture_app.command("label")
def label_cmd(
    event_id: Annotated[str, typer.Argument(help="Payment event id")],
    category: Annotated[str | None, typer.Option("--category", help="for money going out")] = None,
    credit_kind: Annotated[
        str | None, typer.Option("--credit-kind", help="for money coming in")
    ] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Give a payment the category you choose."""
    args: dict = {"event_id": event_id}
    if category:
        args["category_id"] = category
    if credit_kind:
        args["credit_kind"] = credit_kind
    if note:
        args["note"] = note
    out = _run(db, user, "label_payment_event", args)
    print_success(f"Tagged {event_id}. To undo: copilot capture undo {out.audit_event_id}")


@capture_app.command("undo")
def undo_cmd(
    audit_event_id: Annotated[str, typer.Argument(help="Id printed when you tagged it")],
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Take a tag back."""
    _run(db, user, "undo", {"audit_event_id": audit_event_id})
    print_success("Undone.")
