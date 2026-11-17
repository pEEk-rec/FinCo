"""
The agent kernel: one loop for every agent that acts on its own initiative.

    precheck  ->  perceive  ->  rank  ->  for each candidate:  verify  ->  propose  ->  commit

* **precheck**: is now a good time at all? (quiet hours, a budget of interruptions, a schedule)
* **perceive**: look at the user's data and list candidates (things that might be worth acting on).
* **rank**: put the most useful candidate first (for example by the user's own priorities).
* **verify**: recompute the candidate along an independent path. A candidate that does not survive
  its own check is dropped and remembered as dropped, never acted on.
* **propose**: turn it into something to say or do; this step may still refuse (for example when a
  sentence carries a number nobody computed).
* **commit**: act, through the governed tool layer, and stop. One action per run.

Every run returns an `AgentRun` with the steps it took, what it dropped and why, and the outcome,
so a run can always be explained afterwards. The kernel never touches money itself; agents act
only through `execute_tool` or through their own audited writes.

The question-answering agent is a LangGraph graph rather than this loop, because a question needs
planning over many tools; it is the same idea (plan, act, observe, revise) with a planner in the
middle. See `copilot/agents/registry.py` for every agent and how each one runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

Candidate = TypeVar("Candidate")


@dataclass
class Step:
    name: str
    detail: str


@dataclass
class AgentRun:
    agent: str
    outcome: str  # what happened, in a word: "sent", "quiet_hours", "nothing_worth_saying", ...
    result: Any = None
    steps: list[Step] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (candidate, why it was dropped)

    @property
    def acted(self) -> bool:
        return self.result is not None


class Agent(ABC, Generic[Candidate]):
    """One agent. Subclasses fill in the steps; `run_agent` runs them in order."""

    name: str = "agent"
    #: the outcome when every candidate was dropped or there were none
    nothing_outcome: str = "nothing_to_do"
    #: the outcome after a successful commit
    done_outcome: str = "done"

    def precheck(self) -> str | None:
        """A reason not to run now, or None."""
        return None

    @abstractmethod
    def perceive(self) -> tuple[list[Candidate], list[tuple[str, str]]]:
        """Candidates, and things already known not to be worth acting on (with the reason)."""

    def rank(self, candidates: list[Candidate]) -> list[Candidate]:
        return candidates

    def skip(self, candidate: Candidate) -> bool:
        """True for a candidate already acted on recently (no repeats)."""
        return False

    def label(self, candidate: Candidate) -> str:
        return str(candidate)

    @abstractmethod
    def verify(self, candidate: Candidate) -> tuple[bool, str]:
        """Recompute the candidate independently. (holds, how it was checked or why it failed)."""

    @abstractmethod
    def propose(self, candidate: Candidate, checked: str) -> tuple[Any | None, str]:
        """What to say or do, or (None, why not)."""

    @abstractmethod
    def commit(self, candidate: Candidate, proposal: Any, checked: str) -> Any:
        """Act. Returns the result kept on the run."""

    def finish(self, run: AgentRun) -> None:
        """Called once at the end, whatever happened (for example to record the drops)."""


def run_agent(agent: Agent) -> AgentRun:
    run = AgentRun(agent=agent.name, outcome=agent.nothing_outcome)
    reason = agent.precheck()
    if reason:
        run.outcome = reason
        run.steps.append(Step("precheck", reason))
        return run
    candidates, known_drops = agent.perceive()
    run.dropped.extend(known_drops)
    run.steps.append(Step("perceive", f"{len(candidates)} candidate(s)"))
    for candidate in agent.rank(candidates):
        label = agent.label(candidate)
        if agent.skip(candidate):
            run.steps.append(Step("skip", f"{label}: already said recently"))
            continue
        ok, how = agent.verify(candidate)
        run.steps.append(Step("verify", f"{label}: {'holds' if ok else 'dropped'} ({how})"))
        if not ok:
            run.dropped.append((label, how))
            continue
        proposal, why = agent.propose(candidate, how)
        if proposal is None:
            run.steps.append(Step("propose", f"{label}: refused ({why})"))
            run.dropped.append((label, why))
            continue
        run.result = agent.commit(candidate, proposal, how)
        run.outcome = agent.done_outcome
        run.steps.append(Step("commit", label))
        break
    agent.finish(run)
    return run
