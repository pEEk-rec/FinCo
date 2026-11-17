# ruff: noqa: E501  (long SQL lines)
"""
Running the cascade on the ledger, and the switch between the new and the old engine
(PLAN_AGENTIC_V2, A3 and A7).

`run_categorisation` has the same call shape and the same report as the old
`run_categorization_pipeline`, so the places that categorise (the agent graph, live import) call one
function and `config/understand.yaml: engine` decides which engine answers. The old engine stays
available behind `engine: legacy`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from copilot.llm.client import LLMClient
from copilot.tools.categorisation import CategorizeUpdate
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.understand.advisor import NoAdvisor, RouterAdvisor
from copilot.understand.cascade import Cascade, Decision, Item
from copilot.understand.config import load_understand_config
from copilot.understand.legacy_pipeline import PipelineReport, run_categorization_pipeline
from copilot.understand.rules import CategorizationRule

#: how a stage's decision is recorded on the ledger row (the ledger knows four sources)
LEDGER_SOURCE = {"S0": "override", "S1": "rule", "S2": "cache", "S3": "cache", "S4": "llm"}
SELECT_UNANSWERED = (
    "SELECT id, merchant_raw, amount_paise, direction FROM transactions WHERE user_id = ?"
    " AND category_source IN ('none', 'rule', 'cache', 'llm')"
    " AND (category_id IS NULL OR needs_review = 1) ORDER BY occurred_at, id LIMIT ?"
)


@dataclass
class LedgerRun:
    decisions: list[Decision]
    model_calls: int
    model_failures: int
    updated: int
    review_queue: int


def _categories(ctx: ExecutionContext) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in ctx.conn.execute(
            "SELECT id, name FROM categories WHERE user_id = ?", (ctx.user_id,)
        )
    }


#: A model suggestion is shown on the review screen as a suggestion, so it is stored below the
#: ledger's acceptance line (0.85) and stays "needs review" until the user confirms it.
SUGGESTION_CEILING = 0.84


def _update(d: Decision) -> CategorizeUpdate:
    if d.applied:
        return CategorizeUpdate(
            transaction_id=d.tx_id, category_id=d.category_id,
            confidence=min(1.0, d.p_bp / 10000), source=LEDGER_SOURCE[d.stage],
        )  # fmt: skip
    guess = next((c for c in reversed(d.candidates) if c["stage"] == "S4"), None)
    if guess:
        return CategorizeUpdate(
            transaction_id=d.tx_id, category_id=guess["category"],
            confidence=min(guess["raw_bp"] / 10000, SUGGESTION_CEILING), source="llm",
        )  # fmt: skip
    return CategorizeUpdate(transaction_id=d.tx_id, category_id=None, confidence=0.0, source="none")


def run_on_ledger(
    ctx: ExecutionContext,
    llm: LLMClient | None,
    rules: list[CategorizationRule],
    aliases: dict[str, str],
    apply: Callable[[list[CategorizeUpdate]], tuple[int, int]],
    *,
    batch_size: int = 20,
    limit: int = 2000,
) -> LedgerRun:
    """Decide for every unanswered payment, then hand the proposals to `apply` (updated, queued)."""
    rows = ctx.conn.execute(SELECT_UNANSWERED, (ctx.user_id, limit)).fetchall()
    if not rows:
        return LedgerRun([], 0, 0, 0, 0)
    advisor = RouterAdvisor(llm, batch_size=batch_size) if llm else NoAdvisor()
    cascade = Cascade(
        ctx.conn, ctx.user_id, categories=_categories(ctx), rules=rules, aliases=aliases,
        advisor=advisor, clock=ctx.clock if isinstance(ctx.clock, datetime) else None,
    )  # fmt: skip
    decisions = cascade.run([Item(r[0], r[1], abs(r[2]), r[3]) for r in rows])
    updates = [_update(d) for d in decisions]
    updated, queued = apply(updates)
    return LedgerRun(
        decisions, cascade.model_calls, getattr(advisor, "failures", 0), updated, queued
    )


def run_categorisation(
    ctx: ExecutionContext,
    llm: LLMClient,
    rules: list[CategorizationRule],
    aliases: dict[str, str],
    model_name: str,
    prompt_version: str,
    settings: Any | None = None,
) -> PipelineReport:
    """Categorise with whichever engine the config names. Same report either way."""
    if load_understand_config().engine == "legacy":
        return run_categorization_pipeline(
            ctx, llm, rules, aliases, model_name, prompt_version, settings
        )

    def apply(updates: list[CategorizeUpdate]) -> tuple[int, int]:
        res = execute_tool(ctx, "categorize_batch", {"updates": [u.model_dump() for u in updates]})
        return (res.data.updated_count, res.data.review_queue_count) if res.ok else (0, 0)

    batch = getattr(getattr(settings, "categorization", None), "llm_batch_size", 20)
    run = run_on_ledger(ctx, llm, rules, aliases, apply, batch_size=batch)
    by_source: dict[str, int] = {}
    for d in run.decisions:
        key = LEDGER_SOURCE[d.stage] if d.applied else _update(d).source
        by_source[key] = by_source.get(key, 0) + 1
    return PipelineReport(
        considered=len(run.decisions),
        by_source=by_source,
        llm_calls=run.model_calls,
        llm_failures=run.model_failures,
        updated=run.updated,
        review_queue=run.review_queue,
    )
