"""
The personal-model tools through `execute_tool`, and rules 7 and 10 of PLAN_AGENTIC_V2:
budgets, goals, rules and merges change only by a user action; nothing anywhere moves money.
"""

import re
from datetime import datetime

import pytest

from copilot.common.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Category, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.personal import PERSONAL_TOOLS, register_personal_tools
from copilot.tools.registry import clear_registry, list_specs
from copilot.tools.understand import UNDERSTAND_TOOLS, register_understand_tools

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=IST)


@pytest.fixture
def make_ctx():
    clear_registry()
    register_personal_tools()
    register_understand_tools()
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at=T0))
    insert_account(
        conn, Account(id="acc", user_id=USER, name="S", opening_balance_paise=0, created_at=T0)
    )
    for cid in ("food", "housing"):
        insert_category(conn, Category(id=cid, user_id=USER, name=cid.title(), created_at=T0))
    policy = load_policy("config/policy.yaml")

    def make(actor="user", policy_override=None):
        return ExecutionContext(
            conn=conn,
            user_id=USER,
            run_id="r",
            policy=policy_override or policy,
            actor=actor,
            clock=NOW,
        )

    make.conn = conn
    make.policy = policy
    yield make
    clear_registry()


def test_the_profile_round_trips_through_the_tools_and_the_agent_cannot_state_a_value(make_ctx):
    ok = execute_tool(make_ctx("user"), "profile_set", {"field": "nudge_style", "value": "direct"})
    assert ok.ok, ok.error
    got = execute_tool(make_ctx("agent"), "profile_get", {})
    assert (
        got.ok and got.data.data["values"]["nudge_style"] == "direct" and got.data.data["interview"]
    )
    denied = execute_tool(
        make_ctx("agent"), "profile_set", {"field": "nudge_style", "value": "gentle"}
    )
    assert not denied.ok and denied.error.code.value == "DENIED_BY_POLICY"


def test_the_agent_may_suggest_but_the_suggestion_is_not_used_until_confirmed(make_ctx):
    assert execute_tool(make_ctx("agent"), "profile_infer", {}).ok
    assert not execute_tool(make_ctx("agent"), "profile_confirm", {"field": "income"}).ok


def test_the_check_in_can_be_run_by_the_system_and_answered_only_by_the_user(make_ctx):
    res = execute_tool(make_ctx("system"), "run_checkin", {"ignore_timing": True})
    assert res.ok and res.data.sent is False  # an empty ledger has nothing worth saying
    assert not execute_tool(
        make_ctx("agent"), "respond_checkin", {"checkin_id": "x", "response": "acted"}
    ).ok


def test_shared_expenses_through_the_tools_balance_to_zero(make_ctx):
    g = execute_tool(make_ctx("user"), "create_split_group", {"name": "Flat", "others": ["Asha"]})
    gid = g.data.data["group_id"]
    me, asha = (m["id"] for m in g.data.data["members"])
    assert execute_tool(
        make_ctx("user"),
        "add_split_expense",
        {"group_id": gid, "paid_by": me, "amount_paise": 10_001, "note": "milk"},
    ).ok
    view = execute_tool(make_ctx("agent"), "split_balances", {"group_id": gid}).data.data
    assert sum(b["net_paise"] for b in view["balances"]) == 0
    assert not execute_tool(
        make_ctx("agent"), "add_split_expense", {"group_id": gid, "paid_by": me, "amount_paise": 5}
    ).ok


# ---- Rule 7: only a user action changes budgets, goals, rules and merges ---------------------------------------
USER_ONLY = [
    ("budget_apply", {}),
    ("budget_move", {"from_category": "a", "to_category": "b", "amount_paise": 1}),
    ("profile_set", {"field": "nudge_style", "value": "gentle"}),
    ("answer_shop", {"category_id": "food", "entity_id": "x"}),
    ("merge_entities", {"keep": "a", "absorb": "b"}),
    ("split_entity", {"entity_id": "a", "alias_ids": ["x"]}),
    ("decide_rule_proposal", {"proposal_id": "p", "accept": True}),
    (
        "record_split_settlement",
        {"group_id": "g", "from_member": "a", "to_member": "b", "amount_paise": 1},
    ),
    ("mark_subscription", {"series_id": "s", "note": "unused"}),
]


def check_rule7(make_ctx, policy=None):
    for tool, args in USER_ONLY:
        res = execute_tool(make_ctx("agent", policy), tool, args)
        assert not res.ok and res.error.code.value == "DENIED_BY_POLICY", (
            f"the agent could use {tool}"
        )


def test_rule7_holds(make_ctx):
    check_rule7(make_ctx)


def test_rule7_fails_when_the_agent_is_allowed_to(make_ctx):
    loose = (
        make_ctx.policy.model_copy(deep=True)
        if hasattr(make_ctx.policy, "model_copy")
        else make_ctx.policy
    )
    for tool, _ in USER_ONLY:
        rules = loose.tools[tool]
        loose.tools[tool] = type(rules)(
            **{
                **(rules.model_dump() if hasattr(rules, "model_dump") else dict(rules)),
                "agent": "allow",
            }
        )
    with pytest.raises(AssertionError):
        check_rule7(make_ctx, loose)


# ---- Rule 10: no money movement and no payment initiation, including settle-ups ---------------------------------
BANNED = {
    "pay",
    "transfer",
    "send",
    "withdraw",
    "deposit",
    "remit",
    "buy",
    "sell",
    "trade",
    "upi",
    "neft",
    "imps",
}


def money_words(specs) -> list[str]:
    found = []
    for s in specs:
        words = set(re.findall(r"[a-z]+", f"{s.name} {s.description}".lower()))
        hit = sorted(words & BANNED)
        if hit:
            found.append(f"{s.name}: {hit}")
    return found


def check_rule10():
    names = {s.name for s in (*PERSONAL_TOOLS, *UNDERSTAND_TOOLS)}
    registered = [s for s in list_specs() if s.name in names]
    assert len(registered) == len(names) >= 20, "the new tools are not all registered"
    assert not money_words(registered), money_words(registered)


def test_rule10_holds(make_ctx):
    check_rule10()


def test_rule10_fails_when_a_payment_tool_is_registered(make_ctx):
    from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
    from copilot.tools.registry import register

    class In(ToolInput):
        pass

    register(ToolSpec(name="send_money_to_friend", description="Send money to a friend.", input_model=In,
                      output_model=ToolOutput, side_effect=SideEffect.WRITE_LOGICAL, handler=lambda ctx, **k: ToolOutput()))  # fmt: skip
    names = {s.name for s in (*PERSONAL_TOOLS, *UNDERSTAND_TOOLS)} | {"send_money_to_friend"}
    registered = [s for s in list_specs() if s.name in names]
    assert money_words(registered), "the check must notice a money tool"
