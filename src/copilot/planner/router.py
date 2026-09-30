"""
Planner interface and a trivial keyword router.

PLACEHOLDER for Phase 2: `TrivialRouter` exists only so later phases have something that
satisfies the `Planner` interface. It does no reasoning, and it only ever plans READ tools;
write tools such as `recategorize_transaction` are never planned automatically.
"""

import re
from typing import Protocol

from copilot.models.run_state import RunState

# (keywords, tools) in priority order; the plan is the union of matching rules, in this order.
ROUTES: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (frozenset({"balance"}), ("get_balance",)),
    (frozenset({"budget", "budgets"}), ("check_budgets",)),
    (frozenset({"spend", "spent", "spending"}), ("aggregate_spend_by_category",)),
    (frozenset({"forecast", "projection", "project"}), ("forecast_category_spend",)),
    (frozenset({"transaction", "transactions"}), ("get_transactions",)),
)

_WORD = re.compile(r"[a-z]+")


class Planner(Protocol):
    """Anything that turns a run's state into an ordered list of tool names."""

    def plan(self, state: RunState) -> list[str]:
        """Return the tool names to run, in order."""
        ...


class TrivialRouter:
    """Maps whole-word keywords in `state.intent` to fixed lists of read tools."""

    def plan(self, state: RunState) -> list[str]:
        """Tool names for the intent's keywords, deduplicated; [] when nothing matches."""
        words = set(_WORD.findall((state.intent or "").lower()))
        tools: list[str] = []
        for keywords, route in ROUTES:
            if words & keywords:
                tools += [t for t in route if t not in tools]
        return tools
