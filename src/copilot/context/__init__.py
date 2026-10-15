"""
Context engineering, memory retrieval, and injection hardening (PLAN_PHASE3 Stage 3.12).
"""

from copilot.context.builder import BuiltContext, ContextBuilder
from copilot.context.hardening import (
    DATA_FIELD_NOTICE,
    delimit_data_field,
    detect_injection_attempt,
    redact_and_count,
)
from copilot.context.retrieval import ScoredMemory, retrieve_relevant_memories

__all__ = [
    "ContextBuilder",
    "BuiltContext",
    "retrieve_relevant_memories",
    "ScoredMemory",
    "delimit_data_field",
    "redact_and_count",
    "detect_injection_attempt",
    "DATA_FIELD_NOTICE",
]
