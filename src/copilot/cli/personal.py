# ruff: noqa: E501  (long lines)
"""
Typer CLI for the personal model (PLAN_AGENTIC_V2, A8 to A12).

    copilot me profile / set <field> <json> / confirm <field> / forget <field> / suggest
    copilot me budget / apply / replan / move
    copilot me checkin / checkins / respond <id> acted
    copilot me group <name> <people...> / spent / balances / settled
    copilot me subscriptions / mark <series> unused

Every command goes through `execute_tool`, so each one is governed and audited.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich import box
from rich.table import Table

from copilot.cli.formatters import console, format_inr, print_error, print_json, print_success
from copilot.cli.storage import get_db_path, make_exec_ctx, open_db
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered

me_app = typer.Typer(
    help="Your profile, budget, check-ins, shared expenses and subscriptions.", no_args_is_help=True
)
_DB = Annotated[str | None, typer.Option("--db", help="SQLite database path")]
_USER = Annotated[str, typer.Option("--user", "-u", help="User ID")]


def _run(db, user, tool, args=None, actor="user"):
    ensure_tools_registered()
    conn = open_db(get_db_path(db))
    try:
        res = execute_tool(make_exec_ctx(conn=conn, user_id=user, actor=actor), tool, args or {})
        conn.commit()
    finally:
        conn.close()
    if not res.ok:
        print_error(res.error.message if res.error else "That did not work.")
        raise typer.Exit(code=1)
    return res.data


# ---- profile ----------------------------------------------------------------------------------------------
@me_app.command("profile")
def profile_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """What I know about you: confirmed values, suggestions waiting for you, and what is missing."""
    d = _run(db, user, "profile_get").data
    for k, v in d["values"].items():
        console.print(f"[bold]{k}[/bold]: {json.dumps(v)}")
    for k, v in d["suggestions"].items():
        console.print(
            f"[yellow]suggested[/yellow] {k}: {json.dumps(v)}  (confirm with: copilot me confirm {k})"
        )
    if d["missing"]:
        console.print("[dim]not yet told: " + ", ".join(d["missing"]) + "[/dim]")


@me_app.command("set")
def set_cmd(
    field: str,
    value: Annotated[str, typer.Argument(help="a JSON value, e.g. 5000000 or '\"gentle\"'")],
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """State a value for your profile."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    _run(db, user, "profile_set", {"field": field, "value": parsed})
    print_success(f"{field} saved.")


@me_app.command("confirm")
def confirm_cmd(field: str, user: _USER = "u1", db: _DB = None) -> None:
    """Accept a suggestion."""
    _run(db, user, "profile_confirm", {"field": field})
    print_success(f"{field} confirmed.")


@me_app.command("forget")
def forget_cmd(field: str, user: _USER = "u1", db: _DB = None) -> None:
    """Remove a part of your profile."""
    n = _run(db, user, "profile_delete", {"field": field}).data["deleted"]
    print_success(f"{n} removed.")


@me_app.command("suggest")
def suggest_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Suggest profile values from your own money (they wait for you to confirm)."""
    got = _run(db, user, "profile_infer", actor="agent").data["suggested"]
    console.print("suggested: " + (", ".join(got) or "nothing new"))


# ---- budget ------------------------------------------------------------------------------------------------
@me_app.command("budget")
def budget_cmd(
    user: _USER = "u1", db: _DB = None, as_json: Annotated[bool, typer.Option("--json")] = False
) -> None:
    """A month's budget from your income, commitments, goals and priorities."""
    p = _run(db, user, "budget_propose").data
    if as_json:
        print_json(p)
        return
    console.print(p["note"])
    if p["lines"]:
        t = Table(title=f"Budget for {p['period']}", box=box.ROUNDED)
        for c in ("Category", "Limit", "Usual", "Why"):
            t.add_column(c)
        for ln in p["lines"]:
            t.add_row(
                ln["category_id"],
                format_inr(ln["limit_paise"]),
                format_inr(ln["usual_paise"]),
                ln["reason"],
            )
        console.print(t)
        console.print(
            f"income {format_inr(p['income_paise'])} = fixed {format_inr(p['fixed_paise'])} + goals {format_inr(p['goals_paise'])} + savings {format_inr(p['savings_paise'])} + limits + unallocated {format_inr(p['unallocated_paise'])}"
        )


@me_app.command("apply")
def apply_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Make the proposed budget this month's budgets."""
    d = _run(db, user, "budget_apply").data
    print_success(f"{d['lines']} category budgets set.")


@me_app.command("replan")
def replan_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Ways to rebalance categories heading over their limit."""
    plans = _run(db, user, "budget_replan").data
    for p in plans:
        console.print(
            f"[bold]{p['category_id']}[/bold]: heading {format_inr(p['overrun_paise'])} over {format_inr(p['limit_paise'])}"
        )
        for o in p["options"]:
            console.print(
                f"  - {o['text']}"
                + (
                    f"   [dim](apply: copilot me move {o['from_category']} {o['category_id']} {o['amount_paise']})[/dim]"
                    if o["kind"] == "move"
                    else ""
                )
            )
    if not plans:
        console.print("[dim]Nothing is heading over.[/dim]")


@me_app.command("move")
def move_cmd(
    from_category: str, to_category: str, amount_paise: int, user: _USER = "u1", db: _DB = None
) -> None:
    """Move budget limit from one category to another."""
    _run(
        db,
        user,
        "budget_move",
        {"from_category": from_category, "to_category": to_category, "amount_paise": amount_paise},
    )
    print_success("Moved.")


# ---- check-ins -----------------------------------------------------------------------------------------------
@me_app.command("checkin")
def checkin_cmd(
    now: Annotated[bool, typer.Option("--now", help="ignore the preferred time")] = False,
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Look for the one thing worth saying, check it, and say it (or stay quiet)."""
    out = _run(db, user, "run_checkin", {"ignore_timing": now}, actor="agent")
    if out.sent:
        console.print(f"[bold]{out.checkin.headline}[/bold]\n{out.checkin.body}")
        for o in out.checkin.options:
            console.print(f"  - {o}")
    else:
        console.print(f"Nothing to say ({out.reason.replace('_', ' ')}).")
    for kind, why in out.dropped:
        console.print(f"[dim]dropped {kind}: {why}[/dim]")


@me_app.command("checkins")
def checkins_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """Recent check-ins and how you like to be helped."""
    d = _run(db, user, "list_checkins").data
    for c in d["checkins"]:
        console.print(
            f"{c['created_at'][:10]}  [{c['status']}]  {c['headline']}: {c['body']}  ({c['id']})"
        )
    v = d["verification"]
    console.print(f"[dim]{v['sent']} sent, {v['dropped']} dropped by their own check.[/dim]")


@me_app.command("respond")
def respond_cmd(
    checkin_id: str,
    response: Annotated[str, typer.Argument(help="acted, dismissed or not_useful")],
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Answer a check-in."""
    _run(db, user, "respond_checkin", {"checkin_id": checkin_id, "response": response})
    print_success("Thanks, noted.")


# ---- shared expenses -------------------------------------------------------------------------------------------
@me_app.command("group")
def group_cmd(name: str, people: list[str], user: _USER = "u1", db: _DB = None) -> None:
    """Start a sharing group: me and the people you name."""
    d = _run(db, user, "create_split_group", {"name": name, "others": people}).data
    console.print(f"group {d['group_id']}")
    for m in d["members"]:
        console.print(f"  {m['name']}: {m['id']}")


@me_app.command("spent")
def spent_cmd(
    group_id: str,
    paid_by: str,
    amount_paise: int,
    note: str = "",
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Record a shared expense, split equally."""
    _run(
        db,
        user,
        "add_split_expense",
        {"group_id": group_id, "paid_by": paid_by, "amount_paise": amount_paise, "note": note},
    )
    print_success("Recorded.")


@me_app.command("balances")
def balances_cmd(group_id: str, user: _USER = "u1", db: _DB = None) -> None:
    """Who owes whom, and the fewest settle-ups."""
    v = _run(db, user, "split_balances", {"group_id": group_id}).data
    for b in v["balances"]:
        console.print(
            f"{b['name']}: {'is owed' if b['net_paise'] > 0 else 'owes'} {format_inr(abs(b['net_paise']))}"
        )
    for s in v["settle_up"]:
        console.print(
            f"  settle: {s['from_member']} -> {s['to_member']}  {format_inr(s['amount_paise'])}  [dim](records only, nothing is paid here)[/dim]"
        )


@me_app.command("settled")
def settled_cmd(
    group_id: str,
    from_member: str,
    to_member: str,
    amount_paise: int,
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Record that two people say they settled up. Nothing is paid here."""
    _run(
        db,
        user,
        "record_split_settlement",
        {
            "group_id": group_id,
            "from_member": from_member,
            "to_member": to_member,
            "amount_paise": amount_paise,
        },
    )
    print_success("Recorded.")


# ---- subscriptions ------------------------------------------------------------------------------------------------
@me_app.command("subscriptions")
def subscriptions_cmd(user: _USER = "u1", db: _DB = None) -> None:
    """What renews, when, and what changed."""
    items = _run(db, user, "list_subscriptions").data
    t = Table(title="Subscriptions", box=box.ROUNDED)
    for c in ("Name", "Amount", "Per month", "Renews in", "Price change", "You said", "Id"):
        t.add_column(c)
    for s in items:
        t.add_row(s["name"], format_inr(s["amount_paise"]), format_inr(s["monthly_paise"]), f"{s['days_until_renewal']} days",
                  f"{s['price_change_bp'] / 100:+.0f}%" if s["price_change_bp"] else "-", s["note"] or "-", s["series_id"])  # fmt: skip
    console.print(t)


@me_app.command("mark")
def mark_cmd(
    series_id: str,
    note: Annotated[str, typer.Argument(help="unused or keep")],
    user: _USER = "u1",
    db: _DB = None,
) -> None:
    """Say whether you still use a subscription."""
    _run(db, user, "mark_subscription", {"series_id": series_id, "note": note})
    print_success("Noted.")
