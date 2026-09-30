import pytest

from copilot.models.run_state import RunState
from copilot.planner.router import ROUTES, Planner, TrivialRouter
from copilot.tools.contracts import SideEffect
from copilot.tools.financial import FINANCIAL_TOOLS


def plan_for(intent: str | None) -> list[str]:
    state = RunState(run_id="r1", user_id="u1", intent=intent, created_at="2024-01-01T00:00:00Z")
    return TrivialRouter().plan(state)


@pytest.mark.parametrize(
    "intent, expected",
    [
        ("What is my balance?", ["get_balance"]),
        ("Am I over BUDGET this month", ["check_budgets"]),
        ("how much have I spent on food", ["aggregate_spend_by_category"]),
        ("forecast my travel spending", ["aggregate_spend_by_category", "forecast_category_spend"]),
        ("show my transactions", ["get_transactions"]),
        ("balance and budgets please", ["get_balance", "check_budgets"]),
        ("recategorize transaction t1 to food", ["get_transactions"]),
        ("my accounts are in imbalance", []),  # whole words only
        ("hello", []),
        ("", []),
        (None, []),
    ],
)
def test_router_plans(intent, expected):
    assert plan_for(intent) == expected


def test_router_only_routes_to_registered_read_tools():
    reads = {s.name for s in FINANCIAL_TOOLS if s.side_effect is SideEffect.READ}
    routed = {tool for _, tools in ROUTES for tool in tools}
    assert routed <= reads


def test_trivial_router_satisfies_planner_protocol():
    planner: Planner = TrivialRouter()
    assert planner.plan(
        RunState(run_id="r", user_id="u", intent="balance", created_at="2024-01-01T00:00:00Z")
    ) == ["get_balance"]
