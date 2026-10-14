"""
API tests. Everything goes through the FastAPI test client into the real executor, so audit
rows are asserted on the real path.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.audit.events import list_events
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "api.db", clock=DEMO_CLOCK, token="test-token")
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def audit(state, **kwargs):
    conn = state.connect()
    try:
        return list_events(conn, state.user_id, **kwargs)
    finally:
        conn.close()


# ------------------------------------------------------------------ auth and health


def test_health_is_open_everything_else_needs_the_token(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    for path in ("/api/session", "/api/dashboard", "/api/transactions", "/api/review-queue"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHORIZED"
    wrong = client.get("/api/session", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


def test_cors_is_limited_to_the_dev_origin(client):
    allowed = client.options(
        "/api/session",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.options(
        "/api/session",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in other.headers


# ------------------------------------------------------------------ read models


def test_dashboard_numbers_are_server_computed_and_consistent(client):
    d = client.get("/api/dashboard", headers=AUTH).json()
    pace = d["budget_pace"]
    assert d["has_transactions"] is True
    assert pace["left_to_spend_paise"] == pace["total_limit_paise"] - pace["spent_paise"]
    assert pace["pace"] in {"under", "on", "over"}
    assert pace["actual"][-1]["paise"] == pace["spent_paise"]
    assert len(pace["ideal"]) == d["period"]["days_in_month"]
    assert d["headline"] is not None
    assert d["review_count"] == len(d["review_preview"]) or d["review_count"] > 4


def test_transactions_filters_and_pagination(client):
    page = client.get("/api/transactions?limit=5", headers=AUTH).json()
    assert len(page["items"]) == 5 and page["total"] > 5
    march = client.get("/api/transactions?period=2024-03&limit=200", headers=AUTH).json()
    assert march["total"] > 0
    assert all(i["occurred_at"].startswith(("2024-03", "2024-02-29")) for i in march["items"])
    review = client.get("/api/transactions?needs_review=true", headers=AUTH).json()
    assert review["total"] > 0 and all(i["needs_review"] for i in review["items"])
    found = client.get("/api/transactions?q=swiggy", headers=AUTH).json()
    assert found["total"] > 0
    assert client.get("/api/transactions?limit=500", headers=AUTH).status_code == 422
    assert client.get("/api/transactions?period=March", headers=AUTH).status_code == 422


def test_review_queue_has_context_for_each_item(client):
    queue = client.get("/api/review-queue", headers=AUTH).json()
    assert queue["total"] == len(queue["items"]) > 0
    item = queue["items"][0]
    assert item["why"] and item["suggestions"]
    assert {s["reason"] for s in item["suggestions"]} <= {
        "ai_suggestion",
        "past_choice",
        "frequent",
    }


# ------------------------------------------------------------------ governed writes


def test_correction_goes_through_the_executor_and_is_audited_as_the_user(client, state):
    queue = client.get("/api/review-queue", headers=AUTH).json()
    tx_id = queue["items"][0]["transaction"]["id"]
    response = client.post(
        f"/api/transactions/{tx_id}/category",
        headers=AUTH,
        json={"category_id": "food", "remember": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detail"]["transaction"]["category_id"] == "food"
    assert body["detail"]["transaction"]["category_source"] == "user"

    changed = [
        e for e in audit(state, entity_id=tx_id) if e.event_type == "transaction_recategorized"
    ]
    assert len(changed) == 1 and changed[0].actor == "user"
    assert changed[0].after["needs_review"] is False
    calls = [
        e for e in audit(state, entity_id="recategorize_transaction") if e.event_type == "tool_call"
    ]
    assert calls and calls[-1].actor == "user" and calls[-1].policy_decision == "allow"


def test_correcting_an_item_removes_it_from_the_review_queue_and_undo_restores_it(client):
    queue = client.get("/api/review-queue", headers=AUTH).json()
    tx_id = queue["items"][0]["transaction"]["id"]
    out = client.post(
        f"/api/transactions/{tx_id}/category", headers=AUTH, json={"category_id": "food"}
    ).json()
    after = client.get("/api/review-queue", headers=AUTH).json()
    assert after["total"] == queue["total"] - 1
    assert tx_id not in [i["transaction"]["id"] for i in after["items"]]

    assert (
        client.post(
            "/api/undo", headers=AUTH, json={"audit_event_id": out["audit_event_id"]}
        ).status_code
        == 200
    )
    restored = client.get("/api/review-queue", headers=AUTH).json()
    assert restored["total"] == queue["total"]
    detail = client.get(f"/api/transactions/{tx_id}", headers=AUTH).json()
    assert detail["transaction"]["category_id"] is None
    assert detail["history"][0]["event_type"] == "undo"


def test_second_undo_and_stale_undo_are_refused_with_typed_errors(client):
    queue = client.get("/api/review-queue", headers=AUTH).json()
    tx_id = queue["items"][0]["transaction"]["id"]
    first = client.post(
        f"/api/transactions/{tx_id}/category", headers=AUTH, json={"category_id": "food"}
    ).json()
    second = client.post(
        f"/api/transactions/{tx_id}/category", headers=AUTH, json={"category_id": "travel"}
    ).json()
    stale = client.post("/api/undo", headers=AUTH, json={"audit_event_id": first["audit_event_id"]})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_DATA"

    assert (
        client.post(
            "/api/undo", headers=AUTH, json={"audit_event_id": second["audit_event_id"]}
        ).status_code
        == 200
    )
    again = client.post(
        "/api/undo", headers=AUTH, json={"audit_event_id": second["audit_event_id"]}
    )
    assert again.status_code == 422 and again.json()["code"] == "INVALID_INPUT"


# ------------------------------------------------------------------ error mapping and isolation


def test_error_codes_map_to_http_statuses(client):
    unknown_category = client.post(
        "/api/transactions/anything/category", headers=AUTH, json={"category_id": "nope"}
    )
    assert unknown_category.status_code == 404 and unknown_category.json()["code"] == "NOT_FOUND"
    assert client.get("/api/transactions/missing", headers=AUTH).status_code == 404
    bad = client.post("/api/whatif", headers=AUTH, json={"kind": "add_spend", "amount_paise": -5})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_INPUT"
    unknown_field = client.post("/api/undo", headers=AUTH, json={"audit_event_id": "x", "extra": 1})
    assert unknown_field.status_code == 404  # unknown event id; extra body fields are ignored
    assert client.get("/api/monthly-reviews/2024-13", headers=AUTH).status_code == 422


def test_other_users_data_is_invisible(client, state):
    conn = state.connect()
    conn.execute("INSERT INTO users (id, created_at) VALUES ('intruder', '2024-01-01T00:00:00Z')")
    conn.execute(
        "INSERT INTO accounts (id, user_id, name, created_at) VALUES "
        "('ia', 'intruder', 'Other', '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction, "
        "merchant_raw, description, category_source, created_at) VALUES "
        "('secret', 'intruder', 'ia', '2024-03-01T00:00:00Z', 999, 'debit', 'SECRET', 'd', 'none', "
        "'2024-03-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    assert client.get("/api/transactions/secret", headers=AUTH).status_code == 404
    listed = client.get("/api/transactions?q=secret&limit=200", headers=AUTH).json()
    assert listed["total"] == 0
    recategorize = client.post(
        "/api/transactions/secret/category", headers=AUTH, json={"category_id": "food"}
    )
    assert recategorize.status_code == 404


# ------------------------------------------------------------------ consent lifecycle


def test_revoked_consent_blocks_imports_and_is_audited(client, state):
    consent = client.get("/api/consents", headers=AUTH).json()[0]
    assert consent["status"] == "active"
    revoked = client.post(f"/api/consents/{consent['id']}/revoke", headers=AUTH)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    refused = client.post(f"/api/consents/{consent['id']}/import", headers=AUTH)
    assert refused.status_code == 409
    assert any(e.event_type == "consent_revoked" and e.actor == "user" for e in audit(state))
    again = client.post(f"/api/consents/{consent['id']}/approve", headers=AUTH)
    assert again.status_code == 422  # a revoked consent cannot come back


def test_reimport_is_idempotent(client):
    consent = client.get("/api/consents", headers=AUTH).json()[0]
    result = client.post(f"/api/consents/{consent['id']}/import", headers=AUTH).json()
    assert result["inserted"] == 0 and result["skipped_existing"] == result["fetched"] > 0


# ------------------------------------------------------------------ monthly review and advice


def test_monthly_review_advice_is_period_scoped_and_decided_once(client, state):
    built = client.post("/api/monthly-reviews", headers=AUTH, json={"period": "2024-02"}).json()
    advice = built["review"]["advice"]
    assert advice and all("February 2024" in a["text"] or "₹" in a["text"] for a in advice)
    march = client.post("/api/monthly-reviews", headers=AUTH, json={"period": "2024-03"}).json()
    assert {a["id"] for a in march["review"]["advice"]}.isdisjoint({a["id"] for a in advice})

    again = client.post("/api/monthly-reviews", headers=AUTH, json={"period": "2024-02"}).json()
    assert len(again["review"]["advice"]) == len(advice), "regenerating must not duplicate advice"
    assert again["review"]["version"] == 2 and len(again["versions"]) == 2

    first = advice[0]["id"]
    ok = client.post(f"/api/advice/{first}/decision", headers=AUTH, json={"decision": "approved"})
    assert ok.status_code == 200
    twice = client.post(
        f"/api/advice/{first}/decision", headers=AUTH, json={"decision": "rejected"}
    )
    assert twice.status_code == 422 and twice.json()["code"] == "INVALID_INPUT"
    refreshed = client.get("/api/monthly-reviews/2024-02", headers=AUTH).json()["review"]["advice"]
    assert next(a for a in refreshed if a["id"] == first)["status"] == "approved"
    assert any(e.event_type == "advice_decided" and e.actor == "user" for e in audit(state))


# ------------------------------------------------------------------ agent surfaces


def test_money_movement_requests_are_refused_by_the_agent(client):
    result = client.post("/api/ask", headers=AUTH, json={"text": "transfer 5000 to rahul"}).json()
    assert result["refusal_reason"]


def test_investigation_returns_evidence_and_inconclusive_is_a_normal_outcome(client):
    anomalies = client.get("/api/anomalies", headers=AUTH).json()
    assert anomalies
    inv = client.post(
        "/api/investigate/anomaly", headers=AUTH, json={"anomaly_id": anomalies[0]["id"]}
    )
    assert inv.status_code == 200
    assert inv.json()["investigation"]["outcome"] in {
        "explained",
        "partially_explained",
        "inconclusive",
    }
    change = client.post(
        "/api/investigate/change", headers=AUTH, json={"period": "2024-02", "category_id": "food"}
    )
    assert change.status_code == 200


def test_whatif_compare_against_baseline(client):
    scenario = {"kind": "add_spend", "category_id": "food", "amount_paise": 200000, "months": 3}
    out = client.post("/api/whatif/compare", headers=AUTH, json={"scenarios": [scenario]}).json()
    rows = out["comparison"]["side_by_side"]
    assert rows and "baseline_surplus_paise" in rows[-1] and "scenario_1_surplus_paise" in rows[-1]
    assert rows[-1]["scenario_1_surplus_paise"] < rows[-1]["baseline_surplus_paise"]


# ------------------------------------------------------------------ structure


BANNED = ("pay", "transfer", "trade", "withdraw", "deposit", "send", "wire", "remit")


def test_no_route_can_move_money(client):
    paths = [route.path for route in client.app.routes if hasattr(route, "methods")]
    assert paths
    for path in paths:
        words = re.split(r"[/_\-{}]+", path.lower())
        assert not any(b in words for b in BANNED), path
    assert client.post("/api/transfer", headers=AUTH, json={}).status_code in (404, 405)


def test_only_get_and_post_exist_and_every_write_is_governed(client):
    methods = {m for route in client.app.routes if hasattr(route, "methods") for m in route.methods}
    assert methods <= {"GET", "POST", "HEAD", "OPTIONS"}


def test_openapi_snapshot_is_current(client):
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    live = client.app.openapi()
    assert sorted(committed["paths"]) == sorted(live["paths"]), "run: npm run gen:api (frontend)"
    assert sorted(committed["components"]["schemas"]) == sorted(live["components"]["schemas"])


def test_generated_typescript_types_cover_every_schema():
    types = (ROOT / "frontend" / "src" / "api" / "schema.d.ts").read_text(encoding="utf-8")
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    missing = [n for n in committed["components"]["schemas"] if f"    {n}: " not in types]
    assert missing == [], "run: npm run gen:api (frontend)"


def test_ask_returns_the_validated_plan_and_the_node_trace(client):
    out = client.post(
        "/api/ask", headers=AUTH, json={"text": "why did my food spend change in February"}
    ).json()
    assert [p["tool_name"] for p in out["plan"]] == [
        "aggregate_spend_by_category",
        "explain_change",
    ]
    assert all(p["proposed_by"] == "deterministic" and p["rationale"] for p in out["plan"])
    nodes = [t["node"] for t in out["trace"]]
    assert (
        nodes[:2] == ["understand", "plan"] and nodes.count("act") == 2 and nodes[-1] == "finalize"
    )
    investigation = next(o for o in out["observations"] if o["tool_name"] == "explain_change")
    assert investigation["ok"] and investigation["data_summary"]["investigation"]["hypotheses"]
    assert out["intent"]["category_id"] == "food" and out["intent"]["period"] == "2024-02"


def test_ask_whatif_plans_a_simulation_and_leaves_the_draft_for_the_user(client, state):
    out = client.post(
        "/api/ask",
        headers=AUTH,
        json={"text": "what if I spend ₹2,000 more on food each month for 3 months"},
    ).json()
    assert [p["tool_name"] for p in out["plan"]] == ["check_budgets", "compare_options"]
    sim = next(o for o in out["observations"] if o["tool_name"] == "compare_options")
    assert sim["ok"]
    assert out["answer"] and out["answer"]["headline"] and out["answer"]["written_by"] == "rules"
    assert out["llm"]["available"] is False
    assert out["pending_recommendations"], "agent drafts must wait for a human decision"
    assert not any(e.event_type == "recommendation_decided" for e in audit(state))


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("should I invest in mutual funds", "investment advice"),
        ("transfer 5000 to rahul", "payments"),
        ("my otp is 123456", "OTP"),
        ("will the market crash", "market"),
    ],
)
def test_the_input_gate_refuses_before_any_planning(client, text, fragment):
    out = client.post("/api/ask", headers=AUTH, json={"text": text}).json()
    assert fragment.lower() in out["refusal_reason"].lower()
    assert out["plan"] == [] and out["observations"] == []
    assert [t["node"] for t in out["trace"]][:1] == ["understand"]
    assert "act" not in [t["node"] for t in out["trace"]]


def test_the_planner_is_only_offered_read_and_compute_tools():
    from copilot.planner.capabilities import get_selectable_tools

    selectable = set(get_selectable_tools())
    writes = {
        "recategorize_transaction",
        "approve_consent",
        "revoke_consent",
        "decide_advice",
        "decide_alert",
        "create_goal",
        "update_goal",
        "ingest_statements",
        "undo",
        "categorize_batch",
        "draft_advice",
        "set_alert_preference",
        "dismiss_anomaly",
    }
    assert selectable and selectable.isdisjoint(writes)


def test_user_can_create_a_category_and_it_is_audited(client, state):
    out = client.post("/api/categories", headers=AUTH, json={"name": "  Pet   care "})
    assert out.status_code == 200 and out.json() == {"id": "pet_care", "name": "Pet care"}
    again = client.post("/api/categories", headers=AUTH, json={"name": "pet CARE"}).json()
    assert again["id"] == "pet_care"  # same name, no duplicate
    names = [c["name"] for c in client.get("/api/categories", headers=AUTH).json()]
    assert names.count("Pet care") == 1
    assert [e.event_type for e in audit(state)].count("category_created") == 1
    assert client.post("/api/categories", headers=AUTH, json={"name": ""}).status_code == 422
    assert client.post("/api/categories", json={"name": "x"}).status_code == 401


@pytest.mark.parametrize(
    "text, expect",
    [
        ("how much did I spend in the last 3 months", "over the last"),
        ("what did I spend this week", "whole months"),
    ],
)
def test_relative_periods_are_answered_honestly_not_crashed(client, text, expect):
    out = client.post("/api/ask", headers=AUTH, json={"text": text})
    assert out.status_code == 200
    body = out.json()["answer"]
    assert expect in body["headline"] + " ".join(body["points"])
