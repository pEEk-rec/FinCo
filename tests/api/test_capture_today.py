"""
The Today review (PLAN_CAPTURE Stage C6c): money in and out, grouped by what is left for you to
do, listed once each, with totals the backend worked out.
"""

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.core.capture_reconcile import reconcile_events
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}
DAY = "2024-03-18"  # the demo's today


class Sender:
    def __init__(self):
        self.sent = []

    def __call__(self, sub, payload, pem, claims, ttl):
        import json

        self.sent.append(json.loads(payload))


@pytest.fixture(autouse=True)
def _vapid(tmp_path, monkeypatch):
    monkeypatch.setattr("copilot.core.capture_push.VAPID_FILE", tmp_path / "v.json")


@pytest.fixture
def sender():
    return Sender()


@pytest.fixture
def state(tmp_path, sender):
    clear_registry()
    st = ApiState(
        db_path=tmp_path / "t.db",
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


def sim(client, name, amount=25000, kind="debit", **kw):
    body = {"bank": "axis", "kind": kind, "amount_paise": amount, "counterparty": name} | kw
    res = client.post("/api/capture/simulate", json=body, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def tag(client, event_id, **kw):
    res = client.post("/api/capture/labels", json={"event_id": event_id, **kw}, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def today(client, day=DAY):
    res = client.get(f"/api/capture/today?day={day}", headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def only(view, kind="event"):
    return [i for i in view["items"] if i["kind"] == kind]


def test_an_empty_day_is_a_valid_empty_view(client):
    view = today(client, "2023-01-01")
    assert view["items"] == [] and view["totals"] == {"in_paise": 0, "out_paise": 0}
    assert view["counts"] == {"needs_you": 0, "auto": 0, "by_you": 0}
    assert view["is_today"] is False


def test_money_in_and_out_are_both_listed_grouped_and_totalled(client):
    paid = sim(client, "XQ9 Traders Yard", amount=25000)["event"]
    person = sim(client, "Ramesh K", amount=40000, vpa="9876543210@ybl")["event"]
    got = sim(client, "Priya S", amount=100000, kind="credit", vpa="priya.s@okaxis")["event"]
    tag(client, paid["id"], category_id="food")
    view = today(client)
    events = {i["id"]: i for i in only(view)}
    assert (
        events[paid["id"]]["group"] == "by_you" and events[paid["id"]]["category_name"] == "Dining"
    )
    assert events[person["id"]]["group"] == "needs_you"
    assert events[got["id"]]["group"] == "needs_you" and events[got["id"]]["direction"] == "credit"
    assert view["totals"] == {"in_paise": 100000, "out_paise": 65000}
    assert view["counts"] == {"needs_you": 2, "auto": 0, "by_you": 1}
    assert view["is_today"] is True


def test_items_come_in_time_order(client):
    sim(client, "First Traders Yard", amount=11100)
    sim(client, "Second Traders Yard", amount=22200)
    times = [i["time"] for i in today(client)["items"]]
    assert times == sorted(times)


def test_auto_tagged_payments_say_why_and_a_users_tag_does_not(client):
    first = sim(client, "Sharma Stationers")["event"]
    tag(client, first["id"], category_id="shopping")
    auto = sim(client, "Sharma Stationers")["event"]
    view = {i["id"]: i for i in only(today(client))}
    assert (
        view[auto["id"]]["group"] == "auto"
        and view[auto["id"]]["reason"] == "A shop you have tagged before"
    )
    assert view[first["id"]]["group"] == "by_you" and view[first["id"]]["reason"] is None


def test_an_unanswered_prompt_stays_under_needs_you_until_it_is_tagged(client):
    out = sim(client, "XQ9 Traders Yard")["event"]
    assert [i["id"] for i in today(client)["items"] if i["group"] == "needs_you"] == [out["id"]]
    tag(client, out["id"], category_id="food")
    view = today(client)
    assert view["counts"]["needs_you"] == 0 and view["counts"]["by_you"] == 1
    assert view["totals"]["out_paise"] == 25000, "tagging does not change what was spent"


def test_tagging_from_today_closes_notifications_and_updates_the_inbox(client, sender):
    client.post(
        "/api/capture/push/subscribe",
        json={
            "endpoint": "https://push.example/abc-123",
            "keys": {"p256dh": "B" * 40, "auth": "A" * 16},
        },
        headers=AUTH,
    )
    out = sim(client, "XQ9 Traders Yard")["event"]
    assert any(p["type"] == "prompt" for p in sender.sent)
    tag(client, out["id"], category_id="food")
    assert any(p["type"] == "close" for p in sender.sent)
    assert client.get("/api/capture/inbox", headers=AUTH).json()["pending_count"] == 0


def test_own_transfers_and_both_sides_of_a_reversal_are_not_in_the_totals(client, state):
    from copilot.core import capture as cap

    sim(client, "Self transfer to savings", amount=500000)
    kept = sim(client, "Kept Traders Yard", amount=11100)["event"]
    conn = state.connect()
    try:
        paid = cap.record_payment_event(
            conn, state.user_id, source="sms", amount_paise=25000, direction="debit",
            display_name="Cancelled Traders Yard", occurred_at=kept["occurred_at"], utr="628900000001",
            clock=DEMO_CLOCK,
        )  # fmt: skip
        cap.record_payment_event(
            conn, state.user_id, source="sms", amount_paise=25000, direction="credit",
            display_name="Reversal", occurred_at=kept["occurred_at"], reversal_of_utr="628900000001",
            clock=DEMO_CLOCK,
        )  # fmt: skip
        conn.commit()
    finally:
        conn.close()
    view = today(client)
    assert view["totals"] == {"in_paise": 0, "out_paise": 11100}
    by_id = {i["id"]: i for i in only(view)}
    assert by_id[paid.event.id]["reversed"] is True
    assert [i for i in only(view) if i["name"] == "Reversal"][0]["reversed"] is True
    own = [i for i in only(view) if i["name"].lower().startswith("self transfer")][0]
    assert own["reason"] == "Between your own accounts"


def test_a_reconciled_payment_is_listed_once_not_as_event_and_ledger_row(client, state):
    from copilot.db.repo import insert_transaction
    from copilot.models.domain import Transaction

    out = sim(client, "XQ9 Traders Yard", amount=25000, utr="628900000042")["event"]
    conn = state.connect()
    try:
        insert_transaction(
            conn,
            Transaction(
                id="t_dup", user_id=state.user_id, account_id=_account(conn),
                occurred_at=out["occurred_at"], amount_paise=25000, direction="debit",
                merchant_raw="UPI-XQ9-REF628900000042", description="", created_at=out["occurred_at"],
            ),
        )  # fmt: skip
        reconcile_events(conn, state.user_id, clock=DEMO_CLOCK)
        conn.commit()
    finally:
        conn.close()
    view = today(client)
    assert len(view["items"]) == 1 and view["items"][0]["kind"] == "event"
    assert view["items"][0]["verified"] is True
    assert view["totals"]["out_paise"] == 25000, "counted once"


def _account(conn) -> str:
    return conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]


def test_ledger_rows_with_no_category_wait_under_needs_you_with_a_review_link(client):
    view = today(client, "2024-03-12")  # a day the demo data leaves one payment uncategorised
    waiting = [i for i in view["items"] if i["group"] == "needs_you"]
    assert waiting and all(i["needs_review_link"] and i["kind"] == "ledger" for i in waiting)
    assert all(i["verified"] for i in view["items"])


def test_ledger_rows_are_split_into_auto_and_tagged_by_you(client):
    view = today(client, "2024-03-14")
    groups = {i["group"] for i in view["items"]}
    assert groups <= {"auto", "by_you", "needs_you"} and view["items"]
    user = [i for i in view["items"] if i["group"] == "by_you"]
    assert all(i["reason"] is None for i in user)


def test_the_day_must_be_a_real_date_shape_and_the_token_is_required(client):
    assert client.get("/api/capture/today?day=yesterday", headers=AUTH).status_code == 422
    assert client.get("/api/capture/today").status_code == 401
