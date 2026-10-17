"""A repeated question reuses the model's plan proposal instead of paying for it again."""

import json

from copilot.llm.client import FakeLLMClient
from copilot.models.agentic import Intent
from copilot.planner import llm_planner
from copilot.planner.llm_planner import LLMPlanner

REPLY = json.dumps({"steps": []})


def _intent() -> Intent:
    return Intent(type="summarize_period", period="2026-09", year=2026, month=9)


def test_second_identical_request_makes_no_model_call():
    llm_planner._PLAN_CACHE.clear()
    client = FakeLLMClient([REPLY, REPLY])
    planner = LLMPlanner(client=client)
    state = {"raw_text": "how much on food"}
    planner.propose("t1", "u1", _intent(), state)
    first = len(client.prompts)
    planner.propose("t2", "u1", _intent(), state)
    assert first == 1 and len(client.prompts) == 1


def test_a_different_user_or_question_is_not_served_from_the_cache():
    llm_planner._PLAN_CACHE.clear()
    client = FakeLLMClient([REPLY, REPLY, REPLY])
    planner = LLMPlanner(client=client)
    planner.propose("t1", "u1", _intent(), {"raw_text": "how much on food"})
    planner.propose("t2", "u2", _intent(), {"raw_text": "how much on food"})
    planner.propose("t3", "u1", _intent(), {"raw_text": "how much on rent"})
    assert len(client.prompts) == 3
