"""Bank consents: request, approve, revoke and list them."""

from datetime import UTC, datetime
from typing import Annotated

import typer

from copilot.cli.app import consent_app
from copilot.cli.formatters import (
    console,
    print_consents_table,
    print_error,
    print_json,
    print_success,
)
from copilot.cli.storage import (
    get_db_path,
    open_db,
)
from copilot.common.timeutil import now_utc, to_utc_iso


@consent_app.command("list")
def consent_list_cmd(
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List all bank consents for a user."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    rows = conn.execute(
        """
        SELECT id, user_id, purpose, account_ids, date_range_from, date_range_to,
               status, expires_at, created_at
        FROM consents WHERE user_id = ? ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    consents = [dict(r) for r in rows]
    if as_json:
        print_json(consents)
    else:
        print_consents_table(consents)


@consent_app.command("create")
def consent_create_cmd(
    account_id: Annotated[str, typer.Argument(help="Account ID")] = "a1",
    institution: Annotated[
        str | None, typer.Option("--institution", help="Institution name")
    ] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="User ID")] = "u1",
    purpose: Annotated[str, typer.Option("--purpose", help="Consent purpose")] = "sync",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a new bank consent (status: pending)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    now_iso = to_utc_iso(now_utc())
    cid = f"consent_{user_id}_{int(datetime.now(tz=UTC).timestamp())}"
    conn.execute(
        """
        INSERT INTO consents (
            id, user_id, purpose, fi_types, account_ids,
            date_range_from, date_range_to, status, expires_at, created_at
        ) VALUES (?, ?, ?, 'DEPOSIT', ?, '2020-01-01T00:00:00Z',
                  '2030-01-01T00:00:00Z', 'pending', '2030-01-01T00:00:00Z', ?)
        """,
        (cid, user_id, purpose, f'["{account_id}"]', now_iso),
    )
    conn.commit()
    conn.close()

    res = {"id": cid, "status": "pending", "user_id": user_id, "account_id": account_id}
    if as_json:
        print_json(res)
    else:
        print_success(f"Created consent [cyan]{cid}[/cyan] (status: [yellow]PENDING[/yellow])")
        console.print(f"To activate: [bold]copilot consent approve {cid}[/bold]")


@consent_app.command("approve")
def consent_approve_cmd(
    consent_id: Annotated[str, typer.Argument(help="Consent ID to approve")],
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Approve a bank consent (status: active)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    cur = conn.execute("UPDATE consents SET status = 'active' WHERE id = ?", (consent_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        print_error(f"Consent '{consent_id}' not found.")
        raise typer.Exit(code=1)

    if as_json:
        print_json({"id": consent_id, "status": "active"})
    else:
        print_success(f"Consent [cyan]{consent_id}[/cyan] approved (status: [green]ACTIVE[/green])")


@consent_app.command("revoke")
def consent_revoke_cmd(
    consent_id: Annotated[str, typer.Argument(help="Consent ID to revoke")],
    reason: Annotated[str | None, typer.Option("--reason", help="Revocation reason")] = None,
    db: Annotated[str | None, typer.Option("--db", help="SQLite database path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Revoke a bank consent (status: revoked)."""
    db_path = get_db_path(db)
    conn = open_db(db_path)
    cur = conn.execute("UPDATE consents SET status = 'revoked' WHERE id = ?", (consent_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        print_error(f"Consent '{consent_id}' not found.")
        raise typer.Exit(code=1)

    if as_json:
        print_json({"id": consent_id, "status": "revoked"})
    else:
        print_success(f"Consent [cyan]{consent_id}[/cyan] revoked (status: [red]REVOKED[/red])")
