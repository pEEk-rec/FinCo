# ruff: noqa: E501  (descriptions read better on one line)
"""
Every agent in FinCo, declared in one place.

An agent here means something that decides on its own what to do next, using tools, toward a
goal, and checks itself before anything reaches the user. Each entry says what wakes it up, what it
is trying to achieve, how it runs, which tools it may use, how it checks itself, and where its
result goes. `copilot agents` prints this table.

Two ways of running exist, on purpose:

* **graph**: a LangGraph state machine with a planner in the middle. Used when the job is open
  ended (a question can need any of a hundred tools in any order).
* **kernel**: the fixed loop in `copilot.agents.kernel` (precheck, perceive, rank, verify, propose,
  commit). Used when the job is narrow and repeated (a weekly check-in, one decision per run).

The categoriser and the capture lane are deliberately *pipelines*, not free agents: they decide one
transaction at a time, by rules and calibrated confidence, and ask the user when unsure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AgentInfo:
    name: str
    trigger: Literal["question", "schedule", "event"]
    goal: str
    runs_as: Literal["graph", "kernel", "pipeline", "specialist"]
    entry: str  # module:function that runs it
    tools: str  # which tools it may use
    checks: str  # how it verifies itself
    output: str  # where its result goes


AGENTS: tuple[AgentInfo, ...] = (
    AgentInfo(
        "ask", "question",
        "Answer a question about your money from computed figures, never invented ones.",
        "graph", "copilot.api.agent:run_ask",
        "planner-selectable read and compute tools only (config/planner_capabilities.yaml)",
        "plan validator; grounded answers (every figure from a tool); approval for any write",
        "the answer, its plan and its trace",
    ),
    AgentInfo(
        "multi_agent", "question",
        "Split a question that spans several areas across specialists, merge, and review.",
        "graph", "copilot.workflow.multi_agent_graph:build_multi_agent_subgraph",
        "each specialist only its own tool subset (copilot.workflow.specialists)",
        "Reflexion-style reviewer with at most one revision; deterministic merge",
        "a merged answer with findings and gaps",
    ),
    AgentInfo(
        "coach", "question",
        "Answer questions about experiments, challenges and progress.",
        "specialist", "copilot.workflow.specialists:run_specialist",
        "experiment, offer, progress and goal read tools",
        "a partial answer instead of an error when a tool fails",
        "part of the ask agent's answer",
    ),
    AgentInfo(
        "checkin", "schedule",
        "Once in a while, say the one thing that matters most to you, or stay quiet.",
        "kernel", "copilot.agents.checkin:run_checkin",
        "reads budgets, pace, renewals, goals, anomalies and cash flow; writes only its own message",
        "recomputes every candidate along a second path; every number in the text must be computed",
        "the For you screen (at most twice a week, never in quiet hours)",
    ),
    AgentInfo(
        "categoriser", "event",
        "Give every payment a category, or ask you when it is not sure enough.",
        "pipeline", "copilot.understand.ledger:run_categorisation",
        "rules, your answers, similar shops, the brand dictionary, then one batched model request",
        "per-stage calibration on your own answers; a model alone never labels a payment",
        "ledger categories, or a question in the review queue",
    ),
    AgentInfo(
        "capture", "event",
        "When a bank alert arrives, decide whether to ask you right away and what to guess.",
        "pipeline", "copilot.capture.events:record_payment_event",
        "record, label and reconcile payment events",
        "ask policy (known shop, person rule, quiet hours, daily budget); reconciliation never merges on doubt",
        "an in-app prompt or a notification, then the ledger",
    ),
    AgentInfo(
        "monthly_review", "schedule",
        "Write the month's review: what changed, why, and what to look at.",
        "graph", "copilot.workflow.graph:build_monthly_review_graph",
        "read tools and the advice drafts",
        "advice validator (figures from tools); reviewer node",
        "the monthly review page",
    ),
    AgentInfo(
        "runtime", "schedule",
        "Run the scheduled jobs: reconcile, expire prompts, fetch from the bank link, check in, learn.",
        "pipeline", "copilot.runtime.runner:run_due_jobs",
        "each job calls exactly one tool as the system actor",
        "leases so a job never runs twice at once; retries then a dead letter",
        "job runs in the database, visible in the activity timeline",
    ),
)  # fmt: skip


def get(name: str) -> AgentInfo | None:
    return next((a for a in AGENTS if a.name == name), None)
