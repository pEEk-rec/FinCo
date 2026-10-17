"""Goals can be created, edited, paused, finished and contributed to through the API."""

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.audit.events import list_events
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "g.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def _new(client, **over):
    body = {"name": "Goa trip", "target_paise": 2500000, "deadline": "2024-09-30", **over}
    res = client.post("/api/goals", json=body, headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_created_goal_comes_back_with_its_progress(client):
    out = _new(client)
    goal = next(g for g in out["goals"] if g["name"] == "Goa trip")
    prog = next(p for p in out["progress"] if p["goal_id"] == goal["id"])
    assert goal["status"] == "active" and goal["target_paise"] == 2500000
    assert prog["remaining_paise"] == 2500000 and prog["percent_bp"] == 0
    assert prog["required_monthly_paise"] > 0


def test_a_contribution_moves_progress_and_is_audited(client, state):
    goal = next(g for g in _new(client)["goals"] if g["name"] == "Goa trip")
    out = client.post(
        f"/api/goals/{goal['id']}/contributions", json={"amount_paise": 500000}, headers=AUTH
    ).json()
    prog = next(p for p in out["progress"] if p["goal_id"] == goal["id"])
    assert prog["current_paise"] == 500000 and prog["percent_bp"] == 2000
    conn = state.connect()
    try:
        kinds = {e.event_type for e in list_events(conn, state.user_id)}
    finally:
        conn.close()
    assert {"goal_created", "goal_contribution_recorded"} & kinds


def test_edit_pause_and_finish(client):
    goal = next(g for g in _new(client)["goals"] if g["name"] == "Goa trip")
    url = f"/api/goals/{goal['id']}/update"
    out = client.post(url, json={"name": "Goa 2024", "target_paise": 3000000}, headers=AUTH).json()
    edited = next(g for g in out["goals"] if g["id"] == goal["id"])
    assert edited["name"] == "Goa 2024" and edited["target_paise"] == 3000000
    for status in ("paused", "done"):
        out = client.post(url, json={"status": status}, headers=AUTH).json()
        assert next(g for g in out["goals"] if g["id"] == goal["id"])["status"] == status


def test_bad_input_is_a_typed_error_not_a_crash(client):
    assert client.post("/api/goals", json={"name": "x", "target_paise": 0}, headers=AUTH).status_code == 422
    missing = client.post("/api/goals/nope/update", json={"status": "done"}, headers=AUTH)
    assert missing.status_code == 404
    zero = client.post("/api/goals/nope/contributions", json={"amount_paise": 0}, headers=AUTH)
    assert zero.status_code == 422


def test_goals_need_the_token(client):
    assert client.post("/api/goals", json={"name": "x", "target_paise": 1}).status_code == 401
