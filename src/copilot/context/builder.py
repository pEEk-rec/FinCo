"""
Context engineering and token budget manager (PLAN_PHASE3 Section 5.14).

ContextBuilder is the single choke point for building LLM prompts.
It enforces:
1. Token budgets per purpose (from config/context.yaml).
2. Priority-based source ranking per purpose.
3. Untrusted data-field delimiting and injection hardening.
4. PII and credential redaction inside the builder.
5. ContextManifest recording without storing raw prompt text, user text, or merchant names.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from copilot.config.phase3 import ContextConfig, load_context_config
from copilot.context.hardening import delimit_data_field, redact_and_count
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import insert_context_manifest
from copilot.llm.client import LLMClient
from copilot.llm.client import structured_call as core_structured_call
from copilot.models.phase3 import ContextManifest, MemoryItem
from copilot.ops.tracing import span

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
ModelT = TypeVar("ModelT", bound=BaseModel)

# Priority rankings per purpose (lower number = higher priority)
_DEFAULT_PRIORITIES: dict[str, dict[str, int]] = {
    "intent_extraction": {
        "instruction": 1,
        "untrusted_data": 2,
        "categories": 3,
        "goals": 4,
        "memories": 5,
    },
    "planning": {
        "instruction": 1,
        "intent": 2,
        "catalogue": 3,
        "untrusted_data": 4,
        "memories": 5,
        "categories": 6,
        "goals": 7,
    },
    "narration": {
        "instruction": 1,
        "intent": 2,
        "sub_question": 2,
        "findings": 3,
        "memories": 4,
        "untrusted_data": 5,
    },
    "critique": {
        "instruction": 1,
        "sub_questions": 2,
        "intent": 2,
        "findings": 3,
        "memories": 4,
        "untrusted_data": 5,
    },
    "decomposition": {
        "instruction": 1,
        "intent": 2,
        "catalogue": 3,
        "untrusted_data": 4,
        "memories": 5,
    },
}


@dataclass
class ContextItemCandidate:
    source: str
    item_id: str
    priority: int
    content: str
    estimated_tokens: int
    redactions: int = 0


@dataclass
class BuiltContext:
    prompt: str
    manifest: ContextManifest
    budget_tokens: int
    estimated_tokens: int
    included: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    redactions_count: int


class ContextBuilder:
    """
    Builds structured, hardened, redacted, and budget-governed prompts
    for every LLM call path.
    """

    def __init__(
        self,
        config: ContextConfig | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
            cfg_path = CONFIG_DIR / "context.yaml"
            self.config = (
                load_context_config(cfg_path)
                if cfg_path.exists()
                else ContextConfig(
                    token_budgets={
                        "intent_extraction": 1000,
                        "planning": 2500,
                        "narration": 3000,
                        "critique": 1500,
                        "decomposition": 1500,
                    },
                    top_k_memories=5,
                    character_token_ratio=4,
                )
            )
        self.conn = conn

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using configured character-to-token ratio."""
        ratio = max(1, self.config.character_token_ratio)
        return max(1, math.ceil(len(text) / ratio))

    def build(
        self,
        *,
        user_id: str,
        task_id: str,
        purpose: str,
        instruction: str,
        intent: Any | None = None,
        sub_question: Any | None = None,
        sub_questions: list[Any] | None = None,
        findings: list[Any] | None = None,
        memories: list[MemoryItem | dict[str, Any]] | None = None,
        categories: list[dict[str, str]] | dict[str, str] | None = None,
        goals: list[dict[str, str]] | dict[str, str] | None = None,
        catalogue: list[dict[str, Any]] | None = None,
        untrusted_data: Any | None = None,
        extra_sections: dict[str, str] | None = None,
        clock: datetime | None = None,
        prompt_version: str = "v3.12",
        conn: sqlite3.Connection | None = None,
    ) -> BuiltContext:
        """
        Assemble and budget the context. Persists ContextManifest to database.
        """
        effective_conn = conn or self.conn
        now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)
        clock_iso = to_utc_iso(now_dt)

        budget_tokens = self.config.token_budgets.get(purpose, 2000)
        priorities = _DEFAULT_PRIORITIES.get(purpose, {})

        candidates: list[ContextItemCandidate] = []
        total_redactions = 0

        # 1. Base instruction (mandatory)
        inst_redacted, r_count = redact_and_count(instruction.strip())
        total_redactions += r_count
        candidates.append(
            ContextItemCandidate(
                source="instruction",
                item_id="system_instruction",
                priority=priorities.get("instruction", 1),
                content=inst_redacted,
                estimated_tokens=self.estimate_tokens(inst_redacted),
                redactions=r_count,
            )
        )

        # 2. Intent summary
        if intent is not None:
            intent_dict = (
                intent.model_dump() if hasattr(intent, "model_dump") else dict(intent)
            )
            intent_lines = [f"{k}: {v}" for k, v in intent_dict.items() if v is not None]
            intent_str = "INTENT SPECIFICATION:\n" + "\n".join(intent_lines)
            intent_redacted, r_count = redact_and_count(intent_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="intent",
                    item_id=str(intent_dict.get("type", "intent_spec")),
                    priority=priorities.get("intent", 2),
                    content=intent_redacted,
                    estimated_tokens=self.estimate_tokens(intent_redacted),
                    redactions=r_count,
                )
            )

        # 3. Sub-question / Sub-questions
        if sub_question is not None:
            sq_dict = (
                sub_question.model_dump()
                if hasattr(sub_question, "model_dump")
                else dict(sub_question)
            )
            sq_str = f"SUB-QUESTION: {json.dumps(sq_dict)}"
            sq_redacted, r_count = redact_and_count(sq_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="sub_question",
                    item_id=str(sq_dict.get("question_kind", "sub_q")),
                    priority=priorities.get("sub_question", 2),
                    content=sq_redacted,
                    estimated_tokens=self.estimate_tokens(sq_redacted),
                    redactions=r_count,
                )
            )

        if sub_questions:
            sq_list = [
                sq.model_dump() if hasattr(sq, "model_dump") else dict(sq)
                for sq in sub_questions
            ]
            sqs_str = f"SUB-QUESTIONS LIST:\n{json.dumps(sq_list, indent=2)}"
            sqs_redacted, r_count = redact_and_count(sqs_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="sub_questions",
                    item_id="sub_questions_list",
                    priority=priorities.get("sub_questions", 2),
                    content=sqs_redacted,
                    estimated_tokens=self.estimate_tokens(sqs_redacted),
                    redactions=r_count,
                )
            )

        # 4. Untrusted data (user queries, narrations, merchant names, notes)
        if untrusted_data is not None:
            delimited = delimit_data_field(untrusted_data)
            del_redacted, r_count = redact_and_count(delimited)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="untrusted_data",
                    item_id="user_untrusted_input",
                    priority=priorities.get("untrusted_data", 3),
                    content=del_redacted,
                    estimated_tokens=self.estimate_tokens(del_redacted),
                    redactions=r_count,
                )
            )

        # 5. Tools or Skills catalogue slice
        if catalogue:
            cat_lines = []
            for t in catalogue:
                name = t.get("tool_name", t.get("name", "unknown"))
                desc = t.get("short_description", t.get("description", ""))
                params = t.get("parameters", t.get("inputs", {}))
                cat_lines.append(f"- {name}: {desc} | args: {params}")
            cat_str = "AVAILABLE CAPABILITIES:\n" + "\n".join(cat_lines)
            cat_redacted, r_count = redact_and_count(cat_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="catalogue",
                    item_id="capabilities_slice",
                    priority=priorities.get("catalogue", 3),
                    content=cat_redacted,
                    estimated_tokens=self.estimate_tokens(cat_redacted),
                    redactions=r_count,
                )
            )

        # 6. Findings
        if findings:
            for idx, f in enumerate(findings):
                f_data = f.model_dump() if hasattr(f, "model_dump") else dict(f)
                fid = f_data.get("id", f"finding_{idx}")
                f_str = f"Finding {fid}: {json.dumps(f_data)}"
                f_redacted, r_count = redact_and_count(f_str)
                total_redactions += r_count
                candidates.append(
                    ContextItemCandidate(
                        source="findings",
                        item_id=str(fid),
                        priority=priorities.get("findings", 3),
                        content=f_redacted,
                        estimated_tokens=self.estimate_tokens(f_redacted),
                        redactions=r_count,
                    )
                )

        # 7. Categories
        if categories:
            cat_payload = (
                categories
                if isinstance(categories, list)
                else [{"name": k, "id": v} for k, v in categories.items()]
            )
            cat_str = f"KNOWN CATEGORIES:\n{json.dumps(cat_payload)}"
            cat_redacted, r_count = redact_and_count(cat_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="categories",
                    item_id="known_categories",
                    priority=priorities.get("categories", 4),
                    content=cat_redacted,
                    estimated_tokens=self.estimate_tokens(cat_redacted),
                    redactions=r_count,
                )
            )

        # 8. Goals
        if goals:
            goal_payload = (
                goals
                if isinstance(goals, list)
                else [{"name": k, "id": v} for k, v in goals.items()]
            )
            goal_str = f"KNOWN GOALS:\n{json.dumps(goal_payload)}"
            goal_redacted, r_count = redact_and_count(goal_str)
            total_redactions += r_count
            candidates.append(
                ContextItemCandidate(
                    source="goals",
                    item_id="known_goals",
                    priority=priorities.get("goals", 5),
                    content=goal_redacted,
                    estimated_tokens=self.estimate_tokens(goal_redacted),
                    redactions=r_count,
                )
            )

        # 9. Behavioral Memories
        if memories:
            for m in memories:
                mid = m.id if hasattr(m, "id") else m.get("id", "mem_unknown")
                subj = (
                    m.subject_key if hasattr(m, "subject_key") else m.get("subject_key", "")
                )
                kind = m.kind if hasattr(m, "kind") else m.get("kind", "")
                stmt = (
                    m.statement_json
                    if hasattr(m, "statement_json")
                    else m.get("statement_json", {})
                )
                m_str = f"Memory [{kind}|{subj}]: {json.dumps(stmt)}"
                m_redacted, r_count = redact_and_count(m_str)
                total_redactions += r_count
                candidates.append(
                    ContextItemCandidate(
                        source="memories",
                        item_id=str(mid),
                        priority=priorities.get("memories", 5),
                        content=m_redacted,
                        estimated_tokens=self.estimate_tokens(m_redacted),
                        redactions=r_count,
                    )
                )

        # 10. Extra custom sections
        if extra_sections:
            for sec_name, sec_text in extra_sections.items():
                s_redacted, r_count = redact_and_count(sec_text)
                total_redactions += r_count
                candidates.append(
                    ContextItemCandidate(
                        source="extra_section",
                        item_id=sec_name,
                        priority=9,
                        content=s_redacted,
                        estimated_tokens=self.estimate_tokens(s_redacted),
                        redactions=r_count,
                    )
                )

        # Sort candidates deterministically: by priority ascending, then item_id ascending
        candidates.sort(key=lambda c: (c.priority, c.item_id))

        # Greedy token budget allocation
        current_tokens = 0
        included_candidates: list[ContextItemCandidate] = []
        included_manifest: list[dict[str, Any]] = []
        excluded_manifest: list[dict[str, Any]] = []

        for cand in candidates:
            # Mandatory instruction is always included
            if cand.source == "instruction":
                included_candidates.append(cand)
                current_tokens += cand.estimated_tokens
                included_manifest.append(
                    {
                        "source": cand.source,
                        "id": cand.item_id,
                        "reason": "mandatory_system_instruction",
                        "estimated_tokens": cand.estimated_tokens,
                    }
                )
                continue

            if current_tokens + cand.estimated_tokens <= budget_tokens:
                included_candidates.append(cand)
                current_tokens += cand.estimated_tokens
                included_manifest.append(
                    {
                        "source": cand.source,
                        "id": cand.item_id,
                        "reason": "priority_fit",
                        "estimated_tokens": cand.estimated_tokens,
                    }
                )
            else:
                excluded_manifest.append(
                    {
                        "source": cand.source,
                        "id": cand.item_id,
                        "reason": "budget_exceeded",
                        "estimated_tokens": cand.estimated_tokens,
                    }
                )

        # Assemble final prompt string
        prompt_parts = [c.content for c in included_candidates]
        prompt = "\n\n".join(prompt_parts)

        # Construct ContextManifest
        # Invariant (Safety Rule 19): Manifest NEVER contains raw text, user text, or merchant names
        call_id = str(uuid.uuid4())
        manifest = ContextManifest(
            id=f"cm_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            call_id=call_id,
            task_id=task_id,
            purpose=purpose,
            budget_tokens=budget_tokens,
            estimated_tokens=current_tokens,
            included=included_manifest,
            excluded=excluded_manifest,
            redactions_count=total_redactions,
            prompt_version=prompt_version,
            created_at=clock_iso,
        )

        if effective_conn is not None:
            insert_context_manifest(effective_conn, manifest)

        return BuiltContext(
            prompt=prompt,
            manifest=manifest,
            budget_tokens=budget_tokens,
            estimated_tokens=current_tokens,
            included=included_manifest,
            excluded=excluded_manifest,
            redactions_count=total_redactions,
        )

    def complete(
        self,
        client: LLMClient,
        *,
        user_id: str,
        task_id: str,
        purpose: str,
        instruction: str,
        conn: sqlite3.Connection | None = None,
        **build_kwargs: Any,
    ) -> tuple[str, ContextManifest]:
        """Build budgeted prompt, log manifest, and complete with LLM client."""
        built = self.build(
            user_id=user_id,
            task_id=task_id,
            purpose=purpose,
            instruction=instruction,
            conn=conn,
            **build_kwargs,
        )
        with span(
            kind="llm",
            name=purpose,
            attrs={
                "purpose": purpose,
                "model": getattr(client, "model", "default"),
                "budget_tokens": built.budget_tokens,
                "tokens_used": built.estimated_tokens,
            },
            user_id=user_id,
            trace_id=task_id,
            conn=conn or self.conn,
        ):
            reply = client.complete(built.prompt)
        return reply, built.manifest

    def structured_call(
        self,
        client: LLMClient,
        output_model: type[ModelT],
        *,
        user_id: str,
        task_id: str,
        purpose: str,
        instruction: str,
        max_retries: int = 2,
        conn: sqlite3.Connection | None = None,
        **build_kwargs: Any,
    ) -> tuple[ModelT, ContextManifest]:
        """Build budgeted prompt, log manifest, and invoke structured_call."""
        built = self.build(
            user_id=user_id,
            task_id=task_id,
            purpose=purpose,
            instruction=instruction,
            conn=conn,
            **build_kwargs,
        )
        with span(
            kind="llm",
            name=purpose,
            attrs={
                "purpose": purpose,
                "model": getattr(client, "model", "default"),
                "budget_tokens": built.budget_tokens,
                "tokens_used": built.estimated_tokens,
            },
            user_id=user_id,
            trace_id=task_id,
            conn=conn or self.conn,
        ):
            result = core_structured_call(
                client=client,
                prompt=built.prompt,
                output_model=output_model,
                max_retries=max_retries,
                purpose=purpose,
            )
        return result, built.manifest
