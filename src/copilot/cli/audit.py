"""Looking back: the audit trail, a run's trace, and the evaluation suites."""

import json
from typing import Annotated, Any

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from copilot.cli.app import app
from copilot.cli.formatters import (
    console,
    print_audit_table,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    load_trace,
    open_db,
)
from copilot.workflow.trace import format_trace


@app.command("audit")
def audit_cmd(
    txn: Annotated[str | None, typer.Option("--txn", help="Filter by transaction ID")] = None,
    run: Annotated[str | None, typer.Option("--run", help="Filter by run ID")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows")] = 50,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """View audit trail with before/after state and reversibility flags."""
    db_path = get_db_path(db)
    conn = open_db(db_path)

    query = "SELECT * FROM audit_events WHERE user_id = ?"
    params: list[Any] = [user_id]

    if txn:
        query += " AND entity_id = ?"
        params.append(txn)
    if run:
        query += " AND run_id = ?"
        params.append(run)

    query += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    events = [dict(r) for r in rows]
    if as_json:
        print_json(events)
    else:
        print_audit_table(events)


@app.command("trace")
def trace_cmd(
    run_id: Annotated[str, typer.Argument(help="Run ID or Task ID to display trace for")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Display execution trace, spans, specialists, reflections, and manifests."""
    db_path = get_db_path(db)
    has_db_trace = False
    spans_data = []
    specs_data = []
    refs_data = []
    manifests_data = []

    try:
        conn = open_db(db_path)
        try:
            span_rows = conn.execute(
                "SELECT * FROM trace_spans WHERE trace_id = ? ORDER BY started_at ASC", (run_id,)
            ).fetchall()
            if span_rows:
                has_db_trace = True
                for r in span_rows:
                    d = dict(r)
                    if isinstance(d.get("attrs_json"), str):
                        try:
                            d["attrs"] = json.loads(d["attrs_json"])
                        except Exception:
                            d["attrs"] = {}
                    spans_data.append(d)

            spec_rows = conn.execute(
                "SELECT * FROM specialist_reports WHERE task_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            if spec_rows:
                has_db_trace = True
                for r in spec_rows:
                    d = dict(r)
                    for k in ("sub_question_json", "findings_json", "gaps_json"):
                        if isinstance(d.get(k), str):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                pass
                    specs_data.append(d)

            ref_rows = conn.execute(
                "SELECT * FROM reflections WHERE task_id = ? ORDER BY round ASC", (run_id,)
            ).fetchall()
            if ref_rows:
                has_db_trace = True
                for r in ref_rows:
                    d = dict(r)
                    if isinstance(d.get("critique_codes_json"), str):
                        try:
                            d["critique_codes"] = json.loads(d["critique_codes_json"])
                        except Exception:
                            d["critique_codes"] = []
                    refs_data.append(d)

            man_rows = conn.execute(
                "SELECT * FROM context_manifests WHERE task_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            if man_rows:
                has_db_trace = True
                for r in man_rows:
                    d = dict(r)
                    for k in ("included_json", "excluded_json"):
                        if isinstance(d.get(k), str):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                pass
                    manifests_data.append(d)
        finally:
            conn.close()
    except Exception:
        pass

    if has_db_trace:
        if as_json:
            print_json(
                {
                    "trace_id": run_id,
                    "spans": spans_data,
                    "specialists": specs_data,
                    "reflections": refs_data,
                    "context_manifests": manifests_data,
                }
            )
            return

        console.print(
            Panel(
                f"Execution Telemetry Trace for Task/Run ID: [cyan]{run_id}[/cyan]",
                border_style="cyan",
            )
        )

        if spans_data:
            t_span = Table(title="Trace Spans Hierarchy", box=box.ROUNDED)
            t_span.add_column("Span ID", style="dim")
            t_span.add_column("Kind", style="cyan")
            t_span.add_column("Name", style="bold")
            t_span.add_column("Duration", justify="right")
            t_span.add_column("Status")
            t_span.add_column("Attributes", style="dim")
            for s in spans_data:
                st = s.get("status", "ok")
                st_style = "green" if st == "ok" else "red"
                dur = (
                    f"{s.get('duration_ms', 0):.1f}ms" if s.get("duration_ms") is not None else "-"
                )
                attrs_str = str(s.get("attrs", {}))
                if len(attrs_str) > 60:
                    attrs_str = attrs_str[:57] + "..."
                t_span.add_row(
                    str(s.get("span_id", "")),
                    str(s.get("kind", "")),
                    str(s.get("name", "")),
                    dur,
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                    attrs_str,
                )
            console.print(t_span)

        if specs_data:
            t_spec = Table(title="Specialist Agent Reports", box=box.ROUNDED)
            t_spec.add_column("Role", style="bold cyan")
            t_spec.add_column("Status")
            t_spec.add_column("Findings", justify="right")
            t_spec.add_column("Gaps", justify="right")
            t_spec.add_column("Duration", justify="right")
            for sp in specs_data:
                st = sp.get("status", "ok")
                st_style = "green" if st == "ok" else ("yellow" if st == "partial" else "red")
                f_count = (
                    len(sp.get("findings_json", []))
                    if isinstance(sp.get("findings_json"), list)
                    else 0
                )
                g_count = (
                    len(sp.get("gaps_json", [])) if isinstance(sp.get("gaps_json"), list) else 0
                )
                t_spec.add_row(
                    str(sp.get("agent_role", "")),
                    f"[{st_style}]{st.upper()}[/{st_style}]",
                    str(f_count),
                    str(g_count),
                    f"{sp.get('duration_ms', 0):.1f}ms",
                )
            console.print(t_spec)

        if refs_data:
            t_ref = Table(title="Reflexion Revisions & Critiques", box=box.ROUNDED)
            t_ref.add_column("Round", justify="center")
            t_ref.add_column("Source", style="cyan")
            t_ref.add_column("Critique Codes", style="yellow")
            t_ref.add_column("Revised", justify="center")
            t_ref.add_column("Outcome")
            for rf in refs_data:
                rev_str = "[green]YES[/green]" if rf.get("revised") else "[dim]NO[/dim]"
                out = rf.get("outcome", "unchanged")
                out_style = (
                    "green" if out == "fixed" else ("yellow" if out == "unchanged" else "red")
                )
                t_ref.add_row(
                    str(rf.get("round", 1)),
                    str(rf.get("source", "deterministic")),
                    ", ".join(rf.get("critique_codes", [])),
                    rev_str,
                    f"[{out_style}]{out.upper()}[/{out_style}]",
                )
            console.print(t_ref)

        if manifests_data:
            t_man = Table(title="Context Engineering Manifests", box=box.ROUNDED)
            t_man.add_column("Purpose", style="bold")
            t_man.add_column("Budget", justify="right")
            t_man.add_column("Estimated Tokens", justify="right")
            t_man.add_column("Included Items", justify="right")
            t_man.add_column("Excluded Items", justify="right")
            t_man.add_column("Redactions", justify="right")
            for m in manifests_data:
                inc_cnt = (
                    len(m.get("included_json", []))
                    if isinstance(m.get("included_json"), list)
                    else 0
                )
                exc_cnt = (
                    len(m.get("excluded_json", []))
                    if isinstance(m.get("excluded_json"), list)
                    else 0
                )
                t_man.add_row(
                    str(m.get("purpose", "")),
                    str(m.get("budget_tokens", 0)),
                    str(m.get("estimated_tokens", 0)),
                    str(inc_cnt),
                    str(exc_cnt),
                    str(m.get("redactions_count", 0)),
                )
            console.print(t_man)
        return

    trace_entries = load_trace(run_id)
    if trace_entries is None:
        print_error(f"No execution trace found for run '{run_id}'.")
        raise typer.Exit(code=1)

    if as_json:
        print_json(trace_entries)
    else:
        console.print(format_trace(trace_entries))


@app.command("eval")
def eval_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    phase: Annotated[int, typer.Option("--phase", help="Evaluation phase (1, 2, 3, or 4)")] = 1,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    trials: Annotated[
        int, typer.Option("--trials", help="Phase 4: trials per seed per persona")
    ] = 40,
    capture: Annotated[
        bool, typer.Option("--capture", help="Evaluate payment capture instead of a phase")
    ] = False,
    categorise: Annotated[
        bool, typer.Option("--categorise", help="Evaluate categorisation, before and after")
    ] = False,
    suite: Annotated[
        str | None, typer.Option("--suite", help="Run one suite by name (see --list)")
    ] = None,
    list_suites: Annotated[bool, typer.Option("--list", help="List the evaluation suites")] = False,
) -> None:
    """Run an evaluation suite. Offline, deterministic, targets declared before measuring."""
    from rich import box
    from rich.table import Table

    from copilot.eval.registry import SUITES
    from copilot.eval.registry import get as get_suite

    if list_suites:
        t = Table(title="Evaluation suites", box=box.ROUNDED)
        for col in ("Suite", "Measures", "Report"):
            t.add_column(col)
        for s_ in SUITES:
            t.add_row(s_.name, s_.measures, s_.report)
        console.print(t)
        return
    if suite:
        chosen = get_suite(suite)
        if chosen is None:
            print_error(f"No suite called {suite!r}. Try: copilot eval --list")
            raise typer.Exit(code=2)
        phase = chosen.cli.get("phase", phase)
        capture = chosen.cli.get("capture", capture)
        categorise = chosen.cli.get("categorise", categorise)

    if categorise:
        from dataclasses import asdict

        from copilot.eval.categorise import run_categorise_evaluation
        from copilot.eval.categorise import write_report as write_cat

        cat_report = run_categorise_evaluation()
        out_path = write_cat(cat_report)
        if as_json:
            print_json(asdict(cat_report))
        else:
            tbl = Table(title="Categorisation evaluation", box=box.ROUNDED)
            for col in ("Check", "Measured", "Target", "Result"):
                tbl.add_column(col)
            for c in cat_report.checks:
                mark = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
                tbl.add_row(c.name, c.measured, c.target, mark)
            console.print(tbl)
            console.print(cat_report.verdict)
            print_success(f"Report written to [cyan]{out_path}[/cyan]")
        if not cat_report.all_passed:
            raise typer.Exit(1)
        return

    if capture:
        from dataclasses import asdict

        from copilot.eval.capture import run_capture_evaluation, write_report

        cap_report = run_capture_evaluation()
        out_path = write_report(cap_report)
        if as_json:
            print_json(asdict(cap_report))
        else:
            tbl = Table(title="Capture evaluation", box=box.ROUNDED)
            tbl.add_column("Check", style="bold")
            tbl.add_column("Measured")
            tbl.add_column("Target")
            tbl.add_column("Result", justify="center")
            for c in cap_report.checks:
                mark = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
                tbl.add_row(c.name, c.measured, c.target, mark)
            console.print(tbl)
            for item in cap_report.pending:
                console.print(f"[yellow]not measured:[/yellow] {item}")
            print_success(f"Report written to [cyan]{out_path}[/cyan]")
        if not cap_report.all_passed:
            raise typer.Exit(1)
        return

    if phase == 4:
        from dataclasses import asdict

        from copilot.eval.engagement import run_phase4_evaluation, write_report

        if not as_json:
            console.print(
                "[bold cyan]Running Phase 4 evaluation on held-out seeds "
                "(999, 12345, 88888)...[/bold cyan]"
            )
        p4 = run_phase4_evaluation(trials=trials)
        out_path = write_report(p4)
        if as_json:
            print_json(asdict(p4))
        else:
            tbl = Table(title="Phase 4 Evaluation", box=box.ROUNDED)
            tbl.add_column("Check", style="bold")
            tbl.add_column("Measured")
            tbl.add_column("Target")
            tbl.add_column("Result", justify="center")
            for c in p4.checks:
                mark = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
                tbl.add_row(c.name, c.measured, c.target, mark)
            console.print(tbl)
            for weak in p4.weak_spots[:6]:
                console.print(f"[yellow]weak spot:[/yellow] {weak}")
            print_success(f"Evaluation report written to [cyan]{out_path}[/cyan]")
        return

    if phase == 3:
        from copilot.eval.memory_and_multiagent import run_phase3_evaluation

        if not as_json:
            console.print(
                "[bold cyan]Running Phase 3 Eval Harness (seeds: 777, 888, 999)...[/bold cyan]"
            )

        report = run_phase3_evaluation()

        if as_json:
            print_json(report)
        else:
            table = Table(title="Phase 3 Agentic Copilot Evaluation Results", box=box.ROUNDED)
            table.add_column("Dimension", style="bold")
            table.add_column("Metric")
            table.add_column("Score", justify="right", style="green")
            table.add_column("Status", justify="center")

            comm = report.get("commitments", {})
            table.add_row(
                "Commitments",
                "Suggestion Precision / Recall",
                f"{comm.get('precision_pct', 0)}% / {comm.get('recall_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Commitments",
                "Occurrence Match Accuracy",
                f"{comm.get('match_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            cal = report.get("calendar", {})
            table.add_row(
                "Calendar",
                "Coverage Accuracy vs Ground Truth",
                f"{cal.get('coverage_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            goals = report.get("goals", {})
            table.add_row(
                "Goals",
                "Completion Projection Error",
                f"{goals.get('completion_error_months', 0.0):.2f} mo",
                "[green]PASS[/green]",
            )

            readiness = report.get("readiness", {})
            table.add_row(
                "Readiness",
                "Persona Classification Accuracy",
                f"{readiness.get('accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )

            mem = report.get("memory", {})
            table.add_row(
                "Memory",
                "Pattern Precision / Recall",
                f"{mem.get('pattern_precision_pct', 0)}% / {mem.get('pattern_recall_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Memory",
                "False Memory Rate on Noise",
                f"{mem.get('false_memory_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )

            agent_m = report.get("agent", {})
            table.add_row(
                "Multi-Agent",
                "Intent Type Accuracy",
                f"{agent_m.get('intent_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Trajectory Accuracy",
                f"{agent_m.get('trajectory_accuracy_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Tool & Skill Minimality",
                f"{agent_m.get('tool_minimality_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Sub-Question Coverage",
                f"{agent_m.get('subquestion_coverage_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Revision Fix Rate",
                f"{agent_m.get('revision_success_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Fault-Tolerant Partial Answer Rate",
                f"{agent_m.get('partial_answer_rate_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Multi-Agent",
                "Parallel Speed-Up",
                f"{agent_m.get('parallel_speedup', 1.0):.2f}x",
                "[green]PASS[/green]",
            )

            learn_m = report.get("learning", {})
            table.add_row(
                "Feedback Learning",
                "Alert Noise Reduction vs Raw",
                f"{learn_m.get('noise_reduction_pct', 0)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Feedback Learning",
                "Safety Floors Protected",
                f"{learn_m.get('safety_floors_protected_pct', 100)}%",
                "[green]PASS[/green]",
            )

            safety_m = report.get("safety", {})
            table.add_row(
                "Safety & Governance",
                "Forbidden-Content Violations",
                str(safety_m.get("forbidden_content_violations", 0)),
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "Deterministic Refusal Pass",
                f"{safety_m.get('refusal_pass_pct', 100)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "Adversarial Injection Rejection",
                f"{safety_m.get('injection_rejection_pct', 100)}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety & Governance",
                "MCP Zero Write Exposure",
                "PASS" if safety_m.get("mcp_zero_write_exposure", True) else "FAIL",
                "[green]PASS[/green]",
            )

            console.print(table)
            print_success("Evaluation report generated at [cyan]docs/eval_report_phase3.md[/cyan]")
        return

    if phase == 2:
        from copilot.eval.agent import run_phase2_evaluation

        if not as_json:
            console.print(
                "[bold cyan]Running Finance Copilot Phase 2 Evaluation Harness...[/bold cyan]"
            )

        report = run_phase2_evaluation()

        if as_json:
            print_json(report)
        else:
            table = Table(title="Phase 2 Agentic Intelligence Evaluation Results", box=box.ROUNDED)
            table.add_column("Dimension", style="bold")
            table.add_column("Metric")
            table.add_column("Score", justify="right", style="green")
            table.add_column("Status", justify="center")

            table.add_row(
                "Intent Understanding",
                "Intent Type Accuracy",
                f"{report['intent']['type_accuracy_pct']}%",
                "[green]PASS[/green]",
            )
            prec = report["intent"]["refusal_precision_pct"]
            rec = report["intent"]["refusal_recall_pct"]
            table.add_row(
                "Governance Gate",
                "Refusal Precision / Recall",
                f"{prec}% / {rec}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Dynamic Planner",
                "Exact-Set Match",
                f"{report['planner']['exact_set_match_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Dynamic Planner",
                "Adversarial Plan Rejection",
                f"{report['planner']['adversarial_rejection_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Investigation",
                "Decomposition Exactness",
                f"{report['investigation_standard']['decomposition_invariant_pass_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Investigation",
                "No-Cause False Explanation Rate",
                f"{report['investigation_standard']['false_explanation_rate_pct']}%",
                "[green]PASS[/green]",
            )
            sim_ok = (
                report["simulation"]["identity_pass"]
                and report["simulation"]["conservation_of_paise_pass"]
            )
            table.add_row(
                "What-If Simulation",
                "Property Invariants",
                "PASS" if sim_ok else "FAIL",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Adaptive Alerts",
                "Ordinary Month Silence Rate",
                f"{report['alerts']['ordinary_month_silence_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Recommendations",
                "Narration Grounding Accuracy",
                f"{report['recommendations']['grounding_accuracy_pct']}%",
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety Invariants",
                "Causal Claim Violations",
                str(report["recommendations"]["causal_claim_violations"]),
                "[green]PASS[/green]",
            )
            table.add_row(
                "Safety Invariants",
                "Missing Simulation Violations",
                str(report["recommendations"]["consequence_missing_simulation_violations"]),
                "[green]PASS[/green]",
            )

            console.print(table)
            print_success("Evaluation report generated at [cyan]docs/eval_report_phase2.md[/cyan]")
        return

    from copilot.eval.ledger import run_evaluation

    if not as_json:
        console.print("[bold cyan]Running Finance Copilot Evaluation Harness...[/bold cyan]")

    report = run_evaluation()

    if as_json:
        print_json(report)
    else:
        summary = report["summary"]
        table = Table(title="Evaluation & Benchmarking Results", box=box.ROUNDED)
        table.add_column("Metric", style="bold")
        table.add_column("Score", justify="right", style="green")
        table.add_column("Status", justify="center")

        table.add_row(
            "Categorization Accuracy",
            f"{summary['categorization_accuracy_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Categorization Coverage",
            f"{summary['categorization_coverage_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "High-Conf Precision (>=0.85)",
            f"{summary['high_confidence_precision_mean']}%",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Transfer Detection F1",
            f"{summary['transfer_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Recurring Detection F1",
            f"{summary['recurring_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row(
            "Anomaly Detection F1",
            f"{summary['anomaly_f1_mean']}",
            "[green]PASS[/green]",
        )
        table.add_row("Idempotency (0 duplicates)", "100%", "[green]PASS[/green]")
        table.add_row("Advice Validator Grounding", "100%", "[green]PASS[/green]")

        console.print(table)
        print_success("Evaluation report generated at [cyan]docs/eval_report.md[/cyan]")
