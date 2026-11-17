"""Alerts: what FinCo flags, how you answered, and how often you want to hear."""

from typing import Annotated

import typer

from copilot.cli.app import alerts_app
from copilot.cli.common import tool_dict, tool_out
from copilot.cli.formatters import (
    print_alerts_table,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    make_exec_ctx,
    open_db,
)
from copilot.tools.executor import execute_tool
from copilot.workflow.nodes import ensure_tools_registered


@alerts_app.command("list")
def alerts_list_cmd(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status: open, acknowledged, dismissed, snoozed"),
    ] = None,
    period: Annotated[
        str | None, typer.Option("--period", help="Filter by period (YYYY-MM)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List active or historical adaptive alerts."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "list_alerts", {"status": status})
    conn.close()

    if not res.ok:
        print_error(f"Failed to list alerts: {res.error.message}")
        raise typer.Exit(code=1)

    alerts = tool_out(res, "alerts") or []
    if as_json:
        print_json([a.model_dump(mode="json") for a in alerts])
    else:
        print_alerts_table([a.model_dump(mode="json") for a in alerts])


@alerts_app.command("evaluate")
def alerts_evaluate_cmd(
    period: Annotated[
        str | None, typer.Option("--period", help="Period to evaluate (YYYY-MM)")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Evaluate signals and generate adaptive alerts for a period."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(ctx, "evaluate_alerts", {"period": period})
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Alert evaluation failed: {res.error.message}")
        raise typer.Exit(code=1)

    out_data = tool_dict(res)
    if as_json:
        print_json(out_data)
    else:
        print_success(
            f"Alerts evaluated for {out_data.get('period')}: "
            f"created={out_data.get('created_count')}, "
            f"escalated={out_data.get('escalated_count')}, "
            f"suppressed={out_data.get('suppressed_count')}"
        )
        if out_data.get("alerts"):
            print_alerts_table(out_data["alerts"])


@alerts_app.command("ack")
def alerts_ack_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to acknowledge")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Optional acknowledgment note")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Acknowledge an adaptive alert."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "acknowledge", "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to acknowledge alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' acknowledged.")


@alerts_app.command("dismiss")
def alerts_dismiss_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to dismiss")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Optional dismissal reason")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Dismiss an adaptive alert."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "dismiss", "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to dismiss alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' dismissed.")


@alerts_app.command("snooze")
def alerts_snooze_cmd(
    alert_id: Annotated[str, typer.Argument(help="Alert ID to snooze")],
    days: Annotated[int, typer.Option("--days", help="Days to snooze (1-90)")] = 7,
    reason: Annotated[str | None, typer.Option("--reason", help="Optional snooze note")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Snooze an adaptive alert for a specified number of days."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "decide_alert",
        {"alert_id": alert_id, "action": "snooze", "snooze_days": days, "reason": reason},
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to snooze alert: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(tool_dict(res))
    else:
        print_success(f"Alert '[cyan]{alert_id}[/cyan]' snoozed for {days} days.")


@alerts_app.command("prefs")
def alerts_prefs_cmd(
    category: Annotated[
        str | None, typer.Option("--category", help="Category ID to configure")
    ] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Alert kind filter")] = None,
    min_severity: Annotated[
        str,
        typer.Option(
            "--min-severity", help="Minimum severity threshold: info, notice, warning, critical"
        ),
    ] = "info",
    muted: Annotated[
        bool, typer.Option("--muted/--unmuted", help="Silence alerts matching this preference")
    ] = False,
    max_open: Annotated[
        int | None, typer.Option("--max-open", help="Cap on open alerts before escalation")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Configure user preferences and silencing rules for adaptive alerts."""
    ensure_tools_registered()
    db_path = get_db_path(db)
    conn = open_db(db_path)
    ctx = make_exec_ctx(conn=conn, user_id=user_id, actor="user")

    res = execute_tool(
        ctx,
        "set_alert_preference",
        {
            "category_id": category,
            "kind": kind,
            "min_severity": min_severity,
            "muted": muted,
            "max_open_alerts": max_open,
        },
    )
    conn.commit()
    conn.close()

    if not res.ok:
        print_error(f"Failed to update alert preferences: {res.error.message}")
        raise typer.Exit(code=1)

    if as_json:
        print_json(tool_dict(res))
    else:
        print_success("Alert preferences updated successfully.")
