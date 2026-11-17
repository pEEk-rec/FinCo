"""
The `copilot` command line. Each area's commands live in their own module; importing them
here registers them on `copilot.cli.app.app`. Run with `copilot ...` or
`python -m copilot.cli.main ...`.
"""

# The import order below is the order `copilot --help` lists the commands in.
# isort: off
from copilot.cli import (  # noqa: F401  (imported for their commands)
    data,
    consent,
    review,
    ledger,
    audit,
    goals,
    whatif,
    alerts,
    ask,
    commitments,
    planning,
    memory,
    runtime,
    learning,
)

# isort: on
from copilot.cli.app import app
from copilot.cli.common import parse_cli_amount

__all__ = ["app", "parse_cli_amount"]

if __name__ == "__main__":
    app()
