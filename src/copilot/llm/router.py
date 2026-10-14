"""
Smart Multi-Key LLM Router for Gemini API (PLAN_PHASE2).

Provides:
1. Agentic Purpose Routing (Planning, Intent Understanding, Investigation, Narration).
2. Dynamic Load Balancing and Token-Bucket Rate Limiting per key.
3. Automatic Failover and Cooldown on 429 (Rate Limit), 503 (Unavailable), or 401 (Auth errors).
4. Masked telemetry and health statistics.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.llm.client import LLMClient
from copilot.llm.gemini import RateLimiter

logger = logging.getLogger(__name__)


class LLMPurpose(StrEnum):
    """Agentic behavior categories for intelligent routing."""

    PLANNING = "planning"
    INTENT = "intent"
    INVESTIGATION = "investigation"
    NARRATION = "narration"
    GENERAL = "general"


def mask_key(key: str) -> str:
    """Mask secret API key for logging and stats display."""
    if not key or len(key) < 10:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


@dataclass
class KeySlot:
    """Tracks rate limiting, health, and cooldown state for a single API key."""

    api_key: str
    label: str = "general"
    rpm: float = 15.0
    limiter: RateLimiter = field(init=False)
    cooldown_until: float = 0.0
    consecutive_errors: int = 0
    total_calls: int = 0
    total_errors: int = 0
    is_disabled: bool = False

    def __post_init__(self) -> None:
        self.limiter = RateLimiter(self.rpm)

    @property
    def is_available(self) -> bool:
        if self.is_disabled:
            return False
        return time.monotonic() >= self.cooldown_until

    def mark_success(self) -> None:
        self.total_calls += 1
        self.consecutive_errors = 0

    def mark_cooldown(self, seconds: float = 60.0) -> None:
        self.total_errors += 1
        self.consecutive_errors += 1
        self.cooldown_until = time.monotonic() + seconds
        logger.warning(
            "API key %s placed in cooldown for %ss (consecutive errors: %d)",
            mask_key(self.api_key),
            seconds,
            self.consecutive_errors,
        )

    def mark_disabled(self, reason: str) -> None:
        self.is_disabled = True
        self.total_errors += 1
        logger.error("API key %s permanently disabled: %s", mask_key(self.api_key), reason)


class SmartLLMRouter(LLMClient):
    """
    Intelligent Multi-Key Router and Failover Provider for Google Gemini.
    """

    def __init__(
        self,
        key_pool: list[str] | None = None,
        purpose_keys: dict[LLMPurpose, str] | None = None,
        model: str = "gemini-3.8-flash",
        rpm_per_key: float = 15.0,
    ) -> None:
        self.model = model
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.rpm_per_key = rpm_per_key

        self.slots: dict[str, KeySlot] = {}
        self.purpose_mapping: dict[LLMPurpose, list[str]] = {p: [] for p in LLMPurpose}
        self._round_robin_idx: int = 0

        # Register purpose-specific keys
        if purpose_keys:
            for purpose, k in purpose_keys.items():
                if k and k.strip():
                    k_clean = k.strip()
                    if k_clean not in self.slots:
                        self.slots[k_clean] = KeySlot(
                            api_key=k_clean, label=purpose.value, rpm=rpm_per_key
                        )
                    self.purpose_mapping[purpose].append(k_clean)

        # Register general key pool
        if key_pool:
            for k in key_pool:
                if k and k.strip():
                    k_clean = k.strip()
                    if k_clean not in self.slots:
                        self.slots[k_clean] = KeySlot(
                            api_key=k_clean, label="pool", rpm=rpm_per_key
                        )
                    for p in LLMPurpose:
                        if k_clean not in self.purpose_mapping[p]:
                            self.purpose_mapping[p].append(k_clean)

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "SmartLLMRouter":
        """Load router keys and settings from .env file or environment variables."""
        env_vars: dict[str, str] = {}
        # Parse .env if it exists
        if env_path is None:
            env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()

        # Overlay with real os.environ
        for k, v in os.environ.items():
            env_vars[k] = v

        model = env_vars.get("GEMINI_MODEL", "gemini-3.8-flash")
        rpm = float(env_vars.get("GEMINI_RPM_LIMIT", "15.0"))

        purpose_keys: dict[LLMPurpose, str] = {}
        if "GEMINI_KEY_PLANNER" in env_vars:
            purpose_keys[LLMPurpose.PLANNING] = env_vars["GEMINI_KEY_PLANNER"]
        if "GEMINI_KEY_INTENT" in env_vars:
            purpose_keys[LLMPurpose.INTENT] = env_vars["GEMINI_KEY_INTENT"]
        if "GEMINI_KEY_INVESTIGATION" in env_vars:
            purpose_keys[LLMPurpose.INVESTIGATION] = env_vars["GEMINI_KEY_INVESTIGATION"]
        if "GEMINI_KEY_NARRATOR" in env_vars:
            purpose_keys[LLMPurpose.NARRATION] = env_vars["GEMINI_KEY_NARRATOR"]

        key_pool: list[str] = []
        if "GEMINI_API_KEYS" in env_vars:
            for item in env_vars["GEMINI_API_KEYS"].split(","):
                if item.strip():
                    key_pool.append(item.strip())
        elif "GEMINI_API_KEY" in env_vars:
            key_pool.append(env_vars["GEMINI_API_KEY"].strip())

        return cls(
            key_pool=key_pool,
            purpose_keys=purpose_keys,
            model=model,
            rpm_per_key=rpm,
        )

    def _select_candidate_slots(self, purpose: LLMPurpose) -> list[KeySlot]:
        """Return list of candidate key slots for the purpose, prioritized by health."""
        # 1. Preferred keys mapped to this purpose
        preferred = self.purpose_mapping.get(purpose, [])
        candidate_keys = list(preferred)

        # 2. Add any other configured keys as fallback
        for k in self.slots:
            if k not in candidate_keys:
                candidate_keys.append(k)

        all_slots = [self.slots[k] for k in candidate_keys if k in self.slots]
        available_slots = [s for s in all_slots if s.is_available]

        if available_slots:
            # Round-robin rotation among available slots
            idx = self._round_robin_idx % len(available_slots)
            self._round_robin_idx += 1
            return available_slots[idx:] + available_slots[:idx]

        # If none available (all on cooldown), return slots with earliest cooldown
        return sorted(all_slots, key=lambda s: s.cooldown_until)

    def complete(self, prompt: str, **options: Any) -> str:
        """
        Execute completion with intelligent routing, rate-limiting, and failover.
        Pass `purpose=LLMPurpose.PLANNING` in options to route to dedicated agentic keys.
        """
        purpose = options.get("purpose", LLMPurpose.GENERAL)
        if isinstance(purpose, str):
            try:
                purpose = LLMPurpose(purpose)
            except ValueError:
                purpose = LLMPurpose.GENERAL

        candidates = self._select_candidate_slots(purpose)
        if not candidates:
            raise ToolFailure(
                ErrorCode.TOOL_FAILURE,
                "No Gemini API keys configured in router.",
                retryable=False,
            )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": options.get("temperature", 0.0),
            },
        }
        data = json.dumps(payload).encode("utf-8")

        last_error: Exception | None = None

        for slot in candidates:
            if slot.is_disabled:
                continue

            # Wait for rate limiter token for this specific key
            slot.limiter.acquire()

            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json", "x-goog-api-key": slot.api_key},
            )

            try:
                with urllib.request.urlopen(req, timeout=30.0) as response:
                    resp_data = json.loads(response.read().decode("utf-8"))

                if "candidates" not in resp_data or not resp_data["candidates"]:
                    raise ToolFailure(ErrorCode.TOOL_FAILURE, "No candidates returned by Gemini.")

                candidate = resp_data["candidates"][0]
                if candidate.get("finishReason") == "SAFETY":
                    raise ToolFailure(ErrorCode.TOOL_FAILURE, "Response blocked by safety filters.")

                slot.mark_success()
                return candidate["content"]["parts"][0]["text"]

            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    slot.mark_cooldown(60.0)
                    logger.warning("429 Rate limit on %s. Failing over...", mask_key(slot.api_key))
                    continue
                if exc.code in (401, 403):
                    slot.mark_disabled(f"Auth error HTTP {exc.code}")
                    logger.warning(
                        "Auth failure HTTP %d on %s. Disabling key...",
                        exc.code,
                        mask_key(slot.api_key),
                    )
                    continue
                if exc.code in (500, 503, 504):
                    slot.mark_cooldown(15.0)
                    logger.warning(
                        "Server error %d on %s. Failing over...", exc.code, mask_key(slot.api_key)
                    )
                    continue
                raise ToolFailure(
                    ErrorCode.TOOL_FAILURE,
                    f"Gemini API HTTP {exc.code}: {exc.reason}",
                    retryable=False,
                ) from exc

            except urllib.error.URLError as exc:
                last_error = exc
                slot.mark_cooldown(10.0)
                logger.warning(
                    "Network error on %s: %s. Failing over...", mask_key(slot.api_key), exc
                )
                continue

        # If all candidates failed
        raise ToolFailure(
            ErrorCode.TOOL_FAILURE,
            f"All available Gemini keys failed. Last error: {last_error}",
            retryable=True,
        )

    def get_stats(self) -> dict[str, Any]:
        """Return operational stats and health for all configured keys."""
        stats = {}
        for key, slot in self.slots.items():
            stats[mask_key(key)] = {
                "label": slot.label,
                "calls": slot.total_calls,
                "errors": slot.total_errors,
                "is_disabled": slot.is_disabled,
                "is_available": slot.is_available,
                "cooldown_remaining_sec": max(0.0, slot.cooldown_until - time.monotonic()),
            }
        return stats
