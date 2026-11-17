"""
The arithmetic every learner here shares: a Beta posterior kept as integer milli-counts.

A learner keeps two counts for a thing (how often it worked, how often it did not), starting from a
small prior so one observation never swings it far. Its belief is the posterior mean
`alpha / (alpha + beta)`. Counts are stored in thousandths so a half-weight observation (a dismissed
nudge) stays an integer. Every learner in `copilot.learning` and `copilot.capture.learning` uses
these two functions, so they all move the same way and can all be inspected and reset the same way.
"""

from __future__ import annotations

MILLI = 1000


def posterior_mean(alpha_milli: int, beta_milli: int) -> float:
    """Belief that the thing works, between 0 and 1. 0.5 when nothing is known."""
    total = alpha_milli + beta_milli
    return alpha_milli / total if total > 0 else 0.5


def step(
    alpha_milli: int, beta_milli: int, success: bool, weight_milli: int = MILLI
) -> tuple[int, int]:
    """One observation, never letting a count fall to zero."""
    if success:
        return max(1, alpha_milli + weight_milli), beta_milli
    return alpha_milli, max(1, beta_milli + weight_milli)
