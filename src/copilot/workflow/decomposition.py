"""
Multi-agent intent decomposition, validation, template fallback, and routing
(PLAN_PHASE3 Section 5.13).
"""


import json
import logging
import sqlite3
from typing import Any

import yaml
from pydantic import BaseModel, Field

from copilot.audit.events import record_event
from copilot.context.builder import ContextBuilder
from copilot.core.config import PROJECT_ROOT
from copilot.llm.client import LLMClient, extract_json
from copilot.models.agentic import Intent
from copilot.models.phase3 import SubQuestion

logger = logging.getLogger(__name__)

MULTI_DOMAIN_INTENTS = {
    "affordability",
    "tradeoff_compare",
    "contribution_check",
    "trip_planning",
    "challenge_affordability",
}


def load_decomposition_config() -> dict[str, Any]:
    """Load decomposition templates and registered question kinds from YAML config."""
    config_path = PROJECT_ROOT / "config" / "decomposition.yaml"
    if not config_path.is_file():
        return {
            "max_subquestions_per_task": 4,
            "decomposition_templates": {},
            "registered_question_kinds": {},
        }
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


class LLMDecompositionProposal(BaseModel):
    """Schema for LLM-proposed decomposition."""

    subquestions: list[SubQuestion] = Field(default_factory=list)


class DecompositionValidator:
    """
    Validates LLM-proposed decomposition against config, user isolation, and intent coverage.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or load_decomposition_config()
        self.config = cfg
        self.max_subquestions = (
            cfg.get("max_subquestions_per_task", 4)
            if isinstance(cfg, dict)
            else getattr(cfg, "max_subquestions_per_task", 4)
        )
        self.templates = (
            cfg.get("decomposition_templates", {})
            if isinstance(cfg, dict)
            else getattr(cfg, "decomposition_templates", {})
        )
        self.registered_kinds = (
            cfg.get("registered_question_kinds", {})
            if isinstance(cfg, dict)
            else getattr(cfg, "registered_question_kinds", {})
        )

    def validate(
        self,
        subquestions: list[SubQuestion],
        intent_type: str,
        user_id: str | None = None,
        valid_user_ids: set[str] | None = None,
        other_user_ids: set[str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Validate subquestions. Returns (True, None) on success, or (False, reason) on failure.
        """
        if not subquestions:
            return False, "Subquestions list is empty"

        if len(subquestions) > self.max_subquestions:
            return (
                False,
                f"Proposed {len(subquestions)} sub-questions, exceeding maximum budget of "
                f"{self.max_subquestions}",
            )

        # 1. Validate question kinds and domain consistency
        for sq in subquestions:
            if sq.question_kind not in self.registered_kinds:
                return False, f"Unknown question kind: {sq.question_kind}"

            expected_domain = self.registered_kinds[sq.question_kind]
            if sq.domain != expected_domain:
                return (
                    False,
                    f"Domain mismatch for {sq.question_kind}: expected {expected_domain}, "
                    f"got {sq.domain}",
                )

        # 2. Validate tenant isolation: cannot reference other user's entity IDs
        for sq in subquestions:
            for param_key, param_val in sq.parameters.items():
                if isinstance(param_val, str):
                    if other_user_ids and param_val in other_user_ids:
                        return (
                            False,
                            f"Subquestion references another user's entity id: {param_val}",
                        )
                    if valid_user_ids is not None and (
                        param_key.endswith("_id")
                        or param_key in ("goal_id", "bucket_id", "account_id")
                    ):
                        if param_val not in valid_user_ids:
                            return (
                                False,
                                f"Subquestion references entity id not belonging to user: "
                                f"{param_val}",
                            )


        # 3. Validate coverage: must cover required domains for the intent template
        template = self.templates.get(intent_type)
        if template:
            required_domains = {step["domain"] for step in template if "domain" in step}
            proposed_domains = {sq.domain for sq in subquestions}
            missing_domains = required_domains - proposed_domains
            if missing_domains:
                return (
                    False,
                    f"Decomposition misses required domain coverage for {intent_type}: "
                    f"missing {missing_domains}",
                )

        return True, None



def get_deterministic_subquestions(
    intent_type: str,
    parameters: dict[str, Any] | None = None,
) -> list[SubQuestion]:
    """Fallback: builds deterministic subquestions from config templates."""
    cfg = load_decomposition_config()
    templates = cfg.get("decomposition_templates", {})
    params = dict(parameters or {})

    template_steps = templates.get(intent_type)
    if template_steps:
        subquestions = []
        for step in template_steps:
            subquestions.append(
                SubQuestion(
                    domain=step["domain"],
                    question_kind=step["question_kind"],
                    parameters=dict(params),
                )
            )
        return subquestions

    # Default single-domain mappings if intent is not in templates
    domain_map = {
        "cashflow": "cashflow",
        "summarize_period": "cashflow",
        "whatif_add_spend": "cashflow",
        "goal_check": "goals",
        "budget_status": "goals",
        "investment_readiness": "readiness",
        "contribution_plan": "readiness",
        "anomalies": "behaviour",
    }
    domain = domain_map.get(intent_type, "cashflow")
    kind_map = {
        "cashflow": "forecast",
        "goals": "goal_impact",
        "readiness": "readiness_assessment",
        "behaviour": "anomaly_check",
    }
    return [
        SubQuestion(
            domain=domain,  # type: ignore[arg-type]
            question_kind=kind_map.get(domain, "forecast"),
            parameters=dict(params),
        )
    ]


def should_route_to_multi_agent(
    intent: Intent | dict[str, Any] | str,
    subquestions: list[SubQuestion] | None = None,
) -> bool:
    """
    Routing rule (PLAN_PHASE3 Section 5.13):
    Routes to multi-agent ONLY for multi-domain intents (affordability, tradeoff_compare,
    contribution_check, trip_planning, or any intent whose decomposition yields >= 2 domains).
    Single-domain intents keep the Phase 2 single loop.
    """
    if isinstance(intent, Intent):
        intent_type = intent.type
    elif isinstance(intent, dict):
        intent_type = intent.get("type", "")
    else:
        intent_type = str(intent)

    if intent_type in MULTI_DOMAIN_INTENTS:
        return True

    if subquestions:
        unique_domains = {sq.domain for sq in subquestions}
        if len(unique_domains) >= 2:
            return True

    return False


def decompose_intent(
    intent: Intent | dict[str, Any] | str,
    user_data: dict[str, Any] | None = None,
    llm_client: LLMClient | None = None,
    conn: sqlite3.Connection | None = None,
    user_id: str | None = None,
    task_id: str | None = None,
    other_user_ids: set[str] | None = None,
) -> list[SubQuestion]:
    """
    Decompose an intent into typed SubQuestions.
    Attempts LLM proposal first (if client provided), validates strictly,
    and falls back to deterministic templates on any validation failure, error, or LLM-off.
    """
    if isinstance(intent, Intent):
        intent_type = intent.type
        params = intent.model_dump()
    elif isinstance(intent, dict):
        intent_type = intent.get("type", "")
        params = dict(intent)
    else:
        intent_type = str(intent)
        params = {}

    if user_data:
        params.update({k: v for k, v in user_data.items() if k not in params})

    validator = DecompositionValidator()

    # Determine valid user entity IDs if user_id and conn are available
    valid_user_ids: set[str] | None = None
    if user_data and "valid_user_ids" in user_data:
        valid_user_ids = set(user_data["valid_user_ids"])
    elif conn and user_id:
        valid_user_ids = set()
        # Collect goals
        for row in conn.execute("SELECT id FROM goals WHERE user_id = ?", (user_id,)).fetchall():
            valid_user_ids.add(row[0])
        # Collect buckets
        for row in conn.execute("SELECT id FROM buckets WHERE user_id = ?", (user_id,)).fetchall():
            valid_user_ids.add(row[0])
        # Collect accounts
        for row in conn.execute("SELECT id FROM accounts WHERE user_id = ?", (user_id,)).fetchall():
            valid_user_ids.add(row[0])

    if llm_client is not None:
        try:
            builder = ContextBuilder(conn=conn)
            instruction = (
                f"You are a multi-agent decomposition supervisor. "
                f"Decompose the user intent '{intent_type}' into sub-questions.\n"
                'Return JSON matching: {"subquestions": [{"domain": "...", '
                '"question_kind": "...", "parameters": {...}}]}'
            )
            raw_reply, _ = builder.complete(
                client=llm_client,
                user_id=user_id or "user_unknown",
                task_id=task_id or "task_decomposition",
                purpose="decomposition",
                instruction=instruction,
                intent={"type": intent_type, "params": params},
                catalogue=[
                    {"name": k, "description": f"Domain: {v}"}
                    for k, v in validator.registered_kinds.items()
                ],
                untrusted_data=params,
                conn=conn,
            )
            payload = json.loads(extract_json(raw_reply))
            raw_subqs = payload.get("subquestions", [])
            proposed = [SubQuestion.model_validate(sq) for sq in raw_subqs]

            is_valid, reason = validator.validate(
                subquestions=proposed,
                intent_type=intent_type,
                user_id=user_id,
                valid_user_ids=valid_user_ids,
                other_user_ids=other_user_ids,
            )

            if is_valid:
                return proposed

            # Proposal failed validation -> record audit event and fallback
            logger.warning("LLM decomposition proposal failed validation: %s", reason)
            if conn and user_id:
                record_event(
                    conn=conn,
                    user_id=user_id,
                    actor="agent",
                    event_type="validator_fallback",
                    reason=f"Decomposition validation failed: {reason}",
                    run_id=task_id,
                    metadata={"intent_type": intent_type, "validation_error": reason},
                )
        except Exception as exc:
            logger.warning("LLM decomposition error: %s; falling back to deterministic", exc)
            if conn and user_id:
                record_event(
                    conn=conn,
                    user_id=user_id,
                    actor="agent",
                    event_type="validator_fallback",
                    reason=f"Decomposition LLM exception: {exc}",
                    run_id=task_id,
                    metadata={"intent_type": intent_type, "error": str(exc)},
                )

    # Deterministic fallback
    return get_deterministic_subquestions(intent_type, params)
