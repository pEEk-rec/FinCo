from typing import Literal

import pytest
from pydantic import BaseModel, Field

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm.client import (
    FakeLLMClient,
    StructuredOutputError,
    extract_json,
    structured_call,
)


class Intent(BaseModel):
    intent: Literal["balance", "budget", "unknown"]
    confidence: float = Field(ge=0, le=0.7)


VALID = '{"intent": "balance", "confidence": 0.6}'


def test_valid_json_passes_first_time():
    client = FakeLLMClient([VALID])
    result = structured_call(client, "Classify: what's my balance?", Intent)
    assert result == Intent(intent="balance", confidence=0.6)
    assert len(client.prompts) == 1
    assert "what's my balance?" in client.prompts[0]
    assert '"intent"' in client.prompts[0]  # schema included


def test_invalid_then_valid_succeeds_on_retry():
    client = FakeLLMClient(["Sure! The intent is balance.", VALID])
    assert structured_call(client, "Classify", Intent).intent == "balance"
    assert len(client.prompts) == 2
    assert "Your last output was invalid because" in client.prompts[1]
    assert "Classify" in client.prompts[1]  # the retry repeats the task


def test_schema_violation_is_retried():
    client = FakeLLMClient(['{"intent": "balance", "confidence": 0.95}', VALID])
    assert structured_call(client, "Classify", Intent).confidence == 0.6
    assert "less than or equal to 0.7" in client.prompts[1]


@pytest.mark.parametrize("max_retries", [0, 1, 2, 5])
def test_always_invalid_raises_after_exactly_max_retries_plus_one(max_retries):
    client = FakeLLMClient(["not json"] * 10)
    with pytest.raises(StructuredOutputError) as info:
        structured_call(client, "Classify", Intent, max_retries=max_retries)
    assert len(client.prompts) == max_retries + 1
    assert info.value.attempts == max_retries + 1
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert isinstance(info.value, ToolFailure)


def test_fenced_json_is_accepted():
    client = FakeLLMClient([f"```json\n{VALID}\n```"])
    assert structured_call(client, "Classify", Intent).intent == "balance"


@pytest.mark.parametrize(
    "text, expected",
    [(VALID, VALID), (f"  {VALID}\n", VALID), (f"```\n{VALID}\n```", VALID)],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


def test_client_failure_becomes_typed_error_without_retry():
    class Broken:
        calls = 0

        def complete(self, prompt, **options):
            Broken.calls += 1
            raise ConnectionError("provider down")

    with pytest.raises(ToolFailure) as info:
        structured_call(Broken(), "Classify", Intent)
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert info.value.error.retryable is True
    assert Broken.calls == 1


class Nested(BaseModel):
    amount_paise: int


class Sneaky(BaseModel):
    items: list[Nested]


@pytest.mark.parametrize("model", [Nested, Sneaky])
def test_money_fields_are_refused(model):
    client = FakeLLMClient([])
    with pytest.raises(ValueError, match="money fields"):
        structured_call(client, "Guess the amount", model)
    assert client.prompts == []  # refused before any call


def test_negative_retries_rejected():
    with pytest.raises(ValueError):
        structured_call(FakeLLMClient([]), "x", Intent, max_retries=-1)


def test_fake_client_exhaustion_is_loud():
    client = FakeLLMClient([])
    with pytest.raises(RuntimeError, match="no scripted replies"):
        client.complete("hi")
