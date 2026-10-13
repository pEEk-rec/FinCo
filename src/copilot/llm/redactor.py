"""
LLM providers and wrappers.
"""

import re
from typing import Any

from copilot.llm.client import LLMClient

# Basic redactors:
# UPI IDs: something@bank
# Account numbers: 10+ digits
_UPI_RE = re.compile(r"\b[a-zA-Z0-9.\-_]+@[a-zA-Z]+\b")
_ACCOUNT_RE = re.compile(r"\b\d{10,20}\b")


def redact(text: str) -> str:
    """Redact sensitive PII from a prompt."""
    text = _UPI_RE.sub("[UPI]", text)
    text = _ACCOUNT_RE.sub("[ACCOUNT]", text)
    return text


class RedactingLLMClient:
    """Wraps an LLMClient to redact PII from prompts."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner

    def complete(self, prompt: str, **options: Any) -> str:
        redacted = redact(prompt)
        return self.inner.complete(redacted, **options)
