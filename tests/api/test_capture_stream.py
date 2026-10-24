"""
The live prompt stream (PLAN_CAPTURE Stage C6): only payments the ask policy says to ask about
produce a prompt; a reconnect re-announces what is still waiting; answered ones are resolved.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.capture_stream import capture_events
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "s.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def sim(client, name, amount=25000, kind="debit", bank="axis", vpa=None):
    body = {"bank": bank, "kind": kind, "amount_paise": amount, "counterparty": name}
    if vpa:
        body["vpa"] = vpa
    res = client.post("/api/capture/simulate", json=body, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def tag(client, event_id, category):
    res = client.post(
        "/api/capture/labels", json={"event_id": event_id, "category_id": category}, headers=AUTH
    )
    assert res.status_code == 200, res.text


def frames(client):
    """Every event of a one-shot stream, as (name, data) pairs."""
    res = client.get("/api/capture/stream?once=true", headers=AUTH)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    out, name = [], None
    for line in res.text.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            out.append((name, json.loads(line[6:])))
            name = None
    return out


def test_only_ambiguous_payments_produce_a_prompt(client):
    # a known merchant (after one answer), an AutoPay, an own transfer, a tiny payment
    first = sim(client, "Sharma Stationers")["event"]
    tag(client, first["id"], "shopping")
    known = sim(client, "Sharma Stationers")
    autopay = sim(client, "Netflix", amount=19900, kind="autopay")
    own = sim(client, "Self transfer to savings", amount=500000, kind="debit")
    tiny = sim(client, "Corner Kiosk Traders", amount=2000)
    # a payee nobody knows, and a person
    unknown = sim(client, "XQ9 Traders Yard")
    person = sim(client, "Ramesh K", vpa="9876543210@ybl")

    assert known["decision"] == "auto_label" and autopay["decision"] == "auto_label"
    assert own["decision"] == "no_ask" and tiny["decision"] == "guess_only"
    assert unknown["decision"] == "ask" and person["decision"] == "ask"

    got = frames(client)
    prompts = [d for n, d in got if n == "prompt"]
    assert sorted(p["event"]["id"] for p in prompts) == sorted(
        [unknown["event"]["id"], person["event"]["id"]]
    )
    assert all(p["decision"] == "ask" and len(p["guesses"]) == 3 for p in prompts)


def test_quiet_chips_announce_what_was_tagged_without_asking(client):
    first = sim(client, "Sharma Stationers")["event"]
    tag(client, first["id"], "shopping")
    sim(client, "Sharma Stationers")
    chips = [d for n, d in frames(client) if n == "auto_tagged"]
    assert len(chips) == 1
    assert chips[0]["name"] and chips[0]["reason"] == "known_merchant"
    assert chips[0]["event"]["category_source"] == "auto"


def test_a_payment_held_for_quiet_hours_or_the_budget_does_not_interrupt(client, state):
    from copilot.config.capture import load_capture_config

    cap = load_capture_config().prompts.max_per_day
    ids = [
        sim(client, f"Unknown Mart {i}", amount=25000 + i)["event"]["id"] for i in range(cap + 2)
    ]
    shown = [d for n, d in frames(client) if n == "prompt"]
    assert len(shown) == cap, "the rest wait quietly in the inbox"
    assert len(ids) == cap + 2
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == cap + 2


def test_a_reconnect_re_announces_what_is_still_waiting_and_not_what_was_answered(client):
    a = sim(client, "XQ9 Traders Yard")["event"]
    b = sim(client, "Ramesh K", vpa="9876543210@ybl")["event"]
    assert {d["event"]["id"] for n, d in frames(client) if n == "prompt"} == {a["id"], b["id"]}
    tag(client, a["id"], "food")
    again = {d["event"]["id"] for n, d in frames(client) if n == "prompt"}
    assert again == {b["id"]}


def test_the_stream_needs_the_session_token(client):
    assert client.get("/api/capture/stream?once=true").status_code == 401


def test_the_live_stream_announces_then_resolves_as_things_happen(state):
    async def run():
        app = create_app(state)
        client = TestClient(app)
        seen: list[tuple[str, dict]] = []
        gen = capture_events(state, None, interval=0.05)

        async def read(until: str, timeout: float = 5.0):
            async def loop():
                async for frame in gen:
                    if frame.startswith("event: "):
                        name = frame.split("\n", 1)[0][7:]
                        data = json.loads(frame.split("data: ", 1)[1].split("\n", 1)[0])
                        seen.append((name, data))
                        if name == until:
                            return

            await asyncio.wait_for(loop(), timeout)

        sim(client, "XQ9 Traders Yard")
        await read("prompt")
        event_id = seen[-1][1]["event"]["id"]
        tag(client, event_id, "food")
        await read("resolved")
        await gen.aclose()
        return seen

    seen = asyncio.run(run())
    assert [n for n, _ in seen] == ["prompt", "resolved"]
    assert seen[1][1]["event_id"] == seen[0][1]["event"]["id"]
