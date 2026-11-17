"""
`copilot agents`: every agent in FinCo, what wakes it, what it does, how it checks itself.

    copilot agents            # the table
    copilot agents checkin    # one agent in full
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.agents.registry import AGENTS, get
from copilot.cli.formatters import console, print_error

agents_app = typer.Typer(
    help="The agents in FinCo and how each one runs.", invoke_without_command=True
)


@agents_app.callback()
def agents_cmd(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="one agent to describe")] = None,
) -> None:
    if ctx.invoked_subcommand:
        return
    if name:
        info = get(name)
        if info is None:
            print_error(f"No agent called {name!r}.")
            raise typer.Exit(code=2)
        for label, value in (
            ("Agent", info.name), ("Wakes on", info.trigger), ("Goal", info.goal),
            ("Runs as", info.runs_as), ("Entry", info.entry), ("Tools", info.tools),
            ("Checks itself by", info.checks), ("Result goes to", info.output),
        ):  # fmt: skip
            console.print(f"[bold]{label}:[/bold] {value}")
        return
    t = Table(title="Agents", box=box.ROUNDED)
    for col in ("Agent", "Wakes on", "Runs as", "Goal"):
        t.add_column(col)
    for a in AGENTS:
        t.add_row(a.name, a.trigger, a.runs_as, a.goal)
    console.print(t)
