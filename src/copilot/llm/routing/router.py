"""
The model router: serves each agentic task from a pool of keys and models, adaptively.

It is a small agent of its own, and each call goes round the same loop:

  observe  quota left on every key, success rate and latency of every model, cooldowns
  decide   score every (model, key) allowed for this task and pick the best one
  act      reserve the quota first, then call, with a deadline
  reflect  classify the outcome; if the reply fails validation, escalate to another model and
           tell it what was wrong
  learn    update key state and model health, so the next decision is better

What that buys:
  * quota is booked before every call, so keys are paced under their per-minute, per-token and
    per-day limits instead of being driven into 429s (and a real 429 is honoured: that key rests
    for exactly as long as the provider asked);
  * a rejected key is retired, a retired model is dropped for hours, an overloaded model backs
    off, and each comes back when it recovers;
  * a task's candidate list is only a prior: live health reorders it.
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm.client import extract_json
from copilot.llm.routing.config import (
    DEFAULT_CONFIG,
    Candidate,
    RouterConfig,
    TaskPolicy,
    load_router_config,
)
from copilot.llm.routing.providers import (
    CallError,
    Transport,
    call,
    estimate_tokens,
    urllib_transport,
)
from copilot.llm.routing.slots import KeySlot, ModelHealth

log = logging.getLogger("copilot.llm.router")
ModelT = TypeVar("ModelT", bound=BaseModel)

MAX_ATTEMPTS = 8
QUICK_WAIT_S = 2.5  # first pass: only consider keys that are free within this long
MIN_CALL_S = 1.0  # do not start a call with less than this left before the deadline


class LLMUnavailable(ToolFailure):
    """No model could serve the task in time. Callers fall back to deterministic code."""

    def __init__(self, task: str, summary: str) -> None:
        super().__init__(
            ErrorCode.TOOL_FAILURE, f"No model could serve '{task}': {summary}", retryable=True
        )


class Clock:
    """Time source; tests replace it so rate-limit behaviour can be checked without waiting."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


@dataclass
class Attempt:
    """One call made while serving a request (for observability and tests)."""

    provider: str
    model: str
    key: str
    outcome: str
    latency_ms: int


@dataclass
class RouteResult:
    """A served request and how it was served."""

    text: str
    task: str
    provider: str
    model: str
    key: str
    latency_ms: int
    attempts: list[Attempt] = field(default_factory=list)
    escalations: int = 0


@dataclass
class TaskStats:
    calls: int = 0
    ok: int = 0
    failed: int = 0
    failovers: int = 0
    escalations: int = 0


class LLMRouter:
    """Implements the `LLMClient` protocol: `complete(prompt, task=...)`."""

    def __init__(
        self,
        config: RouterConfig,
        keys: dict[str, list[str]],
        transport: Transport = urllib_transport,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.clock = clock or Clock()
        self.slots: dict[str, list[KeySlot]] = {
            provider: [
                KeySlot(provider, key, config.providers[provider])  # type: ignore[index]
                for key in dict.fromkeys(k for k in provider_keys if k)
            ]
            for provider, provider_keys in keys.items()
            if provider in config.providers
        }
        self.health: dict[tuple[str, str], ModelHealth] = {}
        for policy in config.tasks.values():
            for c in policy.candidates:
                self.health.setdefault((c.provider, c.model), ModelHealth(c.provider, c.model))
        self.stats: dict[str, TaskStats] = {}
        self._lock = threading.Lock()

    # -- construction ---------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        config_path: Path | None = None,
        env_path: Path | None = None,
        transport: Transport = urllib_transport,
    ) -> "LLMRouter":
        """Build from config/llm_router.yaml and keys in `.env` or the environment."""
        env = read_env(env_path)
        return cls(load_router_config(config_path or DEFAULT_CONFIG), keys_from_env(env), transport)

    def available(self) -> bool:
        """True when at least one key could still serve a call."""
        return any(not s.dead for slots in self.slots.values() for s in slots)

    # -- the loop -------------------------------------------------------------------------

    def route(
        self,
        task: str,
        prompt: str,
        validate: Callable[[str], str | None] | None = None,
    ) -> RouteResult:
        """
        Serve one request. `validate(text)` returns None if the reply is acceptable, or a short
        description of what is wrong; in that case the next-best model is asked, with that
        description appended.
        """
        policy = self.config.policy(task)
        stats = self.stats.setdefault(task, TaskStats())
        with self._lock:
            stats.calls += 1
        start = self.clock.now()
        deadline = start + policy.deadline_s
        excluded: set[tuple[str, str]] = set()
        attempts: list[Attempt] = []
        escalations = 0
        current_prompt = prompt
        failovers = 0

        while len(attempts) < MAX_ATTEMPTS:
            now = self.clock.now()
            est = estimate_tokens(current_prompt, policy.max_tokens)
            choice = self._decide(policy, est, excluded, now, deadline)
            if choice is None:
                break
            candidate, slot, wait = choice
            if wait > 0:
                self.clock.sleep(wait)
            now = self.clock.now()
            timeout = min(slot.limits.timeout_s, deadline - now)
            if timeout < MIN_CALL_S:
                break

            slot.reserve(now, est)
            began = self.clock.now()
            health = self.health[(candidate.provider, candidate.model)]
            try:
                reply = call(self.transport, candidate, slot.key, current_prompt, policy, timeout)
            except CallError as err:
                latency = int((self.clock.now() - began) * 1000)
                attempts.append(
                    Attempt(candidate.provider, candidate.model, slot.fp, err.kind, latency)
                )
                self._learn_failure(candidate, slot, health, err, excluded)
                failovers += 1
                continue

            latency = int((self.clock.now() - began) * 1000)
            slot.settle(now, est, reply.tokens)
            slot.on_success(self.clock.now(), reply.remaining_tokens, reply.reset_tokens_s)
            problem = validate(reply.text) if validate else None
            if problem:
                attempts.append(
                    Attempt(candidate.provider, candidate.model, slot.fp, "invalid", latency)
                )
                health.failure(self.clock.now(), f"invalid reply: {problem[:80]}")
                health.escalations += 1
                excluded.add((candidate.provider, candidate.model))
                escalations += 1
                current_prompt = (
                    f"{prompt}\n\nYour previous reply was rejected: {problem[:300]}\n"
                    "Reply again, fixing exactly that."
                )
                continue

            attempts.append(Attempt(candidate.provider, candidate.model, slot.fp, "ok", latency))
            health.success(latency)
            with self._lock:
                stats.ok += 1
                stats.failovers += failovers
                stats.escalations += escalations
            return RouteResult(
                reply.text,
                task,
                candidate.provider,
                candidate.model,
                slot.fp,
                latency,
                attempts,
                escalations,
            )

        with self._lock:
            stats.failed += 1
            stats.failovers += failovers
            stats.escalations += escalations
        summary = (
            ", ".join(f"{a.model} {a.outcome}" for a in attempts[-4:]) or "no key was free in time"
        )
        log.warning("LLM task '%s' unserved (%s)", task, summary)
        raise LLMUnavailable(task, summary)

    def _decide(
        self,
        policy: TaskPolicy,
        est_tokens: int,
        excluded: set[tuple[str, str]],
        now: float,
        deadline: float,
    ) -> tuple[Candidate, KeySlot, float] | None:
        """Pick the best (model, key) for this call, or None if nothing can serve in time."""
        remaining = deadline - now - MIN_CALL_S
        for max_wait in (QUICK_WAIT_S, min(policy.max_wait_s, remaining)):
            if max_wait < 0:
                return None
            best: tuple[float, int, Candidate, KeySlot, float] | None = None
            for rank, cand in enumerate(policy.candidates):
                health = self.health[(cand.provider, cand.model)]
                if (cand.provider, cand.model) in excluded or not health.available(now):
                    continue
                for slot in self.slots.get(cand.provider, []):
                    delay = slot.delay_for(now, est_tokens)
                    if delay is None or delay > max_wait:
                        continue
                    score = (
                        (len(policy.candidates) - rank)  # the configured preference
                        + 3.0 * health.p_ok()  # reliability
                        - 0.6 * (health.ewma_ms / 1000.0)  # speed
                        - 2.5 * slot.load(now)  # quota headroom
                        - 1.0 * delay  # waiting
                    )
                    key = (score, -slot.calls)  # ties go to the least-used key
                    if best is None or key > (best[0], best[1]):
                        best = (score, -slot.calls, cand, slot, delay)
            if best is not None:
                return best[2], best[3], best[4]
        return None

    def _learn_failure(
        self,
        candidate: Candidate,
        slot: KeySlot,
        health: ModelHealth,
        err: CallError,
        excluded: set[tuple[str, str]],
    ) -> None:
        """Update key and model state after a failed call."""
        now = self.clock.now()
        pair = (candidate.provider, candidate.model)
        if err.kind == "rate_limited":
            slot.on_rate_limited(now, err.retry_after_s)  # another key may still serve this model
        elif err.kind == "auth":
            slot.on_auth_error()
            log.warning("%s key %s was rejected and is retired", slot.provider, slot.fp)
        elif err.kind == "model_gone":
            health.failure(now, f"model not served: {err.message[:80]}", retired=True)
            excluded.add(pair)
            log.warning(
                "%s model %s is no longer served; dropped", candidate.provider, candidate.model
            )
        elif err.kind in {"server", "timeout", "network"}:
            slot.on_error(now, err.kind)
            health.failure(now, f"{err.kind}: {err.message[:80]}")
            excluded.add(pair)
        else:  # bad_request, truncated, blocked, empty: this model cannot do this request
            health.failure(now, f"{err.kind}: {err.message[:120]}")
            health.escalations += 1
            excluded.add(pair)

    # -- LLMClient protocol ---------------------------------------------------------------

    def complete(self, prompt: str, **options: Any) -> str:
        """`LLMClient.complete`: pass `task="planning"` (or `purpose=`) to choose the policy."""
        task = options.get("task") or options.get("purpose") or "general"
        task = str(getattr(task, "value", task)).lower()
        return self.route(task, prompt).text

    def structured(self, task: str, prompt: str, model: type[ModelT]) -> tuple[ModelT, RouteResult]:
        """
        A validated object from the best model that can produce one. Invalid replies escalate
        to the next model with the validation error attached.
        """
        parsed: dict[str, ModelT] = {}

        def check(text: str) -> str | None:
            try:
                parsed["value"] = model.model_validate_json(extract_json(text))
                return None
            except (ValidationError, ValueError) as exc:
                return str(exc).replace("\n", " ")[:300]

        result = self.route(task, prompt, validate=check)
        return parsed["value"], result

    # -- observability --------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Status for the UI. Contains no key material, only fingerprints."""
        now = self.clock.now()
        providers: dict[str, Any] = {}
        for name, slots in self.slots.items():
            keys = []
            for s in slots:
                reqs, toks, day = s.usage(now)
                keys.append(
                    {
                        "id": s.fp,
                        "state": s.state(now),
                        "calls": s.calls,
                        "errors": s.errors,
                        "rate_limited": s.rate_limited,
                        "minute_requests": reqs,
                        "minute_tokens": toks,
                        "day_requests": day,
                        "load_pct": int(s.load(now) * 100),
                        "last_error": s.last_error,
                    }
                )
            providers[name] = {"keys": keys}
        models = []
        for (provider, model), h in sorted(self.health.items()):
            models.append(
                {
                    "provider": provider,
                    "model": model,
                    "ok": h.ok,
                    "failed": h.failed,
                    "avg_ms": int(h.ewma_ms),
                    "escalations": h.escalations,
                    "state": "ready" if h.available(now) else "paused",
                    "last_error": h.last_error,
                }
            )
        tasks = {
            name: {
                "calls": s.calls,
                "ok": s.ok,
                "failed": s.failed,
                "failovers": s.failovers,
                "escalations": s.escalations,
            }
            for name, s in sorted(self.stats.items())
        }
        all_slots = [s for slots in self.slots.values() for s in slots]
        return {
            "providers": providers,
            "models": models,
            "tasks": tasks,
            "routes": {
                name: [f"{c.provider}:{c.model}" for c in p.candidates]
                for name, p in self.config.tasks.items()
            },
            "totals": {
                "keys": len(all_slots),
                "keys_ready": sum(1 for s in all_slots if s.state(now) == "ready"),
                "keys_rejected": sum(1 for s in all_slots if s.dead),
                "calls": sum(s.calls for s in all_slots),
                "rate_limited": sum(s.rate_limited for s in all_slots),
            },
        }


# ---------------------------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------------------------


def read_env(env_path: Path | None = None) -> dict[str, str]:
    """Settings from `.env` (if present) overlaid by real environment variables."""
    path = env_path or Path(__file__).resolve().parents[4] / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip("\"'")
    values.update({k: v for k, v in os.environ.items() if k.startswith(("GEMINI", "GROQ"))})
    return values


def _split(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def keys_from_env(env: dict[str, str]) -> dict[str, list[str]]:
    """Provider -> API keys. Accepts plural lists, singular keys and legacy per-purpose keys."""
    gemini = _split(env.get("GEMINI_API_KEYS")) + _split(env.get("GEMINI_API_KEY"))
    gemini += [v for k, v in env.items() if k.startswith("GEMINI_KEY_") and v]
    groq = _split(env.get("GROQ_API_KEYS")) + _split(env.get("GROQ_API_KEY"))
    return {
        "groq": list(dict.fromkeys(groq)),
        "gemini": list(dict.fromkeys(gemini)),
    }
