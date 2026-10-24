"""
Account Aggregator consent (PLAN_CAPTURE Stage C7, ADR-0002).

A consent is the user's permission for a fixed purpose, scope, frequency and lifetime. Nothing
is fetched without an active, in-scope consent, and revoking takes effect on the very next
check. The states are:

    pending -> active | revoked | expired
    active  -> paused | revoked | expired
    paused  -> active | revoked | expired
    revoked, expired: final

`describe` renders the consent artefact in plain language for the web screen: what is read, why,
how often, for how long, and how to take it back.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from copilot.audit.events import Actor, record_event
from copilot.config.capture import AaConfig, load_aa_config
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso

Status = Literal["pending", "active", "paused", "revoked", "expired"]
Action = Literal["approve", "pause", "resume", "revoke"]

#: Where each action may be taken from, and where it leads.
TRANSITIONS: dict[Action, tuple[tuple[str, ...], Status]] = {
    "approve": (("pending",), "active"),
    "pause": (("active",), "paused"),
    "resume": (("paused",), "active"),
    "revoke": (("pending", "active", "paused"), "revoked"),
}
FINAL = ("revoked", "expired")
_DAYS_PER_MONTH = 30  # consent and data-life months are counted as 30 days, stated on screen


class BankLinkView(BaseModel):
    id: str
    status: Status
    connector: str
    purpose: str
    what: list[str]
    why: str
    how_often: str
    how_long: str
    data_kept: str
    revoke: str
    created_at: str
    approved_at: str | None
    expires_at: str | None
    last_fetch_at: str | None
    range_from: str
    range_to: str
    can: list[Action]


def _frequency(cfg: AaConfig) -> str:
    unit = cfg.frequency.unit.lower()
    n = cfg.frequency.value
    if cfg.fetch_type == "ONETIME":
        return "Once, when you approve."
    return f"Every {unit}." if n == 1 else f"Every {n} {unit}s."


def _row_to_view(row: sqlite3.Row, cfg: AaConfig) -> BankLinkView:
    status: Status = row["status"]
    months = max(
        1, round((from_utc_iso(row["range_to"]) - from_utc_iso(row["created_at"])).days / 30)
    )
    can = [a for a, (src, _dst) in TRANSITIONS.items() if status in src]
    return BankLinkView(
        id=row["id"],
        status=status,
        connector=row["connector"],
        purpose="Customer spending patterns, budget or other reportings",
        what=[
            "Your savings and current account transactions: date, amount, narration, reference.",
            "Nothing else. No loans, investments, insurance or account holder details.",
        ],
        why="To match what you tagged at the moment of payment with what your bank recorded, "
        "so your month is complete and nothing is counted twice.",
        how_often=_frequency(cfg),
        how_long=f"{months} months from approval, unless you stop it sooner.",
        data_kept=(
            f"Fetched copies are deleted after {row['data_life_days']} days. The transactions "
            "added to your ledger stay yours until you delete them."
        ),
        revoke="You can pause or revoke at any time. Fetching stops at once.",
        created_at=row["created_at"],
        approved_at=row["approved_at"],
        expires_at=row["expires_at"],
        last_fetch_at=row["last_fetch_at"],
        range_from=row["range_from"],
        range_to=row["range_to"],
        can=can,  # type: ignore[arg-type]
    )


def create_consent(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    external_ref: str | None = None,
    clock: datetime | None = None,
    cfg: AaConfig | None = None,
) -> BankLinkView:
    cfg = cfg or load_aa_config()
    now = now_utc(clock)
    if conn.execute(
        "SELECT 1 FROM aa_consents WHERE user_id = ? AND status IN ('pending', 'active', 'paused')",
        (user_id,),
    ).fetchone():
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            "A bank link is already set up. Revoke it before making another.",
        )
    cid = f"aac_{uuid.uuid4().hex[:12]}"
    life = (
        cfg.data_life.value * {"DAY": 1, "MONTH": _DAYS_PER_MONTH, "YEAR": 365}[cfg.data_life.unit]
    )
    conn.execute(
        "INSERT INTO aa_consents (id, user_id, status, connector, external_ref, purpose_code,"
        " fi_types, consent_types, fetch_type, frequency_json, consent_mode, range_from, range_to,"
        " data_life_days, created_at) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid, user_id, cfg.connector, external_ref, cfg.purpose_code,
            json.dumps(cfg.fi_types), json.dumps(cfg.consent_types), cfg.fetch_type,
            cfg.frequency.model_dump_json(), cfg.consent_mode,
            to_utc_iso(now - timedelta(days=cfg.data_range_months * _DAYS_PER_MONTH)),
            to_utc_iso(now + timedelta(days=cfg.consent_duration_months * _DAYS_PER_MONTH)),
            life, to_utc_iso(now),
        ),
    )  # fmt: skip
    record_event(
        conn, user_id=user_id, actor=actor, event_type="aa_consent_created",
        reason="A bank link was requested and is waiting for approval", run_id=run_id,
        entity_type="aa_consent", entity_id=cid,
        metadata={"connector": cfg.connector, "purpose": cfg.purpose_code}, clock=now,
    )  # fmt: skip
    return get_consent(conn, user_id, cid, cfg=cfg)  # type: ignore[return-value]


def get_consent(
    conn: sqlite3.Connection, user_id: str, consent_id: str, *, cfg: AaConfig | None = None
) -> BankLinkView | None:
    row = conn.execute(
        "SELECT * FROM aa_consents WHERE user_id = ? AND id = ?", (user_id, consent_id)
    ).fetchone()
    return _row_to_view(row, cfg or load_aa_config()) if row else None


def current_consent(
    conn: sqlite3.Connection, user_id: str, *, cfg: AaConfig | None = None
) -> BankLinkView | None:
    """The consent that is live, else the most recent one (so the screen can show how it ended)."""
    row = conn.execute(
        "SELECT * FROM aa_consents WHERE user_id = ? ORDER BY"
        " (status IN ('pending', 'active', 'paused')) DESC, created_at DESC, id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return _row_to_view(row, cfg or load_aa_config()) if row else None


def transition(
    conn: sqlite3.Connection,
    user_id: str,
    consent_id: str,
    action: Action,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> BankLinkView:
    now = now_utc(clock)
    row = conn.execute(
        "SELECT * FROM aa_consents WHERE user_id = ? AND id = ?", (user_id, consent_id)
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "That bank link does not exist.")
    sources, target = TRANSITIONS[action]
    if row["status"] not in sources:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, f"A {row['status']} bank link cannot be {action}d."
        )
    if action == "approve":
        conn.execute(
            "UPDATE aa_consents SET status = ?, approved_at = ?, expires_at = ?"
            " WHERE id = ? AND user_id = ?",
            (target, to_utc_iso(now), row["range_to"], consent_id, user_id),
        )
    else:
        stamp = {"pause": "paused_at", "revoke": "revoked_at"}.get(action)
        extra = f", {stamp} = ?" if stamp else ""
        args = [target, *([to_utc_iso(now)] if stamp else []), consent_id, user_id]
        conn.execute(f"UPDATE aa_consents SET status = ?{extra} WHERE id = ? AND user_id = ?", args)
    record_event(
        conn, user_id=user_id, actor=actor, event_type=f"aa_consent_{target}",
        reason=f"Bank link {action}d", run_id=run_id, entity_type="aa_consent",
        entity_id=consent_id, before_data={"status": row["status"]},
        after_data={"status": target}, clock=now,
    )  # fmt: skip
    if action == "revoke":
        # Revoking also withdraws what was fetched under it: nothing lingers past the permission.
        conn.execute(
            "DELETE FROM aa_raw WHERE user_id = ? AND consent_id = ?", (user_id, consent_id)
        )
    return get_consent(conn, user_id, consent_id)  # type: ignore[return-value]


def require_active(
    conn: sqlite3.Connection, user_id: str, consent_id: str, clock: datetime | None = None
) -> sqlite3.Row:
    """The consent row, only if fetching under it is allowed right now. Else a clear refusal."""
    now = now_utc(clock)
    row = conn.execute(
        "SELECT * FROM aa_consents WHERE user_id = ? AND id = ?", (user_id, consent_id)
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "That bank link does not exist.")
    if row["status"] != "active":
        raise ToolFailure(
            ErrorCode.DENIED_BY_POLICY,
            f"The bank link is {row['status']}, so nothing was fetched.",
        )
    if row["expires_at"] and from_utc_iso(row["expires_at"]) <= now:
        raise ToolFailure(ErrorCode.DENIED_BY_POLICY, "The bank link has expired.")
    if "TRANSACTIONS" not in json.loads(row["consent_types"]) or "DEPOSIT" not in json.loads(
        row["fi_types"]
    ):
        raise ToolFailure(ErrorCode.DENIED_BY_POLICY, "This bank link does not cover transactions.")
    return row


def expire_due(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> tuple[int, int]:
    """Expire consents past their end, and delete fetched copies past their data life."""
    now = now_utc(clock)
    expired = 0
    for row in conn.execute(
        "SELECT id, status FROM aa_consents WHERE user_id = ? AND status IN"
        " ('pending', 'active', 'paused') AND ? >= COALESCE(expires_at, range_to)",
        (user_id, to_utc_iso(now)),
    ).fetchall():
        conn.execute("UPDATE aa_consents SET status = 'expired' WHERE id = ?", (row["id"],))
        record_event(
            conn, user_id=user_id, actor=actor, event_type="aa_consent_expired",
            reason="The bank link reached its end date", run_id=run_id,
            entity_type="aa_consent", entity_id=row["id"],
            before_data={"status": row["status"]}, after_data={"status": "expired"}, clock=now,
        )  # fmt: skip
        expired += 1
    cur = conn.execute(
        "DELETE FROM aa_raw WHERE user_id = ? AND delete_after <= ?", (user_id, to_utc_iso(now))
    )
    deleted = cur.rowcount
    if deleted:
        record_event(
            conn, user_id=user_id, actor=actor, event_type="aa_raw_deleted",
            reason="Fetched copies passed their data life and were deleted", run_id=run_id,
            metadata={"deleted": deleted}, clock=now,
        )  # fmt: skip
    return expired, deleted
