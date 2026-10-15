"""
CLI sub-application for offline policy simulation and off-policy evaluation.
(PLAN_PHASE4 Section 5.12 & Stage 4.9)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure project root is on sys.path for eval.sim
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from eval.sim.off_policy import evaluate_arm_off_policy  # noqa: E402
from eval.sim.personas import get_default_personas  # noqa: E402
from eval.sim.simulator import run_simulation  # noqa: E402

sim_app = typer.Typer(
    name="sim",
    help="Offline offer policy simulation and evaluation",
    no_args_is_help=True,
)
console = Console()


@sim_app.command(name="run", help="Run multi-week decision simulator under an offer policy.")
def run_sim_command(
    policy: Annotated[
        Literal["thompson", "greedy", "random"],
        typer.Option("--policy", "-p", help="Policy algorithm: thompson, greedy, or random"),
    ] = "thompson",
    persona_name: Annotated[
        str,
        typer.Option("--persona", help="Persona name: ThriftyCook, BusyCommuter, or FickleDrifter"),
    ] = "ThriftyCook",
    weeks: Annotated[
        int,
        typer.Option("--weeks", "-w", help="Number of simulated weeks (default: 52)"),
    ] = 52,
    seed: Annotated[
        int,
        typer.Option("--seed", "-s", help="Random seed for simulation reproducibility"),
    ] = 42,
    max_offers: Annotated[
        int,
        typer.Option("--max-offers", help="Max candidate offers presented per week"),
    ] = 3,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw simulation result as JSON"),
    ] = False,
) -> None:
    personas = get_default_personas()
    if persona_name not in personas:
        console.print(
            f"[bold red]Unknown persona:[/bold red] '{persona_name}'. "
            f"Available personas: {list(personas.keys())}"
        )
        raise typer.Exit(code=1)

    persona = personas[persona_name]
    res = run_simulation(
        policy=policy,
        persona=persona,
        weeks=weeks,
        seed=seed,
        max_offers=max_offers,
    )

    if output_json:
        data = {
            "policy": res.policy_name,
            "persona": res.persona_name,
            "weeks": res.weeks,
            "seed": res.seed,
            "total_reward": res.total_reward,
            "best_fixed_arm": res.best_fixed_arm,
            "best_fixed_reward": res.best_fixed_reward,
            "cumulative_regret": res.cumulative_regret,
            "offers_shown": res.offers_shown,
            "offers_accepted": res.offers_accepted,
            "offers_completed": res.offers_completed,
            "rest_weeks_count": res.rest_weeks_count,
            "interactions_count": len(res.history),
        }
        console.print(json.dumps(data, indent=2))
        return

    table = Table(title="Policy Simulation Results", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim", width=25)
    table.add_column("Value", style="bold green")

    table.add_row("Policy", res.policy_name.upper())
    table.add_row("Persona", f"{res.persona_name} ({persona.description})")
    table.add_row("Simulated Weeks", str(res.weeks))
    table.add_row("Seed", str(res.seed))
    table.add_row("Total Reward", f"{res.total_reward:.2f}")
    table.add_row("Best Fixed Arm", f"{res.best_fixed_arm} ({res.best_fixed_reward:.2f})")
    table.add_row("Cumulative Regret", f"{res.cumulative_regret:.2f}")
    table.add_row("Offers Shown", str(res.offers_shown))
    table.add_row("Offers Accepted", str(res.offers_accepted))
    table.add_row("Offers Completed", str(res.offers_completed))
    table.add_row("Rest Weeks Triggered", str(res.rest_weeks_count))

    # Evaluate best arm off-policy if we have history
    if res.history:
        ips, snips = evaluate_arm_off_policy(res.history, res.best_fixed_arm)
        ips_desc = (
            f"{ips.estimate:.4f} ± {ips.error_bound:.4f} "
            f"(SE: {ips.standard_error:.4f}, ESS: {ips.effective_sample_size})"
        )
        table.add_row("IPS Best Arm Value", ips_desc)
        table.add_row(
            "SNIPS Best Arm Value",
            f"{snips.estimate:.4f} ± {snips.error_bound:.4f} (SE: {snips.standard_error:.4f})",
        )

    console.print(
        Panel(table, title="[bold cyan]FinCo Simulation Engine[/bold cyan]", expand=False)
    )
