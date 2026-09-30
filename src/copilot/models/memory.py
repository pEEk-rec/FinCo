"""
Long-term memory entry schema (Phase 0: schema plus insert/list only).

Every entry must say where it came from (`source`, `provenance`) and how much to trust it
(`confidence`, a threshold signal, not a probability). Retrieval ranking, decay and confidence
updates are Phase 3.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from copilot.models.domain import DomainModel, Id, UtcTimestamp

NonBlank = Annotated[str, Field(min_length=1, pattern=r"\S")]


class MemoryEntry(DomainModel):
    """One remembered fact about the user."""

    id: Id
    user_id: Id
    kind: Literal["preference", "pattern", "feedback"]
    content: NonBlank
    source: Literal["user_stated", "observed", "inferred"]
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: UtcTimestamp
    last_confirmed_at: UtcTimestamp
    provenance: NonBlank

    @model_validator(mode="after")
    def _confirmed_after_created(self) -> "MemoryEntry":
        """An entry cannot be confirmed before it existed."""
        if self.last_confirmed_at < self.created_at:
            raise ValueError("last_confirmed_at must not be before created_at")
        return self
