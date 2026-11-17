"""
Verifiers: how an agent checks itself before anything reaches the user.

FinCo has one rule for anything the model or an agent produces: it is checked by code before it is
used. The checks live here or next to the agent that needs them, and all of them have the same
shape, `(holds: bool, how: str)`, so the agent kernel and the traces treat them alike:

* `claims.claim_check`: every number in a sentence must appear in the figures that were computed.
* recomputation (`copilot.agents.checkin.verify`): a candidate is recomputed along a second path.
* the reviewer (`copilot.workflow.reviewer`): a Reflexion-style critic over a multi-agent answer,
  with one bounded revision.
* plan validation (`copilot.planner.validator`): a proposed plan may only use allowed tools with
  valid arguments; anything else falls back to the deterministic plan.
* calibration (`copilot.understand.calibration`): a stage's confidence is only believed as far as
  its track record on the user's own answers.
"""

from typing import Protocol


class Verifier(Protocol):
    def __call__(self, *args, **kwargs) -> tuple[bool, str]: ...
