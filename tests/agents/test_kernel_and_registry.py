"""The agent kernel runs its steps in order and keeps a trace; every declared agent resolves."""

import importlib

import pytest

from copilot.agents.checkin import CheckinAgent
from copilot.agents.kernel import Agent, run_agent
from copilot.agents.registry import AGENTS
from copilot.learning.beta import posterior_mean, step
from copilot.verify.claims import claim_check, holds


class Toy(Agent[int]):
    """Candidates are numbers; even ones survive verification; 4 is refused when proposing."""

    name = "toy"

    def __init__(self, items, gate=None):
        self.items, self.gate, self.committed, self.finished = items, gate, [], False

    def precheck(self):
        return self.gate

    def perceive(self):
        return list(self.items), [("seed", "known not worth it")]

    def rank(self, c):
        return sorted(c, reverse=True)

    def verify(self, c):
        return (c % 2 == 0, "even" if c % 2 == 0 else "odd")

    def propose(self, c, checked):
        return (None, "four is refused") if c == 4 else (f"say {c}", checked)

    def commit(self, c, proposal, checked):
        self.committed.append(proposal)
        return proposal

    def finish(self, run):
        self.finished = True


def test_the_loop_ranks_verifies_proposes_and_commits_once():
    agent = Toy([1, 2, 4, 5, 6])
    run = run_agent(agent)
    assert run.outcome == "done" and run.result == "say 6" and agent.committed == ["say 6"]
    # 6 is the highest, survives its check and is committed: nothing after it is looked at
    assert [s.name for s in run.steps] == ["perceive", "verify", "commit"]


def test_dropped_candidates_are_kept_with_their_reason_and_the_next_one_is_tried():
    run = run_agent(Toy([5, 4, 3, 2]))
    assert run.result == "say 2"
    assert (
        ("5", "odd") in run.dropped
        and ("4", "four is refused") in run.dropped
        and ("seed", "known not worth it") in run.dropped
    )


def test_a_precheck_stops_the_run_before_anything_is_looked_at():
    agent = Toy([2], gate="quiet_hours")
    run = run_agent(agent)
    assert (
        run.outcome == "quiet_hours"
        and not run.acted
        and agent.committed == []
        and not agent.finished
    )


def test_nothing_worth_doing_is_an_outcome_not_an_error():
    agent = Toy([1, 3])
    run = run_agent(agent)
    assert run.outcome == "nothing_to_do" and agent.finished and len(run.dropped) == 3


def test_the_checkin_agent_is_a_kernel_agent():
    assert issubclass(CheckinAgent, Agent)


@pytest.mark.parametrize("info", AGENTS, ids=lambda a: a.name)
def test_every_declared_agent_points_at_real_code(info):
    module, func = info.entry.split(":")
    assert callable(getattr(importlib.import_module(module), func))
    assert info.goal and info.tools and info.checks and info.output


def test_the_shared_learning_arithmetic_is_bounded():
    assert posterior_mean(0, 0) == 0.5
    a, b = step(2000, 2000, success=False, weight_milli=10_000)
    assert a == 2000 and b == 12000 and 0 < posterior_mean(a, b) < 0.5
    assert step(1, 1, success=True, weight_milli=-5000) == (1, 1)


def test_claims_are_checked_number_by_number():
    assert claim_check("Rs 1,200 over by 300", ["Rs 1,200", "300"]) == []
    assert holds("97 percent", ["Rs 10"]) == (False, "uncomputed number 97")
