"""
Gemini API provider for the LLM client.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm.client import LLMClient


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, requests_per_minute: float) -> None:
        self.rpm = requests_per_minute
        self.tokens = 1.0
        self.last_update = time.monotonic()

    def acquire(self) -> None:
        if self.rpm <= 0:
            return

        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(1.0, self.tokens + elapsed * (self.rpm / 60.0))
        self.last_update = now

        if self.tokens < 1.0:
            sleep_time = (1.0 - self.tokens) * (60.0 / self.rpm)
            time.sleep(sleep_time)
            self.tokens = 0.0
            self.last_update = time.monotonic()
        else:
            self.tokens -= 1.0


class GeminiProvider(LLMClient):
    """Google Gemini provider via REST API."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", rpm: float = 15.0) -> None:
        self.api_key = api_key
        self.model = model
        self.url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )
        self.limiter = RateLimiter(rpm)
        self.logger = logging.getLogger(__name__)

    def complete(self, prompt: str, **options: Any) -> str:
        """Generate content with exponential backoff on 429/5xx."""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": options.get("temperature", 0.0),
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
        )

        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            self.limiter.acquire()
            try:
                with urllib.request.urlopen(req, timeout=30.0) as response:
                    resp_data = json.loads(response.read().decode("utf-8"))

                if "candidates" not in resp_data or not resp_data["candidates"]:
                    raise ToolFailure(ErrorCode.TOOL_FAILURE, "No candidates returned by Gemini.")

                candidate = resp_data["candidates"][0]

                # Check for finishReason safety
                if candidate.get("finishReason") == "SAFETY":
                    raise ToolFailure(ErrorCode.TOOL_FAILURE, "Response blocked by safety filters.")

                return candidate["content"]["parts"][0]["text"]

            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 503, 504) and attempt < max_retries:
                    self.logger.warning("Gemini API error %d. Retrying in %ss...", exc.code, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Quota exhaustion or fatal error
                raise ToolFailure(
                    ErrorCode.TOOL_FAILURE,
                    f"Gemini API error {exc.code}: {exc.reason}",
                    retryable=(exc.code in (429, 500, 503, 504)),
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < max_retries:
                    self.logger.warning("Network error: %s. Retrying in %ss...", exc, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ToolFailure(
                    ErrorCode.TOOL_FAILURE, f"Network error: {exc}", retryable=True
                ) from exc  # noqa: E501
