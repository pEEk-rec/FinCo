"""
Typer CLI for understanding transactions (PLAN_AGENTIC_V2).

    copilot understand run
    copilot understand questions
    copilot understand answer --shop <entity_id> --category food
    copilot understand why <transaction_id>
    copilot understand rules / accept-rule <id> / dismiss-rule <id>

Every command goes through `execute_tool`, so each one is governed and audited.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.formatters import console, print_error, print_json, print_success
from copilot.cli.storage import get_db_path, make_exec_ctx, open_db
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

understand_app = typer.Typer(
    help="See how payments get their categories, and answer what is left.", no_args_is_help=True
)
_DB = Annotated[str | None, typer.Option("--db", help="SQLite database path")]
_USER = Annotated[str, typer.Option("--user", "-u", help="User ID")]


def _run(db: str | None, user: str, tool: str, args: dict, actor: str = "user"):
    ensure_tools_registered()
    conn = open_db(get_db_path(db))
    try:
        res = execute_tool(make_exec_ctx(conn=conn, user_id=user, actor=actor), tool, args)
        conn.commit()
    finally:
        conn.close()
    if not res.ok:
        print_error(res.error.message if res.error else "That did not work.")
        raise typer.Exit(code=1)
    return res.data


@understand_app.command("run")
def run_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Categorise what is not yet answered: your answers, rules, similar shops, brands, then ask."""
    out = _run(db, user, "run_cascade", {}, actor="agent")
    stages = ", ".join(f"{k}: {v}" for k, v in sorted(out.by_stage.items())) or "nothing to do"
    print_success(
        f"{out.considered} looked at, {out.applied} labelled, {out.asked} to ask you about "
        f"({stages}); {out.model_calls} model request(s)."
    )


@understand_app.command("questions")
def questions_cmd(
    user: _USER = "u1", db: _DB = None, as_json: Annotated[bool, typer.Option("--json")] = False
) -> None:
    """What to ask next, most useful first."""
    out = _run(db, user, "entity_questions", {})
    if as_json:
        print_json(out.model_dump(mode="json"))
        return
    table = Table(title="Worth asking about", box=box.ROUNDED)
    for col in ("Shop", "Kind", "Payments", "Guess", "Why", "Id"):
        table.add_column(col)
    for q in out.questions:
        table.add_row(
            q.display_name,
            q.kind,
            str(q.payments) + (" (one tap)" if q.batch else ""),
            q.best_guess or "-",
            q.reason,
            q.entity_id,
        )
    console.print(table)
    if not out.questions:
        console.print("[dim]Nothing to ask.[/dim]")


@understand_app.command("answer")
def answer_cmd(
    category: Annotated[str, typer.Option("--category", help="category id")],
    shop: Annotated[str | None, typer.Option("--shop", help="entity id from `questions`")] = None,
    payment: Annotated[str | None, typer.Option("--payment", help="one transaction id")] = None,
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Say what a shop (all its spellings) or one payment was."""
    args = {"category_id": category, "entity_id": shop, "transaction_id": payment}
    out = _run(db, user, "answer_shop", {k: v for k, v in args.items() if v})
    print_success(f"{out.settled} payment(s) settled. Undo with: copilot undo {out.audit_event_id}")
    if out.rule_proposal:
        console.print(f"A rule is proposed: copilot understand rules (id {out.rule_proposal}).")


@understand_app.command("why")
def why_cmd(
    transaction_id: Annotated[str, typer.Argument()],
    user: _USER = "u1",
    db: _DB = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Why a payment has the category it has."""
    out = _run(db, user, "explain_decision", {"transaction_id": transaction_id})
    if as_json:
        print_json(out.model_dump(mode="json"))
        return
    conf = f"{out.confidence_bp / 100:.1f}%" if out.confidence_bp is not None else "-"
    console.print(
        f"[bold]{out.shop or 'unknown shop'}[/bold]  ->  {out.category_id or 'not decided'}"
    )
    console.print(f"stage {out.stage}, confidence {conf}: {out.reason}")
    if out.spellings:
        console.print("spellings: " + ", ".join(out.spellings))
    for c in out.candidates:
        console.print(
            f"  considered {c['stage']}: {c['category']} (claimed {c['raw_bp'] / 100:.0f}%)"
        )


@understand_app.command("rules")
def rules_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Rules the agent noticed. Nothing applies until you accept it."""
    conn = open_db(get_db_path(db))
    try:
        rows = conn.execute(
            "SELECT id, pattern, category_id, status FROM rule_proposals WHERE user_id = ?"
            " ORDER BY created_at",
            (user,),
        ).fetchall()
    finally:
        conn.close()
    table = Table(title="Proposed rules", box=box.ROUNDED)
    for col in ("Id", "Pattern", "Category", "Status"):
        table.add_column(col)
    for r in rows:
        table.add_row(r[0], r[1], r[2], r[3])
    console.print(table)


@understand_app.command("accept-rule")
def accept_rule_cmd(
    proposal_id: Annotated[str, typer.Argument()], user: _USER = "u1", db: _DB = None
) -> None:
    """Accept a proposed rule."""
    out = _run(db, user, "decide_rule_proposal", {"proposal_id": proposal_id, "accept": True})
    print_success(f"Rule {out.pattern} accepted.")


@understand_app.command("dismiss-rule")
def dismiss_rule_cmd(
    proposal_id: Annotated[str, typer.Argument()], user: _USER = "u1", db: _DB = None
) -> None:
    """Dismiss a proposed rule."""
    out = _run(db, user, "decide_rule_proposal", {"proposal_id": proposal_id, "accept": False})
    print_success(f"Rule {out.pattern} dismissed.")


@understand_app.command("gold-prepare")
def gold_prepare_cmd(
    out: Annotated[str | None, typer.Option("--out", help="where to write the sheet")] = None,
    rows: Annotated[int, typer.Option("--rows", help="how many recent payments")] = 150,
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Write a labelling sheet from your own ledger: date, cleaned name, amount, empty category."""
    from pathlib import Path

    from copilot.understand.gold import prepare_sheet

    conn = open_db(get_db_path(db))
    try:
        path, n = prepare_sheet(conn, user, Path(out) if out else None, rows)
    finally:
        conn.close()
    print_success(
        f"{n} rows written to {path}. Fill in the category column on your own computer, "
        "then run `copilot understand gold-eval`. The folder is git-ignored; do not share the file."
    )


@understand_app.command("gold-eval")
def gold_eval_cmd(
    file: Annotated[str | None, typer.Option("--file", help="the filled-in sheet")] = None,
) -> None:
    """Replay your labelled sheet offline. Prints totals only, safe to share."""
    from pathlib import Path

    from copilot.common.errors import ToolFailure
    from copilot.understand.gold import GOLD_DIR, evaluate_sheet

    try:
        r = evaluate_sheet(Path(file) if file else GOLD_DIR / "sheet.csv")
    except (ToolFailure, FileNotFoundError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(
        f"{r.rows} payments over {r.weeks} weeks, {r.categories} categories: "
        f"accuracy on labelled {r.accuracy:.1%}, coverage {r.coverage:.1%}, "
        f"{r.questions_per_100:.1f} questions per 100 payments (no model, no network)."
    )
