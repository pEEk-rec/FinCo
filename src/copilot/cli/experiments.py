"""
Typer CLI commands for Phase 4 Behavioral Engagement and Gamification.

Implements CLI commands for:
- copilot experiments (design, start, list, show, pause, resume, abandon, checkin, review,
  feedback, tick)
- copilot challenges (offers, accept, dismiss)
- copilot adjustments (list, accept, reject)
- copilot progress [--json]
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.formatters import console, format_inr, print_error, print_json, print_success
from copilot.cli.storage import get_db_path, make_exec_ctx, open_db
from copilot.core.intent import parse_amount_paise
from copilot.core.review_wording import describe_review
from copilot.core.rewards import get_user_progress as core_get_user_progress
from copilot.core.timeutil import IST, from_utc_iso, now_utc
from copilot.db.repo_phase4 import (
    get_experiment as repo_get_experiment,
)
from copilot.db.repo_phase4 import (
    get_experiment_review as repo_get_experiment_review,
)
from copilot.db.repo_phase4 import (
    list_adjustment_proposals as repo_list_adjustment_proposals,
)
from copilot.db.repo_phase4 import (
    list_experiment_checkins as repo_list_experiment_checkins,
)
from copilot.db.repo_phase4 import (
    list_experiments as repo_list_experiments,
)
from copilot.db.repo_phase4 import (
    list_offers as repo_list_offers,
)
from copilot.models.phase4 import Progress
from copilot.runtime.runner import run_job
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

experiments_app = typer.Typer(
    help="Manage behavioral financial experiments (PLAN_PHASE4 Section 5.12).",
    no_args_is_help=True,
)

challenges_app = typer.Typer(
    help="Manage personalized opt-in challenges (PLAN_PHASE4 Section 5.12).",
    no_args_is_help=True,
)

adjustments_app = typer.Typer(
    help="Inspect and decide on adaptive challenge adjustments (PLAN_PHASE4 Section 5.12).",
    no_args_is_help=True,
)


def _parse_clock(clock_str: str | None) -> datetime | None:
    if not clock_str:
        return None
    try:
        return from_utc_iso(clock_str)
    except Exception:
        try:
            dt = datetime.strptime(clock_str, "%Y-%m-%d")
            return dt.replace(tzinfo=UTC)
        except Exception:
            try:
                dt = datetime.fromisoformat(clock_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST)
                return dt.astimezone(UTC)
            except Exception as exc:
                raise ValueError(f"Invalid clock timestamp: '{clock_str}'") from exc


def _parse_amt(val: str | int | None) -> int:
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    clean = str(val).strip()
    if clean.isdigit():
        return int(clean)
    parsed = parse_amount_paise(clean)
    if parsed is not None:
        return parsed
    clean_num = clean.replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
    try:
        return int(round(float(clean_num) * 100))
    except Exception as exc:
        raise ValueError(f"Invalid monetary amount: '{val}'") from exc


# =================================================================================================
# 1. Experiments Commands
# =================================================================================================


@experiments_app.command("design")
def experiments_design_cmd(
    template: Annotated[str | None, typer.Option("--template", "-t", help="Template code")] = None,
    metric: Annotated[str | None, typer.Option("--metric", "-m", help="Metric code")] = None,
    categories: Annotated[
        str | None, typer.Option("--categories", "-c", help="Comma-separated categories")
    ] = None,
    merchants: Annotated[
        str | None, typer.Option("--merchants", help="Comma-separated merchants")
    ] = None,
    duration: Annotated[
        int, typer.Option("--duration", "-d", help="Duration in days (7..56)")
    ] = 14,
    difficulty: Annotated[
        str, typer.Option("--difficulty", help="Difficulty: easy, medium, hard")
    ] = "medium",
    target: Annotated[
        str | None, typer.Option("--target", help="Target value (e.g. ₹2500)")
    ] = None,
    baseline_median: Annotated[
        str | None, typer.Option("--baseline-median", help="Baseline median (e.g. ₹5000)")
    ] = None,
    start_date: Annotated[
        str | None, typer.Option("--start-date", help="Window start date YYYY-MM-DD")
    ] = None,
    goal_id: Annotated[str | None, typer.Option("--goal-id", help="Linked goal ID")] = None,
    rationale: Annotated[
        str | None, typer.Option("--rationale", help="Hypothesis rationale")
    ] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Design a structured financial experiment hypothesis."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)

        cat_list = [c.strip() for c in categories.split(",")] if categories else []
        merch_list = [m.strip() for m in merchants.split(",")] if merchants else []
        target_paise = _parse_amt(target) if target else None
        base_med_paise = _parse_amt(baseline_median) if baseline_median else None

        res = execute_tool(
            ctx,
            "design_experiment",
            {
                "template_code": template,
                "metric_code": metric or "category_spend",
                "categories": cat_list,
                "merchants": merch_list,
                "duration_days": duration,
                "difficulty": difficulty,
                "target_value": target_paise,
                "baseline_median": base_med_paise,
                "start_date": start_date,
                "goal_id": goal_id,
                "rationale": rationale,
            },
        )
        if not res.ok:
            print_error(f"Failed to design experiment: {res.error}")
            raise typer.Exit(1)

        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return

        exp_data = data.get("experiment", {})
        hyp = exp_data.get("hypothesis_json", {})
        baseline = exp_data.get("baseline_json", {})
        console.print(
            Panel(
                f"[bold cyan]Intervention:[/bold cyan] {hyp.get('intervention')}\n"
                f"[bold cyan]Metric:[/bold cyan] {hyp.get('metric')} ({hyp.get('direction')} {format_inr(hyp.get('target', 0))})\n"  # noqa: E501
                f"[bold cyan]Duration:[/bold cyan] {exp_data.get('duration_days')} days | [bold cyan]Difficulty:[/bold cyan] {exp_data.get('difficulty')}\n"  # noqa: E501
                f"[bold cyan]Baseline Range:[/bold cyan] {format_inr(baseline.get('low', 0))} to {format_inr(baseline.get('high', 0))} "  # noqa: E501
                f"(Median: {format_inr(baseline.get('median', 0))}, K={baseline.get('k')})\n"
                f"[bold cyan]Statement:[/bold cyan] [italic]If I {hyp.get('intervention')}, then {hyp.get('metric')} will be {hyp.get('direction')} {format_inr(hyp.get('target', 0))}[/italic]",  # noqa: E501
                title=f"Experiment Design: {exp_data.get('title', 'Custom Experiment')}",
                box=box.ROUNDED,
            )
        )
    finally:
        conn.close()


@experiments_app.command("start")
def experiments_start_cmd(
    experiment_id: Annotated[
        str | None, typer.Option("--id", help="Experiment ID to start directly")
    ] = None,
    title: Annotated[str | None, typer.Option("--title", help="Experiment title")] = None,
    metric: Annotated[str | None, typer.Option("--metric", "-m", help="Metric code")] = None,
    template: Annotated[str | None, typer.Option("--template", "-t", help="Template code")] = None,
    categories: Annotated[
        str | None, typer.Option("--categories", "-c", help="Comma-separated categories")
    ] = None,
    merchants: Annotated[
        str | None, typer.Option("--merchants", help="Comma-separated merchants")
    ] = None,
    duration: Annotated[int, typer.Option("--duration", "-d", help="Duration in days")] = 14,
    difficulty: Annotated[
        str, typer.Option("--difficulty", help="Difficulty: easy, medium, hard")
    ] = "medium",
    target: Annotated[str, typer.Option("--target", help="Target value (e.g. ₹2500)")] = "0",
    baseline_median: Annotated[
        str | None, typer.Option("--baseline-median", help="Baseline median (e.g. ₹5000)")
    ] = None,
    start_date: Annotated[
        str | None, typer.Option("--start-date", help="Window start date YYYY-MM-DD")
    ] = None,
    goal_id: Annotated[str | None, typer.Option("--goal-id", help="Linked goal ID")] = None,
    rationale: Annotated[
        str | None, typer.Option("--rationale", help="Hypothesis rationale")
    ] = None,
    origin: Annotated[
        str, typer.Option("--origin", help="Origin: user, offer, goal_decomposition")
    ] = "user",
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Start an active financial experiment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)

        exp_id = experiment_id
        if not exp_id:
            cat_list = [c.strip() for c in categories.split(",")] if categories else []
            merch_list = [m.strip() for m in merchants.split(",")] if merchants else []
            target_paise = _parse_amt(target)
            base_med_paise = _parse_amt(baseline_median) if baseline_median else target_paise

            des_res = execute_tool(
                ctx,
                "design_experiment",
                {
                    "title": title or "Custom Experiment",
                    "metric_code": metric or "category_spend",
                    "template_code": template,
                    "categories": cat_list,
                    "merchants": merch_list,
                    "duration_days": duration,
                    "difficulty": difficulty,
                    "target_value": target_paise,
                    "baseline_median": base_med_paise,
                    "start_date": start_date,
                    "goal_id": goal_id,
                    "rationale": rationale,
                    "origin": origin,
                },
            )
            if not des_res.ok:
                print_error(f"Failed to design experiment before start: {des_res.error}")
                raise typer.Exit(1)
            exp_id = des_res.data.experiment.id

        res = execute_tool(
            ctx,
            "start_experiment",
            {"experiment_id": exp_id},
        )
        if not res.ok:
            print_error(f"Failed to start experiment: {res.error}")
            raise typer.Exit(1)

        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return

        exp_obj = res.data.experiment
        print_success(
            f"Started experiment '[bold]{exp_obj.title}[/bold]' (ID: [cyan]{exp_obj.id}[/cyan])\n"
            f"Window: {exp_obj.window_start} to {exp_obj.window_end} | Target: {format_inr(exp_obj.target_value)}"  # noqa: E501
        )
    finally:
        conn.close()


@experiments_app.command("list")
def experiments_list_cmd(
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List financial experiments."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        exps = repo_list_experiments(conn, user_id=user, status=status)
        if json_output:
            print_json([e.model_dump(mode="json") for e in exps])
            return

        table = Table(title=f"Experiments for User '{user}'", box=box.ROUNDED)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="bold")
        table.add_column("Metric", style="green")
        table.add_column("Status", style="magenta")
        table.add_column("Target", justify="right")
        table.add_column("Window Start", style="dim")
        table.add_column("Window End", style="dim")

        for e in exps:
            status_style = "bold green" if e.status == "active" else "dim"
            metric_str = e.metric_def_json.get("metric", e.metric_def_json.get("metric_code", ""))
            table.add_row(
                e.id,
                e.title,
                metric_str,
                f"[{status_style}]{e.status}[/{status_style}]",
                format_inr(e.target_value),
                e.window_start,
                e.window_end,
            )
        console.print(table)
        if not exps:
            console.print("[dim]No experiments found.[/dim]")
    finally:
        conn.close()


@experiments_app.command("show")
def experiments_show_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show details and mid-experiment pace for an experiment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)

        exp = repo_get_experiment(conn, user_id=user, experiment_id=experiment_id)
        if not exp:
            print_error(f"Experiment '{experiment_id}' not found.")
            raise typer.Exit(1)

        res = execute_tool(ctx, "experiment_progress", {"experiment_id": experiment_id})
        progress_data = (
            res.data.model_dump(mode="json")
            if (res.ok and hasattr(res.data, "model_dump"))
            else (res.data if res.ok else {})
        )

        full_data = {
            "experiment": exp.model_dump(mode="json"),
            "progress": progress_data,
        }
        if json_output:
            print_json(full_data)
            return

        prog_inner = progress_data.get("progress", {})
        pace_status = prog_inner.get("pace_status", "unknown")
        obs_val = prog_inner.get("observed_value", 0)
        exp_target = exp.target_value

        pace_style = "bold green" if pace_status in ("ahead", "on_pace") else "bold yellow"
        hyp = exp.hypothesis_json
        base = exp.baseline_json

        console.print(
            Panel(
                f"[bold cyan]ID:[/bold cyan] {exp.id} | [bold cyan]Status:[/bold cyan] {exp.status}\n"  # noqa: E501
                f"[bold cyan]Hypothesis:[/bold cyan] Intervention: {hyp.get('intervention')} | "
                f"Target: {hyp.get('direction')} {format_inr(hyp.get('target', 0))}\n"
                f"[bold cyan]Window:[/bold cyan] {exp.window_start} to {exp.window_end} "
                f"({prog_inner.get('elapsed_days', 0)}/{prog_inner.get('total_days', 0)} days elapsed)\n"  # noqa: E501
                f"[bold cyan]Target:[/bold cyan] {format_inr(exp_target)} | "
                f"[bold cyan]Observed to date:[/bold cyan] {format_inr(obs_val)}\n"
                f"[bold cyan]Pace Status:[/bold cyan] [{pace_style}]{pace_status.upper()}[/{pace_style}]\n"  # noqa: E501
                f"[bold cyan]Baseline Range:[/bold cyan] {format_inr(base.get('low', 0))} to {format_inr(base.get('high', 0))} "  # noqa: E501
                f"(Median: {format_inr(base.get('median', 0))}, K={base.get('k')})",
                title=f"Experiment: {exp.title}",
                box=box.ROUNDED,
            )
        )
    finally:
        conn.close()


@experiments_app.command("pause")
def experiments_pause_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Pause an active experiment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "pause_experiment", {"experiment_id": experiment_id})
        if not res.ok:
            print_error(f"Failed to pause experiment: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(f"Paused experiment '[bold]{experiment_id}[/bold]'.")
    finally:
        conn.close()


@experiments_app.command("resume")
def experiments_resume_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Resume a paused experiment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "resume_experiment", {"experiment_id": experiment_id})
        if not res.ok:
            print_error(f"Failed to resume experiment: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(f"Resumed experiment '[bold]{experiment_id}[/bold]'.")
    finally:
        conn.close()


@experiments_app.command("abandon")
def experiments_abandon_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    reason: Annotated[str | None, typer.Option("--reason", "-r", help="Optional reason")] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Abandon an experiment without penalty or shame."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(
            ctx, "abandon_experiment", {"experiment_id": experiment_id, "reason": reason}
        )
        if not res.ok:
            print_error(f"Failed to abandon experiment: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(
            f"Experiment '[bold]{experiment_id}[/bold]' abandoned. "
            "You can still review what happened and earn learning XP."
        )
    finally:
        conn.close()


@experiments_app.command("checkin")
def experiments_checkin_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID or Checkin ID")],
    response: Annotated[
        str, typer.Argument(help="Response: going_well, hard, want_to_pause, skip")
    ],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Answer a scheduled experiment check-in."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)

        checkin_id = experiment_id if experiment_id.startswith("chk_") else None
        if not checkin_id:
            from copilot.core.experiments import create_checkins as core_create_checkins

            chks = repo_list_experiment_checkins(conn, user_id=user, experiment_id=experiment_id)
            if chks:
                checkin_id = chks[-1].id
            else:
                created = core_create_checkins(conn, user_id=user, clock=clock_dt)
                matching = [c for c in created if c.experiment_id == experiment_id]
                if matching:
                    checkin_id = matching[0].id
                else:
                    exp = repo_get_experiment(conn, user_id=user, experiment_id=experiment_id)
                    if exp is not None and exp.status == "active":
                        import uuid

                        from copilot.core.experiments import calculate_pace
                        from copilot.core.metrics import calculate_metric
                        from copilot.core.timeutil import IST, to_utc_iso
                        from copilot.db.repo_phase4 import insert_experiment_checkin
                        from copilot.models.phase4 import ExperimentCheckin

                        now_dt = clock_dt or now_utc()
                        cur_date_str = now_dt.astimezone(IST).date().isoformat()
                        obs = calculate_metric(
                            conn,
                            user,
                            metric_code=exp.metric_def_json["metric_code"],
                            start_date=exp.window_start,
                            end_date=cur_date_str,
                            params=exp.params_json,
                        )
                        pace = calculate_pace(
                            observed_value=obs,
                            target_value=exp.target_value,
                            start_date=exp.window_start,
                            end_date=exp.window_end,
                            as_of_date=cur_date_str,
                            metric_code=exp.metric_def_json["metric_code"],
                        )
                        chk = ExperimentCheckin(
                            id=f"chk_{uuid.uuid4().hex[:12]}",
                            user_id=user,
                            experiment_id=exp.id,
                            checkin_date=cur_date_str,
                            observed_value=obs,
                            pace_status=pace,
                            created_at=to_utc_iso(now_dt),
                        )
                        insert_experiment_checkin(conn, chk)
                        checkin_id = chk.id
                    else:
                        print_error(f"No check-in found or due for experiment '{experiment_id}'.")
                        raise typer.Exit(1)

        res = execute_tool(
            ctx,
            "answer_checkin",
            {"checkin_id": checkin_id, "response": response},
        )
        if not res.ok:
            print_error(f"Failed to submit check-in: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(
            f"Recorded check-in response '[cyan]{response}[/cyan]' for check-in '{checkin_id}'."
        )
    finally:
        conn.close()


@experiments_app.command("review")
def experiments_review_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID to inspect review")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show review outcome and honest rank-based measurement for an experiment."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        review = repo_get_experiment_review(conn, user_id=user, experiment_id=experiment_id)
        if not review:
            print_error(f"Review for experiment '{experiment_id}' not found or not yet generated.")
            raise typer.Exit(1)

        data = review.model_dump(mode="json")
        if json_output:
            print_json(data)
            return

        experiment = repo_get_experiment(conn, user_id=user, experiment_id=experiment_id)
        if experiment is not None:
            wording = describe_review(experiment, review)
            console.print(
                Panel(wording.text(), title="Experiment review", box=box.ROUNDED, expand=False)
            )
            if wording.needs_confirmation:
                console.print(
                    f"To confirm: copilot experiments confirm {experiment_id} --user {user}"
                )

        # Neutral colours: the measurement is information, not a verdict
        outcome_style = "bold green" if review.outcome == "beyond_usual_range" else "cyan"
        target_str = "yes" if review.target_met else "not this time"

        console.print(
            Panel(
                f"[bold cyan]Experiment ID:[/bold cyan] {review.experiment_id}\n"
                f"[bold cyan]Observed Value:[/bold cyan] {format_inr(review.observed_value)}\n"
                f"[bold cyan]Outcome:[/bold cyan] [{outcome_style}]{review.outcome.upper()}[/{outcome_style}]\n"  # noqa: E501
                f"[bold cyan]Effect Value:[/bold cyan] {format_inr(review.effect_value)} (Median - Observed)\n"  # noqa: E501
                f"[bold cyan]Rank P-Value:[/bold cyan] {review.rank_p_bp / 100:.2f}%\n"
                f"[bold cyan]Target Met:[/bold cyan] {target_str}\n"
                f"[bold cyan]User Feedback:[/bold cyan] Difficulty: {review.user_difficulty or 'none'}, "  # noqa: E501
                f"Helpful: {review.user_helpful}, Would Repeat: {review.user_would_repeat}",
                title="Experiment Review (Honest Measurement)",
                box=box.ROUNDED,
            )
        )
    finally:
        conn.close()


@experiments_app.command("confirm")
def experiments_confirm_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
) -> None:
    """Confirm that payments recategorised during the window were genuine corrections."""
    ensure_tools_registered()
    conn = open_db(get_db_path(db))
    try:
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=_parse_clock(clock))
        res = execute_tool(ctx, "confirm_review_integrity", {"experiment_id": experiment_id})
        if not res.ok:
            print_error(f"Could not confirm: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        print_success("Confirmed. The target can now count toward rewards.")
    finally:
        conn.close()


@experiments_app.command("feedback")
def experiments_feedback_cmd(
    experiment_id: Annotated[str, typer.Argument(help="Experiment ID")],
    difficulty: Annotated[
        int, typer.Option("--difficulty", "-d", min=1, max=5, help="Difficulty (1..5)")
    ] = 3,
    helpful: Annotated[
        bool | None, typer.Option("--helpful/--unhelpful", help="Was this helpful?")
    ] = None,
    repeat: Annotated[
        bool | None, typer.Option("--repeat/--no-repeat", help="Would you repeat?")
    ] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Submit post-experiment review feedback to update learning loop."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(
            ctx,
            "submit_review_feedback",
            {
                "experiment_id": experiment_id,
                "user_difficulty": difficulty,
                "user_helpful": helpful,
                "user_would_repeat": repeat,
            },
        )
        if not res.ok:
            print_error(f"Failed to submit feedback: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success("Feedback recorded. Template posteriors and behavioral memory updated.")
    finally:
        conn.close()


@experiments_app.command("tick")
def experiments_tick_cmd(
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Execute background runtime jobs (checkins, reviews, detectors, rewards, expiries)."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock) or now_utc()
        jobs = [
            "expire_offers",
            "run_adaptive_detectors",
            "create_checkins",
            "create_due_reviews",
            "award_xp_and_badges",
        ]
        results = {}
        for job in jobs:
            run = run_job(conn, user_id=user, job_kind=job, as_of=clock_dt, force=True)
            results[job] = {
                "run_id": run.id,
                "status": run.status,
                "summary": run.summary_json,
            }
        conn.commit()

        if json_output:
            print_json(results)
            return

        table = Table(
            title=f"Runtime Tick Results ({clock_dt.strftime('%Y-%m-%d %H:%M:%S UTC')})",
            box=box.ROUNDED,
        )
        table.add_column("Job Kind", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Details", style="dim")

        for k, v in results.items():
            summary_str = json.dumps(v.get("summary") or {})
            table.add_row(k, v["status"], summary_str)
        console.print(table)
        print_success("Executed all Phase 4 runtime tick jobs.")
    finally:
        conn.close()


# =================================================================================================
# 2. Challenges Commands
# =================================================================================================


@challenges_app.command("offers")
def challenges_offers_cmd(
    week_start: Annotated[
        str | None, typer.Option("--week-start", help="Week start date YYYY-MM-DD")
    ] = None,
    generate: Annotated[
        bool, typer.Option("--generate/--no-generate", help="Generate offers if none shown")
    ] = True,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List or generate weekly personalized challenge offers."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock) or now_utc()
        w_start = week_start or clock_dt.strftime("%Y-%m-%d")

        offers = repo_list_offers(conn, user_id=user, status="shown")
        if not offers and generate:
            # Generate new offers
            ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
            res = execute_tool(ctx, "suggest_challenges", {"week_start": w_start})
            conn.commit()
            if not res.ok:
                print_error(f"Could not generate offers: {res.error.message}")
                raise typer.Exit(code=1)
            offers = repo_list_offers(conn, user_id=user, status="shown")

        if json_output:
            print_json([o.model_dump(mode="json") for o in offers])
            return

        table = Table(title=f"Weekly Challenge Offers for User '{user}'", box=box.ROUNDED)
        table.add_column("Offer ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="bold")
        table.add_column("Metric", style="green")
        table.add_column("Difficulty", style="magenta")
        table.add_column("Target", justify="right")
        table.add_column("Propensity", justify="right")
        table.add_column("Reason")

        for o in offers:
            title = o.params_json.get("title", o.template_code)
            metric = o.params_json.get("metric_code", "")
            target = o.params_json.get("target_value", 0)
            said = o.reason_json or {}
            reason = said.get("statement") or said.get("text") or ""
            table.add_row(
                o.id,
                title,
                metric,
                o.difficulty,
                format_inr(target),
                f"{o.propensity_bp / 100:.1f}%",
                reason,
            )
        console.print(table)
        if not offers:
            console.print(
                "[dim]No active challenge offers. (May be in rest weeks or all dismissed).[/dim]"
            )
    finally:
        conn.close()


@challenges_app.command("accept")
def challenges_accept_cmd(
    offer_id: Annotated[str, typer.Argument(help="Offer ID to accept")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Accept an opt-in challenge offer to start an experiment."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "accept_offer", {"offer_id": offer_id})
        if not res.ok:
            print_error(f"Failed to accept offer: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(
            f"Accepted offer '{offer_id}'. Started active experiment '[bold cyan]{data.get('experiment_id')}[/bold cyan]'."  # noqa: E501
        )
    finally:
        conn.close()


@challenges_app.command("dismiss")
def challenges_dismiss_cmd(
    offer_id: Annotated[str, typer.Argument(help="Offer ID to dismiss")],
    reason: Annotated[
        str | None, typer.Option("--reason", "-r", help="Optional dismissal reason")
    ] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Dismiss a challenge offer with a plain 'Not now'."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "dismiss_offer", {"offer_id": offer_id, "reason": reason})
        if not res.ok:
            print_error(f"Failed to dismiss offer: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(f"Dismissed offer '{offer_id}'. No penalty or guilt recorded.")
    finally:
        conn.close()


# =================================================================================================
# 3. Adjustments Commands
# =================================================================================================


@adjustments_app.command("list")
def adjustments_list_cmd(
    experiment_id: Annotated[
        str | None, typer.Option("--experiment-id", "-e", help="Filter by experiment ID")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List adaptive difficulty adjustments."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        proposals = repo_list_adjustment_proposals(
            conn, user_id=user, experiment_id=experiment_id, status=status
        )
        if json_output:
            print_json([p.model_dump(mode="json") for p in proposals])
            return

        table = Table(title=f"Adjustment Proposals for User '{user}'", box=box.ROUNDED)
        table.add_column("Proposal ID", style="cyan", no_wrap=True)
        table.add_column("Experiment ID", style="blue")
        table.add_column("Kind", style="magenta")
        table.add_column("Reason Code")
        table.add_column("Status", style="bold")
        table.add_column("Created At", style="dim")

        for p in proposals:
            table.add_row(
                p.id,
                p.experiment_id,
                p.kind,
                p.reason_code,
                p.status,
                p.created_at,
            )
        console.print(table)
        if not proposals:
            console.print("[dim]No adjustment proposals found.[/dim]")
    finally:
        conn.close()


@adjustments_app.command("accept")
def adjustments_accept_cmd(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID to accept")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Accept an adaptive adjustment proposal."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "accept_adjustment", {"proposal_id": proposal_id})
        if not res.ok:
            print_error(f"Failed to accept adjustment: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(f"Accepted adjustment '{proposal_id}'.")
    finally:
        conn.close()


@adjustments_app.command("reject")
def adjustments_reject_cmd(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID to reject")],
    reason: Annotated[str | None, typer.Option("--reason", "-r", help="Optional reason")] = None,
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")] = "u1",
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    clock: Annotated[str | None, typer.Option("--clock", help="Simulated clock ISO string")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Reject an adaptive adjustment proposal."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        clock_dt = _parse_clock(clock)
        ctx = make_exec_ctx(conn, user_id=user, actor="user", clock=clock_dt)
        res = execute_tool(ctx, "reject_adjustment", {"proposal_id": proposal_id, "reason": reason})
        if not res.ok:
            print_error(f"Failed to reject adjustment: {res.error}")
            raise typer.Exit(1)
        conn.commit()
        data = res.data.model_dump(mode="json") if hasattr(res.data, "model_dump") else res.data
        if json_output:
            print_json(data)
            return
        print_success(f"Rejected adjustment '{proposal_id}'. Target remains unchanged.")
    finally:
        conn.close()


# =================================================================================================
# 4. Progress & Gamification
# =================================================================================================


def render_progress_cmd(
    user: str = "u1",
    db: str | None = None,
    json_output: bool = False,
) -> None:
    """Display user level, XP, unlocked badges, streaks, and personal bests."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    try:
        progress: Progress = core_get_user_progress(conn, user_id=user)
        if json_output:
            print_json(progress.model_dump(mode="json"))
            return

        # 1. Main Profile Panel
        console.print(
            Panel(
                f"[bold cyan]Level:[/bold cyan] {progress.level_number} ({progress.level_name})\n"
                f"[bold cyan]Total XP:[/bold cyan] {progress.total_xp} points\n"
                f"[bold cyan]Level Progress:[/bold cyan] {progress.xp_in_level} XP earned in current tier\n"  # noqa: E501
                f"[bold cyan]Next Tier:[/bold cyan] {progress.xp_for_next_level or 'Max tier reached'} XP",  # noqa: E501
                title=f"User Progress: '{user}'",
                box=box.ROUNDED,
            )
        )

        # 2. Badges Table
        badge_table = Table(title="Unlocked Badges", box=box.ROUNDED)
        badge_table.add_column("Badge Code", style="bold green")
        badge_table.add_column("Awarded At", style="dim")

        for b in progress.badges:
            badge_table.add_row(b.badge_code, b.awarded_at)
        console.print(badge_table)
        if not progress.badges:
            console.print("[dim]No badges unlocked yet.[/dim]")

        # 3. Streaks Table
        streak_table = Table(title="Active Streaks (Forgiving)", box=box.ROUNDED)
        streak_table.add_column("Streak", style="cyan")
        streak_table.add_column("Current Length", justify="right", style="bold")

        for streak_name, length in progress.active_streaks.items():
            streak_table.add_row(streak_name, f"{length} days")
        console.print(streak_table)

        # 4. Personal Bests Table
        bests_table = Table(title="Personal Bests (Self-Competition Only)", box=box.ROUNDED)
        bests_table.add_column("Metric", style="green")
        bests_table.add_column("Window", justify="right")
        bests_table.add_column("Best Value", justify="right", style="bold")
        bests_table.add_column("Achieved On", style="dim")

        for pb in progress.personal_bests:
            bests_table.add_row(
                pb.metric_code,
                f"{pb.window_length_days}d",
                format_inr(pb.best_value) if "spend" in pb.metric_code else str(pb.best_value),
                pb.achieved_at,
            )
        console.print(bests_table)
        if not progress.personal_bests:
            console.print("[dim]No personal bests recorded yet.[/dim]")
    finally:
        conn.close()
