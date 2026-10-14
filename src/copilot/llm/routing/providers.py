"""
Provider adapters for Groq and Gemini: build a request, parse the reply, classify failures.

HTTP goes through a `Transport` function so tests can simulate rate limits, outages and slow
models without a network.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from copilot.llm.routing.config import Candidate, TaskPolicy
from copilot.llm.routing.slots import parse_duration

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
USER_AGENT = "finco/1.0"

Failure = Literal[
    "rate_limited",  # 429: this key is spent for now
    "auth",  # 401/403: this key is invalid
    "model_gone",  # 404: this model is not served any more
    "bad_request",  # 400/422: this model or prompt combination does not work
    "server",  # 5xx: provider overloaded
    "timeout",  # no answer in time
    "network",  # connection problem
    "truncated",  # reply cut off at the token limit
    "blocked",  # safety filter
    "empty",  # no text in the reply
]


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], bytes, float], HttpResponse]


def urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> HttpResponse:
    """The real network call. Timeouts and connection errors surface as Python exceptions."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


@dataclass
class Reply:
    """A successful completion."""

    text: str
    tokens: int | None
    remaining_tokens: int | None = None
    reset_tokens_s: float | None = None


@dataclass
class CallError(Exception):
    """A classified failure of one call."""

    kind: Failure
    message: str = ""
    retry_after_s: float | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


def estimate_tokens(prompt: str, max_tokens: int) -> int:
    """Cheap token estimate for budgeting: prompt at 4 characters per token plus the reply."""
    return len(prompt) // 4 + int(max_tokens * 0.6) + 20


def _classify(status: int, headers: dict[str, str], body: bytes) -> CallError:
    snippet = body[:160].decode("utf-8", "replace").replace("\n", " ")
    retry_after = parse_duration(headers.get("retry-after"))
    if status == 429:
        return CallError("rate_limited", snippet, retry_after, headers)
    if status in (401, 403):
        return CallError("auth", snippet, None, headers)
    if status == 404:
        return CallError("model_gone", snippet, None, headers)
    if status in (400, 422):
        return CallError("bad_request", snippet, None, headers)
    return CallError("server", f"HTTP {status} {snippet}", retry_after, headers)


def build_request(
    candidate: Candidate, key: str, prompt: str, policy: TaskPolicy
) -> tuple[str, dict[str, str], bytes]:
    """URL, headers and JSON body for one completion."""
    if candidate.provider == "groq":
        messages = []
        if policy.json_mode:
            messages.append({"role": "system", "content": "Reply with a single JSON object only."})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": candidate.model,
            "messages": messages,
            "temperature": policy.temperature,
            "max_tokens": policy.max_tokens,
        }
        if policy.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        return GROQ_URL, headers, json.dumps(payload).encode("utf-8")

    config: dict[str, Any] = {
        "temperature": policy.temperature,
        "maxOutputTokens": policy.max_tokens,
    }
    if policy.json_mode:
        config["responseMimeType"] = "application/json"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": USER_AGENT}
    return GEMINI_URL.format(model=candidate.model), headers, json.dumps(payload).encode("utf-8")


def parse_response(candidate: Candidate, response: HttpResponse) -> Reply:
    """Turn a 200 response into a Reply, or raise a classified CallError."""
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CallError("empty", f"unreadable reply ({type(exc).__name__})") from exc

    if candidate.provider == "groq":
        choices = data.get("choices") or []
        if not choices:
            raise CallError("empty", "no choices")
        choice = choices[0]
        text = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "length":
            raise CallError("truncated", "reply hit the token limit")
        if not text.strip():
            raise CallError("empty", "empty reply")
        h = response.headers
        remaining = h.get("x-ratelimit-remaining-tokens")
        return Reply(
            text=text,
            tokens=(data.get("usage") or {}).get("total_tokens"),
            remaining_tokens=int(remaining) if remaining and remaining.isdigit() else None,
            reset_tokens_s=parse_duration(h.get("x-ratelimit-reset-tokens")),
        )

    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise CallError("blocked" if reason else "empty", reason or "no candidates")
    first = candidates[0]
    finish = first.get("finishReason")
    if finish == "SAFETY":
        raise CallError("blocked", "safety filter")
    parts = (first.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if finish == "MAX_TOKENS":
        raise CallError("truncated", "reply hit the token limit")
    if not text.strip():
        raise CallError("empty", "empty reply")
    return Reply(text=text, tokens=(data.get("usageMetadata") or {}).get("totalTokenCount"))


def call(
    transport: Transport,
    candidate: Candidate,
    key: str,
    prompt: str,
    policy: TaskPolicy,
    timeout_s: float,
) -> Reply:
    """One completion. Returns a Reply or raises CallError (never leaks the key)."""
    url, headers, body = build_request(candidate, key, prompt, policy)
    try:
        response = transport(url, headers, body, timeout_s)
    except TimeoutError as exc:
        raise CallError("timeout", f"no reply within {timeout_s:.0f}s") from exc
    except OSError as exc:
        text = str(exc)
        kind: Failure = "timeout" if "timed out" in text else "network"
        raise CallError(kind, type(exc).__name__) from exc
    if response.status != 200:
        raise _classify(response.status, response.headers, response.body)
    return parse_response(candidate, response)
