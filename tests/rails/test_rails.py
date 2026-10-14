"""The rails demo: alerts, receipts, reconciliation, pacing, audit, and isolation."""

import pytest
from fastapi.testclient import TestClient

from copilot.api.services import DEMO_CLOCK
from copilot.rails import demo
from copilot.rails.api import create_rails_app
from copilot.rails.receipts import NotAReceipt, parse_receipt, split_by_category
from copilot.rails.server import build_state
from copilot.rails.sms import NotAPayment, parse_sms
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer rails-token"}
ZERO = "₹0"


@pytest.fixture
def client(tmp_path):
    clear_registry()
    state = build_state(tmp_path / "rails.db", "rails-token")
    yield TestClient(create_rails_app(state))
    clear_registry()


def _pace(client):
    return {r["category_id"]: r for r in client.get("/rails/pacing", headers=AUTH).json()["rows"]}


def _send_all(client):
    texts = [a["text"] for a in demo.ALERTS]
    client.post("/rails/sms/batch", headers=AUTH, json={"messages": texts})


# ----------------------------------------------------------------------------- parsers


@pytest.mark.parametrize("item", demo.ALERTS)
def test_every_demo_alert_reads_as_a_payment(item):
    p = parse_sms(item["text"], DEMO_CLOCK)
    assert p.amount_paise > 0 and p.direction == "debit" and p.merchant != "UNKNOWN"


@pytest.mark.parametrize("item", demo.NOISE)
def test_otps_and_mandates_are_refused(item):
    with pytest.raises(NotAPayment):
        parse_sms(item["text"], DEMO_CLOCK)


def test_the_balance_in_an_alert_is_not_the_amount():
    assert parse_sms(demo.ALERTS[0]["text"], DEMO_CLOCK).amount_paise == 48000


def test_a_credit_alert_is_a_credit():
    text = (
        "Rs 2000.00 credited to a/c **1234 on 18-03-24 by VPA suresh@okaxis "
        "(UPI Ref No 428900000001)"
    )
    assert parse_sms(text, DEMO_CLOCK).direction == "credit"


def test_receipt_split_adds_up_exactly_with_fees_and_discount():
    parts = dict(split_by_category(parse_receipt(demo.RECEIPT), 85000, "shopping"))
    assert parts == {"education": 60000, "food": 25000}


def test_split_remainder_is_distributed_in_whole_paise():
    text = "Shop\nBook ₹100.00\nSnack ₹100.00\nDelivery ₹0.01\nTotal ₹200.01"
    parts = split_by_category(parse_receipt(text), 20001, "shopping")
    assert sum(p for _, p in parts) == 20001


def test_a_receipt_that_does_not_add_up_is_refused():
    with pytest.raises(ValueError):
        split_by_category(parse_receipt("Shop\nBook ₹100.00\nTotal ₹150.00"), 15000, "x")
    with pytest.raises(NotAReceipt):
        parse_receipt("thanks for shopping")


# ----------------------------------------------------------------------------- the demo day


def test_alert_makes_the_budget_react_before_the_statement(client):
    before = _pace(client)["food"]
    out = client.post("/rails/sms", headers=AUTH, json={"text": demo.ALERTS[1]["text"]}).json()
    assert out["outcome"] == "provisional" and out["event"]["category_id"] == "food"
    after = _pace(client)["food"]
    assert after["provisional"] != ZERO
    assert after["projected_percent"] > before["projected_percent"]


def test_the_same_alert_twice_is_counted_once(client):
    body = {"text": demo.ALERTS[0]["text"]}
    first = client.post("/rails/sms", headers=AUTH, json=body).json()
    again = client.post("/rails/sms", headers=AUTH, json=body).json()
    assert first["outcome"] == "provisional" and again["outcome"] == "duplicate"
    assert len(client.get("/rails/events", headers=AUTH).json()) == 1


def test_sync_verifies_alerts_and_never_double_counts(client):
    _send_all(client)
    during = {k: v["total"] for k, v in _pace(client).items()}
    sync = client.post("/rails/sync", headers=AUTH).json()
    assert sync["posted"] == 6 and sync["verified"] == 5 and sync["still_provisional"] == 1
    after = _pace(client)
    assert {k: v["total"] for k, v in after.items()} == during  # same spend, now verified
    again = client.post("/rails/sync", headers=AUTH).json()
    assert again["posted"] == 0 and again["skipped_existing"] == 6 and again["verified"] == 0


def test_party_order_trips_the_food_projection(client):
    _send_all(client)
    assert _pace(client)["food"]["status"] in ("projected_over", "over")


def test_receipt_split_is_a_draft_until_the_user_approves(client):
    client.post("/rails/sms", headers=AUTH, json={"text": demo.ALERTS[3]["text"]})
    shopping_before = _pace(client)["shopping"]["total"]
    r = client.post("/rails/receipt", headers=AUTH, json={"text": demo.RECEIPT}).json()
    assert r["outcome"] == "suggested"
    assert sum(p["amount_paise"] for p in r["parts"]) == 85000
    assert _pace(client)["shopping"]["total"] == shopping_before  # nothing moved yet
    url = f"/rails/splits/{r['receipt_id']}/decision"
    assert client.post(url, headers=AUTH, json={"decision": "approved"}).status_code == 200
    assert _pace(client)["shopping"]["total"] != shopping_before
    assert client.post(url, headers=AUTH, json={"decision": "rejected"}).status_code == 404


def test_approved_split_survives_reconciliation(client):
    client.post("/rails/sms", headers=AUTH, json={"text": demo.ALERTS[3]["text"]})
    r = client.post("/rails/receipt", headers=AUTH, json={"text": demo.RECEIPT}).json()
    url = f"/rails/splits/{r['receipt_id']}/decision"
    client.post(url, headers=AUTH, json={"decision": "approved"})
    during = _pace(client)
    client.post("/rails/sync", headers=AUTH)
    after = _pace(client)
    # other statement rows land in food and groceries; the split payment must not move
    assert after["shopping"]["total"] == during["shopping"]["total"]
    splits = client.get("/rails/splits", headers=AUTH).json()
    assert all(x["status"] == "approved" for x in splits)


def test_receipt_with_no_matching_payment_is_not_guessed(client):
    r = client.post("/rails/receipt", headers=AUTH, json={"text": demo.RECEIPT}).json()
    assert r["outcome"] == "unmatched"


def test_p2p_alert_asks_for_a_category_instead_of_guessing(client):
    out = client.post("/rails/sms", headers=AUTH, json={"text": demo.ALERTS[5]["text"]}).json()
    assert out["event"]["needs_review"] is True and out["event"]["category_id"] is None


def test_every_state_change_is_audited_and_reset_restores_the_day(client):
    client.post("/rails/sms", headers=AUTH, json={"text": demo.ALERTS[0]["text"]})
    client.post("/rails/sync", headers=AUTH)
    kinds = {a["event_type"] for a in client.get("/rails/audit", headers=AUTH).json()}
    assert {"rail_sms_ingested", "rail_event_verified"} <= kinds
    client.post("/rails/demo/reset", headers=AUTH)
    assert client.get("/rails/events", headers=AUTH).json() == []


def test_garbage_input_is_refused_not_stored(client):
    body = {"text": "hello there, lunch tomorrow?"}
    out = client.post("/rails/sms", headers=AUTH, json=body).json()
    assert out["outcome"] == "refused"
    assert client.get("/rails/events", headers=AUTH).json() == []


def test_auth_is_required_and_the_page_loads(client):
    assert client.get("/rails/pacing").status_code == 401
    assert client.get("/rails/health").json()["status"] == "ok"
    assert "FinCo Rails" in client.get("/").text


def test_the_main_app_is_not_touched(tmp_path):
    from copilot.api.app import create_app
    from copilot.api.state import ApiState

    app = create_app(ApiState(db_path=tmp_path / "main.db"))
    assert not any(getattr(r, "path", "").startswith("/rails") for r in app.routes)
