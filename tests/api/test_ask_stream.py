"""The live Ask stream: steps arrive as the agent takes them, and the end result is the real one."""

import json

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
    st = ApiState(db_path=tmp_path / "s.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield TestClient(create_app(st))
    clear_registry()


def stream(client: TestClient, text: str) -> list[tuple[str, dict]]:
    """Read one streamed ask to the end, as (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    with client.stream("POST", "/api/ask/stream", json={"text": text}, headers=AUTH) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: ") and kind:
                events.append((kind, json.loads(line[6:])))
                kind = None
    return events


def test_the_steps_arrive_in_the_order_the_agent_took_them_then_the_result(client):
    events = stream(client, "why did my food spend change in February")
    kinds = [k for k, _ in events]
    assert kinds[-1] == "result" and kinds.count("result") == 1
    assert set(kinds[:-1]) == {"step"}
    stages = [d["stage"] for k, d in events if k == "step"]
    assert stages[0] == "start"
    assert stages.index("understand") < stages.index("plan") < stages.index("act")
    assert stages.index("act") < stages.index("answer") < stages.index("verified")
    # time only moves forward
    marks = [d["ms"] for k, d in events if k == "step"]
    assert marks == sorted(marks)


def test_each_tool_result_is_a_step_with_its_own_figures(client):
    events = stream(client, "why did my food spend change in February")
    tools = [d for k, d in events if k == "step" and d["stage"] == "act"]
    assert [t["tool"] for t in tools] == ["aggregate_spend_by_category", "explain_change"]
    assert all(t["ok"] for t in tools) and all(t["data"] for t in tools)
    plan = next(d for k, d in events if k == "step" and d["stage"] == "plan")
    assert [s["tool_name"] for s in plan["steps"]] == [t["tool"] for t in tools]


def test_the_streamed_result_is_exactly_what_the_plain_ask_returns(client):
    text = "why did my food spend change in February"
    streamed = stream(client, text)[-1][1]
    plain = client.post("/api/ask", json={"text": text}, headers=AUTH).json()
    for key in ("intent", "plan", "status", "stop_reason", "refusal_reason", "question"):
        assert streamed[key] == plain[key]
    assert streamed["answer"]["headline"] == plain["answer"]["headline"]
    assert streamed["answer"]["facts"] == plain["answer"]["facts"]
    verified = next(d for k, d in streamed_steps(text, client) if d["stage"] == "verified")
    assert verified["title"].startswith(f"Checked {len(plain['answer']['facts'])} figure")


def streamed_steps(text: str, client: TestClient):
    return [(k, d) for k, d in stream(client, text) if k == "step"]


def test_a_refusal_stops_at_the_gate_with_no_plan_and_no_tool(client):
    events = stream(client, "transfer 5000 to rahul")
    stages = [d["stage"] for k, d in events if k == "step"]
    assert "plan" not in stages and "act" not in stages and "answer" not in stages
    gate = next(d for k, d in events if k == "step" and d["stage"] == "understand")
    assert gate["tone"] == "stop"
    result = events[-1][1]
    assert result["refusal_reason"] and result["plan"] == [] and result["answer"] is None


def test_the_stream_needs_the_token_and_a_question(client):
    assert client.post("/api/ask/stream", json={"text": "hi"}).status_code == 401
    assert client.post("/api/ask/stream", json={"text": ""}, headers=AUTH).status_code == 422
