"""
The SMS parser (PLAN_CAPTURE Stage C2): a golden corpus of invented, redacted-style messages,
and the safety properties that must hold for any input.
"""

import inspect
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from copilot.config.capture import SmsSendersConfig, load_sms_senders, load_sms_templates
from copilot.core import sms_parser
from copilot.core.sms_parser import (
    Dropped,
    ParsedPayment,
    Unparsed,
    amount_to_paise,
    drift_report,
    normalise_sender,
    parse_sms,
    record_parse_outcome,
)
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_user
from copilot.models.domain import User

CORPUS = Path(__file__).resolve().parents[1] / "sms_corpus"
NOW = datetime(2026, 10, 18, 11, 0, tzinfo=IST)


def _all_banks_enabled() -> SmsSendersConfig:
    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = True
    return SmsSendersConfig.model_validate(raw)


SENDERS = _all_banks_enabled()
TEMPLATES = load_sms_templates()


def _cases():
    for path in sorted(CORPUS.glob("*.json")):
        for c in json.loads(path.read_text(encoding="utf-8")):
            yield pytest.param(c, id=f"{path.stem}: {c['name']}")


def _parse(sender, text):
    return parse_sms(sender, text, NOW, senders=SENDERS, templates=TEMPLATES)


@pytest.mark.parametrize("case", list(_cases()))
def test_golden_corpus(case):
    out = _parse(case["sender"], case["text"])
    expect = case["expect"]
    if expect == "unparsed":
        assert isinstance(out, Unparsed)
    elif isinstance(expect, str) and expect.startswith("dropped:"):
        assert isinstance(out, Dropped) and out.reason == expect.split(":", 1)[1]
    else:
        assert isinstance(out, ParsedPayment), out
        when = datetime.fromisoformat(expect["occurred_at_ist"]).replace(tzinfo=IST)
        want = {
            "kind": expect["kind"], "direction": expect["direction"],
            "amount_paise": expect["amount_paise"], "account_last4": expect["account_last4"],
            "utr": expect["utr"], "display_name": expect["display_name"], "vpa": expect["vpa"],
            "channel": expect["channel"], "occurred_at": to_utc_iso(when),
        }  # fmt: skip
        got = {k: getattr(out, k) for k in want}
        assert got == want


def test_the_corpus_covers_every_shipped_bank_and_every_kind():
    kinds, banks = set(), set()
    for path in CORPUS.glob("*.json"):
        for c in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(c["expect"], dict):
                kinds.add(c["expect"]["kind"])
                banks.add(path.stem)
    assert banks == set(TEMPLATES)
    assert kinds == {"debit", "credit", "reversal", "autopay", "upi_lite_summary"}


# ---- safety properties ------------------------------------------------------------------------
class _Poison(str):
    """A message that explodes if anything looks inside it."""

    def __getattribute__(self, name):
        raise AssertionError(f"the text was touched: {name}")


def test_a_stranger_is_dropped_without_the_text_ever_being_touched():
    for sender in ("+919812345678", "OFFERS", "HDFCBK1", ""):
        out = parse_sms(sender, _Poison("anything"), NOW, senders=SENDERS, templates=TEMPLATES)
        assert out == Dropped("sender_not_allowed")


def test_a_stranger_is_never_returned_with_a_sender_or_bank():
    out = _parse(
        "RANDOM", "Sent Rs.250.00 From HDFC Bank A/C *1234 To X On 18/10/26 Ref 123456789012"
    )
    assert out.bank is None and out.sender is None


def test_no_message_from_a_sender_off_the_list_ever_parses():
    """Property: the same alert text parses from a listed sender and from no unlisted one."""
    text = "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 628912345678"
    assert isinstance(_parse("HDFCBK", text), ParsedPayment)
    rng = random.Random(7)
    listed = set(SENDERS.allowed_senders())
    for _ in range(300):
        sender = "".join(
            rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-") for _ in range(rng.randint(0, 9))
        )
        if normalise_sender(sender) in listed:
            continue
        assert isinstance(_parse(sender, text), Dropped)


def test_a_disabled_bank_reads_nothing():
    senders = load_sms_senders()  # shipped config: every bank disabled
    out = parse_sms(
        "HDFCBK",
        "Sent Rs.250.00 From HDFC Bank A/C *1234 To X On 18/10/26 Ref 1",
        NOW,
        senders=senders,
    )
    assert out == Dropped("sender_not_allowed")


@pytest.mark.parametrize(
    "text",
    [
        "Your OTP is 123456",
        "one time password 1234 for Rs 250.00 debited from a/c **1234 to VPA a@ybl (UPI Ref No 628912345678)",
        "Verification code 8821: Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 628912345678",
        "cvv 123 for card",
    ],
)
def test_an_otp_is_dropped_even_when_it_also_looks_like_a_payment(text):
    out = _parse("HDFCBK", text)
    assert isinstance(out, Dropped) and out.reason == "otp"


def test_an_overlong_message_is_not_a_bank_alert():
    out = _parse("HDFCBK", "Sent Rs.250.00 " + "x" * 700)
    assert isinstance(out, Dropped) and out.reason == "too_long"


def test_amounts_are_exact_integers_never_floats():
    assert amount_to_paise("1,234.50") == 123450
    assert amount_to_paise("250") == 25000
    assert amount_to_paise("250.5") == 25050
    assert amount_to_paise("0.07") == 7
    assert amount_to_paise("10,00,000.99") == 100000099
    for bad in ("", "abc", "1.234", "-5", "1e3", "1,2,3.456"):
        with pytest.raises(ValueError):
            amount_to_paise(bad)
    source = inspect.getsource(sms_parser)
    assert "float(" not in source, "the parser must never use floating point"


def test_a_zero_amount_is_not_a_payment():
    out = _parse(
        "HDFCBK", "Sent Rs.0.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 628912345678"
    )
    assert isinstance(out, Unparsed)


def test_sender_headers_are_normalised():
    assert normalise_sender("VM-HDFCBK-S") == "HDFCBK"
    assert normalise_sender("hdfcbk") == "HDFCBK"
    assert normalise_sender("AX-SBIUPI") == "SBIUPI"


def test_a_missing_date_falls_back_to_the_arrival_time():
    out = _parse("KOTAKB", "Rs.2000.00 withdrawn from Kotak Bank AC X1234 at ATM on 99-99-26.")
    assert isinstance(out, (ParsedPayment, Unparsed))
    if isinstance(out, ParsedPayment):
        assert out.occurred_at == to_utc_iso(NOW)


def test_the_result_carries_no_message_text():
    out = _parse(
        "HDFCBK",
        "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 628912345678 Not You? Call 18002586161",
    )
    blob = json.dumps(out.__dict__, default=str)
    assert "Not You" not in blob and "18002586161" not in blob


# ---- template drift ---------------------------------------------------------------------------
@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id="u1", created_at="2026-01-01T00:00:00Z"))
    return c


def test_drift_raises_the_alarm_only_with_enough_messages_and_too_many_failures(conn):
    good = "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 628912345678"
    bad = "INR 250.00 was paid via your HDFC wallet"

    def feed(text, n, when):
        for _ in range(n):
            record_parse_outcome(conn, "u1", _parse("HDFCBK", text), when)

    feed(good, 7, NOW)
    feed(bad, 2, NOW)  # 9 messages: below the minimum, no alarm yet
    row = drift_report(conn, "u1", NOW)[0]
    assert (row.parsed, row.unparsed, row.alert) == (7, 2, False)
    feed(good, 1, NOW)  # 10 messages, 2 unparsed (20%): alarm
    row = drift_report(conn, "u1", NOW)[0]
    assert row.failure_bp == 2000 and row.alert is True
    feed(good, 90, NOW)  # 100 messages, 2 unparsed (2%): exactly at the line is not over it
    row = drift_report(conn, "u1", NOW)[0]
    assert row.failure_bp == 200 and row.alert is False


def test_old_failures_age_out_of_the_window(conn):
    bad = "INR 250.00 was paid via your HDFC wallet"
    long_ago = NOW - timedelta(days=60)
    for _ in range(12):
        record_parse_outcome(conn, "u1", _parse("HDFCBK", bad), long_ago)
    assert drift_report(conn, "u1", NOW) == []


def test_strangers_and_text_are_never_logged(conn):
    record_parse_outcome(conn, "u1", _parse("OFFERS", "Credit Alert! Rs.5 secret"), NOW)
    record_parse_outcome(conn, "u1", _parse("HDFCBK", "Rs 1.00 hello unparsed secret words"), NOW)
    rows = conn.execute("SELECT * FROM sms_parse_log").fetchall()
    assert len(rows) == 1
    assert "secret" not in json.dumps([tuple(r) for r in rows])
    assert rows[0]["sender"] == "HDFCBK" and rows[0]["outcome"] == "unparsed"
