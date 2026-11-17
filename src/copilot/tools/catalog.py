# ruff: noqa: E501  (one family per line reads better than wrapped)
"""
The tool catalogue: every family of tools FinCo has, in one list.

A tool is something the agent (or the user, or a runtime job) can *do*. Each family lives in its
own module under `copilot/tools/` and registers its `ToolSpec`s. This file is the only place that
knows all of them, so:

* adding a family means adding one line here (plus its rules in `config/policy.yaml` and its entry
  in `config/planner_capabilities.yaml`; `tests/tools/test_catalog.py` fails if either is missing);
* everything that needs tools (the agent graphs, the API, the CLI, the runtime, MCP) calls
  `register_all()` and gets the same set, registered once, safely from several threads.

Registering a tool never makes it callable on its own: every call still goes through
`execute_tool`, which applies policy, validation, a savepoint and an audit row.
"""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass

from copilot.tools.registry import get


@dataclass(frozen=True)
class Family:
    name: str  # what a reader would call it
    module: str
    register: str  # the function in `module` that registers the family
    probe: str  # one tool of the family: if it is registered, the family is
    api_only: bool = False  # registered by the API, not offered to the agent graphs


FAMILIES: tuple[Family, ...] = (
    Family("ledger and categories", "copilot.tools.financial", "register_financial_tools", "get_financial_state"),
    Family("goals", "copilot.tools.goals", "register_goals_tools", "create_goal"),
    Family("what-if", "copilot.tools.whatif", "register_whatif_tools", "run_whatif"),
    Family("investigations", "copilot.tools.investigation", "register_investigation_tools", "investigate_anomaly"),
    Family("alerts", "copilot.tools.alerts", "register_alert_tools", "evaluate_alerts"),
    Family("commitments", "copilot.tools.commitments", "register_commitment_tools", "create_commitment"),
    Family("buckets", "copilot.tools.buckets", "register_bucket_tools", "create_bucket"),
    Family("cash calendar", "copilot.tools.calendar", "register_calendar_tools", "get_calendar"),
    Family("investment readiness", "copilot.tools.readiness", "register_readiness_tools", "assess_investment_readiness"),
    Family("goal contributions", "copilot.tools.contributions", "register_contributions_tools", "plan_contributions"),
    Family("memory", "copilot.tools.memory", "register_memory_tools", "list_memories"),
    Family("skills", "copilot.skills.tools", "register_skill_tools", "affordability_check"),
    Family("experiments", "copilot.tools.experiments", "register_experiment_tools", "design_experiment"),
    Family("payment capture", "copilot.tools.capture", "register_capture_tools", "record_payment_event"),
    Family("personal model", "copilot.tools.personal", "register_personal_tools", "profile_get"),
    Family("understanding transactions", "copilot.tools.understand", "register_understand_tools", "run_cascade"),
    Family("bank link", "copilot.tools.aa", "register_aa_tools", "aa_status"),
    Family("adjustments", "copilot.tools.adjustments", "register_adjustment_tools", "list_adjustments"),
    Family("challenges and offers", "copilot.tools.challenges", "register_challenge_tools", "list_offers"),
    Family("rewards and progress", "copilot.tools.rewards", "register_rewards_tools", "get_user_progress"),
    Family("consents and monthly review", "copilot.tools.consents", "register_consent_tools", "approve_consent", api_only=True),
)  # fmt: skip

_LOCK = threading.RLock()


def register_all(include_api_only: bool = False) -> None:
    """Register every family that is not registered yet. Idempotent and thread-safe."""
    with _LOCK:
        for fam in FAMILIES:
            if fam.api_only and not include_api_only:
                continue
            if get(fam.probe) is None:
                getattr(importlib.import_module(fam.module), fam.register)()
