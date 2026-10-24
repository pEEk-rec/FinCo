"""The capture endpoints: simulate a payment, see it in the inbox, tag it, undo it."""

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "cap.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield TestClient(create_app(st))
    clear_registry()


def simulate(client, **over):
    body = {
        "bank": "hdfc",
        "kind": "debit",
        "amount_paise": 25000,
        "counterparty": "XQ9 Traders Yard",
    }
    res = client.post("/api/capture/simulate", json=body | over, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_inbox_offers_the_simulator_options_and_starts_empty(client):
    inbox = client.get("/api/capture/inbox", headers=AUTH).json()
    assert inbox["prompts"] == [] and inbox["pending_count"] == 0
    assert {b["code"] for b in inbox["banks"]} == {"hdfc", "sbi", "icici", "axis", "kotak"}
    assert "salary" in inbox["credit_kinds"] and "debit" in inbox["kinds"]


def test_a_simulated_payment_appears_in_the_inbox_marked_simulated(client):
    out = simulate(client)
    assert out["event"]["simulated"] is True and out["decision"] == "ask"
    inbox = client.get("/api/capture/inbox", headers=AUTH).json()
    assert inbox["pending_count"] == 1
    prompt = inbox["prompts"][0]
    assert prompt["event"]["simulated"] is True
    assert len(prompt["guesses"]) == 3 and all(g["name"] for g in prompt["guesses"])


def test_tagging_a_payment_removes_it_from_the_inbox_and_can_be_undone(client):
    ev = simulate(client)["event"]
    cat = client.get("/api/categories", headers=AUTH).json()[0]["id"]
    res = client.post(
        "/api/capture/labels",
        json={"event_id": ev["id"], "category_id": cat, "rank_picked": 1},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["event"]["category_id"] == cat and body["event"]["category_source"] == "user"
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 0
    undo = client.post("/api/undo", json={"audit_event_id": body["audit_event_id"]}, headers=AUTH)
    assert undo.status_code == 200, undo.text
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 1


def test_bad_input_is_a_typed_error(client):
    bad_bank = client.post(
        "/api/capture/simulate", json={"bank": "nope", "amount_paise": 5}, headers=AUTH
    )
    assert bad_bank.status_code == 422
    missing = client.post(
        "/api/capture/labels", json={"event_id": "pev_x", "category_id": "food"}, headers=AUTH
    )
    assert missing.status_code == 404
    ev = simulate(client)["event"]
    wrong = client.post(
        "/api/capture/labels",
        json={"event_id": ev["id"], "category_id": "no_such"},
        headers=AUTH,
    )
    assert wrong.status_code == 422


def test_a_person_can_be_set_to_always_ask(client):
    out = simulate(client, counterparty="Ramesh K", vpa="9876543210@ybl")
    key = out["event"]["counterparty_key"]
    res = client.post(
        "/api/capture/counterparty-policy",
        json={"counterparty_key": key, "policy": "always_ask"},
        headers=AUTH,
    )
    assert res.status_code == 200 and res.json()["profile"]["policy"] == "always_ask"


def test_capture_routes_need_the_token(client):
    assert client.get("/api/capture/inbox").status_code == 401
    assert client.post("/api/capture/simulate", json={}).status_code == 401
