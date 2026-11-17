"""The demo story: connect a bank on a real clock, see this month filled in, then play live payments."""

from collections import Counter
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import ensure_demo
from copilot.api.state import ApiState
from copilot.bank.demo_story import LIVE_PAYMENTS, build_demo_story
from copilot.common.timeutil import IST
from copilot.rails.engine import categorize
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "d.db", clock=None, token="test-token", llm=None)
    ensure_demo(st, "empty")
    yield TestClient(create_app(st))
    clear_registry()


def test_the_story_is_recent_and_always_the_same_for_a_given_day():
    now = datetime.now(tz=IST)
    a, b = build_demo_story("u1", "a1", now), build_demo_story("u1", "a1", now)
    assert [(t.occurred_at, t.amount_paise, t.merchant_raw) for t in a] == [
        (t.occurred_at, t.amount_paise, t.merchant_raw) for t in b
    ]
    newest = max(t.occurred_at for t in a)
    assert newest >= (now - timedelta(days=2)).astimezone(IST).strftime("%Y-%m-%d")
    assert min(t.occurred_at for t in a) >= (now - timedelta(days=90)).strftime("%Y-%m-%d")


def test_most_of_the_story_is_recognised_and_some_is_left_for_review():
    tx = build_demo_story("u1", "a1", datetime.now(tz=IST))
    known = Counter(categorize(t.merchant_raw, abs(t.amount_paise), t.direction)[0] for t in tx)
    unknown = known.pop(None, 0)
    assert unknown / len(tx) < 0.2 and unknown >= 8  # review has real work, but is not a wall
    assert known["food"] > known["travel"]  # a student's money goes mostly on food


def test_connecting_fills_this_month_and_review_is_small(client):
    cid = client.get("/api/consents", headers=AUTH).json()[0]["id"]
    assert client.get("/api/dashboard", headers=AUTH).json()["has_transactions"] is False
    assert client.post(f"/api/consents/{cid}/approve", headers=AUTH).status_code == 200
    done = client.post(f"/api/consents/{cid}/import", headers=AUTH).json()
    assert done["inserted"] > 150 and done["by_rule"] > done["needs_review"] * 4
    dash = client.get("/api/dashboard", headers=AUTH).json()
    assert dash["has_transactions"] is True and dash["budget_pace"]["spent_paise"] > 0
    assert 0 < dash["review_count"] < 45


def test_the_story_spans_many_everyday_kinds_of_spending(client):
    import sqlite3

    cid = client.get("/api/consents", headers=AUTH).json()[0]["id"]
    client.post(f"/api/consents/{cid}/approve", headers=AUTH)
    client.post(f"/api/consents/{cid}/import", headers=AUTH)
    db = sqlite3.connect(client.app.state.api.db_path)
    spent = dict(
        db.execute(
            "SELECT category_id, COUNT(*) FROM transactions "
            "WHERE direction = 'debit' AND category_id IS NOT NULL GROUP BY category_id"
        ).fetchall()
    )
    everyday = {
        "food", "groceries", "travel", "shopping", "entertainment", "subscriptions",
        "health", "personal", "education", "bills", "housing",
    }  # fmt: skip
    assert everyday <= set(spent), f"missing: {everyday - set(spent)}"


def test_the_consent_window_is_recent_not_years_old(client):
    consent = client.get("/api/consents", headers=AUTH).json()[0]
    assert not consent["range_from"].startswith("2024")


def test_live_payments_play_in_order_and_wrap_round(client, monkeypatch):
    monkeypatch.setenv("FINCO_MIN_ASK_PAISE", "100")
    first = client.post("/api/demo/live-payment", headers=AUTH).json()
    assert first["counterparty"] == LIVE_PAYMENTS[0].counterparty and first["position"] == 1
    for _ in range(len(LIVE_PAYMENTS) - 1):
        last = client.post("/api/demo/live-payment", headers=AUTH).json()
    assert last["position"] == len(LIVE_PAYMENTS)
    again = client.post("/api/demo/live-payment", headers=AUTH).json()
    assert again["counterparty"] == LIVE_PAYMENTS[0].counterparty


def test_a_new_shop_asks_and_a_known_merchant_is_tagged_quietly(client):
    cid = client.get("/api/consents", headers=AUTH).json()[0]["id"]
    client.post(f"/api/consents/{cid}/approve", headers=AUTH)
    client.post(f"/api/consents/{cid}/import", headers=AUTH)
    client.post("/api/demo/live-payment", headers=AUTH)  # Gupta Juice Centre
    pending = client.get("/api/capture/inbox", headers=AUTH).json()["prompts"]
    assert [p["event"]["display_name"] for p in pending] == ["GUPTA JUICE CENTRE"]
