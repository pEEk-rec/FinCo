"""
The model reads a question first; the rules guard its answer and are the fallback
(PLAN_PHASE4 section 0.8). Every model reply here is scripted: no network, no keys.
"""

import json

import pytest

from copilot.core import intent as intent_module
from copilot.core.intent import create_agent_task
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.llm.client import FakeLLMClient
from copilot.llm.routing.config import load_router_config
from copilot.models.domain import Account, Category, User

T0 = "2026-01-01T00:00:00Z"
USER = "user_alice"
PARAPHRASE = "can you set me up with a challenge to eat out less"


def _reply(intent_type, **extra):
    return json.dumps({"intent_type": intent_type, **extra})


@pytest.fixture(autouse=True)
def _model_first(monkeypatch):
    monkeypatch.setenv("FINCO_LLM_PRIMARY", "1")
    intent_module._INTENT_CACHE.clear()
    yield
    intent_module._INTENT_CACHE.clear()


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(c, Account(id="acc", user_id=USER, name="M", created_at=T0))
    insert_category(c, Category(id="food", user_id=USER, name="Dining", created_at=T0))
    return c


def _ask(conn, text, client):
    return create_agent_task(conn, USER, text, llm_client=client, clock="2026-09-01T10:00:00+05:30")


def test_the_model_reads_a_paraphrase_the_rules_cannot(conn):
    client = FakeLLMClient([_reply("start_experiment", category_name="Dining")])
    task = _ask(conn, PARAPHRASE, client)
    assert task.intent.type == "start_experiment" and task.intent.source == "llm"
    assert task.intent.category_id == "food"
    assert len(client.prompts) == 1


def test_the_model_can_name_every_intent_not_just_the_first_eleven(conn):
    client = FakeLLMClient([_reply("progress_summary")])
    _ask(conn, "how am I doing overall with my habits and rewards", client)
    prompt = client.prompts[0]
    for name in ("start_experiment", "experiment_status", "what_worked", "challenge_suggestions",
                 "progress_summary", "affordability", "trip_planning"):
        assert name in prompt


def test_a_category_the_user_does_not_have_is_dropped_not_trusted(conn):
    client = FakeLLMClient([_reply("start_experiment", category_name="Offshore Yachts")])
    task = _ask(conn, PARAPHRASE, client)
    assert task.intent.type == "start_experiment" and task.intent.category_id is None


def test_an_invalid_reply_falls_back_to_the_rules(conn):
    client = FakeLLMClient(["not json at all"] * 4)
    task = _ask(conn, "what is my progress summary", client)
    assert task.intent.type == "progress_summary" and task.intent.source != "llm"


def test_an_intent_the_model_invents_is_rejected(conn):
    client = FakeLLMClient([_reply("wire_money_abroad")] * 4)
    task = _ask(conn, "what is my progress summary", client)
    assert task.intent.type == "progress_summary" and task.intent.source != "llm"


def test_the_same_question_is_answered_from_the_cache(conn):
    client = FakeLLMClient([_reply("start_experiment")])  # only one scripted reply
    first = _ask(conn, PARAPHRASE, client)
    second = _ask(conn, PARAPHRASE, client)
    assert first.intent.type == second.intent.type == "start_experiment"
    assert len(client.prompts) == 1, "the second identical question must not reach the model"


def test_the_refusal_gate_runs_before_any_model_call(conn):
    client = FakeLLMClient([_reply("summarize_period")])
    task = _ask(conn, "transfer 5000 to rahul", client)
    assert task.status == "refused"
    assert client.prompts == []


def test_with_the_switch_off_the_rules_decide_and_the_model_is_not_asked(conn, monkeypatch):
    monkeypatch.setenv("FINCO_LLM_PRIMARY", "0")
    client = FakeLLMClient([_reply("forecast")])
    task = _ask(conn, "what is my progress summary", client)
    assert task.intent.type == "progress_summary"
    assert client.prompts == []


def test_without_a_model_the_rules_still_work(conn):
    task = _ask(conn, "what is my progress summary", None)
    assert task.intent.type == "progress_summary"


def test_the_context_builders_purposes_map_to_router_tasks():
    config = load_router_config()
    assert config.policy("intent_extraction") == config.policy("intent")
    assert config.policy("critique") == config.policy("planning")
    assert config.policy("decomposition") == config.policy("planning")
    assert config.policy("something_unknown") == config.policy("general")


def test_a_model_outage_falls_back_to_the_rules_instead_of_failing(conn):
    from copilot.core.errors import ErrorCode, ToolFailure

    class Down:
        def complete(self, prompt, **options):
            raise ToolFailure(ErrorCode.TOOL_FAILURE, "Language model unavailable.", retryable=True)

    task = _ask(conn, "what is my progress summary", Down())
    assert task.intent.type == "progress_summary" and task.intent.source != "llm"


def test_the_glossary_describes_every_intent_the_model_may_choose():
    from typing import get_args

    from copilot.core.intent import _intent_glossary_text
    from copilot.models.agentic import IntentType

    text = _intent_glossary_text()
    for name in get_args(IntentType):
        assert f"- {name}: " in text, f"{name} has no description in config/intent_glossary.yaml"
