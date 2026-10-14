"""
Parse bank transaction alerts (SMS or push text) into a structured payment.

Indian banks word these differently, so one tolerant reader handles the common shapes:
amount (Rs / INR / rupee sign), direction (debited, spent, credited, received), the account
tail, the UPI reference, the counterparty and the date. Anything that is not a completed
payment (OTPs, mandates, "will be debited", failed attempts) is refused rather than guessed.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from copilot.core.money import rupees_to_paise
from copilot.core.timeutil import IST, to_utc_iso

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_DEBIT = re.compile(r"\b(debited|spent|paid|withdrawn|withdrawal|sent|purchase)\b", re.I)
_CREDIT = re.compile(r"\b(credited|received|deposited|refund(?:ed)?|reversed)\b", re.I)
_SKIP = re.compile(
    r"\b(otp|one[- ]time|will be debited|has been requested|request(?:ed)?|due on|declined|"
    r"failed|unsuccessful|autopay (?:mandate|set)|mandate)\b",
    re.I,
)
_ACCOUNT = re.compile(r"(?:a/?c|acct|account|card)[^0-9]{0,15}(\d{4})\b", re.I)
_REF = re.compile(
    r"(?:ref(?:erence)?\.?\s*(?:no\.?|number)?\s*[:\-]?\s*|upi[:/]\s*(?:ref\s*(?:no)?\.?\s*)?|"
    r"rrn\s*:?\s*|p2[ma]/)(\d{9,12})",
    re.I,
)
_ANY_REF = re.compile(r"\b(\d{12})\b")
_DATE_NAMED = re.compile(r"\b(\d{1,2})[-/ ]?([A-Za-z]{3})[a-z]*[-/ ]?(\d{2,4})\b")
_DATE_NUM = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_BANKS = {
    "sbi": "SBI",
    "hdfc": "HDFC",
    "icici": "ICICI",
    "axis": "Axis",
    "kotak": "Kotak",
    "pnb": "PNB",
    "canara": "Canara",
}
_NOT_A_PARTY = re.compile(r"^(a/?c|acct|account|your|card|bank|upi)\b", re.I)


@dataclass(frozen=True)
class ParsedSms:
    """A completed payment read from an alert."""

    direction: str  # "debit" | "credit"
    amount_paise: int  # always positive
    account_tail: str | None
    merchant: str
    reference: str | None
    occurred_at: str  # UTC, "...Z"
    bank: str | None
    is_card: bool
    is_p2p: bool


class NotAPayment(ValueError):
    """The text is not a completed payment alert."""


def _paise(text: str) -> int:
    return rupees_to_paise(text.replace(",", ""))


def _first_amount(text: str) -> int:
    for m in _AMOUNT.finditer(text):
        before = text[max(0, m.start() - 24) : m.start()].lower()
        if "bal" in before or "limit" in before or "avl" in before:
            continue
        return _paise(m.group(1))
    raise NotAPayment("no amount in the message")


def _direction(text: str) -> str:
    d, c = _DEBIT.search(text), _CREDIT.search(text)
    if d and c:
        return "debit" if d.start() < c.start() else "credit"
    if d:
        return "debit"
    if c:
        return "credit"
    raise NotAPayment("no debit or credit word in the message")


def _when(text: str, received_at: datetime) -> str:
    year = month = day = None
    m = _DATE_NAMED.search(text)
    if m and m.group(2).lower() in _MONTHS:
        day, month, year = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    else:
        n = _DATE_NUM.search(text)
        if n:
            day, month, year = int(n.group(1)), int(n.group(2)), int(n.group(3))
    if year is None:
        return to_utc_iso(received_at)
    year += 2000 if year < 100 else 0
    t = _TIME.search(text)
    hh, mm, ss = (
        (int(t.group(1)), int(t.group(2)), int(t.group(3) or 0))
        if t
        else (
            received_at.astimezone(IST).hour,
            received_at.astimezone(IST).minute,
            0,
        )
    )
    try:
        return to_utc_iso(datetime(year, month, day, hh, mm, ss, tzinfo=IST))
    except ValueError as exc:
        raise NotAPayment("unreadable date") from exc


def _merchant(text: str, direction: str) -> str:
    vpa = re.search(r"\bvpa\s+([\w.\-]+@[\w]+)", text, re.I)
    if vpa:
        return vpa.group(1)
    p2 = re.search(r"upi/p2[ma]/\d+/([^/]+?)(?:/|\s*$)", text, re.I)
    if p2:
        return p2.group(1)
    icici = re.search(r";\s*([A-Za-z0-9 &*.\-]{2,30}?)\s+(?:credited|debited)", text)
    if icici:
        return icici.group(1).strip()
    word = r"(?:from|by)" if direction == "credit" else r"(?:to|at)"
    for m in re.finditer(
        rf"\b{word}\s+([A-Za-z][A-Za-z0-9&*.' \-]{{2,35}}?)(?=\s+(?:on|ref|upi|via|using|if|avl|"
        rf"bal|\()|[.,;]|\s*$)",
        text,
        re.I,
    ):
        candidate = m.group(1).strip()
        if not _NOT_A_PARTY.match(candidate):
            return candidate
    return "UNKNOWN"


def parse_sms(text: str, received_at: datetime) -> ParsedSms:
    """Read one alert. Raises NotAPayment for anything that is not a completed payment."""
    body = " ".join(text.split())
    if len(body) < 12 or len(body) > 600:
        raise NotAPayment("message length is not a bank alert")
    if _SKIP.search(body):
        raise NotAPayment("not a completed payment (OTP, request, mandate or failure)")
    amount = _first_amount(body)
    if amount <= 0:
        raise NotAPayment("amount must be positive")
    direction = _direction(body)
    account = _ACCOUNT.search(body)
    ref = _REF.search(body) or _ANY_REF.search(body)
    merchant = _merchant(body, direction)
    lower = body.lower()
    bank = next((name for key, name in _BANKS.items() if key in lower), None)
    p2p = bool(re.search(r"upi/p2a/|\bp2p\b", lower)) or (
        "@" in merchant and not re.search(r"[a-z]{4,}\d*@", merchant.lower().split("@")[0] + "@")
    )
    return ParsedSms(
        direction=direction,
        amount_paise=amount,
        account_tail=account.group(1) if account else None,
        merchant=merchant,
        reference=ref.group(1) if ref else None,
        occurred_at=_when(body, received_at),
        bank=bank,
        is_card=bool(re.search(r"\bcard\b", lower)),
        is_p2p=p2p,
    )
