# ruff: noqa: E501  (long SQL lines)
"""
Understanding tools (PLAN_AGENTIC_V2, A2 to A6). Every one goes through `execute_tool`. The
agent may run the cascade (it only proposes, and nothing it proposes outranks you); only the user
can answer for a shop, merge or split spellings, or accept a rule.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.settings import load_settings
from copilot.tools.categorisation import CategorizeUpdate, categorize_batch_handler
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register
from copilot.understand import learn
from copilot.understand.entities import EntityStore
from copilot.understand.ledger import run_on_ledger
from copilot.understand.rules import load_aliases, load_rules

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


def _clock(ctx: ExecutionContext) -> datetime | None:
    return ctx.clock if isinstance(ctx.clock, datetime) else None


def _categories(ctx: ExecutionContext) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in ctx.conn.execute(
            "SELECT id, name FROM categories WHERE user_id = ?", (ctx.user_id,)
        )
    }


# ---- run the cascade ---------------------------------------------------------------------------
class RunCascadeInput(ToolInput):
    limit: int = Field(default=2000, ge=1, le=20000)


class RunCascadeOutput(ToolOutput):
    considered: int
    applied: int
    asked: int
    by_stage: dict[str, int]
    model_calls: int
    audits: int


def run_cascade_handler(ctx: ExecutionContext, **kwargs) -> RunCascadeOutput:
    p = RunCascadeInput.model_validate(kwargs)
    settings = load_settings()

    def apply(updates: list[CategorizeUpdate]) -> tuple[int, int]:
        out = categorize_batch_handler(ctx, updates)
        return out.updated_count, out.review_queue_count

    run = run_on_ledger(
        ctx, ctx.llm_client, load_rules(settings.categorization_rules_path),
        load_aliases(settings.merchant_aliases_path), apply,
        batch_size=settings.categorization.llm_batch_size, limit=p.limit,
    )  # fmt: skip
    by_stage: dict[str, int] = {}
    for d in run.decisions:
        by_stage[d.stage] = by_stage.get(d.stage, 0) + 1
    return RunCascadeOutput(
        considered=len(run.decisions),
        applied=sum(d.applied for d in run.decisions),
        asked=sum(d.asks_user for d in run.decisions),
        by_stage=by_stage,
        model_calls=run.model_calls,
        audits=sum(d.audit for d in run.decisions),
    )


# ---- questions and answers ---------------------------------------------------------------------
class QuestionsInput(ToolInput):
    limit: int = Field(default=20, ge=1, le=200)


class QuestionView(BaseModel):
    entity_id: str
    display_name: str
    kind: str
    payments: int
    batch: bool
    best_guess: str | None
    reason: str
    confirm_only: bool
    score: int


class QuestionsOutput(ToolOutput):
    questions: list[QuestionView]


def questions_handler(ctx: ExecutionContext, **kwargs) -> QuestionsOutput:
    p = QuestionsInput.model_validate(kwargs)
    qs = learn.rank_questions(ctx.conn, ctx.user_id, clock=_clock(ctx))[: p.limit]
    return QuestionsOutput(
        questions=[
            QuestionView(
                entity_id=q.entity_id,
                display_name=q.display_name,
                kind=q.kind,
                payments=len(q.tx_ids),
                batch=q.batch,
                best_guess=q.best_guess,
                reason=q.reason,
                confirm_only=q.audit,
                score=q.score,
            )
            for q in qs
        ]
    )


class AnswerInput(ToolInput):
    category_id: str
    entity_id: str | None = None
    transaction_id: str | None = None


class AnswerOutput(ToolOutput):
    entity_id: str
    settled: int
    audit_event_id: str | None = None
    rule_proposal: str | None = None


def answer_handler(ctx: ExecutionContext, **kwargs) -> AnswerOutput:
    p = AnswerInput.model_validate(kwargs)
    if bool(p.entity_id) == bool(p.transaction_id):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Give either a shop or a payment, not both.")
    if p.entity_id:
        out = learn.answer_entity(
            ctx.conn, ctx.user_id, p.entity_id, p.category_id,
            actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx),
        )  # fmt: skip
    else:
        out = learn.answer_transaction(
            ctx.conn, ctx.user_id, p.transaction_id, p.category_id,  # type: ignore[arg-type]
            actor=ctx.actor, run_id=ctx.run_id, clock=_clock(ctx),
        )  # fmt: skip
    return AnswerOutput(
        entity_id=out["entity_id"], settled=out["settled"],
        audit_event_id=out["audit_event_id"], rule_proposal=out["rule_proposal"],
    )  # fmt: skip


# ---- merge, split, undo ------------------------------------------------------------------------
class MergeInput(ToolInput):
    keep: str
    absorb: str


class SplitInput(ToolInput):
    entity_id: str
    alias_ids: list[str] = Field(min_length=1)


class UndoMergeInput(ToolInput):
    log_id: str


class MergeOutput(ToolOutput):
    log_id: str | None = None
    new_entity_id: str | None = None


def merge_handler(ctx: ExecutionContext, **kwargs) -> MergeOutput:
    p = MergeInput.model_validate(kwargs)
    store = EntityStore(ctx.conn, ctx.user_id, clock=_clock(ctx))
    return MergeOutput(log_id=store.merge(p.keep, p.absorb, actor=ctx.actor, run_id=ctx.run_id))


def split_handler(ctx: ExecutionContext, **kwargs) -> MergeOutput:
    p = SplitInput.model_validate(kwargs)
    store = EntityStore(ctx.conn, ctx.user_id, clock=_clock(ctx))
    new = store.split(p.entity_id, p.alias_ids, actor=ctx.actor, run_id=ctx.run_id)
    return MergeOutput(new_entity_id=new)


def undo_merge_handler(ctx: ExecutionContext, **kwargs) -> MergeOutput:
    p = UndoMergeInput.model_validate(kwargs)
    EntityStore(ctx.conn, ctx.user_id, clock=_clock(ctx)).undo(p.log_id, actor=ctx.actor)
    return MergeOutput(log_id=p.log_id)


# ---- rules -------------------------------------------------------------------------------------
class DecideRuleInput(ToolInput):
    proposal_id: str
    accept: bool


class DecideRuleOutput(ToolOutput):
    id: str
    status: str
    pattern: str


def decide_rule_handler(ctx: ExecutionContext, **kwargs) -> DecideRuleOutput:
    p = DecideRuleInput.model_validate(kwargs)
    out = learn.decide_rule(
        ctx.conn, ctx.user_id, p.proposal_id, p.accept, actor=ctx.actor, clock=_clock(ctx)
    )
    return DecideRuleOutput(**out)


# ---- why ---------------------------------------------------------------------------------------
class ExplainInput(ToolInput):
    transaction_id: str


class ExplainOutput(ToolOutput):
    transaction_id: str
    entity_id: str | None
    shop: str | None
    spellings: list[str]
    stage: str | None
    category_id: str | None
    confidence_bp: int | None
    reason: str | None
    candidates: list[dict]


def explain_handler(ctx: ExecutionContext, **kwargs) -> ExplainOutput:
    p = ExplainInput.model_validate(kwargs)
    d = ctx.conn.execute(
        "SELECT * FROM category_decisions WHERE user_id = ? AND transaction_id = ?"
        " AND superseded_by IS NULL ORDER BY created_at DESC, id DESC LIMIT 1",
        (ctx.user_id, p.transaction_id),
    ).fetchone()
    if d is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "Nothing has been decided for that payment yet.")
    store = EntityStore(ctx.conn, ctx.user_id)
    ent = store.entity(d["entity_id"]) if d["entity_id"] else None
    evidence = json.loads(d["evidence_json"])
    return ExplainOutput(
        transaction_id=p.transaction_id,
        entity_id=ent["id"] if ent else None,
        shop=ent["display_name"] if ent else None,
        spellings=[a["alias_value"] for a in store.aliases(ent["id"]) if a["alias_type"] == "name"]
        if ent
        else [],
        stage=d["stage"],
        category_id=d["category_id"],
        confidence_bp=d["confidence_bp"],
        reason=evidence.get("reason"),
        candidates=evidence.get("candidates", []),
    )


UNDERSTAND_TOOLS = (
    ToolSpec(
        name="run_cascade",
        description="Categorise what is not yet answered: your answers, rules, similar shops, brands, the model, then ask.",
        input_model=RunCascadeInput,
        output_model=RunCascadeOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=run_cascade_handler,
    ),
    ToolSpec(
        name="entity_questions",
        description="What to ask the user next, most useful first.",
        input_model=QuestionsInput,
        output_model=QuestionsOutput,
        side_effect=SideEffect.READ,
        handler=questions_handler,
    ),
    ToolSpec(
        name="answer_shop",
        description="Say what a shop (or a single payment) was. Settles every waiting payment of that shop.",
        input_model=AnswerInput,
        output_model=AnswerOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=answer_handler,
    ),
    ToolSpec(
        name="merge_entities",
        description="Say two spellings are the same shop.",
        input_model=MergeInput,
        output_model=MergeOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=merge_handler,
    ),
    ToolSpec(
        name="split_entity",
        description="Separate some spellings into their own shop.",
        input_model=SplitInput,
        output_model=MergeOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=split_handler,
    ),
    ToolSpec(
        name="undo_entity_merge",
        description="Undo a merge or split exactly.",
        input_model=UndoMergeInput,
        output_model=MergeOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=undo_merge_handler,
    ),
    ToolSpec(
        name="decide_rule_proposal",
        description="Accept or dismiss a rule the agent noticed.",
        input_model=DecideRuleInput,
        output_model=DecideRuleOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=decide_rule_handler,
    ),
    ToolSpec(
        name="explain_decision",
        description="Why a payment has the category it has: stage, confidence, evidence.",
        input_model=ExplainInput,
        output_model=ExplainOutput,
        side_effect=SideEffect.READ,
        handler=explain_handler,
    ),
)


def register_understand_tools(register_fn=register) -> None:
    for spec in UNDERSTAND_TOOLS:
        register_fn(spec)
