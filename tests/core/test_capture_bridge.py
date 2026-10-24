"""The bridge instructions and secret handling (PLAN_CAPTURE Stage C5)."""

import os

from typer.testing import CliRunner

from copilot.cli.main import app
from copilot.config.capture import SmsSendersConfig, load_sms_senders
from copilot.core import capture_secret
from copilot.core.capture_bridge import adb_command, bridge_instructions, bridge_url

runner = CliRunner()


def senders(enabled: set[str]) -> SmsSendersConfig:
    raw = load_sms_senders().model_dump()
    for code, bank in raw["banks"].items():
        bank["enabled"] = code in enabled
    return SmsSendersConfig.model_validate(raw)


def text(enabled, **kw):
    return bridge_instructions(
        senders(enabled), port=8765, secret="S3CRET", secret_header="X-Capture-Secret", **kw
    )


def test_the_rule_names_the_url_header_secret_and_only_the_enabled_senders():
    out = text({"hdfc"})
    assert bridge_url(8765) in out and "X-Capture-Secret: S3CRET" in out
    assert "[ON ] HDFC Bank: HDFCBK, HDFCBN" in out
    assert "State Bank of India" not in out, "only the banks you switched on are listed"
    assert adb_command(8765) in out
    assert "Allowed sender IDs right now: HDFCBK, HDFCBN" in out


def test_with_no_bank_enabled_the_text_says_nothing_will_be_read():
    out = text(set())
    assert "No bank is switched on yet" in out and "(none enabled)" in out


def test_the_wifi_route_carries_a_warning_and_the_usb_route_does_not():
    wifi = text({"hdfc"}, lan_host="192.168.1.20")
    assert "http://192.168.1.20:8765/api/capture/sms" in wifi and "WARNING" in wifi
    assert "adb reverse" not in wifi
    assert "WARNING" not in text({"hdfc"})


def test_all_three_phone_apps_are_covered_and_the_text_promises_not_to_keep_messages():
    out = text({"hdfc"})
    for app_name in ("MacroDroid", "Tasker", "iPhone"):
        assert app_name in out
    assert "never keeps: the message text" in out


def test_the_secret_comes_from_the_environment_first_then_a_file(tmp_path, monkeypatch):
    file = tmp_path / "secret"
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    assert capture_secret.load_capture_secret(file) is None
    secret, created = capture_secret.ensure_capture_secret(file)
    assert created and len(secret) >= 24 and file.read_text(encoding="utf-8").strip() == secret
    again, created_again = capture_secret.ensure_capture_secret(file)
    assert again == secret and not created_again
    monkeypatch.setenv("CAPTURE_WEBHOOK_SECRET", "from-env")
    assert capture_secret.load_capture_secret(file) == "from-env"


def test_the_secret_is_never_the_same_twice(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    a, _ = capture_secret.ensure_capture_secret(tmp_path / "a")
    b, _ = capture_secret.ensure_capture_secret(tmp_path / "b")
    assert a != b


def test_the_command_prints_the_instructions_and_creates_the_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(capture_secret, "SECRET_FILE", tmp_path / "data" / "capture_secret")
    res = runner.invoke(app, ["capture", "bridge-setup", "--port", "9000"])
    assert res.exit_code == 0, res.output
    assert "Created a new bridge secret" in res.output
    assert "localhost:9000/api/capture/sms" in res.output
    assert os.path.exists(tmp_path / "data" / "capture_secret")
    again = runner.invoke(app, ["capture", "bridge-setup"])
    assert "Created a new bridge secret" not in again.output
