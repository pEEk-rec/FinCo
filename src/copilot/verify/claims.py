"""
Claim checking: no number reaches the user unless code computed it.

`claim_check(text, sources)` lists the numbers in `text` that appear in none of the `sources`
(the formatted figures the agent computed). An empty list means every claim is backed. It is
deliberately strict and simple: it does not try to understand the sentence, only to make sure a
model or a template bug cannot slip in a figure ("97% of people...") that nothing computed.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in NUMBER.findall(text)}


def claim_check(text: str, allowed_sources: list[str]) -> list[str]:
    """Numbers in `text` that appear in none of the computed strings. Empty means all are backed."""
    allowed: set[str] = set()
    for s in allowed_sources:
        allowed |= numbers_in(str(s))
    return sorted(numbers_in(text) - allowed)


def holds(text: str, allowed_sources: list[str]) -> tuple[bool, str]:
    """The verifier shape: (holds, how)."""
    stray = claim_check(text, allowed_sources)
    return (not stray, "every number is computed" if not stray else f"uncomputed number {stray[0]}")
