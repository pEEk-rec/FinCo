"""
LLM providers and wrappers.
"""

import re
from typing import Any

from copilot.llm.client import LLMClient

# Redactors:
# UPI IDs: something@bank
# Account and card numbers: 10+ digits or 4x4 card numbers
# Phone numbers: Indian 10-digit mobile numbers with optional +91/0
_UPI_RE = re.compile(r"\b[a-zA-Z0-9.\-_]+@[a-zA-Z0-9.\-_]+\b")
_ACCOUNT_RE = re.compile(r"\b(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}|\d{10,20})\b")
_PHONE_RE = re.compile(r"\b(?:\+91[\-\s]?|0)?[6-9]\d{9}\b")
_SECRET_RE = re.compile(r"\b(?:otp|pin|cvv|password)\s*[:=]?\s*[\w\d]+\b", re.IGNORECASE)


def redact(text: str) -> str:
    """Redact sensitive PII and financial credentials from a prompt or log."""
    text = _UPI_RE.sub("[UPI]", text)
    text = _SECRET_RE.sub("[REDACTED_SECRET]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _ACCOUNT_RE.sub("[ACCOUNT]", text)
    return text


class RedactingLLMClient:
    """Wraps an LLMClient to redact PII from prompts."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner

    def complete(self, prompt: str, **options: Any) -> str:
        redacted = redact(prompt)
        return self.inner.complete(redacted, **options)
