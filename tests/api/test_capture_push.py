"""
Notifications on the user's devices (PLAN_CAPTURE Stage C6b): who is told, what they are told,
and what happens when two devices answer the same payment.
"""

import json

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.config.capture import load_capture_config
from copilot.core import capture as core
from copilot.core import capture_push
from copilot.core.capture_push import PushFailed, PushGone
from copilot.models.capture import PromptView
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}
P256 = "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
AUTHKEY = "tBHItJI5svbpez7KI4CCXg"


class FakeSender:
    """Records every push instead of sending it. Can be told to fail for an endpoint."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []
        self.fail: dict[str, Exception] = {}

    def __call__(self, sub, payload, vapid_pem, claims, ttl):
        if sub["endpoint"] in self.fail:
            raise self.fail[sub["endpoint"]]
        assert "BEGIN" in vapid_pem and claims["sub"].startswith("mailto:") and ttl > 0
        self.sent.append((sub["endpoint"], json.loads(payload)))

    def of(self, kind):
        return [(e, p) for e, p in self.sent if p["type"] == kind]


@pytest.fixture(autouse=True)
def _vapid_in_tmp(tmp_path, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(capture_push, "VAPID_FILE", tmp_path / "vapid.json")


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def state(tmp_path, sender):
    clear_registry()
    st = ApiState(
        db_path=tmp_path / "p.db",
        clock=DEMO_CLOCK,
        token="test-token",
        llm=None,
        push_sender=sender,
    )
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def device(client, n):
    res = client.post(
        "/api/capture/push/subscribe",
        json={
            "endpoint": f"https://push.example/device-{n}",
            "keys": {"p256dh": P256, "auth": AUTHKEY},
            "label": f"Device {n}",
        },
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return f"https://push.example/device-{n}"


def sim(client, name="XQ9 Traders Yard", amount=25000, **kw):
    body = {"bank": "axis", "kind": "debit", "amount_paise": amount, "counterparty": name} | kw
    res = client.post("/api/capture/simulate", json=body, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def action(client, payload, label, rank=1, token=None, prompt=None):
    return client.post(
        "/api/capture/push/action",
        json={
            "prompt_id": prompt or payload["prompt_id"],
            "token": token or payload["token"],
            "label": label,
            "rank": rank,
        },
    )


# ---- subscriptions ----------------------------------------------------------------------------
def test_status_gives_the_public_key_and_lists_devices(client):
    status = client.get("/api/capture/push/status", headers=AUTH).json()
    assert status["enabled"] and status["devices"] == [] and len(status["public_key"]) > 40
    again = client.get("/api/capture/push/status", headers=AUTH).json()
    assert again["public_key"] == status["public_key"], "the key is created once and kept"
    device(client, 1)
    assert [
        d["label"] for d in client.get("/api/capture/push/status", headers=AUTH).json()["devices"]
    ] == ["Device 1"]


def test_subscribing_twice_is_one_device_and_unsubscribing_removes_it(client):
    ep = device(client, 1)
    device(client, 1)
    assert len(client.get("/api/capture/push/status", headers=AUTH).json()["devices"]) == 1
    assert client.post(
        "/api/capture/push/unsubscribe", json={"endpoint": ep}, headers=AUTH
    ).json() == {"removed": True}
    assert client.post(
        "/api/capture/push/unsubscribe", json={"endpoint": ep}, headers=AUTH
    ).json() == {"removed": False}


def test_an_insecure_or_incomplete_subscription_is_refused(client):
    bad = client.post(
        "/api/capture/push/subscribe",
        json={"endpoint": "http://push.example/x1234", "keys": {"p256dh": P256, "auth": AUTHKEY}},
        headers=AUTH,
    )
    assert bad.status_code == 422
    assert (
        client.post(
            "/api/capture/push/subscribe",
            json={"endpoint": "https://push.example/x1234"},
            headers=AUTH,
        ).status_code
        == 422
    )


def test_the_push_routes_that_change_things_need_the_session_token(client):
    assert client.get("/api/capture/push/status").status_code == 401
    assert client.post("/api/capture/push/subscribe", json={}).status_code == 401


# ---- what is sent, and when -------------------------------------------------------------------
def test_an_ask_pushes_to_every_device_with_a_minimal_lock_screen_safe_payload(client, sender):
    device(client, 1), device(client, 2)
    out = sim(client, "Ramesh K", vpa="9876543210@ybl", amount=31234)
    assert out["decision"] == "ask"
    got = sender.of("prompt")
    assert sorted(e for e, _ in got) == [
        "https://push.example/device-1",
        "https://push.example/device-2",
    ]
    cfg = load_capture_config().push
    for _, p in got:
        assert set(p) == {
            "type",
            "prompt_id",
            "event_id",
            "credit",
            "title",
            "body",
            "tag",
            "token",
            "actions",
            "ranks",
        }
        assert p["title"] == "1 payment to tag"
        blob = json.dumps(p)
        assert "Ramesh" not in blob and "312" not in blob and "9876543210" not in blob
        assert len(p["actions"]) == cfg.max_actions
        assert all(a["action"].startswith("label:") for a in p["actions"])
        assert p["tag"] == p["prompt_id"]
    assert got[0][1]["token"] != got[1][1]["token"], "each device has its own token"


def test_when_lock_screen_safety_is_off_the_amount_and_payee_may_show():
    cfg = load_capture_config()
    loose = cfg.model_copy(update={"push": cfg.push.model_copy(update={"lock_screen_safe": False})})
    out = capture_push.build_payload(_prompt(), "tok", loose)
    assert out["title"] == "Paid ₹312.34" and out["body"] == "to Ramesh K"


def _prompt() -> PromptView:
    from copilot.models.capture import GuessView, PaymentEvent

    event = PaymentEvent(
        id="pev_1", user_id="u1", source="sms", simulated=False, amount_paise=31234, direction="debit",
        counterparty_key="k", counterparty_kind="person", display_name="Ramesh K", channel="upi",
        occurred_at="2026-10-18T06:00:00Z", state="posted", created_at="2026-10-18T06:00:00Z",
    )  # fmt: skip
    guesses = [GuessView(label=f"cat{i}", name=f"Category {i}", score_bp=0) for i in range(3)]
    return PromptView(
        prompt_id="prm_1", event=event, decision="ask", reason="person_unclear",
        guesses=guesses, status="pending", created_at="2026-10-18T06:00:00Z",
    )  # fmt: skip


def test_only_payments_that_ask_are_pushed(client, sender):
    device(client, 1)
    first = sim(client, "Sharma Stationers")["event"]
    client.post(
        "/api/capture/labels",
        json={"event_id": first["id"], "category_id": "shopping"},
        headers=AUTH,
    )
    sender.sent.clear()
    assert sim(client, "Sharma Stationers")["decision"] == "auto_label"
    assert sim(client, "Tiny Kiosk Traders", amount=2000)["decision"] == "guess_only"
    assert sender.of("prompt") == []


def test_no_devices_means_no_sends(client, sender):
    sim(client)
    assert sender.sent == []


def test_a_prompt_is_never_sent_twice_to_the_same_device(client, state, sender):
    device(client, 1)
    sim(client)
    conn = state.connect()
    try:
        view = core.pending_prompts(conn, state.user_id)[0]
        assert capture_push.notify_prompt(conn, state.user_id, view, sender, clock=DEMO_CLOCK) == 0
    finally:
        conn.close()
    assert len(sender.of("prompt")) == 1


def test_push_can_be_switched_off_in_config(state, sender):
    cfg = load_capture_config()
    off = cfg.model_copy(update={"push": cfg.push.model_copy(update={"enabled": False})})
    conn = state.connect()
    try:
        capture_push.subscribe(
            conn, state.user_id, "https://push.example/d", P256, AUTHKEY, clock=DEMO_CLOCK
        )
        rec = core.record_payment_event(
            conn, state.user_id, source="simulator", amount_paise=25000, direction="debit",
            display_name="XQ9 Traders Yard", occurred_at="2024-03-18T06:30:00Z", simulated=True, clock=DEMO_CLOCK,
        )  # fmt: skip
        view = core.pending_prompts(conn, state.user_id)[0]
        assert rec.decision.action == "ask"
        assert capture_push.notify_prompt(conn, state.user_id, view, sender, cfg=off) == 0
    finally:
        conn.close()


# ---- pressing a button ------------------------------------------------------------------------
def test_a_notification_button_tags_the_payment_with_its_token(client, sender):
    device(client, 1)
    sim(client)
    _, p = sender.of("prompt")[0]
    res = action(client, p, p["actions"][0]["action"].split(":", 1)[1])
    assert res.status_code == 200 and res.json() == {"outcome": "tagged"}
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 0


def test_a_token_works_once_for_its_own_prompt_only(client, sender):
    device(client, 1)
    sim(client, "XQ9 Traders Yard")
    sim(client, "Another Unknown Traders", amount=44400)
    (_, one), (_, two) = sender.of("prompt")
    label = one["actions"][0]["action"].split(":", 1)[1]
    assert action(client, one, label).json()["outcome"] == "tagged"
    assert action(client, one, label).status_code == 401, "a token is single-use"
    assert action(client, two, label).status_code == 200, "its own token works for its own prompt"
    crossed = action(client, two, label, token=one["token"])
    assert crossed.status_code == 401, "a token never opens another prompt"
    assert action(client, two, label, token="x" * 20).status_code == 401


def test_two_devices_answering_the_same_payment_tag_it_once_and_the_other_closes(client, sender):
    a, b = device(client, 1), device(client, 2)
    sim(client)
    prompts = dict(sender.of("prompt"))
    pa, pb = prompts[a], prompts[b]
    label_a = pa["actions"][0]["action"].split(":", 1)[1]
    label_b = pb["actions"][1]["action"].split(":", 1)[1]
    assert label_a != label_b
    assert action(client, pa, label_a).json() == {"outcome": "tagged"}
    assert action(client, pb, label_b).json() == {"outcome": "already_tagged"}
    event_id = pa["event_id"]
    final = client.get("/api/capture/inbox", headers=AUTH).json()
    assert final["pending_count"] == 0
    conn = client.app.state.api.connect()
    try:
        row = conn.execute(
            "SELECT category_id FROM payment_events WHERE id = ?", (event_id,)
        ).fetchone()
        n = conn.execute(
            "SELECT COUNT(*) FROM capture_labels WHERE event_id = ? AND source = 'user'",
            (event_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row[0] == label_a and n == 1, "the first answer wins and the second changes nothing"
    closes = sender.of("close")
    assert [e for e, _ in closes] == [b], "only the other device is told to close"
    assert closes[0][1]["tag"] == pa["tag"]


def test_answering_in_the_app_closes_the_notifications_too(client, sender):
    a, b = device(client, 1), device(client, 2)
    out = sim(client)
    res = client.post(
        "/api/capture/labels",
        json={"event_id": out["event"]["id"], "category_id": "food"},
        headers=AUTH,
    )
    assert res.status_code == 200
    assert sorted(e for e, _ in sender.of("close")) == sorted([a, b])


# ---- trouble ----------------------------------------------------------------------------------
def test_a_device_that_is_gone_is_removed_and_the_others_still_get_the_push(client, sender):
    a, b = device(client, 1), device(client, 2)
    sender.fail[a] = PushGone("410")
    sim(client)
    assert [e for e, _ in sender.of("prompt")] == [b]
    devices = client.get("/api/capture/push/status", headers=AUTH).json()["devices"]
    assert [d["label"] for d in devices] == ["Device 2"]


def test_repeated_failures_remove_a_device_but_one_failure_does_not(client, sender):
    a, b = device(client, 1), device(client, 2)
    sender.fail[a] = PushFailed("timeout")
    max_failures = load_capture_config().push.max_failures
    for i in range(max_failures):
        sim(client, f"Flaky Test Traders {i}", amount=25000 + i)
        remaining = [
            d["label"]
            for d in client.get("/api/capture/push/status", headers=AUTH).json()["devices"]
        ]
        assert ("Device 1" in remaining) is (i + 1 < max_failures)
    assert all(e == b for e, p in sender.of("prompt"))


def test_push_never_carries_message_text_or_a_phone_number(client, sender):
    device(client, 1)
    sim(client, "Ramesh K", vpa="9876543210@ybl")
    blob = json.dumps(sender.sent)
    assert "Sent Rs" not in blob and "SMS" not in blob and "9876543210" not in blob
