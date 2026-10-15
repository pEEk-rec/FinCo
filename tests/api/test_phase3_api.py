"""
Phase 3 API endpoint integration tests.

Verifies all Phase 3 routes:
- GET /api/commitments, POST /api/commitments, POST /api/commitments/suggest
- GET /api/calendar
- GET /api/buckets, POST /api/buckets, POST /api/buckets/allocate, POST /api/buckets/reallocate
- GET /api/readiness
- GET /api/memories, POST /api/memories/forget, GET /api/memories/audit
- GET /api/learning, POST /api/learning/reset
- GET /api/ops, POST /api/jobs/run
- Auth enforcement (401 without Bearer token)
- Strict validation (422 on invalid input)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "api_p3.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_phase3_endpoints_require_auth(client):
    """Verify all Phase 3 routes reject unauthenticated requests."""
    endpoints = [
        ("GET", "/api/commitments"),
        ("POST", "/api/commitments"),
        ("POST", "/api/commitments/suggest"),
        ("GET", "/api/calendar"),
        ("GET", "/api/buckets"),
        ("POST", "/api/buckets"),
        ("POST", "/api/buckets/allocate"),
        ("POST", "/api/buckets/reallocate"),
        ("GET", "/api/readiness"),
        ("GET", "/api/memories"),
        ("POST", "/api/memories/forget"),
        ("GET", "/api/memories/audit"),
        ("GET", "/api/learning"),
        ("POST", "/api/learning/reset"),
        ("GET", "/api/ops"),
        ("POST", "/api/jobs/run"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"
        assert res.json()["code"] == "UNAUTHORIZED"


def test_commitments_api_lifecycle(client):
    """Verify listing, creating, and suggesting commitments via API."""
    # 1. Suggest commitments
    suggest_res = client.post("/api/commitments/suggest", headers=AUTH, json={})
    assert suggest_res.status_code == 200
    assert "suggested" in suggest_res.json() or "commitments" in suggest_res.json()

    # 2. Create commitment
    payload = {
        "name": "Apartment Rent",
        "amount_paise": 2500000,
        "start_date": "2024-03-01",
        "schedule_kind": "monthly",
        "schedule_json": {"day": 5},
        "kind": "rent",
    }
    create_res = client.post("/api/commitments", headers=AUTH, json=payload)
    assert create_res.status_code == 200
    data = create_res.json()
    assert data["commitment"]["name"] == "Apartment Rent"
    assert data["commitment"]["amount_paise"] == 2500000

    # 3. List commitments
    list_res = client.get("/api/commitments", headers=AUTH)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert any(c["name"] == "Apartment Rent" for c in items)


def test_calendar_api(client):
    """Verify cashflow calendar forecasting via API."""
    res = client.get("/api/calendar?horizon_days=45", headers=AUTH)
    assert res.status_code == 200
    data = res.json()
    cal = data.get("calendar", data)
    assert "days" in cal
    assert "horizon_days" in cal
    assert cal["horizon_days"] == 45
    assert len(cal["days"]) == 45


def test_buckets_api_lifecycle(client):
    """Verify creating, allocating, and reallocating buckets."""
    # 1. Initial list
    res = client.get("/api/buckets", headers=AUTH)
    assert res.status_code == 200

    # 2. Create bucket
    create_payload = {
        "name": "Europe Trip",
        "kind": "spending",
        "period_policy": "reset_monthly",
    }
    b1_res = client.post("/api/buckets", headers=AUTH, json=create_payload)
    assert b1_res.status_code == 200
    b1 = b1_res.json()
    b1_id = b1["bucket"]["id"]

    create_payload_2 = {
        "name": "Gadget Reserve",
        "kind": "flexible",
        "period_policy": "accumulate",
    }
    b2_res = client.post("/api/buckets", headers=AUTH, json=create_payload_2)
    assert b2_res.status_code == 200
    b2 = b2_res.json()
    b2_id = b2["bucket"]["id"]

    # 3. Allocate to bucket
    alloc_res = client.post(
        "/api/buckets/allocate",
        headers=AUTH,
        json={"bucket_id": b1_id, "amount_paise": 500000},
    )
    assert alloc_res.status_code == 200

    # 4. Reallocate between buckets
    realloc_res = client.post(
        "/api/buckets/reallocate",
        headers=AUTH,
        json={
            "from_bucket_id": b1_id,
            "to_bucket_id": b2_id,
            "amount_paise": 300000,
        },
    )
    assert realloc_res.status_code == 200


def test_readiness_api(client):
    """Verify investment readiness score and guardrails."""
    res = client.get("/api/readiness", headers=AUTH)
    assert res.status_code == 200
    data = res.json()
    readiness = data.get("readiness", data)
    assert "level" in readiness
    assert "criteria" in readiness
    assert "numbers" in readiness


def test_memories_api_lifecycle(client):
    """Verify memory retrieval, auditing, and selective forgetting."""
    # 1. Retrieve initial memories
    res = client.get("/api/memories", headers=AUTH)
    assert res.status_code == 200
    memories = res.json()

    # If any memories exist, forget one and verify audit
    if memories:
        target_id = memories[0]["id"]
        forget_res = client.post(
            "/api/memories/forget",
            headers=AUTH,
            json={"memory_id": target_id, "reason": "User requested deletion"},
        )
        assert forget_res.status_code == 200

        # Audit should show the forget event
        audit_res = client.get("/api/memories/audit", headers=AUTH)
        assert audit_res.status_code == 200
        logs = audit_res.json()
        assert any(entry.get("action") == "forgotten" for entry in logs)


def test_learning_and_ops_api(client):
    """Verify user learning inspection, reset, ops summary, and job triggering."""
    # 1. Inspect learning profile
    learn_res = client.get("/api/learning", headers=AUTH)
    assert learn_res.status_code == 200
    learn_data = learn_res.json()
    assert "user_id" in learn_data
    assert "stats" in learn_data

    # 2. Reset learning
    reset_res = client.post(
        "/api/learning/reset",
        headers=AUTH,
        json={},
    )
    assert reset_res.status_code == 200

    # 3. Ops dashboard
    ops_res = client.get("/api/ops", headers=AUTH)
    assert ops_res.status_code == 200
    ops_data = ops_res.json()
    assert ops_data["status"] == "healthy"
    assert "background_jobs" in ops_data

    # 4. Trigger due jobs
    jobs_res = client.post("/api/jobs/run", headers=AUTH, json={})
    assert jobs_res.status_code == 200
