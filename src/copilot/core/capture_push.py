"""
Web Push for payment prompts (PLAN_CAPTURE Stage C6b).

Each of the user's devices (a laptop browser, a phone) subscribes once. When a prompt is created
that the ask policy wants answered, every subscribed device is sent a small push. Rules, tested:

- The payload carries only what a notification needs: a title, a short body, up to
  `max_actions` guess buttons, and ids. With `lock_screen_safe` (the default) it says only
  "1 payment to tag"; the amount and payee stay in the app. Never any message text.
- A notification's buttons answer through a single-use token (a service worker cannot read the
  app's login). A token works once, for one prompt, on the device it was sent to.
- If two devices answer the same payment, the first wins; the second finds it already tagged.
- When one device answers, the others are told to close their notification.
- A subscription the push service reports gone is removed; repeated failures remove it too.
- Sending goes through an injectable function, so tests never use the network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from copilot.audit.events import Actor, record_event
from copilot.config.capture import CaptureConfig, load_capture_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.capture import PromptView

log = logging.getLogger(__name__)

VAPID_FILE = PROJECT_ROOT / "data" / "vapid_keys.json"


class PushGone(Exception):
    """The push service says this subscription no longer exists."""


class PushFailed(Exception):
    """A delivery failed for a reason that may pass."""


#: (subscription {endpoint, keys}, payload json, vapid pem, claims, ttl) -> None
Sender = Callable[[dict, str, str, dict, int], None]


# ---------------------------------------------------------------------------------------------
# VAPID keys: generated locally, kept in a git-ignored file, never printed
# ---------------------------------------------------------------------------------------------
def _public_b64(vapid) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def ensure_vapid(path: Path | None = None) -> tuple[str, str]:
    """(private PEM, public application-server key). Created on first use."""
    env_private, env_public = (
        os.environ.get("VAPID_PRIVATE_KEY"),
        os.environ.get("VAPID_PUBLIC_KEY"),
    )
    if env_private and env_public:
        return env_private.replace("\\n", "\n"), env_public
    file = path or VAPID_FILE
    if file.exists():
        data = json.loads(file.read_text(encoding="utf-8"))
        return data["private_pem"], data["public_key"]
    from py_vapid import Vapid

    v = Vapid()
    v.generate_keys()
    private_pem = v.private_pem().decode("ascii")
    public = _public_b64(v)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps({"private_pem": private_pem, "public_key": public}), encoding="utf-8"
    )
    try:
        file.chmod(0o600)
    except OSError:
        pass
    return private_pem, public


def real_sender(subscription: dict, payload: str, vapid_pem: str, claims: dict, ttl: int) -> None:
    """The production sender, through pywebpush. Not used in tests."""
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=Vapid.from_pem(vapid_pem.encode("ascii")),
            vapid_claims=claims,
            ttl=ttl,
            timeout=10,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone(str(status)) from exc
        raise PushFailed(str(exc)) from exc


# ---------------------------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Subscription:
    id: str
    endpoint: str
    p256dh: str
    auth: str
    label: str
    failures: int

    def info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def _row(r: sqlite3.Row) -> Subscription:
    return Subscription(r["id"], r["endpoint"], r["p256dh"], r["auth"], r["label"], r["failures"])


def subscribe(
    conn: sqlite3.Connection,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    label: str = "This device",
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> str:
    if not endpoint.startswith("https://"):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "A push endpoint must be an https address.")
    if not p256dh or not auth:
        raise ToolFailure(ErrorCode.INVALID_INPUT, "The subscription keys are missing.")
    now = to_utc_iso(now_utc(clock))
    existing = conn.execute(
        "SELECT id FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (user_id, endpoint)
    ).fetchone()
    sub_id = existing[0] if existing else f"psub_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, label, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, endpoint) DO UPDATE SET p256dh = excluded.p256dh,"
        " auth = excluded.auth, label = excluded.label, failures = 0",
        (sub_id, user_id, endpoint, p256dh, auth, label[:40], now),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="push_subscribed",
        reason=f"Notifications turned on for {label[:40]}", entity_type="push_subscription",
        entity_id=sub_id, metadata={"label": label[:40]}, clock=clock,
    )  # fmt: skip
    return sub_id


def unsubscribe(
    conn: sqlite3.Connection, user_id: str, endpoint: str, *, actor: Actor = "user",
    clock: datetime | None = None,
) -> bool:  # fmt: skip
    row = conn.execute(
        "SELECT id, label FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (user_id, endpoint),
    ).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (row["id"],))
    record_event(
        conn, user_id=user_id, actor=actor, event_type="push_unsubscribed",
        reason=f"Notifications turned off for {row['label']}", entity_type="push_subscription",
        entity_id=row["id"], clock=clock,
    )  # fmt: skip
    return True


def list_subscriptions(conn: sqlite3.Connection, user_id: str) -> list[Subscription]:
    rows = conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY created_at, id", (user_id,)
    ).fetchall()
    return [_row(r) for r in rows]


# ---------------------------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------------------------
def build_payload(prompt: PromptView, token: str, cfg: CaptureConfig) -> dict:
    """The only data that ever leaves in a push. Small on purpose."""
    event = prompt.event
    safe = cfg.push.lock_screen_safe
    credit = event.direction == "credit"
    if safe:
        title, body = "1 payment to tag", "Open FinCo to say what it was."
    else:
        from copilot.core.capture_sim import _rupees  # whole rupees with paise, no symbol

        title = f"{'Received' if credit else 'Paid'} ₹{_rupees(event.amount_paise)}"
        body = f"{'from' if credit else 'to'} {event.display_name[:30]}"
    actions = [
        {"action": f"label:{g.label}", "title": g.name[:24]}
        for g in prompt.guesses[: cfg.push.max_actions]
    ]
    return {
        "type": "prompt",
        "prompt_id": prompt.prompt_id,
        "event_id": event.id,
        "credit": credit,
        "title": title,
        "body": body,
        "tag": prompt.prompt_id,
        "token": token,
        "actions": actions,
        "ranks": {a["action"]: i + 1 for i, a in enumerate(actions)},
    }


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------------------------
def _send(
    conn: sqlite3.Connection,
    user_id: str,
    sub: Subscription,
    payload: dict,
    sender: Sender,
    cfg: CaptureConfig,
    now: datetime,
) -> bool:
    private, _public = ensure_vapid()
    try:
        sender(
            sub.info(),
            json.dumps(payload),
            private,
            {"sub": cfg.push.subject},
            cfg.push.ttl_seconds,
        )
    except PushGone:
        conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub.id,))
        record_event(
            conn, user_id=user_id, actor="system", event_type="push_subscription_removed",
            reason="The push service says this device is gone", entity_type="push_subscription",
            entity_id=sub.id, clock=now,
        )  # fmt: skip
        return False
    except Exception:  # noqa: BLE001 - one failing device must never break the others
        failures = sub.failures + 1
        if failures >= cfg.push.max_failures:
            conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub.id,))
        else:
            conn.execute(
                "UPDATE push_subscriptions SET failures = ? WHERE id = ?", (failures, sub.id)
            )
        log.warning("push to %s failed (%d in a row)", sub.id, failures)
        return False
    conn.execute(
        "UPDATE push_subscriptions SET failures = 0, last_ok_at = ? WHERE id = ?",
        (to_utc_iso(now), sub.id),
    )
    return True


def notify_prompt(
    conn: sqlite3.Connection,
    user_id: str,
    prompt: PromptView,
    sender: Sender,
    *,
    clock: datetime | None = None,
    cfg: CaptureConfig | None = None,
) -> int:
    """Push a prompt to every subscribed device. Returns how many were sent."""
    cfg = cfg or load_capture_config()
    if not cfg.push.enabled or prompt.decision != "ask" or prompt.status != "pending":
        return 0
    now = now_utc(clock)
    sent = 0
    for sub in list_subscriptions(conn, user_id):
        if conn.execute(
            "SELECT 1 FROM push_deliveries WHERE subscription_id = ? AND prompt_id = ?",
            (sub.id, prompt.prompt_id),
        ).fetchone():
            continue  # this device already has it
        token = secrets.token_urlsafe(18)
        conn.execute(
            "INSERT INTO push_deliveries"
            " (id, user_id, subscription_id, prompt_id, token_hash, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"pdl_{uuid.uuid4().hex[:12]}",
                user_id,
                sub.id,
                prompt.prompt_id,
                _hash(token),
                to_utc_iso(now),
            ),
        )
        if _send(conn, user_id, sub, build_payload(prompt, token, cfg), sender, cfg, now):
            sent += 1
    return sent


def notify_resolved(
    conn: sqlite3.Connection,
    user_id: str,
    prompt_id: str,
    sender: Sender,
    *,
    except_subscription: str | None = None,
    clock: datetime | None = None,
    cfg: CaptureConfig | None = None,
) -> int:
    """Tell every device that received this prompt to close its notification."""
    cfg = cfg or load_capture_config()
    if not cfg.push.enabled:
        return 0
    now = now_utc(clock)
    rows = conn.execute(
        "SELECT s.* FROM push_deliveries d JOIN push_subscriptions s ON s.id = d.subscription_id"
        " WHERE d.user_id = ? AND d.prompt_id = ?",
        (user_id, prompt_id),
    ).fetchall()
    sent = 0
    for r in rows:
        sub = _row(r)
        if sub.id == except_subscription:
            continue
        payload = {"type": "close", "prompt_id": prompt_id, "tag": prompt_id}
        if _send(conn, user_id, sub, payload, sender, cfg, now):
            sent += 1
    return sent


# ---------------------------------------------------------------------------------------------
# A notification button was pressed
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Delivery:
    id: str
    subscription_id: str
    prompt_id: str


def verify_token(
    conn: sqlite3.Connection, user_id: str, token: str, prompt_id: str
) -> Delivery | None:
    """The delivery this token belongs to, if it is genuine, for this prompt, and unused."""
    row = conn.execute(
        "SELECT id, subscription_id, prompt_id FROM push_deliveries WHERE user_id = ?"
        " AND token_hash = ? AND prompt_id = ? AND used_at IS NULL",
        (user_id, _hash(token), prompt_id),
    ).fetchone()
    return Delivery(row["id"], row["subscription_id"], row["prompt_id"]) if row else None


def mark_used(conn: sqlite3.Connection, delivery: Delivery, now: datetime) -> None:
    conn.execute(
        "UPDATE push_deliveries SET used_at = ? WHERE id = ?", (to_utc_iso(now), delivery.id)
    )


def prompt_is_pending(conn: sqlite3.Connection, user_id: str, prompt_id: str) -> str | None:
    """The event id when this prompt is still waiting for an answer, else None."""
    row = conn.execute(
        "SELECT event_id FROM prompt_log WHERE user_id = ? AND id = ? AND status = 'pending'",
        (user_id, prompt_id),
    ).fetchone()
    return row[0] if row else None
