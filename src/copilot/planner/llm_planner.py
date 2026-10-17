"""
LLM Planner using Gemini Structured Output (PLAN_PHASE2 Section 5.3 & Stage 2.8).

Proposes a plan from the planner-selectable tool catalogue.
All proposals must pass through the deterministic PlanValidator; any invalid proposal
is audited as 'plan_rejected' and replaced with the deterministic plan.
"""

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from copilot.context.builder import ContextBuilder
from copilot.llm.client import LLMClient, StructuredOutputError
from copilot.models.agentic import Intent, Plan, PlanStep
from copilot.planner.capabilities import project_tool_catalogue
from copilot.planner.deterministic import DeterministicPlanner

logger = logging.getLogger(__name__)


class LLMStepProposal(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class LLMPlanProposal(BaseModel):
    steps: list[LLMStepProposal] = Field(default_factory=list)


_PLAN_CACHE: dict[str, tuple[float, "LLMPlanProposal"]] = {}
_PLAN_CACHE_MAX = 128
_PLAN_CACHE_TTL_S = 900.0


def _plan_cache_key(user_id: str, intent: Intent, raw_text: str | None, catalogue: Any) -> str:
    """The same user, intent, question and tool catalogue always yield the same proposal."""
    material = json.dumps(
        [user_id, intent.model_dump(mode="json"), raw_text, catalogue], sort_keys=True, default=str
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LLMPlanner:
    """Proposes dynamic plans using Gemini structured output with automatic fallback."""

    def __init__(
        self,
        client: LLMClient | None = None,
        deterministic_fallback: DeterministicPlanner | None = None,
    ) -> None:
        self.client = client
        self.fallback = deterministic_fallback or DeterministicPlanner()

    def propose(
        self,
        task_id: str,
        user_id: str,
        intent: Intent,
        state_projection: dict[str, Any] | None = None,
        tool_catalogue: list[dict[str, Any]] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> Plan:
        """
        Generate a plan via LLM structured call mediated by ContextBuilder.
        Falls back to DeterministicPlanner if the client is missing or fails.
        """
        if self.client is None:
            return self.fallback.propose(task_id, user_id, intent, state_projection, tool_catalogue)

        catalogue = tool_catalogue or project_tool_catalogue()
        builder = ContextBuilder(conn=conn)
        instruction = (
            "You are a financial planning agent. "
            "Given the following user intent and available tools,\n"
            "propose a minimal ordered sequence of tool steps to gather evidence and "
            "fulfill the request.\n\n"
            "RULES:\n"
            "1. Choose ONLY from the allowed tools listed below.\n"
            "2. Never call tools that modify state or move money.\n"
            "3. Provide exact parameters adhering to each tool's schema.\n"
            "4. Keep the plan strictly minimal.\n\n"
            "Return the proposed plan as structured JSON with a list of steps."
        )

        raw_text = state_projection.get("raw_text") if state_projection else None
        cache_key = _plan_cache_key(user_id, intent, raw_text, catalogue)
        hit = _PLAN_CACHE.get(cache_key)
        cached = hit[1] if hit and time.monotonic() - hit[0] < _PLAN_CACHE_TTL_S else None
        try:
            if cached is not None:
                proposal = cached  # a repeated question costs no model call; it is re-validated
            else:
                proposal, _ = builder.structured_call(
                    client=self.client,
                    output_model=LLMPlanProposal,
                    user_id=user_id,
                    task_id=task_id,
                    purpose="planning",
                    instruction=instruction,
                    intent=intent,
                    catalogue=catalogue,
                    untrusted_data=raw_text,
                    conn=conn,
                )
                if len(_PLAN_CACHE) >= _PLAN_CACHE_MAX:
                    _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))
                _PLAN_CACHE[cache_key] = (time.monotonic(), proposal)
        except (StructuredOutputError, Exception) as err:
            logger.warning("LLM planner proposal failed (%s); using deterministic plan", err)
            return self.fallback.propose(task_id, user_id, intent, state_projection, tool_catalogue)

        steps: list[PlanStep] = []
        for idx, step_prop in enumerate(proposal.steps):
            step = PlanStep(
                id=f"step_{uuid.uuid4().hex[:8]}",
                task_id=task_id,
                user_id=user_id,
                seq=idx,
                tool_name=step_prop.tool_name,
                args=step_prop.args,
                rationale=step_prop.rationale or f"LLM proposed step for {intent.type}",
                proposed_by="llm",
                status="proposed",
            )
            steps.append(step)

        return Plan(task_id=task_id, steps=steps)

    def _build_prompt(
        self,
        intent: Intent,
        state_projection: dict[str, Any],
        catalogue: list[dict[str, Any]],
    ) -> str:
        """Construct sanitized prompt using ContextBuilder."""
        builder = ContextBuilder()
        instruction = (
            "You are a financial planning agent. "
            "Given the following user intent and available tools,\n"
            "propose a minimal ordered sequence of tool steps to gather evidence and "
            "fulfill the request.\n\n"
            "RULES:\n"
            "1. Choose ONLY from the allowed tools listed below.\n"
            "2. Never call tools that modify state or move money.\n"
            "3. Provide exact parameters adhering to each tool's schema.\n"
            "4. Keep the plan strictly minimal.\n\n"
            "Return the proposed plan as structured JSON with a list of steps."
        )
        built = builder.build(
            user_id="system",
            task_id="task_build",
            purpose="planning",
            instruction=instruction,
            intent=intent,
            catalogue=catalogue,
            untrusted_data=state_projection.get("raw_text") if state_projection else None,
        )
        return built.prompt
