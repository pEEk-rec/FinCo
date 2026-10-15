"""Design principle 2: no money-moving tool exists. Not disabled, not denied: not registered."""

import pytest

from copilot.tools.alerts import register_alert_tools
from copilot.tools.buckets import register_bucket_tools
from copilot.tools.calendar import register_calendar_tools
from copilot.tools.commitments import register_commitment_tools
from copilot.tools.contracts import SideEffect
from copilot.tools.financial import register_financial_tools
from copilot.tools.goals import register_goals_tools
from copilot.tools.investigation import register_investigation_tools
from copilot.tools.memory import register_memory_tools
from copilot.tools.readiness import register_readiness_tools
from copilot.tools.registry import clear_registry, list_specs, register
from copilot.tools.whatif import register_whatif_tools

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
    yield list_specs()
    clear_registry()




def test_registry_is_not_empty(real_registry):
    # Guards against this test passing vacuously on an empty registry.
    assert len(real_registry) >= 6


def test_no_money_movement_tools_registered(real_registry):
    for spec in real_registry:
        if spec.name == "detect_transfers":
            continue
        text = f"{spec.name} {spec.description}".lower()
        for word in BANNED_WORDS:
            assert word not in text, f"Tool {spec.name!r} mentions money-movement word {word!r}"


def test_no_external_tools_registered(real_registry):
    external = [s.name for s in real_registry if s.side_effect is SideEffect.EXTERNAL]
    assert external == []
