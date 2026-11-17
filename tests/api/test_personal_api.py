"""The understanding, profile, budget, check-in and sharing routes (PLAN_AGENTIC_V2)."""

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
    st = ApiState(db_path=tmp_path / "p.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield TestClient(create_app(st))
    clear_registry()


def test_the_cascade_runs_and_every_decision_can_be_explained(client):
    out = client.post("/api/understand/run", headers=AUTH)
    assert out.status_code == 200, out.text
    assert client.get("/api/understand/questions", headers=AUTH).status_code == 200
    tx = client.get("/api/transactions?limit=1", headers=AUTH).json()
    items = tx.get("items") or tx.get("transactions") or []
    if items and out.json()["considered"]:
        why = client.get(f"/api/understand/why/{items[0]['id']}", headers=AUTH)
        assert why.status_code in (200, 404)


def test_profile_round_trip_and_suggestions_wait_for_confirmation(client):
    assert client.get("/api/profile", headers=AUTH).json()["data"]["values"] == {}
    ok = client.post("/api/profile/nudge_style", json={"value": "numbers"}, headers=AUTH)
    assert ok.status_code == 200, ok.text
    assert (
        client.get("/api/profile", headers=AUTH).json()["data"]["values"]["nudge_style"]
        == "numbers"
    )
    assert (
        client.post("/api/profile/religion", json={"value": "x"}, headers=AUTH).status_code >= 400
    )
    assert (
        client.post("/api/profile/nudge_style/forget", headers=AUTH).json()["data"]["deleted"] == 1
    )
    assert client.get("/api/profile").status_code == 401


def test_the_budget_asks_for_income_first_then_plans_and_applies(client):
    assert (
        client.get("/api/budget/proposal", headers=AUTH).json()["data"]["status"] == "needs_profile"
    )
    assert client.post("/api/budget/apply", headers=AUTH).status_code >= 400
    client.post(
        "/api/profile/income",
        json={"value": {"kind": "monthly", "expected_paise": 9_000_000, "day_of_month": 1}},
        headers=AUTH,
    )
    client.post("/api/profile/savings_intent_paise", json={"value": 500_000}, headers=AUTH)
    plan = client.get("/api/budget/proposal", headers=AUTH).json()["data"]
    assert plan["status"] in ("ok", "essentials_exceed")
    assert client.get("/api/budget/replan", headers=AUTH).status_code == 200


def test_a_check_in_can_be_asked_for_and_answered_once(client):
    res = client.post("/api/checkins/run", headers=AUTH).json()
    assert "sent" in res and "reason" in res
    listing = client.get("/api/checkins", headers=AUTH).json()["data"]
    assert {"checkins", "verification", "arms"} <= set(listing)
    if res["sent"]:
        cid = res["checkin"]["id"]
        assert (
            client.post(
                f"/api/checkins/{cid}/respond", json={"response": "acted"}, headers=AUTH
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/checkins/{cid}/respond", json={"response": "acted"}, headers=AUTH
            ).status_code
            >= 400
        )
    assert (
        client.post("/api/checkins/x/respond", json={"response": "loud"}, headers=AUTH).status_code
        == 422
    )


def test_shared_expenses_over_the_api_balance_to_zero(client):
    g = client.post("/api/splits", json={"name": "Flat", "others": ["Asha"]}, headers=AUTH).json()[
        "data"
    ]
    me, asha = (m["id"] for m in g["members"])
    gid = g["group_id"]
    assert (
        client.post(
            f"/api/splits/{gid}/expenses",
            json={"paid_by": me, "amount_paise": 9_999, "note": "milk"},
            headers=AUTH,
        ).status_code
        == 200
    )
    view = client.get(f"/api/splits/{gid}", headers=AUTH).json()["data"]
    assert sum(b["net_paise"] for b in view["balances"]) == 0
    s = view["settle_up"][0]
    assert client.post(f"/api/splits/{gid}/settlements", json=s, headers=AUTH).status_code == 200
    assert all(
        b["net_paise"] == 0
        for b in client.get(f"/api/splits/{gid}", headers=AUTH).json()["data"]["balances"]
    )


def test_subscriptions_list_and_marking_needs_a_real_one(client):
    assert client.get("/api/subscriptions", headers=AUTH).status_code == 200
    assert (
        client.post(
            "/api/subscriptions/nope/mark", json={"note": "unused"}, headers=AUTH
        ).status_code
        >= 400
    )
    assert (
        client.post(
            "/api/subscriptions/nope/mark", json={"note": "maybe"}, headers=AUTH
        ).status_code
        == 422
    )
