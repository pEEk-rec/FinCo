"""The redaction script keeps structure and removes everything personal (PLAN_CAPTURE C2)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "redact_sms.py"
spec = importlib.util.spec_from_file_location("redact_sms", SCRIPT)
redact = importlib.util.module_from_spec(spec)
sys.modules["redact_sms"] = redact
spec.loader.exec_module(redact)

from datetime import datetime  # noqa: E402

from copilot.config.capture import (  # noqa: E402
    SmsSendersConfig,
    load_sms_senders,
    load_sms_templates,
)
from copilot.core.sms_parser import ParsedPayment, parse_sms  # noqa: E402
from copilot.core.timeutil import IST  # noqa: E402

REAL = [
    (
        "HDFCBK",
        "Sent Rs.1,234.50 From HDFC Bank A/C *4821 To SURESH PATEL On 17/10/26 Ref 628455190823 Not You? Call 18002586161",
    ),
    (
        "SBIUPI",
        "Dear UPI user A/C X7345 debited by 389.0 on date 17Oct26 trf to ANITA RAO Refno 628455190824. -SBI",
    ),
    (
        "KOTAKB",
        "Sent Rs.250.00 from Kotak Bank AC X1976 to suresh.patel77@okhdfcbank on 17-10-26.UPI Ref 628455190825.",
    ),
    (
        "AXISBK",
        "Debit INR 90.00 A/c no. XX3302 17-10-26 10:45:12 UPI/P2P/628455190826/GREEN LEAF CAFE SMS BLOCKUPI Cust ID to 919951860002 Axis Bank",
    ),
]


@pytest.mark.parametrize(("sender", "text"), REAL)
def test_nothing_personal_survives(sender, text):
    out, found = redact.redact_message(text)
    assert found, "something sensitive must have been found"
    assert redact.leaks(found, out) == []
    for secret in (
        "SURESH",
        "PATEL",
        "ANITA",
        "RAO",
        "4821",
        "7345",
        "1976",
        "3302",
        "628455190",
        "919951860002",
    ):
        assert secret.lower() not in out.lower(), secret


@pytest.mark.parametrize(("sender", "text"), REAL)
def test_the_redacted_message_still_parses_to_the_same_shape(sender, text):
    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = True
    senders, templates = SmsSendersConfig.model_validate(raw), load_sms_templates()
    now = datetime(2026, 10, 18, tzinfo=IST)
    before = parse_sms(sender, text, now, senders, templates)
    after = parse_sms(sender, redact.redact_message(text)[0], now, senders, templates)
    assert isinstance(before, ParsedPayment) and isinstance(after, ParsedPayment)
    assert (before.kind, before.channel, before.direction, before.occurred_at) == (
        after.kind, after.channel, after.direction, after.occurred_at,
    )  # fmt: skip
    assert before.amount_paise != after.amount_paise, "the amount must have been replaced"


def test_it_is_deterministic_and_the_seed_changes_the_made_up_values():
    text = REAL[0][1]
    assert redact.redact_message(text)[0] == redact.redact_message(text)[0]
    assert redact.redact_message(text, "a")[0] != redact.redact_message(text, "b")[0]


def test_dates_and_wording_are_kept():
    out, _ = redact.redact_message(REAL[0][1])
    assert "17/10/26" in out and out.startswith("Sent Rs.") and "Not You?" in out


def test_the_same_person_gets_the_same_placeholder_within_a_message():
    out, _ = redact.redact_message(
        "Sent Rs.5.00 to RAMESH K on 1/1/26 and later to RAMESH K on 2/1/26"
    )
    assert out.count("PERSON ONE") == 2


def test_the_command_line_round_trip(tmp_path, capsys):
    src = tmp_path / "mine.json"
    src.write_text(json.dumps([{"sender": s, "text": t} for s, t in REAL]), encoding="utf-8")
    dest = tmp_path / "out" / "corpus.json"
    sys.argv = ["redact_sms.py", str(src), "--out", str(dest)]
    assert redact.main() == 0
    corpus = json.loads(dest.read_text(encoding="utf-8"))
    assert len(corpus) == 4 and all(isinstance(c["expect"], dict) for c in corpus)
    blob = dest.read_text(encoding="utf-8")
    assert "SURESH" not in blob and "628455190823" not in blob


def test_sender_filter_keeps_only_the_chosen_senders(tmp_path):
    src = tmp_path / "mine.json"
    src.write_text(json.dumps([{"sender": s, "text": t} for s, t in REAL]), encoding="utf-8")
    dest = tmp_path / "o.json"
    sys.argv = ["redact_sms.py", str(src), "--out", str(dest), "--senders", "HDFCBK"]
    redact.main()
    assert [c["sender"] for c in json.loads(dest.read_text(encoding="utf-8"))] == ["HDFCBK"]
