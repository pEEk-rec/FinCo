"""Design principle 2: no money-moving tool exists. Not disabled, not denied: not registered."""

import pytest

from copilot.tools.contracts import SideEffect
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry, list_specs, register

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
