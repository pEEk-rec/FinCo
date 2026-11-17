"""
The root `copilot` command and its groups. Command modules decorate these; `copilot.cli.main`
imports every module so each command is registered, in the order `--help` shows them.
"""

from typing import Annotated

import typer

app = typer.Typer(
    name="copilot",
    help="Personal Finance & Budgeting Copilot CLI",
    add_completion=False,
    no_args_is_help=True,
)

consent_app = typer.Typer(
    name="consent",
    help="Manage bank account aggregator consents",
    no_args_is_help=True,
)
app.add_typer(consent_app, name="consent")

goals_app = typer.Typer(
    name="goals",
    help="Manage financial goals",
    no_args_is_help=True,
)
app.add_typer(goals_app, name="goals")

whatif_app = typer.Typer(
    name="whatif",
    help="Simulate what-if spending decisions and scenarios",
    no_args_is_help=True,
)
app.add_typer(whatif_app, name="whatif")

alerts_app = typer.Typer(
    name="alerts",
    help="Manage adaptive financial alerts and preferences",
    no_args_is_help=True,
)
app.add_typer(alerts_app, name="alerts")

from copilot.cli.agents import agents_app  # noqa: E402
from copilot.cli.capture import capture_app  # noqa: E402
from copilot.cli.experiments import (  # noqa: E402
    adjustments_app,
    challenges_app,
    experiments_app,
    render_progress_cmd,
)
from copilot.cli.personal import me_app  # noqa: E402
from copilot.cli.sim import sim_app  # noqa: E402
from copilot.cli.understand import understand_app  # noqa: E402

app.add_typer(sim_app, name="sim")
app.add_typer(experiments_app, name="experiments")
app.add_typer(challenges_app, name="challenges")
app.add_typer(adjustments_app, name="adjustments")
app.add_typer(capture_app, name="capture")
app.add_typer(understand_app, name="understand")
app.add_typer(me_app, name="me")
app.add_typer(agents_app, name="agents")


@app.command("progress")
def progress_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display user level, XP, unlocked badges, streaks, and personal bests (PLAN_PHASE4)."""
    render_progress_cmd(user=user, db=db, json_output=json_output)
