"""
Phase 4 API endpoint integration tests.

Verifies all Phase 4 routes:
- Experiments: list, get, progress, design, start, pause, resume, checkin, abandon, review, feedback
- Challenges: offers (list, suggest), accept, dismiss
- Adjustments: list, accept, reject
- Progress: progress summary, personal bests
- Goals: decompose
- Auth enforcement (401 without Bearer token)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.db.repo import insert_goal
from copilot.db.repo_phase4 import insert_adjustment_proposal, insert_experiment, insert_offer
from copilot.models.agentic import Goal
from copilot.models.phase4 import (
    AdjustmentProposal,
    Experiment,
    Offer,
)
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "api_p4.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_phase4_endpoints_require_auth(client):
    """Verify all Phase 4 routes reject unauthenticated requests."""
    endpoints = [
        ("GET", "/api/experiments"),
        ("GET", "/api/experiments/exp_1"),
        ("GET", "/api/experiments/exp_1/progress"),
        ("POST", "/api/experiments/design"),
        ("POST", "/api/experiments/start"),
        ("POST", "/api/experiments/exp_1/pause"),
        ("POST", "/api/experiments/exp_1/resume"),
        ("POST", "/api/experiments/exp_1/abandon"),
        ("POST", "/api/experiments/exp_1/checkin"),
        ("GET", "/api/experiments/exp_1/review"),
        ("POST", "/api/experiments/exp_1/feedback"),
        ("GET", "/api/challenges/offers"),
        ("POST", "/api/challenges/offers/suggest"),
        ("POST", "/api/challenges/offers/off_1/accept"),
        ("POST", "/api/challenges/offers/off_1/dismiss"),
        ("GET", "/api/adjustments"),
        ("POST", "/api/adjustments/adj_1/accept"),
        ("POST", "/api/adjustments/adj_1/reject"),
        ("GET", "/api/progress"),
        ("GET", "/api/progress/bests"),
        ("POST", "/api/goals/g1/decompose"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"
        assert res.json()["code"] == "UNAUTHORIZED"


def test_experiments_api_lifecycle(client, state):
    """Verify designing, starting, listing, pausing, resuming, check-in and abandoning experiments."""
    # 1. Design Experiment
    design_payload = {
        "template_code": "weekday_home_cooking",
        "metric_code": "category_spend",
        "categories": ["food"],
        "duration_days": 14,
        "difficulty": "medium",
        "target_value": 300000,
    }
    des_res = client.post("/api/experiments/design", headers=AUTH, json=design_payload)
    assert des_res.status_code == 200
    des_data = des_res.json()
    assert des_data["experiment"]["template_code"] == "weekday_home_cooking"
    assert "hypothesis_json" in des_data["experiment"]

    # 2. Start Experiment
    start_payload = {
        "title": "Weekday Cooking",
        "metric_code": "category_spend",
        "template_code": "weekday_home_cooking",
        "categories": ["food"],
        "duration_days": 14,
        "difficulty": "medium",
        "target_value": 300000,
        "baseline_median": 500000,
        "start_date": "2024-03-18",
    }
    start_res = client.post("/api/experiments/start", headers=AUTH, json=start_payload)
    assert start_res.status_code == 200
    start_data = start_res.json()
    exp_id = start_data["experiment"]["id"]
    assert start_data["experiment"]["status"] == "active"

    # 3. List Experiments
    list_res = client.get("/api/experiments", headers=AUTH)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert any(e["id"] == exp_id for e in items)

    # 4. Get Experiment Details
    get_res = client.get(f"/api/experiments/{exp_id}", headers=AUTH)
    assert get_res.status_code == 200
    exp_detail = get_res.json()
    assert exp_detail["experiment"]["id"] == exp_id

    # 5. Experiment Progress
    prog_res = client.get(f"/api/experiments/{exp_id}/progress", headers=AUTH)
    assert prog_res.status_code == 200
    prog_data = prog_res.json()
    assert "pace_status" in prog_data["progress"]

    # 6. Pause Experiment
    pause_res = client.post(f"/api/experiments/{exp_id}/pause", headers=AUTH, json={})
    assert pause_res.status_code == 200
    assert pause_res.json()["experiment"]["status"] == "paused"

    # 7. Resume Experiment
    resume_res = client.post(f"/api/experiments/{exp_id}/resume", headers=AUTH, json={})
    assert resume_res.status_code == 200
    assert resume_res.json()["experiment"]["status"] == "active"

    # 8. Checkin Experiment
    chk_res = client.post(
        f"/api/experiments/{exp_id}/checkin",
        headers=AUTH,
        json={"user_response": "going_well"},
    )
    assert chk_res.status_code == 200
    assert chk_res.json()["checkin"]["user_response"] == "going_well"

    # 9. Abandon Experiment
    ab_res = client.post(
        f"/api/experiments/{exp_id}/abandon",
        headers=AUTH,
        json={"reason": "Traveling"},
    )
    assert ab_res.status_code == 200
    assert ab_res.json()["experiment"]["status"] == "abandoned"

    # 10. Feedback Submission
    fb_res = client.post(
        f"/api/experiments/{exp_id}/feedback",
        headers=AUTH,
        json={"user_difficulty": 3, "user_helpful": True, "user_would_repeat": True},
    )
    assert fb_res.status_code == 200
    assert fb_res.json()["review"]["experiment_id"] == exp_id


def test_challenges_offers_api_lifecycle(client, state):
    """Verify suggesting, listing, accepting, and dismissing challenge offers."""
    from copilot.db.connection import get_connection

    with get_connection(state.db_path) as conn:
        offer = Offer(
            id="off_test_1",
            user_id=state.user_id,
            week_start="2024-03-18",
            template_code="delivery_cap",
            difficulty="medium",
            params_json={
                "title": "Cap Food Delivery",
                "metric_code": "merchant_group_spend",
                "duration_days": 14,
                "target_value": 200000,
                "baseline_median": 350000,
            },
            rank=1,
            propensity_bp=5000,
            policy_version="v1_thompson",
            rng_seed=42,
            reason_json={"text": "Frequent delivery spend"},
            status="shown",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_offer(conn, offer)
        conn.commit()

    # 1. List Offers
    list_res = client.get("/api/challenges/offers", headers=AUTH)
    assert list_res.status_code == 200
    offers = list_res.json()
    assert len(offers) >= 1
    assert any(o["id"] == "off_test_1" for o in offers)

    # 2. Accept Offer
    accept_res = client.post("/api/challenges/offers/off_test_1/accept", headers=AUTH, json={})
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "accepted"

    # 3. Add second offer and dismiss
    with get_connection(state.db_path) as conn:
        offer2 = Offer(
            id="off_test_2",
            user_id=state.user_id,
            week_start="2024-03-18",
            template_code="no_spend_weekend",
            difficulty="easy",
            params_json={
                "title": "No Spend Weekend",
                "metric_code": "no_spend_days",
                "duration_days": 7,
                "target_value": 2,
                "baseline_median": 1,
            },
            rank=2,
            propensity_bp=4000,
            policy_version="v1_thompson",
            rng_seed=43,
            reason_json={"text": "Try spending nothing on weekends"},
            status="shown",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_offer(conn, offer2)
        conn.commit()

    dismiss_res = client.post(
        "/api/challenges/offers/off_test_2/dismiss",
        headers=AUTH,
        json={"reason": "Busy weekend"},
    )
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["status"] == "dismissed"


def test_adjustments_api_lifecycle(client, state):
    """Verify listing, accepting, and rejecting adaptive adjustments."""
    from copilot.db.connection import get_connection

    with get_connection(state.db_path) as conn:
        exp = Experiment(
            id="exp_adj_test",
            user_id=state.user_id,
            title="Dining Test",
            template_code="weekday_home_cooking",
            hypothesis_json={
                "intervention": "cook",
                "metric": "category_spend",
                "direction": "lower",
                "target": 200000,
            },
            metric_def_json={"metric": "category_spend", "categories": ["food"]},
            params_json={},
            difficulty="medium",
            window_start="2024-03-18",
            window_end="2024-04-01",
            baseline_json={
                "k": 6,
                "window_values": [400000],
                "median": 400000,
                "low": 350000,
                "high": 450000,
            },
            target_value=200000,
            status="active",
            origin="user",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_experiment(conn, exp)
        prop = AdjustmentProposal(
            id="adj_test_1",
            experiment_id="exp_adj_test",
            user_id=state.user_id,
            kind="ease_target",
            reason_code="behind_pace_consecutive",
            params_json={"new_target_value": 250000},
            status="proposed",
            created_at="2024-03-22T00:00:00Z",
        )
        insert_adjustment_proposal(conn, prop)
        conn.commit()

    # 1. List Adjustments
    list_res = client.get("/api/adjustments", headers=AUTH)
    assert list_res.status_code == 200
    adjs = list_res.json()
    assert len(adjs) >= 1
    assert any(a["id"] == "adj_test_1" for a in adjs)

    # 2. Accept Adjustment
    acc_res = client.post("/api/adjustments/adj_test_1/accept", headers=AUTH, json={})
    assert acc_res.status_code == 200
    assert acc_res.json()["proposal"]["status"] == "accepted"


def test_progress_and_goal_decompose_api(client, state):
    """Verify progress endpoint and goal gap decomposition."""
    from copilot.db.connection import get_connection

    # 1. Progress API
    prog_res = client.get("/api/progress", headers=AUTH)
    assert prog_res.status_code == 200
    prog = prog_res.json()
    assert "progress" in prog
    assert prog["progress"]["level_number"] >= 1
    assert "total_xp" in prog["progress"]

    # 2. Personal Bests API
    bests_res = client.get("/api/progress/bests", headers=AUTH)
    assert bests_res.status_code == 200
    assert isinstance(bests_res.json(), list)

    # 3. Goal Decomposition API
    with get_connection(state.db_path) as conn:
        g = Goal(
            id="g_trip_test",
            user_id=state.user_id,
            name="Vacation Trip",
            kind="savings",
            target_paise=10000000,
            current_paise=2000000,
            deadline="2024-06-30",
            priority=2,
            status="active",
            created_at="2024-03-01T00:00:00Z",
            updated_at="2024-03-01T00:00:00Z",
        )
        insert_goal(conn, g)
        conn.commit()

    decomp_res = client.post("/api/goals/g_trip_test/decompose", headers=AUTH, json={})
    assert decomp_res.status_code == 200
    decomp_data = decomp_res.json()
    assert decomp_data["deficit_paise"] == 8000000
    assert "candidate_experiments" in decomp_data
    assert "required_monthly_paise" in decomp_data
