"""
Categorization pipeline.

Precedence for each transaction, stopping at the first hit:
    user's own choice (never touched) > merchant override > rule > LLM cache > LLM > review queue

This module only decides *what* to propose. Every write goes through the `categorize_batch`
tool via the executor, so policy, constraints and audit apply. LLM failures never raise: the
affected merchants simply land in the review queue.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from copilot.core.categorisation import CategorizationRule, evaluate_rules, normalize_merchant
from copilot.core.config import load_settings
from copilot.core.errors import ToolFailure
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.llm.client import LLMClient, structured_call
from copilot.llm.redactor import redact
from copilot.tools.categorisation import CategorizeUpdate
from copilot.tools.executor import ExecutionContext, execute_tool


class LLMCategoryDecision(BaseModel):
    merchant_normalized: str
    category_id: str | None
    confidence: float


class LLMBatchOutput(BaseModel):
    decisions: list[LLMCategoryDecision]


@dataclass(frozen=True)
class PipelineReport:
    """Counts only; never merchant text."""

    considered: int = 0
    by_source: dict[str, int] | None = None
    llm_calls: int = 0
    llm_failures: int = 0
    updated: int = 0
    review_queue: int = 0


def get_overrides(conn, user_id: str) -> dict[str, str]:
    """Merchant -> category chosen by the user's past corrections."""
    rows = conn.execute(
        "SELECT merchant_normalized, category_id FROM merchant_overrides WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def get_cache(conn, user_id: str) -> dict[str, tuple[str, float]]:
    """Merchant -> (category, confidence) from earlier LLM answers."""
    rows = conn.execute(
        "SELECT merchant_normalized, category_id, confidence FROM llm_category_cache "
        "WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def get_categories(conn, user_id: str) -> dict[str, str]:
    """Category id -> display name for this user."""
    rows = conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,)).fetchall()
    return {row[0]: row[1] for row in rows}


def save_to_cache(
    conn,
    user_id: str,
    decisions: list[LLMCategoryDecision],
    model: str,
    prompt_version: str,
    clock: datetime | None,
) -> None:
    """Remember accepted LLM answers so the same merchant is never asked twice."""
    now = to_utc_iso(clock or now_utc())
    for d in decisions:
        if d.category_id is None:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO llm_category_cache
            (id, user_id, merchant_normalized, category_id, confidence, model, prompt_version,
             created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{user_id}:{d.merchant_normalized}",
                user_id,
                d.merchant_normalized,
                d.category_id,
                d.confidence,
                model,
                prompt_version,
                now,
            ),
        )


def build_prompt(merchants: list[str], categories: dict[str, str]) -> str:
    """Prompt with only normalized merchant text and the allowed categories, redacted."""
    category_lines = "\n".join(f"- {cid}: {name}" for cid, name in sorted(categories.items()))
    prompt = (
        "Categorize each merchant into exactly one of the allowed categories.\n"
        "Use only these category ids; use null if you are not sure.\n"
        "Return one decision per merchant, copying merchant_normalized exactly.\n"
        f"Allowed categories:\n{category_lines}\n"
        f"Merchants: {sorted(merchants)}"
    )
    return redact(prompt)


def _chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def ask_llm(
    llm: LLMClient,
    merchants: list[str],
    categories: dict[str, str],
    max_retries: int,
    batch_size: int,
) -> tuple[list[LLMCategoryDecision], int, int]:
    """
    Ask the LLM about distinct merchants in batches.

    Returns (valid decisions, calls made, failed calls). Decisions for merchants that were not
    asked about, or naming a category the user does not have, are dropped.
    """
    valid: list[LLMCategoryDecision] = []
    calls = failures = 0
    for chunk in _chunks(sorted(merchants), batch_size):
        calls += 1
        try:
            out = structured_call(
                client=llm,
                prompt=build_prompt(chunk, categories),
                output_model=LLMBatchOutput,
                max_retries=max_retries,
                temperature=0,
            )
        except ToolFailure:
            failures += 1
            continue
        asked = set(chunk)
        seen: set[str] = set()
        for d in out.decisions:
            if d.merchant_normalized not in asked or d.merchant_normalized in seen:
                continue
            seen.add(d.merchant_normalized)
            if d.category_id is not None and d.category_id not in categories:
                continue
            if not 0.0 <= d.confidence <= 1.0:
                continue
            valid.append(d)
    return valid, calls, failures


def run_categorization_pipeline(
    ctx: ExecutionContext,
    llm: LLMClient,
    rules: list[CategorizationRule],
    aliases: dict[str, str],
    model_name: str,
    prompt_version: str,
    settings: Any | None = None,
) -> PipelineReport:
    """Propose categories for every not-yet-confirmed transaction and apply them in one batch."""
    cfg = (settings or load_settings()).categorization
    rows = ctx.conn.execute(
        """
        SELECT id, merchant_raw, amount_paise, direction
        FROM transactions
        WHERE user_id = ? AND category_source IN ('none', 'rule', 'cache', 'llm')
          AND (category_id IS NULL OR needs_review = 1)
        ORDER BY occurred_at, id
        """,
        (ctx.user_id,),
    ).fetchall()
    if not rows:
        return PipelineReport(by_source={})

    overrides = get_overrides(ctx.conn, ctx.user_id)
    cache = get_cache(ctx.conn, ctx.user_id)
    categories = get_categories(ctx.conn, ctx.user_id)

    updates: list[CategorizeUpdate] = []
    pending: dict[str, list[str]] = {}
    by_source: dict[str, int] = {}

    def propose(tx_id, cat, conf, source, **extra) -> None:
        updates.append(
            CategorizeUpdate(
                transaction_id=tx_id, category_id=cat, confidence=conf, source=source, **extra
            )
        )
        by_source[source] = by_source.get(source, 0) + 1

    for tx_id, raw, amount, direction in rows:
        normalized = normalize_merchant(raw, aliases)
        ctx.conn.execute(
            "UPDATE transactions SET merchant_normalized = ? WHERE id = ? AND user_id = ?",
            (normalized, tx_id, ctx.user_id),
        )
        if overrides.get(normalized) in categories:
            propose(tx_id, overrides[normalized], 1.0, "override")
            continue
        hit = evaluate_rules(normalized, amount, direction, rules)
        if hit and hit[0] in categories:
            propose(tx_id, hit[0], hit[1], "rule")
            continue
        if normalized in cache and cache[normalized][0] in categories:
            cat, conf = cache[normalized]
            propose(
                tx_id,
                cat,
                min(conf, cfg.llm_confidence_cap),
                "cache",
                model=model_name,
                prompt_version=prompt_version,
            )
            continue
        pending.setdefault(normalized, []).append(tx_id)

    calls = failures = 0
    if pending:
        decisions, calls, failures = ask_llm(
            llm, list(pending), categories, load_retries(settings), cfg.llm_batch_size
        )
        for d in decisions:
            d.confidence = min(d.confidence, cfg.llm_confidence_cap)
        save_to_cache(ctx.conn, ctx.user_id, decisions, model_name, prompt_version, ctx.clock)
        answered = {d.merchant_normalized: d for d in decisions}
        for merchant, tx_ids in pending.items():
            d = answered.get(merchant)
            for tx_id in tx_ids:
                if d is None or d.category_id is None:
                    propose(tx_id, None, 0.0, "none")
                else:
                    propose(
                        tx_id,
                        d.category_id,
                        d.confidence,
                        "llm",
                        model=model_name,
                        prompt_version=prompt_version,
                    )

    updated = queued = 0
    result = execute_tool(ctx, "categorize_batch", {"updates": [u.model_dump() for u in updates]})
    if result.ok:
        updated, queued = result.data.updated_count, result.data.review_queue_count
    return PipelineReport(
        considered=len(rows),
        by_source=by_source,
        llm_calls=calls,
        llm_failures=failures,
        updated=updated,
        review_queue=queued,
    )


def load_retries(settings: Any | None) -> int:
    """LLM validation retries from settings."""
    return (settings or load_settings()).llm_max_retries
