"""The simulator renders what each bank's template expects, and the result is always simulated."""

from datetime import datetime

import pytest

from copilot.core.capture_sim import KINDS, SENDERS, render_sms, simulate_alert
from copilot.core.errors import ToolFailure
from copilot.core.timeutil import IST, to_utc_iso

WHEN = datetime(2026, 10, 18, 10, 45, 12, tzinfo=IST)
BANKS = sorted(SENDERS)

EXPECT_DIRECTION = {
    "debit": "debit", "card": "debit", "atm": "debit", "autopay": "debit",
    "credit": "credit", "reversal": "credit",
}  # fmt: skip


@pytest.mark.parametrize("bank", BANKS)
@pytest.mark.parametrize("kind", KINDS)
def test_every_bank_and_kind_round_trips_through_the_real_parser(bank, kind):
    parsed, text = simulate_alert(
        bank,
        kind,
        123450,
        "Ramesh K",
        WHEN,
        vpa="ramesh@ybl",
        utr="628912345678",
        account_last4="4321",
    )
    assert parsed.amount_paise == 123450
    assert parsed.direction == EXPECT_DIRECTION[kind]
    assert parsed.bank == bank
    assert parsed.occurred_at[:10] in {"2026-10-18", "2026-10-17"}
    if kind not in ("atm", "card"):
        assert parsed.utr == "628912345678"
    assert "1234.50" in text.replace(",", "") or "1,234.50" in text


def test_the_synthetic_text_is_what_a_template_reads_not_a_real_message():
    text = render_sms("hdfc", "debit", 25000, "Ramesh K", WHEN, utr="111111111111")
    assert text.startswith(
        "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/10/26 Ref 111111111111"
    )


def test_atm_has_no_counterparty_and_cash_kind_follows():
    parsed, _ = simulate_alert("axis", "atm", 200000, "", WHEN)
    assert parsed.channel == "atm" and parsed.display_name == "ATM cash withdrawal"


def test_an_unknown_bank_or_kind_is_a_typed_failure():
    with pytest.raises(ToolFailure):
        render_sms("nobank", "debit", 100, "x", WHEN)
    with pytest.raises(ToolFailure):
        render_sms("hdfc", "mystery", 100, "x", WHEN)


def test_the_time_in_the_alert_is_the_time_given():
    parsed, _ = simulate_alert("axis", "debit", 25000, "Ramesh K", WHEN)
    assert parsed.occurred_at == to_utc_iso(WHEN)
