"""Design principle 2: no money-moving tool exists. Not disabled, not denied: not registered."""

import re

import pytest

from copilot.skills.tools import register_skill_tools
from copilot.tools.adjustments import register_adjustment_tools
from copilot.tools.alerts import register_alert_tools
from copilot.tools.buckets import register_bucket_tools
from copilot.tools.calendar import register_calendar_tools
from copilot.tools.challenges import register_challenge_tools
from copilot.tools.commitments import register_commitment_tools
from copilot.tools.contracts import SideEffect
from copilot.tools.contributions import register_contributions_tools
from copilot.tools.experiments import register_experiment_tools
from copilot.tools.financial import register_financial_tools
from copilot.tools.goals import register_goals_tools
from copilot.tools.investigation import register_investigation_tools
from copilot.tools.memory import register_memory_tools
from copilot.tools.readiness import register_readiness_tools
from copilot.tools.registry import clear_registry, list_specs, register
from copilot.tools.rewards import register_rewards_tools
from copilot.tools.whatif import register_whatif_tools

#: Whole words that merely start like a banned word: comparing scenarios is not trading.
ALLOWED_TOKENS = {"tradeoff", "tradeoffs"}

BANNED_WORDS = (
    "transfer",
    "pay",
    "send_money",
    "trade",
    "withdraw",
    "deposit",
    "upi",
    "neft",
    "imps",
    "remit",
    "buy",
    "sell",
)


@pytest.fixture
def real_registry():
    """The registry exactly as the application builds it."""
    clear_registry()
    register_financial_tools(register)
    register_goals_tools(register)
    register_whatif_tools(register)
    register_investigation_tools(register)
    register_alert_tools(register)
    register_commitment_tools(register)
    register_bucket_tools(register)
    register_calendar_tools(register)
    register_readiness_tools(register)
    register_memory_tools(register)
    # Phase 4: experiments, challenges, adjustments, rewards and the skill tools
    register_experiment_tools(register)
    register_challenge_tools(register)
    register_adjustment_tools()
    register_rewards_tools(register)
    register_contributions_tools(register)
    register_skill_tools(register)
    yield list_specs()
    clear_registry()


def test_registry_is_not_empty(real_registry):
    # Guards against this test passing vacuously on an empty registry.
    assert len(real_registry) >= 6


def test_the_phase_4_tools_are_in_the_checked_registry(real_registry):
    names = {s.name for s in real_registry}
    assert {
        "design_experiment",
        "accept_offer",
        "accept_adjustment",
        "award_xp_and_badges",
        "confirm_review_integrity",
        "suggest_challenges",
    } <= names


def test_no_money_movement_tools_registered(real_registry):
    for spec in real_registry:
        if spec.name == "detect_transfers":
            continue
        text = f"{spec.name} {spec.description}".lower().replace("trade-off", "tradeoff")
        # Words and word starts, so "payment" and "transfers" are caught, "send_money" is caught
        # as a phrase, and the allowed "tradeoffs" (comparing scenarios) is not mistaken for "trade".
        spaced = " " + re.sub(r"[^a-z]+", " ", text) + " "
        for word in BANNED_WORDS:
            for match in re.finditer(r"(?<= )" + re.escape(word.replace("_", " ")), spaced):
                token = re.match(r"[a-z]+", spaced[match.start() :]).group(0)
                if token in ALLOWED_TOKENS:
                    continue
                raise AssertionError(
                    f"Tool {spec.name!r} mentions money-movement word {word!r} ({token!r})"
                )


def test_no_external_tools_registered(real_registry):
    external = [s.name for s in real_registry if s.side_effect is SideEffect.EXTERNAL]
    assert external == []
