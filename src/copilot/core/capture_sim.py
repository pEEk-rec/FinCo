"""
The payment simulator (PLAN_CAPTURE Stage C3).

It renders a realistic bank alert for a chosen bank and kind, then sends it through the *real*
parser and the *real* capture pipeline, so a demo (or a test) with no phone exercises everything
a real alert would. The rendered text is synthetic; the resulting event is always marked
simulated, in every view.

The renderers below are the mirror image of `config/sms_templates/*.yaml`. A test renders every
bank and kind and parses each back, so a template change that the simulator does not follow
fails loudly.
"""

# ruff: noqa: E501  (the message templates below are single long lines on purpose)
from __future__ import annotations

import uuid
from datetime import datetime

from copilot.config.capture import SmsSendersConfig, load_sms_senders, load_sms_templates
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.sms_parser import Dropped, ParsedPayment, Unparsed, parse_sms
from copilot.core.timeutil import IST

KINDS = ("debit", "credit", "card", "atm", "autopay", "reversal")
_MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: bank -> kind -> message. Placeholders are filled from `_fields`.
_RENDER: dict[str, dict[str, str]] = {
    "hdfc": {
        "debit": "Sent Rs.{amt} From HDFC Bank A/C *{acc} To {name} On {d_slash} Ref {utr} Not You? Call 18002586161/SMS BLOCK UPI to 7308080808",
        "credit": "Credit Alert! Rs.{amt} credited to HDFC Bank A/c XX{acc} on {d_dash} from VPA {vpa} (UPI {utr})",
        "card": "Spent Rs.{amt} On HDFC Bank Card {acc} At {name} On {d_iso}:{t}.Not You? Call 18002586161",
        "atm": "Rs {amt} withdrawn from HDFC Bank A/c XX{acc} at ATM on {d_dash} {hm}",
        "autopay": "Rs {amt} debited from a/c **{acc} on {d_dash} for UPI AutoPay mandate {name} (Ref {utr})",
        "reversal": "Rs {amt} credited to a/c **{acc} on {d_dash} towards reversal of UPI txn Ref {utr}",
    },
    "sbi": {
        "debit": "Dear UPI user A/C X{acc} debited by {amt} on date {d_mon} trf to {name} Refno {utr}. If not u? call 1800111109. -SBI",
        "credit": "Dear UPI user A/C X{acc} credited by Rs {amt} on {d_mon} trf from {name} Refno {utr} -SBI",
        "card": "Rs {amt} spent on your SBI Card ending {acc} at {name} on {d_slash}",
        "atm": "Rs {amt} withdrawn at SBI ATM from A/C X{acc} on {d_mon}. Avl Bal Rs 9000.00",
        "autopay": "Rs {amt} debited from A/C X{acc} on {d_mon} UPI AutoPay mandate to {name} Refno {utr}",
        "reversal": "Dear UPI user A/C X{acc} credited by Rs {amt} on {d_mon} refund of Refno {utr} -SBI",
    },
    "icici": {
        "debit": "ICICI Bank Acct XX{acc3} debited for Rs {amt} on {d_mon_dash}; {name} credited. UPI:{utr}. Call 18002662 for dispute.",
        "credit": "ICICI Bank Acct XX{acc3} credited with Rs {amt} on {d_mon_dash} from {name}. UPI:{utr}",
        "card": "Rs {amt} spent using ICICI Bank Card XX{acc} on {d_mon_dash} on {name}. Avl Limit: Rs 50,000.00.",
        "atm": "ICICI Bank Acct XX{acc3} debited with Rs {amt} on {d_mon_dash} ATM WDL. Avl Bal Rs 9000.00",
        "autopay": "ICICI Bank Acct XX{acc3} debited for Rs {amt} on {d_mon_dash} towards UPI AutoPay {name}. UPI:{utr}",
        "reversal": "ICICI Bank Acct XX{acc3} credited with Rs {amt} on {d_mon_dash} as reversal of UPI:{utr}",
    },
    "axis": {
        "debit": "Debit INR {amt} A/c no. XX{acc} {d_dash} {t} UPI/P2P/{utr}/{name} SMS BLOCKUPI Cust ID to 919951860002 Axis Bank",
        "credit": "Credit INR {amt} A/c no. XX{acc} {d_dash} UPI/P2A/{utr}/{name} Axis Bank",
        "card": "INR {amt} spent on Axis Bank Card no. XX{acc} {d_dash} {t} at {name}. Avl Lmt INR 50000.00",
        "atm": "INR {amt} withdrawn from A/c no. XX{acc} {d_dash} {t} at ATM-WDL",
        "autopay": "Debit INR {amt} A/c no. XX{acc} {d_dash} {t} UPI AutoPay/{utr}/{name} Axis Bank",
        "reversal": "Credit INR {amt} A/c no. XX{acc} {d_dash} UPI/REV/{utr}",
    },
    "kotak": {
        "debit": "Sent Rs.{amt} from Kotak Bank AC X{acc} to {vpa} on {d_dash}.UPI Ref {utr}. Not you, https://kotak.com/KBANKT/Fraud",
        "credit": "Received Rs.{amt} in your Kotak Bank AC X{acc} from {vpa} on {d_dash}.UPI Ref {utr}.",
        "card": "Rs.{amt} spent on your Kotak Credit Card ending {acc} at {name} on {d_dash}.",
        "atm": "Rs.{amt} withdrawn from Kotak Bank AC X{acc} at ATM on {d_dash}.",
        "autopay": "Rs.{amt} debited from Kotak Bank AC X{acc} on {d_dash} for UPI AutoPay {name}.UPI Ref {utr}",
        "reversal": "Rs.{amt} reversed to your Kotak Bank AC X{acc} on {d_dash}.UPI Ref {utr}",
    },
}

#: The sender header the simulator pretends the alert came from, per bank.
SENDERS = {
    "hdfc": "HDFCBK",
    "sbi": "SBIUPI",
    "icici": "ICICIB",
    "axis": "AXISBK",
    "kotak": "KOTAKB",
}
BANK_NAMES = {
    "hdfc": "HDFC Bank", "sbi": "State Bank of India", "icici": "ICICI Bank",
    "axis": "Axis Bank", "kotak": "Kotak Mahindra Bank",
}  # fmt: skip


def banks() -> list[dict[str, str]]:
    return [{"code": c, "name": BANK_NAMES[c]} for c in sorted(_RENDER)]


def _rupees(paise: int) -> str:
    return f"{paise // 100}.{paise % 100:02d}"


def _fields(
    paise: int, name: str, vpa: str | None, utr: str, when: datetime, account: str
) -> dict[str, str]:
    d = when.astimezone(IST)
    yy = f"{d.year % 100:02d}"
    handle = vpa or f"{''.join(c for c in name.lower() if c.isalnum())[:14] or 'payee'}@ybl"
    return {
        "amt": _rupees(paise),
        "acc": account,
        "acc3": account[-3:],
        "name": name.upper() if len(name.split()) <= 3 else name,
        "vpa": handle,
        "utr": utr,
        "d_slash": f"{d.day:02d}/{d.month:02d}/{yy}",
        "d_dash": f"{d.day:02d}-{d.month:02d}-{yy}",
        "d_mon": f"{d.day:02d}{_MONTH[d.month - 1]}{yy}",
        "d_mon_dash": f"{d.day:02d}-{_MONTH[d.month - 1]}-{yy}",
        "d_iso": f"{d.year}-{d.month:02d}-{d.day:02d}",
        "t": f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}",
        "hm": f"{d.hour:02d}:{d.minute:02d}",
    }


def new_utr() -> str:
    return str(int(uuid.uuid4().int % 10**12)).zfill(12)


def render_sms(
    bank: str,
    kind: str,
    amount_paise: int,
    counterparty: str,
    when: datetime,
    *,
    vpa: str | None = None,
    utr: str | None = None,
    account_last4: str = "1234",
) -> str:
    """A realistic alert for this bank and kind. Synthetic: nothing here is a real message."""
    if bank not in _RENDER:
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"No simulator for bank {bank!r}.")
    if kind not in _RENDER[bank]:
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Unknown kind {kind!r}.")
    fields = _fields(amount_paise, counterparty, vpa, utr or new_utr(), when, account_last4)
    return _RENDER[bank][kind].format(**fields)


def _all_enabled() -> SmsSendersConfig:
    """The simulator works for every bank even while the real allowlist has none enabled."""
    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = True
    return SmsSendersConfig.model_validate(raw)


def simulate_alert(
    bank: str,
    kind: str,
    amount_paise: int,
    counterparty: str,
    when: datetime,
    *,
    vpa: str | None = None,
    utr: str | None = None,
    account_last4: str = "1234",
) -> tuple[ParsedPayment, str]:
    """Render, then parse with the real parser. Returns (parsed fields, the synthetic text)."""
    text = render_sms(
        bank, kind, amount_paise, counterparty, when, vpa=vpa, utr=utr, account_last4=account_last4
    )
    out = parse_sms(
        SENDERS[bank], text, when, senders=_all_enabled(), templates=load_sms_templates()
    )
    if isinstance(out, Unparsed | Dropped):
        raise ToolFailure(
            ErrorCode.INTERNAL, f"The simulator's {bank} {kind} alert did not parse ({out})."
        )
    return out, text
