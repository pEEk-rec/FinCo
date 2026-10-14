"""
Language-model access for the API: optional, redacted, time-boxed.

The model is never required. If no key is configured, `FINCO_LLM=off` is set, or the model
is slow or failing, every caller falls back to its deterministic path. Three protections:

* every prompt is PII-redacted (UPI ids, account numbers, phones, OTP/PIN patterns);
* each call has a hard deadline and each Ask has a total budget, so the screen never hangs;
* after a failure a circuit breaker switches the model off for a while, so one bad model name
  or outage costs one wait, not one wait per question.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm.client import LLMClient
from copilot.llm.redactor import RedactingLLMClient
from copilot.llm.routing import LLMRouter

log = logging.getLogger("copilot.api.llm")

CALL_DEADLINE_S = 24.0  # one model call, including failover between models and keys
REQUEST_BUDGET_S = 50.0  # all model calls for one Ask
BREAKER_AFTER = 3  # consecutive failures before the guard pauses the model
BREAKER_SECONDS = 60.0  # how long it stays paused


@dataclass
class GuardedLLM:
    """An LLMClient that enforces deadlines and trips a breaker on failure."""

    inner: LLMClient
    model: str
    calls: int = 0
    failures: int = 0
    consecutive: int = 0
    router: LLMRouter | None = None
    _off_until: float = 0.0
    _budget_until: float = field(default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def available(self) -> bool:
        """False while the breaker is open."""
        return time.monotonic() >= self._off_until

    def begin_request(self, seconds: float = REQUEST_BUDGET_S) -> None:
        """Start the time budget for one Ask (or a longer one for a bulk import)."""
        self._budget_until = time.monotonic() + seconds

    def complete(self, prompt: str, **options: Any) -> str:
        """Run one completion within the deadline, or raise a retryable ToolFailure."""
        now = time.monotonic()
        if now < self._off_until:
            raise ToolFailure(ErrorCode.TOOL_FAILURE, "Language model is paused.", retryable=True)
        remaining = (self._budget_until or now + REQUEST_BUDGET_S) - now
        if remaining <= 1.0:
            raise ToolFailure(ErrorCode.TOOL_FAILURE, "Language model budget used.", retryable=True)
        deadline = min(CALL_DEADLINE_S, remaining)

        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["text"] = self.inner.complete(prompt, **options)
            except Exception as exc:  # noqa: BLE001 - reported to the caller below
                box["error"] = exc

        worker = threading.Thread(target=work, daemon=True)
        with self._lock:
            self.calls += 1
        worker.start()
        worker.join(deadline)
        if worker.is_alive() or "error" in box or "text" not in box:
            with self._lock:
                self.failures += 1
                self.consecutive += 1
                if self.consecutive >= BREAKER_AFTER:
                    self._off_until = time.monotonic() + BREAKER_SECONDS
            why = "timed out" if worker.is_alive() else type(box.get("error")).__name__
            log.warning("LLM call failed (%s); %d in a row", why, self.consecutive)
            raise ToolFailure(ErrorCode.TOOL_FAILURE, f"Language model {why}.", retryable=True)
        with self._lock:
            self.consecutive = 0
        return str(box["text"])

    def status(self) -> dict[str, Any] | None:
        """The router's live status (no key material), or None if there is no router."""
        return self.router.snapshot() if self.router is not None else None


def build_llm(env_path: Path | None = None) -> GuardedLLM | None:
    """
    Build the guarded, redacting client over the multi-provider router, or None.

    None when FINCO_LLM=off, or when no Groq or Gemini key is configured.
    """
    if os.environ.get("FINCO_LLM", "auto").lower() in {"off", "0", "false", "no"}:
        return None
    try:
        router = LLMRouter.from_env(env_path=env_path)
    except Exception as exc:  # noqa: BLE001 - a broken config must not break the app
        log.warning("LLM disabled: could not build the router (%s)", type(exc).__name__)
        return None
    if not router.available():
        return None
    return GuardedLLM(inner=RedactingLLMClient(router), model="router", router=router)
