"""
LLM Planner using Gemini Structured Output (PLAN_PHASE2 Section 5.3 & Stage 2.8).

Proposes a plan from the planner-selectable tool catalogue.
All proposals must pass through the deterministic PlanValidator; any invalid proposal
is audited as 'plan_rejected' and replaced with the deterministic plan.
"""

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from copilot.llm.client import LLMClient, StructuredOutputError, structured_call
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
    ) -> Plan:
        """
        Generate a plan via LLM structured call.
        Falls back to DeterministicPlanner if the client is missing or fails.
        """
        if self.client is None:
            return self.fallback.propose(task_id, user_id, intent, state_projection, tool_catalogue)

        catalogue = tool_catalogue or project_tool_catalogue()
        prompt = self._build_prompt(intent, state_projection or {}, catalogue)

        try:
            proposal = structured_call(
                self.client,
                prompt=prompt,
                output_model=LLMPlanProposal,
                purpose="planning",
            )
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
        """Construct sanitized prompt exposing only selectable tools and high-level intent."""
        cat_lines = []
        for tool in catalogue:
            cat_lines.append(
                f"- Tool: {tool['tool_name']}\n"
                f"  Description: {tool['short_description']}\n"
                f"  Parameters: {tool.get('parameters', {})}"
            )
        catalogue_text = "\n".join(cat_lines)

        intent_summary = (
            f"Intent Type: {intent.type}\n"
            f"Period: {intent.period}\n"
            f"Category ID: {intent.category_id}\n"
            f"Goal ID: {intent.goal_id}\n"
            f"Amount Paise: {intent.amount_paise}\n"
            f"Horizon Months: {intent.horizon_months}"
        )

        return (
            "You are a financial planning agent. "
            "Given the following user intent and available tools,\n"
            "propose a minimal ordered sequence of tool steps to gather evidence and "
            "fulfill the request.\n\n"
            "RULES:\n"
            "1. Choose ONLY from the allowed tools listed below.\n"
            "2. Never call tools that modify state or move money.\n"
            "3. Provide exact parameters adhering to each tool's schema.\n"
            "4. Keep the plan strictly minimal.\n\n"
            f"AVAILABLE TOOLS:\n{catalogue_text}\n\n"
            f"INTENT DETAILS:\n{intent_summary}\n\n"
            "Return the proposed plan as structured JSON with a list of steps."
        )
