"""Any bank, no per-bank setup: the generic reader, and the rules it must still keep."""

from datetime import UTC, datetime

import pytest

from copilot.capture.sms_parser import Dropped, ParsedPayment, parse_sms
from copilot.config.capture import load_sms_senders, load_sms_templates

NOW = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)
SENDERS = load_sms_senders()
TEMPLATES = load_sms_templates()


def read(sender: str, text: str, any_sender: bool = True):
    return parse_sms(sender, text, NOW, senders=SENDERS, templates=TEMPLATES, any_sender=any_sender)


@pytest.mark.parametrize(
    ("sender", "text", "paise", "direction", "name"),
    [
        (  # a bank that has no template at all
            "VK-PNBSMS-S",
            "Rs 250.00 debited from A/c XX4321 on 17-11-26 to VPA chaistall@okaxis "
            "(UPI Ref no 612345678901).",
            25000,
            "debit",
            "Chaistall",
        ),
        (
            "JD-BOIIND-S",
            "Rs.1,499.00 spent on Card 8890 at AMAZON PAY on 17-Nov-26. Avl bal Rs.20,000.00",
            149900,
            "debit",
            "AMAZON PAY",
        ),
        (
            "AD-FEDBNK",
            "Rs 5000 credited to A/c XX1122 on 17-11-26 from VPA rahul@ybl (UPI Ref 998877665544)",
            500000,
            "credit",
            "Rahul",
        ),
    ],
)
def test_an_unlisted_banks_alert_is_read(sender, text, paise, direction, name):
    out = read(sender, text)
    assert isinstance(out, ParsedPayment)
    assert (out.amount_paise, out.direction, out.display_name) == (paise, direction, name)
    assert out.template == "generic"


def test_the_balance_is_never_mistaken_for_the_amount():
    out = read("VK-PNBSMS-S", "Avl bal Rs 90,000.00. Rs 40.00 debited from A/c 1234 to VPA x@ybl")
    assert isinstance(out, ParsedPayment) and out.amount_paise == 4000


@pytest.mark.parametrize(
    "text",
    [
        "Your OTP is 482913. Rs 500 will be debited. Do not share.",
        "Rs 500 will be debited from your account on 20-11-26 for the mandate",
        "Dear customer, get a loan up to Rs 5,00,000 today. Apply now",
        "Hi, are you free for lunch",
    ],
)
def test_otps_mandates_offers_and_chat_are_not_payments(text):
    out = read("VM-HDFCBK-S", text)
    assert isinstance(out, Dropped)


def test_a_persons_number_is_dropped_without_the_text_being_read():
    class Poison(str):
        def __getattribute__(self, name):
            raise AssertionError("the text was touched")

    for sender in ("+919812345678", "9812345678", "098123-45678"):
        assert read(sender, Poison("Rs 500 debited from A/c 1234")) == Dropped("sender_not_allowed")


def test_switched_off_it_stays_strict():
    text = "Rs 250.00 debited from A/c XX4321 to VPA chaistall@okaxis (UPI Ref no 612345678901)."
    assert read("VK-PNBSMS-S", text, any_sender=False) == Dropped("sender_not_allowed")


def test_the_result_never_carries_the_message_text():
    text = "Rs 250.00 debited from A/c XX4321 to VPA chaistall@okaxis (UPI Ref no 612345678901)."
    out = read("VK-PNBSMS-S", text)
    assert text not in repr(out)


def test_the_payees_handle_does_not_name_your_bank():
    out = read(
        "VK-PNBSMS-S",
        "Rs 120.00 debited from A/c XX4321 to VPA chaistall@okaxis (UPI Ref no 612345678901).",
    )
    assert isinstance(out, ParsedPayment) and out.bank == "pnbsms"
