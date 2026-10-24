"""The Capture track's configuration loads, and bad edits fail loudly (PLAN_CAPTURE Stage C0)."""

import re

import pytest
import yaml
from pydantic import ValidationError

from copilot.config.capture import (
    CONFIG_DIR,
    AaConfig,
    BankTemplates,
    CaptureConfig,
    ReconcileConfig,
    SmsSendersConfig,
    load_aa_config,
    load_capture_config,
    load_reconcile_config,
    load_sms_senders,
    load_sms_templates,
    validate_capture_setup,
)


def _raw(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def test_every_shipped_file_loads_and_the_setup_is_consistent():
    load_capture_config()
    load_reconcile_config()
    load_aa_config()
    assert set(load_sms_templates()) == set(load_sms_senders().banks)
    assert validate_capture_setup() == []


def test_no_bank_is_allowed_until_it_is_enabled():
    """Shipped senders are unverified guesses, so nothing is read from any of them yet."""
    assert load_sms_senders().allowed_senders() == {}


def test_ranking_weights_must_sum_to_one():
    raw = _raw("capture.yaml")
    raw["ranking"]["weights"]["recency"] += 1
    with pytest.raises(ValidationError, match="sum to 10000"):
        CaptureConfig.model_validate(raw)


def test_person_policy_k_cannot_exceed_n():
    raw = _raw("capture.yaml")
    raw["ask"]["person_policy"] = {"k": 4, "n": 3}
    with pytest.raises(ValidationError, match="cannot exceed"):
        CaptureConfig.model_validate(raw)


@pytest.mark.parametrize("bad", ["25:00", "7:30", "noon"])
def test_quiet_hours_must_be_a_real_clock_time(bad):
    raw = _raw("capture.yaml")
    raw["prompts"]["quiet_hours"]["start"] = bad
    with pytest.raises(ValidationError, match="HH:MM"):
        CaptureConfig.model_validate(raw)


def test_unknown_keys_are_rejected_not_ignored():
    raw = _raw("capture.yaml")
    raw["ask"]["min_ask_amount_rupees"] = 50
    with pytest.raises(ValidationError):
        CaptureConfig.model_validate(raw)


def test_a_sender_cannot_belong_to_two_banks():
    raw = _raw("sms_senders.yaml")
    raw["banks"]["sbi"]["sender_ids"].append("HDFCBK")
    with pytest.raises(ValidationError, match="both"):
        SmsSendersConfig.model_validate(raw)


@pytest.mark.parametrize("sender", ["hdfcbk", "A", "HDFC BK", "HDFC$K"])
def test_sender_ids_must_look_like_dlt_headers(sender):
    raw = _raw("sms_senders.yaml")
    raw["banks"]["hdfc"]["sender_ids"] = [sender]
    with pytest.raises(ValidationError):
        SmsSendersConfig.model_validate(raw)


def test_only_enabled_banks_are_allowed():
    raw = _raw("sms_senders.yaml")
    raw["banks"]["hdfc"]["enabled"] = True
    allowed = SmsSendersConfig.model_validate(raw).allowed_senders()
    assert allowed == {"HDFCBK": "hdfc", "HDFCBN": "hdfc"}


def test_enabling_a_bank_whose_templates_are_a_skeleton_is_reported():
    raw = _raw("sms_senders.yaml")
    raw["banks"]["hdfc"]["enabled"] = True
    templates = dict(load_sms_templates())
    templates["hdfc"] = BankTemplates(bank="hdfc", status="skeleton", templates=[])
    problems = validate_capture_setup(
        senders=SmsSendersConfig.model_validate(raw), templates=templates
    )
    assert any("still a skeleton" in p for p in problems)
    # with the shipped, ready templates the same bank is fine to enable
    assert validate_capture_setup(senders=SmsSendersConfig.model_validate(raw)) == []


def test_templates_for_an_unknown_bank_are_reported():
    templates = dict(load_sms_templates())
    templates["ghost"] = BankTemplates(bank="ghost", status="skeleton", templates=[])
    assert any("no such bank" in p for p in validate_capture_setup(templates=templates))


def test_the_otp_guard_matches_real_otp_wording_and_not_a_payment():
    pattern = load_sms_templates()["hdfc"].templates[0].pattern
    guard = re.compile(pattern)
    assert guard.search("123456 is your OTP for the transaction. Do not share it.")
    assert guard.search("Your one-time password is 4821")
    assert not guard.search("Rs 250.00 debited from a/c XX1234 on 18-10-26 to RAMESH K")
    assert not guard.search("Payment to HOTPOT CAFE of Rs 400")  # whole words only


def test_template_rules():
    base = {"bank": "x", "status": "skeleton"}
    ok = {"name": "d", "kind": "debit", "pattern": r"Rs (?P<amount>[\d,.]+) debited"}
    BankTemplates.model_validate({**base, "templates": [ok]})
    with pytest.raises(ValidationError, match="amount"):
        BankTemplates.model_validate(
            {**base, "templates": [{**ok, "pattern": r"debited (?P<account>\d{4})"}]}
        )
    with pytest.raises(ValidationError, match="compile"):
        BankTemplates.model_validate({**base, "templates": [{**ok, "pattern": "(unclosed"}]})
    with pytest.raises(ValidationError, match="unknown capture groups"):
        BankTemplates.model_validate(
            {**base, "templates": [{**ok, "pattern": r"(?P<amount>\d+) (?P<colour>\w+)"}]}
        )
    with pytest.raises(ValidationError, match="drop: true"):
        BankTemplates.model_validate(
            {**base, "templates": [{"name": "o", "kind": "otp", "pattern": "otp"}]}
        )
    with pytest.raises(ValidationError, match="must not capture"):
        BankTemplates.model_validate(
            {
                **base,
                "templates": [
                    {"name": "o", "kind": "otp", "drop": True, "pattern": r"(?P<amount>\d+)"}
                ],
            }
        )
    with pytest.raises(ValidationError, match="ready bank"):
        BankTemplates.model_validate({"bank": "x", "status": "ready", "templates": []})
    with pytest.raises(ValidationError, match="unique"):
        BankTemplates.model_validate({**base, "templates": [ok, ok]})


def test_reconciliation_always_tries_the_utr_first():
    raw = _raw("reconcile.yaml")
    raw["match_order"] = ["amount_account_time", "utr"]
    with pytest.raises(ValidationError, match="UTR"):
        ReconcileConfig.model_validate(raw)
    raw["match_order"] = ["utr", "utr"]
    with pytest.raises(ValidationError, match="twice"):
        ReconcileConfig.model_validate(raw)


def test_aa_purpose_is_spending_patterns_and_one_time_cannot_stream():
    raw = _raw("aa.yaml")
    assert load_aa_config().purpose_code == "102"
    with pytest.raises(ValidationError):
        AaConfig.model_validate({**raw, "purpose_code": "101"})
    with pytest.raises(ValidationError, match="cannot stream"):
        AaConfig.model_validate({**raw, "fetch_type": "ONETIME", "consent_mode": "STREAM"})
