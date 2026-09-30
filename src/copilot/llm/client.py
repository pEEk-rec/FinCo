"""
LLM access layer: the one place a model is called.

Phase 0 has no real provider: `LLMClient` is an interface and `FakeLLMClient` returns scripted
replies for tests. `structured_call` turns free text into a validated Pydantic model, retrying
with the validation error when the output is invalid.

Design principle 1 is enforced here: an output model may not contain any `*_paise` field, so
the LLM is never asked to produce money amounts. Money is computed by deterministic tools.
"""

import json
import re
from typing import Any, Protocol, TypeVar, get_args

from pydantic import BaseModel, ValidationError

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm import prompts

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
_MAX_ERROR_CHARS = 500


class LLMClient(Protocol):
    """Minimal text-in, text-out model interface."""

    def complete(self, prompt: str, **options: Any) -> str:
        """Return the model's reply to `prompt`."""
        ...


class FakeLLMClient:
    """Returns scripted replies in order and records every prompt it receives."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, **options: Any) -> str:
        """Pop the next scripted reply; raise if the script is exhausted."""
        self.prompts.append(prompt)
        if not self._replies:
            raise RuntimeError("FakeLLMClient has no scripted replies left.")
        return self._replies.pop(0)


class StructuredOutputError(ToolFailure):
    """The model never produced valid output within the allowed attempts."""

    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(
            ErrorCode.TOOL_FAILURE,
            f"LLM output invalid after {attempts} attempt(s): {last_error}",
        )
        self.attempts = attempts
        self.last_error = last_error


def _money_fields(model: type[BaseModel], prefix: str = "") -> list[str]:
    """Names of `*_paise` fields in `model`, including nested models."""
    found = []
    for name, info in model.model_fields.items():
        if name.endswith("_paise"):
            found.append(prefix + name)
        for arg in (info.annotation, *get_args(info.annotation)):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                found += _money_fields(arg, f"{prefix}{name}.")
    return found


def extract_json(text: str) -> str:
    """Return the JSON payload, unwrapping a single ```json fenced block if present."""
    match = _FENCED_JSON.match(text)
    return match.group(1) if match else text.strip()


def structured_call(
    client: LLMClient,
    prompt: str,
    output_model: type[ModelT],
    max_retries: int = 2,
    **options: Any,
) -> ModelT:
    """
    Ask for JSON matching `output_model`, validate it, and retry on invalid output.

    Makes at most `max_retries + 1` calls. Raises StructuredOutputError (TOOL_FAILURE) when
    every attempt is invalid, or ToolFailure (TOOL_FAILURE, retryable) if the client itself
    fails. Never returns unvalidated data.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    money = _money_fields(output_model)
    if money:
        raise ValueError(f"LLM output models must not contain money fields: {money}")

    schema = json.dumps(output_model.model_json_schema(), sort_keys=True)
    original = prompts.STRUCTURED_OUTPUT.format(task=prompt, schema=schema)
    current = original
    last_error = ""
    for _ in range(max_retries + 1):
        try:
            reply = client.complete(current, **options)
        except Exception as exc:  # noqa: BLE001 - provider errors become a typed failure
            raise ToolFailure(
                ErrorCode.TOOL_FAILURE, f"LLM call failed: {exc}", retryable=True
            ) from exc
        try:
            return output_model.model_validate_json(extract_json(reply))
        except ValidationError as exc:
            last_error = str(exc)[:_MAX_ERROR_CHARS]
            current = prompts.RETRY_INVALID_OUTPUT.format(original=original, error=last_error)
    raise StructuredOutputError(attempts=max_retries + 1, last_error=last_error)
