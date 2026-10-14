"""
Key slots and model health: the router's memory of what is safe to call right now.

A KeySlot never lets its key exceed the configured per-minute request and token budgets, or
the daily request budget: `delay_for` says how long a call must wait (or None if it cannot be
served today), and `reserve` books the usage before the call is made. Provider response
headers (Groq reports remaining tokens and requests) correct the local estimate, so the
router follows the provider's truth, not just its own bookkeeping.

Keys are never stored in snapshots or logs: only a short hash fingerprint is shown.
"""

import hashlib
import re
import threading
from collections import deque
from dataclasses import dataclass, field

from copilot.llm.routing.config import ProviderLimits

WINDOW_S = 60.0
DAY_S = 86400.0


def fingerprint(key: str) -> str:
    """Six hex characters identifying a key without revealing it."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]


_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?"
)


def parse_duration(text: str | None) -> float | None:
    """'1m26.4s' -> 86.4, '2.76s' -> 2.76, '350ms' -> 0.35, '30' -> 30.0. None if unparseable."""
    if not text:
        return None
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    m = _DURATION.fullmatch(text)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = m.groups()
    return float(h or 0) * 3600 + float(mi or 0) * 60 + float(s or 0) + float(ms or 0) / 1000


@dataclass
class KeySlot:
    """One API key with its quota state. All methods are thread-safe."""

    provider: str
    key: str
    limits: ProviderLimits
    fp: str = field(init=False)
    dead: bool = False
    cooldown_until: float = 0.0
    blocked_tokens_until: float = 0.0
    calls: int = 0
    errors: int = 0
    rate_limited: int = 0
    consecutive_errors: int = 0
    last_error: str = ""
    _requests: deque[float] = field(default_factory=deque)
    _tokens: deque[tuple[float, int]] = field(default_factory=deque)
    _day_requests: deque[float] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.fp = fingerprint(self.key)

    # -- budget -------------------------------------------------------------------------------

    def _trim(self, now: float) -> None:
        while self._requests and now - self._requests[0] >= WINDOW_S:
            self._requests.popleft()
        while self._tokens and now - self._tokens[0][0] >= WINDOW_S:
            self._tokens.popleft()
        while self._day_requests and now - self._day_requests[0] >= DAY_S:
            self._day_requests.popleft()

    def _delay(self, now: float, est_tokens: int) -> float | None:
        """Seconds until a call of `est_tokens` fits every budget; None if not today."""
        self._trim(now)
        if self.dead:
            return None
        delays = [max(0.0, self.cooldown_until - now), max(0.0, self.blocked_tokens_until - now)]
        rpd = self.limits.usable_rpd
        if rpd is not None and len(self._day_requests) >= rpd:
            return None
        if len(self._requests) >= self.limits.usable_rpm:
            delays.append(self._requests[0] + WINDOW_S - now)
        tpm = self.limits.usable_tpm
        if tpm is not None:
            if est_tokens > tpm:
                return None  # a single call larger than the whole minute can never fit
            used = sum(t for _, t in self._tokens)
            if used + est_tokens > tpm:
                need = used + est_tokens - tpm
                freed = 0
                for stamp, tokens in self._tokens:
                    freed += tokens
                    if freed >= need:
                        delays.append(stamp + WINDOW_S - now)
                        break
        return max(delays)

    def delay_for(self, now: float, est_tokens: int) -> float | None:
        """Public, locked version of `_delay`."""
        with self._lock:
            return self._delay(now, est_tokens)

    def reserve(self, now: float, est_tokens: int) -> None:
        """Book one request and its estimated tokens before calling."""
        with self._lock:
            self._trim(now)
            self._requests.append(now)
            self._day_requests.append(now)
            self._tokens.append((now, est_tokens))
            self.calls += 1

    def settle(self, now: float, est_tokens: int, actual_tokens: int | None) -> None:
        """Replace the estimate with the real token count once known."""
        if actual_tokens is None:
            return
        with self._lock:
            for i in range(len(self._tokens) - 1, -1, -1):
                stamp, tokens = self._tokens[i]
                if tokens == est_tokens:
                    self._tokens[i] = (stamp, actual_tokens)
                    break

    def usage(self, now: float) -> tuple[int, int, int]:
        """(requests this minute, tokens this minute, requests today)."""
        with self._lock:
            self._trim(now)
            return len(self._requests), sum(t for _, t in self._tokens), len(self._day_requests)

    def load(self, now: float) -> float:
        """0 (idle) to 1 (at its budget): the busiest of the minute and day budgets."""
        reqs, toks, day = self.usage(now)
        parts = [reqs / self.limits.usable_rpm]
        if self.limits.usable_tpm:
            parts.append(toks / self.limits.usable_tpm)
        if self.limits.usable_rpd:
            parts.append(day / self.limits.usable_rpd)
        return min(1.0, max(parts))

    # -- outcomes -----------------------------------------------------------------------------

    def on_success(
        self, now: float, remaining_tokens: int | None = None, reset_tokens_s: float | None = None
    ) -> None:
        """A call worked. Follow the provider's own remaining-token report if it gave one."""
        with self._lock:
            self.consecutive_errors = 0
            if remaining_tokens is not None and remaining_tokens < 600 and reset_tokens_s:
                self.blocked_tokens_until = max(self.blocked_tokens_until, now + reset_tokens_s)

    def on_rate_limited(self, now: float, retry_after_s: float | None) -> None:
        """HTTP 429: stop using this key for as long as the provider asked."""
        with self._lock:
            self.rate_limited += 1
            self.errors += 1
            self.consecutive_errors += 1
            wait = (
                retry_after_s
                if retry_after_s is not None
                else 20.0 * min(4, self.consecutive_errors)
            )
            self.cooldown_until = max(self.cooldown_until, now + min(wait, 3600.0))
            self.last_error = "rate limited"

    def on_auth_error(self) -> None:
        """HTTP 401/403: the key is invalid. Retire it for this process."""
        with self._lock:
            self.dead = True
            self.errors += 1
            self.last_error = "key rejected"

    def on_error(self, now: float, reason: str) -> None:
        """A network or server error: back off briefly, longer if it keeps happening."""
        with self._lock:
            self.errors += 1
            self.consecutive_errors += 1
            self.last_error = reason
            if self.consecutive_errors >= 3:
                self.cooldown_until = max(
                    self.cooldown_until, now + min(120.0, 5.0 * 2**self.consecutive_errors)
                )

    def state(self, now: float) -> str:
        if self.dead:
            return "rejected"
        if now < self.cooldown_until:
            return "cooling down"
        return "ready"


@dataclass
class ModelHealth:
    """What the router has learned about one (provider, model) pair."""

    provider: str
    model: str
    ok: int = 0
    failed: int = 0
    ewma_ms: float = 0.0
    consecutive_failures: int = 0
    unavailable_until: float = 0.0
    escalations: int = 0
    last_error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def p_ok(self) -> float:
        """Success rate with a mild optimistic prior, so new models get tried."""
        return (self.ok + 4.0) / (self.ok + self.failed + 5.0)

    def available(self, now: float) -> bool:
        return now >= self.unavailable_until

    def success(self, latency_ms: float) -> None:
        with self._lock:
            self.ok += 1
            self.consecutive_failures = 0
            self.ewma_ms = (
                latency_ms if self.ewma_ms == 0 else 0.7 * self.ewma_ms + 0.3 * latency_ms
            )

    def failure(self, now: float, reason: str, *, retired: bool = False) -> None:
        """A model-level failure: 404 retires it for hours; repeated 5xx/timeouts back off."""
        with self._lock:
            self.failed += 1
            self.consecutive_failures += 1
            self.last_error = reason
            if retired:
                self.unavailable_until = now + 6 * 3600.0
            elif self.consecutive_failures >= 2:
                self.unavailable_until = max(
                    self.unavailable_until,
                    now + min(300.0, 10.0 * 2 ** (self.consecutive_failures - 1)),
                )

    def latency_s(self) -> float:
        return self.ewma_ms / 1000.0
