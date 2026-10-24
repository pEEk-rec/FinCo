"""
Redact your own bank SMS into safe test fixtures (PLAN_CAPTURE Stage C2).

Run this on your own computer, on your own exported messages, *before* anything goes into the
repository. Never paste raw messages into a chat or into any online tool.

    python scripts/redact_sms.py my_sms.json --out tests/sms_corpus/mine_hdfc.json

Accepted input: a JSON list of {"sender": ..., "text": ...} (also "address"/"body"), a CSV with
those columns, or an "SMS Backup & Restore" XML file. Output: a JSON corpus in the format of
tests/sms_corpus/*.json, with the expected parse pre-filled from the current templates for you
to review and correct by hand.

What is replaced, keeping the wording and layout so templates still match:
  amounts and balances, UTR/RRN and phone numbers, account and card digits, UPI handles,
  names after words like "to", "from", "at" and "trf to", and any other run of 5+ digits.
Dates and times are kept (they decide how a template reads them). Look over the output before
you commit it; the script also refuses to write a file in which an original value survived.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_AMOUNT = re.compile(r"(?i)((?:rs\.?|inr|₹)\s*)(\d[\d,]*(?:\.\d{1,2})?)")
_BARE_AMOUNT = re.compile(r"(?i)\b((?:debited|credited) by\s+)(\d[\d,]*(?:\.\d{1,2})?)")
_VPA = re.compile(r"\b([A-Za-z0-9._\-]{2,})@([A-Za-z0-9]{2,})\b")
_ACCOUNT = re.compile(r"(?i)\b((?:a/c|acct|account|card|ac)\b[^0-9]{0,14}[xX*]*)(\d{3,4})\b")
_LONG_DIGITS = re.compile(r"(?<!\d)(\d{5,})(?!\d)")
_NAME = re.compile(
    r"(?i)\b(to|from|at|trf to|trf from|paid to|received from)\s+"
    r"(?!vpa\b|your\b|hdfc\b|sbi\b|icici\b|axis\b|kotak\b|a/c\b|ac\b|atm\b|bank\b)"
    r"([A-Za-z][A-Za-z.&' ]{1,38}?)"
    r"(?=\s+(?:on|ref|refno|upi|not|sms|avl|if|call|dated|using|credited|"
    r"debited)\b|[.;,(]|$)"
)
_ORDINALS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN"]


def _digest(seed: str, value: str) -> int:
    return int(hashlib.sha256(f"{seed}|{value}".encode()).hexdigest(), 16)


def _digits_like(seed: str, original: str) -> str:
    n = len(original)
    d = str(_digest(seed, original))[:n].ljust(n, "7")
    return d if d != original else d[:-1] + str((int(d[-1]) + 1) % 10)


def _amount_like(seed: str, original: str) -> str:
    """A different amount with the same number of decimals; the digits are made up."""
    decimals = len(original.split(".")[1]) if "." in original else 0
    rupees = 10 + _digest(seed, original) % 49990
    if original.replace(",", "").split(".")[0] == str(rupees):
        rupees += 1
    text = f"{rupees:,}" if "," in original else str(rupees)
    return text + (
        f".{_digest(seed, original + 'd') % 100:02d}"[: decimals + 1] if decimals else ""
    )


def redact_message(text: str, seed: str = "finco") -> tuple[str, set[str]]:
    """(redacted text, the original sensitive values that were replaced)."""
    found: set[str] = set()
    names: dict[str, str] = {}

    def amount(m: re.Match) -> str:
        found.add(m.group(2))
        return m.group(1) + _amount_like(seed, m.group(2))

    def vpa(m: re.Match) -> str:
        found.add(m.group(0))
        return f"user{_digest(seed, m.group(1)) % 90 + 10}@{m.group(2)}"

    def account(m: re.Match) -> str:
        found.add(m.group(2))
        return m.group(1) + _digits_like(seed, m.group(2))

    def name(m: re.Match) -> str:
        who = m.group(2).strip()
        found.add(who)
        placeholder = names.setdefault(who.lower(), f"PERSON {_ORDINALS[len(names) % 10]}")
        return f"{m.group(1)} {placeholder}"

    def long_digits(m: re.Match) -> str:
        found.add(m.group(1))
        return _digits_like(seed, m.group(1))

    out = _VPA.sub(vpa, text)
    out = _AMOUNT.sub(amount, out)
    out = _BARE_AMOUNT.sub(amount, out)
    out = _ACCOUNT.sub(account, out)
    out = _NAME.sub(name, out)
    out = _LONG_DIGITS.sub(long_digits, out)
    return out, found


def leaks(original_values: set[str], redacted: str) -> list[str]:
    """Original values (long enough to mean something) that survived in the output."""
    return sorted(v for v in original_values if len(v) >= 4 and v in redacted)


def _load(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        root = ET.parse(path).getroot()
        return [
            {"sender": s.get("address", ""), "text": s.get("body", "")} for s in root.iter("sms")
        ]
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "sender": str(r.get("sender") or r.get("address") or ""),
            "text": str(r.get("text") or r.get("body") or ""),
        }
        for r in rows
    ]


def _expected(sender: str, text: str) -> object:
    """What the current templates make of the (redacted) message, for the owner to review."""
    from copilot.config.capture import SmsSendersConfig, load_sms_senders, load_sms_templates
    from copilot.core.sms_parser import Dropped, ParsedPayment, parse_sms
    from copilot.core.timeutil import IST

    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = True
    out = parse_sms(
        sender,
        text,
        datetime.now(tz=IST),
        SmsSendersConfig.model_validate(raw),
        load_sms_templates(),
    )
    if isinstance(out, ParsedPayment):
        when = datetime.fromisoformat(out.occurred_at.replace("Z", "+00:00")).astimezone(IST)
        return {
            "kind": out.kind, "direction": out.direction, "amount_paise": out.amount_paise,
            "account_last4": out.account_last4, "utr": out.utr, "display_name": out.display_name,
            "vpa": out.vpa, "channel": out.channel,
            "occurred_at_ist": when.strftime("%Y-%m-%dT%H:%M:%S"),
        }  # fmt: skip
    if isinstance(out, Dropped):
        return f"dropped:{out.reason}"
    return "unparsed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("input", type=Path, help="your exported messages (json, csv or xml)")
    ap.add_argument("--out", type=Path, required=True, help="where to write the redacted corpus")
    ap.add_argument("--senders", nargs="*", help="keep only these sender ids (recommended)")
    ap.add_argument("--seed", default="finco", help="changes the made-up replacement values")
    args = ap.parse_args()

    keep = {s.upper() for s in args.senders or []}
    out: list[dict] = []
    sensitive: set[str] = set()
    for i, msg in enumerate(_load(args.input), 1):
        if (
            keep
            and msg["sender"].strip().upper() not in keep
            and not any(k in msg["sender"].upper() for k in keep)
        ):
            continue
        redacted, found = redact_message(msg["text"], args.seed)
        problems = leaks(found, redacted)
        if problems:
            print(f"message {i}: refusing to write, an original value survived", file=sys.stderr)
            return 1
        sensitive |= found
        out.append(
            {
                "name": f"message {len(out) + 1}",
                "sender": msg["sender"],
                "text": redacted,
                "expect": _expected(msg["sender"], redacted),
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    unparsed = sum(1 for m in out if m["expect"] == "unparsed")
    print(
        f"wrote {len(out)} redacted messages to {args.out}; {unparsed} did not match any template."
    )
    print("Review each 'expect' by hand before committing. Delete your original export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
