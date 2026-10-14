"""
Deterministic Plan Validator (PLAN_PHASE2 Section 5.3 & Safety Rule 1, 2).

The key safety piece of Phase 2:
- Every tool_name exists AND is planner-selectable
- Args validate strictly against the tool's input schema
- Referenced IDs (categories, goals, accounts, anomalies) exist and belong to the user
- Step count within max_steps (default 5); no empty plans
- No duplicate (tool, args) pairs
- No step after a terminal step
- Plan must include every tool the template marks required for that intent
- On any failure: audits 'plan_rejected' with the reasons, discards the LLM plan,
  and falls back to the deterministic plan. Never partially accepts an invalid plan.
"""

import json
import sqlite3

from pydantic import ValidationError

from copilot.audit.events import record_event
from copilot.config.phase2 import PlanTemplatesConfig, load_plan_templates
from copilot.db.repo import get_account, get_category, get_goal
from copilot.models.agentic import Intent, Plan, PlanStep
from copilot.planner.capabilities import is_planner_selectable
from copilot.tools.contracts import ToolSpec
from copilot.tools.registry import get as get_tool

TERMINAL_TOOLS = frozenset()  # Currently all read/compute tools can be followed by others


class PlanValidator:
    """Deterministic validator enforcing safety, schema, and isolation invariants on plans."""

    def __init__(
        self,
        config: PlanTemplatesConfig | None = None,
        max_steps: int = 5,
    ) -> None:
        self.config = config or load_plan_templates()
        self.max_steps = max_steps

    def validate_plan(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        plan: Plan,
        intent: Intent,
        *,
        audit_on_rejection: bool = True,
    ) -> tuple[bool, list[str]]:
        """
        Validate an autonomous plan against all safety invariants.
        Returns (is_valid, rejection_reasons).
        If invalid and audit_on_rejection=True, writes a 'plan_rejected' audit event.
        """
        reasons: list[str] = []

        # 1. Step bounds
        if not plan.steps:
            reasons.append("Plan contains zero steps")
            self._handle_rejection(conn, user_id, plan, intent, reasons, audit_on_rejection)
            return False, reasons

        if len(plan.steps) > self.max_steps:
            reasons.append(
                f"Step count {len(plan.steps)} exceeds maximum allowed steps ({self.max_steps})"
            )

        # 2. Check each step individually
        seen_steps: set[tuple[str, str]] = set()
        seen_tools: set[str] = set()
        has_terminal = False

        for idx, step in enumerate(plan.steps):
            if has_terminal:
                reasons.append(
                    f"Step {idx} ('{step.tool_name}') appears after a terminal step"
                )

            # Check tool existence in registry
            spec: ToolSpec | None = get_tool(step.tool_name)
            if spec is None:
                reasons.append(f"Tool '{step.tool_name}' does not exist in tool registry")
                continue

            # Check planner selectability (Rule 1)
            if not is_planner_selectable(step.tool_name):
                reasons.append(
                    f"Tool '{step.tool_name}' is not planner-selectable (write/prohibited tool)"
                )
                continue

            # Check terminal status
            if step.tool_name in TERMINAL_TOOLS:
                has_terminal = True

            # Check duplicate step
            normalized_args = json.dumps(step.args, sort_keys=True)
            step_key = (step.tool_name, normalized_args)
            if step_key in seen_steps:
                reasons.append(
                    f"Duplicate step detected for tool '{step.tool_name}' with identical args"
                )
            seen_steps.add(step_key)
            seen_tools.add(step.tool_name)

            # Check schema conformity of args
            try:
                spec.input_model.model_validate(step.args)
            except ValidationError as err:
                reasons.append(
                    f"Args for tool '{step.tool_name}' do not conform to "
                    f"input schema: {err.errors()}"
                )

            # Check user isolation on referenced IDs
            self._validate_entity_isolation(conn, user_id, step, reasons)

        # 3. Check required tools per intent template
        template = self.config.templates.get(intent.type)
        if template:
            for req_tool in template.required_tools:
                if req_tool not in seen_tools:
                    reasons.append(
                        f"Plan for intent '{intent.type}' is missing required tool '{req_tool}'"
                    )

        is_valid = len(reasons) == 0
        if not is_valid:
            self._handle_rejection(conn, user_id, plan, intent, reasons, audit_on_rejection)

        return is_valid, reasons

    def _validate_entity_isolation(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        step: PlanStep,
        reasons: list[str],
    ) -> None:
        """Verify that any database entity ID referenced in args belongs to the user."""
        args = step.args

        # category_id
        cat_id = args.get("category_id")
        if cat_id is not None and isinstance(cat_id, str):
            if get_category(conn, user_id, cat_id) is None:
                reasons.append(
                    f"Referenced category_id '{cat_id}' does not exist for user '{user_id}'"
                )

        # goal_id
        goal_id = args.get("goal_id")
        if goal_id is not None and isinstance(goal_id, str):
            if get_goal(conn, user_id, goal_id) is None:
                reasons.append(
                    f"Referenced goal_id '{goal_id}' does not exist for user '{user_id}'"
                )

        # account_id
        acc_id = args.get("account_id")
        if acc_id is not None and isinstance(acc_id, str):
            if get_account(conn, user_id, acc_id) is None:
                reasons.append(
                    f"Referenced account_id '{acc_id}' does not exist for user '{user_id}'"
                )

        # anomaly_id
        anom_id = args.get("anomaly_id")
        if anom_id is not None and isinstance(anom_id, str):
            row = conn.execute(
                "SELECT 1 FROM anomalies WHERE id = ? AND user_id = ?",
                (anom_id, user_id),
            ).fetchone()
            if row is None:
                reasons.append(
                    f"Referenced anomaly_id '{anom_id}' does not exist for user '{user_id}'"
                )

        # Nested scenario in run_whatif
        if step.tool_name == "run_whatif" and isinstance(args.get("scenario"), dict):
            sc = args["scenario"]
            if sc.get("category_id") and get_category(conn, user_id, sc["category_id"]) is None:
                reasons.append(
                    f"Referenced category_id '{sc['category_id']}' in scenario "
                    "does not exist for user"
                )
            if sc.get("goal_id") and get_goal(conn, user_id, sc["goal_id"]) is None:
                reasons.append(
                    f"Referenced goal_id '{sc['goal_id']}' in scenario does not exist for user"
                )

    def _handle_rejection(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        plan: Plan,
        intent: Intent,
        reasons: list[str],
        audit: bool,
    ) -> None:
        """Audit plan rejection event."""
        if not audit:
            return

        record_event(
            conn,
            user_id=user_id,
            actor="agent",
            event_type="plan_rejected",
            reason=f"Plan validation failed with {len(reasons)} violation(s): {'; '.join(reasons)}",
            entity_type="plan",
            entity_id=plan.task_id,
            after_data={
                "task_id": plan.task_id,
                "intent_type": intent.type,
                "step_count": len(plan.steps),
                "reasons": reasons,
            },
        )
