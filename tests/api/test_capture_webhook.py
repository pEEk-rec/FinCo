"""
The SMS bridge (PLAN_CAPTURE Stage C5): who may call it, what it refuses, and the promise that
no message text is kept anywhere.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.config.capture import SmsSendersConfig, load_capture_config, load_sms_senders
from copilot.tools.registry import clear_registry

SECRET = "test-bridge-secret"
HDR = {"X-Capture-Secret": SECRET}
AUTH = {"Authorization": "Bearer test-token"}
GOOD = "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/03/24 Ref 628912345678 Not You? Call 18002586161"


def _senders(enabled: bool = True) -> SmsSendersConfig:
    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = enabled
    return SmsSendersConfig.model_validate(raw)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("copilot.core.capture_secret.SECRET_FILE", tmp_path / "no_secret")
    clear_registry()
    st = ApiState(
        db_path=tmp_path / "w.db", clock=DEMO_CLOCK, token="test-token", llm=None,
        capture_secret=SECRET, capture_senders=_senders(),
    )  # fmt: skip
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def post(client, sender="HDFCBK", text=GOOD, headers=HDR, **kw):
    return client.post(
        "/api/capture/sms", json={"sender": sender, "text": text}, headers=headers, **kw
    )


def test_it_refuses_everything_until_a_secret_exists(state, tmp_path):
    state.capture_secret = None
    res = post(TestClient(create_app(state)))
    assert res.status_code == 503 and res.json()["code"] == "SETUP_REQUIRED"


def test_a_missing_or_wrong_secret_is_refused_and_audited_without_content(client, state):
    marker = "ZZMARKERZZ"
    assert post(client, headers={}, text=GOOD + marker).status_code == 401
    assert post(client, headers={"X-Capture-Secret": "nope"}, text=GOOD + marker).status_code == 401
    conn = state.connect()
    try:
        rows = conn.execute(
            "SELECT reason, metadata_json FROM audit_events WHERE event_type = 'capture_webhook_rejected'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert all(marker not in (r[0] + r[1]) for r in rows)
    assert all("bad_secret" in r[1] for r in rows)


def test_the_audit_of_refusals_is_capped_so_it_cannot_flood_the_log(client, state):
    for _ in range(30):
        post(client, headers={})
    conn = state.connect()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'capture_webhook_rejected'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 20


def test_rate_limit_applies_after_authentication(client):
    limit = load_capture_config().webhook.rate_limit_per_minute
    codes = [post(client, text=GOOD + f" {i}").status_code for i in range(limit + 1)]
    assert codes[:limit] == [200] * limit and codes[limit] == 429
    assert post(client, headers={}).status_code == 401, (
        "a stranger still gets a refusal, not a lockout"
    )


def test_an_oversized_body_is_refused(client):
    cap = load_capture_config().webhook.max_body_bytes
    res = post(client, text="Sent Rs.1 " + "x" * (cap + 10))
    assert res.status_code == 413


def test_a_bank_alert_is_recorded_and_waits_in_the_inbox(client):
    res = post(client)
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "recorded" and body["decision"] == "ask" and body["event_id"]
    inbox = client.get("/api/capture/inbox", headers=AUTH).json()
    assert inbox["pending_count"] == 1
    event = inbox["prompts"][0]["event"]
    assert event["source"] == "sms" and event["simulated"] is False
    assert event["amount_paise"] == 25000 and event["utr"] == "628912345678"


def test_a_forwarded_alert_twice_makes_one_payment(client):
    first, second = post(client).json(), post(client).json()
    assert (first["outcome"], second["outcome"]) == ("recorded", "duplicate")
    assert first["event_id"] == second["event_id"]
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 1


def test_a_sender_that_is_not_on_the_list_is_dropped_before_parsing(client, state):
    res = post(client, sender="+919812345678")
    assert res.json() == {
        "outcome": "dropped",
        "reason": "sender_not_allowed",
        "event_id": None,
        "decision": None,
    }
    conn = state.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sms_parse_log").fetchone()[0] == 0, (
            "strangers are not logged"
        )
    finally:
        conn.close()


def test_a_disabled_bank_is_dropped_too(state):
    state.capture_senders = _senders(enabled=False)
    res = post(TestClient(create_app(state)))
    assert res.json()["outcome"] == "dropped"


def test_an_otp_is_dropped_even_from_a_listed_bank(client):
    res = post(client, text="123456 is your OTP for HDFC Bank transaction. Do not share it.")
    assert res.json()["outcome"] == "dropped" and res.json()["reason"] == "otp"
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 0


def test_an_unknown_format_is_counted_not_guessed(client):
    res = post(client, text="Your HDFC wallet was topped up. Thanks!")
    assert res.json()["outcome"] == "unparsed"
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 0


def test_a_reversal_cancels_the_earlier_payment(client):
    post(client)
    rev = (
        "Rs 250.00 credited to a/c **1234 on 18-03-24 towards reversal of UPI txn Ref 628912345678"
    )
    res = post(client, text=rev)
    assert res.json()["outcome"] == "recorded"
    inbox = client.get("/api/capture/inbox", headers=AUTH).json()
    assert inbox["pending_count"] == 0, "the question about the reversed payment is gone"


def test_json_aliases_and_form_posts_work_for_different_forwarder_apps(client):
    a = client.post("/api/capture/sms", json={"from": "HDFCBK", "message": GOOD}, headers=HDR)
    assert a.json()["outcome"] == "recorded"
    other = GOOD.replace("628912345678", "628900000002")
    b = client.post("/api/capture/sms", data={"address": "HDFCBK", "body": other}, headers=HDR)
    assert b.json()["outcome"] == "recorded"
    c = client.post("/api/capture/sms", json={"text": GOOD}, headers=HDR)
    assert c.status_code == 422, "a message with no sender cannot be checked, so it is refused"


def test_the_message_text_is_in_no_table_no_log_and_no_span(client, state, caplog):
    marker = "TAILMARKER99"
    text = GOOD + " " + marker
    caplog.set_level(logging.DEBUG)
    assert post(client, text=text).json()["outcome"] == "recorded"
    post(client, text="OTP 5521 " + marker)
    post(client, text="unknown wording " + marker)
    post(client, sender="STRANGER", text=marker)
    conn = state.connect()
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}"):
                assert marker not in str(tuple(row)), f"the message text reached table {table}"
    finally:
        conn.close()
    assert marker not in caplog.text, "the message text reached a log"
    assert "ZZ" not in caplog.text


def test_the_response_never_echoes_the_message(client):
    for text in (GOOD, "OTP 5521", "unknown wording"):
        assert (
            "Rs.250" not in post(client, text=text).text
            and "OTP" not in post(client, text=text).text
        )


def test_bridge_health_shows_each_bank_its_last_alert_and_drift(client):
    for i in range(10):
        post(client, text=GOOD.replace("628912345678", f"62890000{i:04d}"))
    for _ in range(3):
        post(client, text="a wording the templates do not know")
    health = client.get("/api/capture/bridge", headers=AUTH).json()
    assert health["secret_configured"] is True and health["any_enabled"] is True
    hdfc = next(b for b in health["banks"] if b["bank"] == "hdfc")
    assert hdfc["parsed"] == 10 and hdfc["unparsed"] == 3 and hdfc["last_received_at"]
    assert hdfc["drifting"] is True
    sbi = next(b for b in health["banks"] if b["bank"] == "sbi")
    assert sbi["last_received_at"] is None and sbi["drifting"] is False


def test_bridge_health_needs_the_session_token(client):
    assert client.get("/api/capture/bridge").status_code == 401
