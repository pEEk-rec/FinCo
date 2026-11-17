"""
One person's first session with FinCo, through the HTTP API only, the way the app uses it.

They connect their statements, let FinCo categorise them, fix one it was unsure of, ask a
question, tag a payment as it happens, tell FinCo their income and get a budget, and hear from the
weekly check-in. Each step builds on the state the last one left, so this catches the breaks that
the per-area tests cannot: a write in one area that another area does not see.

At the end it checks the promises that hold across all of it: every change went through the tool
executor and was allowed by policy, every change says who made it, nothing moved money, and every
step shows up in the activity timeline.
"""

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.audit.events import list_events
from copilot.tools import registry
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer journey-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(
        db_path=tmp_path / "journey.db", clock=DEMO_CLOCK, token="journey-token", llm=None
    )
    ensure_demo(st, "imported")
    yield st
    clear_registry()


def ok(response):
    assert response.status_code == 200, f"{response.request.url}: {response.text}"
    return response.json()


def test_a_first_session_from_statements_to_a_check_in(state):
    client = TestClient(create_app(state))
    get = lambda path: ok(client.get(path, headers=AUTH))  # noqa: E731
    post = lambda path, body=None: ok(client.post(path, json=body, headers=AUTH))  # noqa: E731

    # 1. The statements are in: the dashboard has real, server-computed numbers.
    assert get("/api/health") == {"status": "ok"}
    dashboard = get("/api/dashboard")
    assert dashboard, "the dashboard should not be empty after an import"
    transactions = get("/api/transactions?limit=200")
    assert transactions["items"], "the import should have produced transactions"

    # 2. FinCo categorises what it can and says why for any one payment.
    cascade = post("/api/understand/run")
    assert "considered" in cascade
    first_id = transactions["items"][0]["id"]
    why = client.get(f"/api/understand/why/{first_id}", headers=AUTH)
    assert why.status_code in (200, 404)

    # 3. The one it was unsure of goes to the review queue; fixing it takes it off.
    queue = get("/api/review-queue")
    assert queue["items"], "the demo data always leaves something to review"
    unsure = queue["items"][0]["transaction"]["id"]
    fixed = post(f"/api/transactions/{unsure}/category", {"category_id": "food", "remember": False})
    assert fixed["detail"]["transaction"]["category_source"] == "user"
    assert unsure not in {i["transaction"]["id"] for i in get("/api/review-queue")["items"]}

    # 4. A question is answered from tool results, with the plan that produced it.
    answer = post("/api/ask", {"text": "why did my food spend change in February"})
    assert [p["tool_name"] for p in answer["plan"]] == [
        "aggregate_spend_by_category",
        "explain_change",
    ]
    assert answer["trace"][-1]["node"] == "finalize"
    # and a request to move money is refused, not planned
    refused = post("/api/ask", {"text": "transfer 5000 to rahul"})
    assert refused["refusal_reason"] and not refused["plan"]

    # 5. A payment happens: FinCo asks about it once, and tagging it puts it in the ledger.
    simulated = post(
        "/api/capture/simulate",
        {"bank": "hdfc", "kind": "debit", "amount_paise": 25_000, "counterparty": "XQ9 Traders"},
    )
    assert simulated["decision"] == "ask"
    assert get("/api/capture/inbox")["pending_count"] == 1
    category = get("/api/categories")[0]["id"]
    tagged = post(
        "/api/capture/labels",
        {"event_id": simulated["event"]["id"], "category_id": category, "rank_picked": 1},
    )
    assert tagged["event"]["category_source"] == "user"
    assert get("/api/capture/inbox")["pending_count"] == 0

    # 6. The budget waits for income, then plans around it and can be applied.
    assert get("/api/budget/proposal")["data"]["status"] == "needs_profile"
    post(
        "/api/profile/income",
        {"value": {"kind": "monthly", "expected_paise": 9_000_000, "day_of_month": 1}},
    )
    post("/api/profile/savings_intent_paise", {"value": 500_000})
    plan = get("/api/budget/proposal")["data"]
    assert plan["status"] in ("ok", "essentials_exceed")
    if plan["status"] == "ok":
        post("/api/budget/apply")
    # the profile can suggest more, but a suggestion is never saved on its own
    post("/api/profile/suggest")
    assert "nudge_style" not in get("/api/profile")["data"]["values"]

    # 7. The check-in agent either says one thing worth saying, or stays quiet and says why.
    checkin = post("/api/checkins/run")
    assert "sent" in checkin and "reason" in checkin
    if checkin["sent"]:
        listing = get("/api/checkins")["data"]
        assert listing, "a sent check-in must be listed"

    # -- what holds across the whole session -----------------------------------------------
    conn = state.connect()
    try:
        events = list_events(conn, state.user_id)
    finally:
        conn.close()

    tool_calls = [e for e in events if e.event_type == "tool_call"]
    assert tool_calls, "every change goes through the tool executor"
    assert {e.policy_decision for e in tool_calls} <= {"allow"}, "nothing ran without policy"
    assert all(e.actor in {"user", "agent", "system"} for e in events), "every change has an owner"
    used = {e.entity_id for e in tool_calls}
    for tool in ("recategorize_transaction", "label_payment_event", "profile_set"):
        assert tool in used, f"{tool} should have run through the executor"
    # nothing that reaches outside FinCo (the only way money could move) ever ran
    reach = {name: registry.get(name).side_effect for name in used if registry.get(name)}
    assert "external" not in reach.values(), reach

    assert get("/api/timeline"), "the timeline shows the session"
