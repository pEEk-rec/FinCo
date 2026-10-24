"""
Bank SMS parser (PLAN_CAPTURE Stage C2), driven by the per-bank template files.

Privacy and safety rules, all enforced here and tested:
- The sender is checked against the allowlist *before the text is touched*. A message from any
  other sender is dropped without being read.
- A one-time-password message is dropped even from an allowed bank.
- Only structured fields come out. The text is not kept, logged or returned.
- Amounts are parsed as integers (paise) from the digits; no floating point is ever involved.
- A message that matches no template is `unparsed` (counted, never guessed).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from copilot.config.capture import (
    BankTemplates,
    SmsSendersConfig,
    SmsTemplate,
    load_capture_config,
    load_sms_senders,
    load_sms_templates,
)
from copilot.core.timeutil import IST, to_utc_iso

#: A floor in code, under the per-bank OTP guards: these never reach a template.
_OTP_FLOOR = re.compile(r"(?i)\b(otp|one[- ]time password|verification code|cvv)\b")
_SENDER = re.compile(r"^(?:[A-Z]{2}-)?(?P<id>[A-Z0-9]+?)(?:-[A-Z])?$")
_KIND_ORDER = ("reversal", "autopay", "upi_lite_summary", "debit", "credit")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_CHANNELS = (("atm", "atm"), ("autopay", "autopay"), ("card", "card"), ("neft", "neft"),
             ("imps", "imps"), ("upi", "upi"))  # fmt: skip


@dataclass(frozen=True)
class ParsedPayment:
    """The only thing that leaves the parser. No message text."""

    bank: str
    kind: Literal["debit", "credit", "reversal", "autopay", "upi_lite_summary"]
    direction: Literal["debit", "credit"]
    amount_paise: int
    account_last4: str | None
    utr: str | None
    display_name: str
    vpa: str | None
    channel: str
    occurred_at: str  # UTC
    template: str


@dataclass(frozen=True)
class Dropped:
    reason: Literal["sender_not_allowed", "bank_disabled", "too_long", "otp"]
    bank: str | None = None
    sender: str | None = None  # only for allowlisted senders; never for strangers


@dataclass(frozen=True)
class Unparsed:
    bank: str
    sender: str


ParseOutcome = ParsedPayment | Dropped | Unparsed


def normalise_sender(raw: str) -> str:
    """'VM-HDFCBK-S' and 'hdfcbk' are both 'HDFCBK'."""
    s = raw.strip().upper()
    m = _SENDER.match(s)
    return m.group("id") if m else s


def amount_to_paise(text: str) -> int:
    """'1,234.50' -> 123450. Digits only, no float anywhere."""
    cleaned = text.replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        raise ValueError("not an amount")
    rupees, _, frac = cleaned.partition(".")
    return int(rupees) * 100 + int(frac.ljust(2, "0") or "0")


def _parse_date(date: str | None, time: str | None, now: datetime) -> str:
    """The alert's own date and time (IST) when present, otherwise `now`."""
    if not date:
        return to_utc_iso(now)
    d = date.strip().lower()
    day = month = year = None
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", d):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[-/ ]?([a-z]{3})[a-z]*[-/ ]?(\d{2,4})", d):
        day, month, year = int(m[1]), _MONTHS.get(m[2], 0), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", d):
        day, month, year = int(m[1]), int(m[2]), int(m[3])
    if not (day and month and year):
        return to_utc_iso(now)
    year = year + 2000 if year < 100 else year
    hh = mm = ss = 0
    if time and (t := re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", time.strip())):
        hh, mm, ss = int(t[1]), int(t[2]), int(t[3] or 0)
    try:
        return to_utc_iso(datetime(year, month, day, hh, mm, ss, tzinfo=IST))
    except ValueError:
        return to_utc_iso(now)


def _channel(groups: dict[str, str | None], kind: str, match_text: str) -> str:
    raw = (groups.get("channel") or "").lower()
    for needle, channel in _CHANNELS:
        if needle in raw:
            return channel
    if kind == "autopay":
        return "autopay"
    lowered = match_text.lower()
    for needle, channel in _CHANNELS:
        if needle in lowered:
            return channel
    return "other"


def _counterparty(raw: str | None, channel: str) -> tuple[str, str | None]:
    """(display name, vpa). A VPA is also shown as a readable name."""
    if channel == "atm":
        return "ATM cash withdrawal", None
    if not raw:
        return "Unknown", None
    text = raw.strip().strip(".,;")
    if "@" in text:
        local = text.split("@", 1)[0]
        readable = " ".join(re.findall(r"[A-Za-z]+", local)).title() or text
        return readable, text.lower()
    return text[:80], None


def _templates_in_order(templates: list[SmsTemplate]) -> list[SmsTemplate]:
    rank = {k: i for i, k in enumerate(_KIND_ORDER)}
    return sorted(
        (t for t in templates if t.kind != "otp"), key=lambda t: rank.get(t.kind, len(rank))
    )


def parse_sms(
    sender: str,
    text: str,
    now: datetime,
    senders: SmsSendersConfig | None = None,
    templates: dict[str, BankTemplates] | None = None,
    max_chars: int | None = None,
) -> ParseOutcome:
    """Parse one alert. See the module docstring for the rules this enforces."""
    senders = senders or load_sms_senders()
    templates = templates if templates is not None else load_sms_templates()
    allowed = senders.allowed_senders()
    sender_id = normalise_sender(sender)
    bank = allowed.get(sender_id)
    if bank is None:
        # Stop here: the text has not been looked at and the stranger's sender is not kept.
        return Dropped("sender_not_allowed")
    limit = max_chars or load_capture_config().sms.max_text_chars
    if len(text) > limit:
        return Dropped("too_long", bank=bank, sender=sender_id)
    bank_templates = templates.get(bank)
    if bank_templates is None or bank_templates.status != "ready":
        return Dropped("bank_disabled", bank=bank, sender=sender_id)

    if _OTP_FLOOR.search(text) or any(
        re.search(t.pattern, text) for t in bank_templates.templates if t.kind == "otp"
    ):
        return Dropped("otp", bank=bank, sender=sender_id)

    body = " ".join(text.split())
    for tpl in _templates_in_order(bank_templates.templates):
        m = re.search(tpl.pattern, body)
        if not m:
            continue
        g = m.groupdict()
        try:
            amount = amount_to_paise(g["amount"])
        except (KeyError, ValueError, TypeError):
            continue
        if amount <= 0:
            continue
        channel = _channel(g, tpl.kind, body)
        name, vpa = _counterparty(g.get("counterparty"), channel)
        direction = "credit" if tpl.kind in ("credit", "reversal") else "debit"
        if tpl.kind == "upi_lite_summary":
            name, channel = "UPI Lite spends", "upi"
        if tpl.kind == "reversal":
            name = name if g.get("counterparty") else "Reversal"
        account = g.get("account")
        return ParsedPayment(
            bank=bank,
            kind=tpl.kind,  # type: ignore[arg-type]
            direction=direction,
            amount_paise=amount,
            account_last4=account if account and len(account) == 4 else None,
            utr=g.get("utr"),
            display_name=name,
            vpa=vpa,
            channel=channel,
            occurred_at=_parse_date(g.get("date"), g.get("time"), now),
            template=tpl.name,
        )
    return Unparsed(bank=bank, sender=sender_id)


# ---------------------------------------------------------------------------------------------
# Template drift: how often does each sender's wording stop matching?
# ---------------------------------------------------------------------------------------------
def record_parse_outcome(
    conn: sqlite3.Connection, user_id: str, outcome: ParseOutcome, now: datetime
) -> None:
    """Log the outcome (never the text). Strangers are not recorded at all."""
    if isinstance(outcome, ParsedPayment):
        bank, sender, result = outcome.bank, outcome.bank.upper(), "parsed"
        kind, template = outcome.kind, outcome.template
    elif isinstance(outcome, Unparsed):
        bank, sender, result, kind, template = outcome.bank, outcome.sender, "unparsed", None, None
    elif isinstance(outcome, Dropped) and outcome.reason == "otp" and outcome.sender:
        bank, sender, result = outcome.bank or "", outcome.sender, "dropped_otp"
        kind = template = None
    else:
        return
    conn.execute(
        "INSERT INTO sms_parse_log"
        " (id, user_id, bank, sender, outcome, kind, template, occurred_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"spl_{uuid.uuid4().hex[:12]}", user_id, bank, sender, result, kind, template,
            to_utc_iso(now),
        ),
    )  # fmt: skip


@dataclass(frozen=True)
class DriftRow:
    bank: str
    parsed: int
    unparsed: int
    failure_bp: int
    alert: bool


def drift_report(conn: sqlite3.Connection, user_id: str, now: datetime) -> list[DriftRow]:
    """Parse-failure rate per bank over the configured window, with the alarm flag."""
    cfg = load_capture_config().sms
    since = to_utc_iso(now - timedelta(days=cfg.drift_window_days))
    rows = conn.execute(
        "SELECT bank, SUM(outcome = 'parsed') AS parsed, SUM(outcome = 'unparsed') AS unparsed"
        " FROM sms_parse_log WHERE user_id = ? AND occurred_at >= ? GROUP BY bank ORDER BY bank",
        (user_id, since),
    ).fetchall()
    out = []
    for r in rows:
        parsed, unparsed = r["parsed"] or 0, r["unparsed"] or 0
        total = parsed + unparsed
        bp = unparsed * 10000 // total if total else 0
        out.append(
            DriftRow(
                r["bank"],
                parsed,
                unparsed,
                bp,
                alert=total >= cfg.drift_min_messages and bp > cfg.drift_alert_bp,
            )  # fmt: skip
        )
    return out
