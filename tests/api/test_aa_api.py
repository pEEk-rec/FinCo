"""The bank link over the API and through the tool layer (PLAN_CAPTURE Stage C7)."""

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.tools.executor import execute_tool
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def state(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "t.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def consent(client):
    return client.get("/api/aa/consent", headers=AUTH).json()["consent"]


def test_no_link_is_a_valid_empty_state(client):
    assert consent(client) is None


def test_set_up_approve_fetch_and_revoke_over_the_api(client):
    created = client.post("/api/aa/consent", headers=AUTH).json()["consent"]
    assert created["status"] == "pending" and created["can"] == ["approve", "revoke"]
    assert created["why"] and created["revoke"] and created["data_kept"]

    early = client.post("/api/aa/fetch", headers=AUTH)
    assert early.status_code >= 400, "nothing may be fetched before approval"

    cid = created["id"]
    active = client.post(f"/api/aa/consent/{cid}/approve", headers=AUTH).json()["consent"]
    assert active["status"] == "active" and active["expires_at"]
    fetched = client.post("/api/aa/fetch", headers=AUTH)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["consent_id"] == cid

    revoked = client.post(f"/api/aa/consent/{cid}/revoke", headers=AUTH).json()["consent"]
    assert revoked["status"] == "revoked" and revoked["can"] == []
    assert client.post("/api/aa/fetch", headers=AUTH).status_code >= 400


def test_an_illegal_action_is_refused(client):
    cid = client.post("/api/aa/consent", headers=AUTH).json()["consent"]["id"]
    assert client.post(f"/api/aa/consent/{cid}/resume", headers=AUTH).status_code >= 400
    assert consent(client)["status"] == "pending"


def test_unknown_actions_and_missing_token_are_rejected(client):
    assert client.post("/api/aa/consent/x/hack", headers=AUTH).status_code == 422
    assert client.get("/api/aa/consent").status_code == 401


@pytest.mark.parametrize("tool", ["create_aa_consent", "set_aa_consent_state", "fetch_aa_data"])
def test_the_agent_can_never_change_or_use_the_bank_link(state, tool):
    conn = state.connect()
    try:
        args = {"consent_id": "x", "action": "approve"} if tool == "set_aa_consent_state" else {}
        res = execute_tool(state.context(conn, "agent"), tool, args)
        assert not res.ok and res.error.code.value == "DENIED_BY_POLICY"
    finally:
        conn.close()


def test_the_runtime_job_runs_as_the_system_and_fetches_only_under_consent(state):
    conn = state.connect()
    try:
        cycle = execute_tool(state.context(conn, "system"), "run_aa_cycle", {})
        assert cycle.ok and cycle.data.fetches == []
    finally:
        conn.close()
