"""
Financial tools: pure functions with hand-computed values, then handlers through the executor.
"""

from datetime import datetime
from pathlib import Path

import pytest

from copilot.audit.events import list_events
from copilot.core.errors import ErrorCode
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_transaction,
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.financial import (
    budget_status,
    compute_balance,
    days_elapsed_in_month,
    net_spend_by_category,
    register_financial_tools,
    run_rate_forecast,
)
from copilot.tools.registry import clear_registry

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")
T0 = "2024-01-01T00:00:00Z"


def tx(
    tx_id: str,
    amount: int,
    category: str | None = None,
    when: str = "2024-01-10T10:00:00Z",
    account: str = "a1",
) -> Transaction:
    return Transaction(
        id=tx_id,
        user_id="u1",
        account_id=account,
        occurred_at=when,
        amount_paise=amount,
        direction="debit" if amount > 0 else "credit",
        merchant_raw=f"UPI-{tx_id}",
        description="d",
        category_id=category,
        created_at=T0,
    )


# ---------------------------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------------------------


def test_net_spend_nets_refunds_within_category():
    txs = [tx("1", 1000, "food"), tx("2", 500, "food"), tx("3", -300, "food")]
    assert net_spend_by_category(txs) == {"food": 1200}


def test_net_spend_floors_category_at_zero():
    # Refund for last month's purchase is larger than this month's spend
    txs = [tx("1", 200, "food"), tx("2", -500, "food"), tx("3", 100, "travel")]
    assert net_spend_by_category(txs) == {"travel": 100}


def test_uncategorised_income_is_not_spend():
    txs = [tx("salary", -5_000_000), tx("chai", 2000), tx("m", 700, "food")]
    assert net_spend_by_category(txs) == {None: 2000, "food": 700}


def test_category_totals_sum_to_total_spend():
    txs = [tx("1", 1000, "a"), tx("2", 2500, "b"), tx("3", 333), tx("4", -100, "a")]
    totals = net_spend_by_category(txs)
    assert sum(totals.values()) == 900 + 2500 + 333


@pytest.mark.parametrize(
    "spent, limit, warn, expected",
    [
        (0, 1000, 80, (0, "ok")),
        (799, 1000, 80, (79, "ok")),  # one paisa below the threshold
        (800, 1000, 80, (80, "warning")),  # exactly at the threshold
        (1000, 1000, 80, (100, "warning")),  # exactly at the limit is not exceeded
        (1001, 1000, 80, (100, "exceeded")),  # one paisa over
        (29, 100, 29, (29, "warning")),  # float math once returned 28 / ok here
        (1, 3, 34, (33, "ok")),  # 33.3% < 34%
        (0, 0, 80, (None, "ok")),
        (1, 0, 80, (None, "exceeded")),
        (0, 1000, 0, (0, "ok")),  # nothing spent never warns
        (1, 1000, 0, (0, "warning")),
    ],
)
def test_budget_status_boundaries(spent, limit, warn, expected):
    assert budget_status(spent, limit, warn) == expected


@pytest.mark.parametrize(
    "spent, elapsed, days, expected",
    [
        (1500, 15, 31, 3100),  # mid month: 1500 / 15 * 31
        (1000, 1, 31, 31000),  # day 1
        (4000, 31, 31, 4000),  # last day: forecast equals spend
        (0, 10, 30, 0),  # zero spend
        (100, 3, 31, 1033),  # 1033.33 rounds down
        (100, 6, 31, 517),  # 516.67 rounds up
        (1, 2, 29, 15),  # 14.5 rounds half up
        (500, 0, 31, 500),  # no day elapsed (future month)
    ],
)
def test_run_rate_forecast(spent, elapsed, days, expected):
    assert run_rate_forecast(spent, elapsed, days) == expected


def test_run_rate_forecast_rejects_negative_spend():
    with pytest.raises(ValueError):
        run_rate_forecast(-1, 5, 31)


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2024, 1, 1, 0, 0, tzinfo=IST), 1),
        (datetime(2024, 1, 15, 12, 0, tzinfo=IST), 15),
        (datetime(2024, 1, 31, 23, 59, tzinfo=IST), 31),
        (datetime(2024, 1, 31, 18, 30, tzinfo=IST).astimezone(IST), 31),
        (datetime(2024, 2, 1, 0, 0, tzinfo=IST), 31),  # past month counts fully
        (datetime(2023, 12, 31, 23, 59, tzinfo=IST), 0),  # future month
    ],
)
def test_days_elapsed_in_month_uses_ist(now, expected):
    assert days_elapsed_in_month(2024, 1, now) == expected


def test_days_elapsed_converts_utc_to_ist():
    # 2024-01-31 19:00 UTC is already Feb 1 in IST, so January is complete
    utc_now = datetime.fromisoformat("2024-01-31T19:00:00+00:00")
    assert days_elapsed_in_month(2024, 2, utc_now) == 1


def test_compute_balance():
    # opening 10,000.00; spend 1,000.00; salary 5,000.00 -> 14,000.00
    assert compute_balance(1_000_000, [tx("1", 100_000), tx("2", -500_000)]) == 1_400_000


# ---------------------------------------------------------------------------------------------
# Through the executor
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def ctx():
    clear_registry()
    register_financial_tools()
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at=T0))
    insert_user(conn, User(id="u2", created_at=T0))
    insert_account(
        conn,
        Account(
            id="a1", user_id="u1", name="Savings", opening_balance_paise=1_000_000, created_at=T0
        ),
    )
    insert_account(conn, Account(id="a2", user_id="u1", name="Wallet", created_at=T0))
    insert_account(conn, Account(id="b1", user_id="u2", name="Other", created_at=T0))
    for cat_id, name in (("food", "Food"), ("travel", "Travel")):
        insert_category(conn, Category(id=cat_id, user_id="u1", name=name, created_at=T0))
    insert_category(conn, Category(id="u2cat", user_id="u2", name="Food", created_at=T0))

    for t in (
        tx("t1", 1000, "food"),
        tx("t2", 500, "food", when="2024-01-20T10:00:00Z"),
        tx("t3", 2000, None, when="2024-01-25T10:00:00Z"),
        tx("t4", -5000, None, when="2024-01-26T10:00:00Z"),  # salary
        tx("t5", -200, "food", when="2024-01-27T10:00:00Z"),  # refund
        tx("t6", 700, "travel", account="a2"),
        # 23:59 IST on Jan 31 (18:29Z) belongs to January
        tx("edge_jan", 100, "travel", when="2024-01-31T23:59:00+05:30"),
        # 00:00 IST on Feb 1 (18:30Z Jan 31) belongs to February
        tx("edge_feb", 9999, "travel", when="2024-02-01T00:00:00+05:30"),
    ):
        insert_transaction(conn, t)
    insert_budget(
        conn,
        Budget(
            id="b_food", user_id="u1", category_id="food", limit_paise=1300, warn_threshold_pct=80
        ),
    )
    insert_budget(
        conn,
        Budget(
            id="b_trav", user_id="u1", category_id="travel", limit_paise=800, warn_threshold_pct=80
        ),
    )
    conn.commit()
    clock = datetime(2024, 1, 15, 12, 0, tzinfo=IST)
    yield ExecutionContext(conn, "u1", "run1", POLICY, clock)
    clear_registry()


def run(ctx, name, args, approved=False):
    result = execute_tool(ctx, name, args, approved=approved)
    return result


def test_aggregate_spend_by_category(ctx):
    out = run(ctx, "aggregate_spend_by_category", {"year": 2024, "month": 1}).data
    totals = {t.category_id: t.total_spend_paise for t in out.totals}
    # food: 1000 + 500 - 200 = 1300; travel: 700 + 100 (IST edge) = 800; uncategorised: 2000
    assert totals == {"food": 1300, "travel": 800, None: 2000}
    assert out.grand_total_spend_paise == 4100
    assert [t.category_id for t in out.totals] == ["food", "travel", None]


def test_aggregate_february_gets_only_the_ist_edge(ctx):
    out = run(ctx, "aggregate_spend_by_category", {"year": 2024, "month": 2}).data
    assert {t.category_id: t.total_spend_paise for t in out.totals} == {"travel": 9999}


def test_check_budgets(ctx):
    out = run(ctx, "check_budgets", {"year": 2024, "month": 1}).data
    statuses = {s.category_id: s for s in out.statuses}
    # food 1300/1300: exactly at the limit -> warning, not exceeded
    assert (statuses["food"].spent_paise, statuses["food"].pct_used) == (1300, 100)
    assert statuses["food"].status == "warning"
    # travel 800/800 -> warning; one more paisa -> exceeded
    assert statuses["travel"].status == "warning"
    insert_transaction(ctx.conn, tx("one_paisa", 1, "travel", when="2024-01-28T10:00:00Z"))
    out = run(ctx, "check_budgets", {"year": 2024, "month": 1}).data
    assert {s.category_id: s.status for s in out.statuses}["travel"] == "exceeded"


def test_refund_brings_budget_back_under(ctx):
    insert_transaction(ctx.conn, tx("refund", -1300, "food", when="2024-01-28T10:00:00Z"))
    out = run(ctx, "check_budgets", {"year": 2024, "month": 1}).data
    food = {s.category_id: s for s in out.statuses}["food"]
    assert (food.spent_paise, food.status) == (0, "ok")


def test_forecast_mid_month(ctx):
    out = run(
        ctx, "forecast_category_spend", {"year": 2024, "month": 1, "category_id": "food"}
    ).data
    # Clock is Jan 15 IST; month-to-date food net spend over the whole month so far = 1300
    assert (out.spent_so_far_paise, out.days_elapsed, out.days_in_month) == (1300, 15, 31)
    assert out.projected_spend_paise == 2687  # 1300 / 15 * 31 = 2686.67
    assert out.method == "run_rate"


def test_forecast_unknown_category_not_found(ctx):
    r = run(ctx, "forecast_category_spend", {"year": 2024, "month": 1, "category_id": "u2cat"})
    assert r.error.code == ErrorCode.NOT_FOUND


def test_get_balance_all_accounts(ctx):
    ctx.clock = datetime(2024, 3, 1, tzinfo=IST)
    out = run(ctx, "get_balance", {}).data
    # opening 1,000,000 - (1000+500+2000-5000-200+100+9999) on a1, - 700 on a2
    assert out.balance_paise == 1_000_000 - 8399 - 700
    assert out.account_ids == ["a1", "a2"]


def test_get_balance_ignores_future_transactions(ctx):
    # At Jan 15 12:00 IST only t1 (Jan 10) and t6 (Jan 10) have happened
    assert run(ctx, "get_balance", {"account_id": "a1"}).data.balance_paise == 1_000_000 - 1000
    assert run(ctx, "get_balance", {"account_id": "a2"}).data.balance_paise == -700


def test_get_balance_other_users_account_not_found(ctx):
    assert run(ctx, "get_balance", {"account_id": "b1"}).error.code == ErrorCode.NOT_FOUND


def test_get_transactions(ctx):
    start, end = "2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"
    out = run(ctx, "get_transactions", {"start_utc": start, "end_utc": end}).data
    assert [t.id for t in out.transactions][:2] == ["t1", "t6"]
    limited = run(ctx, "get_transactions", {"start_utc": start, "end_utc": end, "limit": 2}).data
    assert len(limited.transactions) == 2
    food = run(
        ctx, "get_transactions", {"start_utc": start, "end_utc": end, "category_id": "food"}
    ).data
    assert {t.id for t in food.transactions} == {"t1", "t2", "t5"}


@pytest.mark.parametrize(
    "args",
    [
        {"start_utc": "yesterday", "end_utc": "tomorrow"},
        {"start_utc": "2024-01-01T00:00:00", "end_utc": "2024-02-01T00:00:00Z"},
        {"start_utc": "2024-02-01T00:00:00Z", "end_utc": "2024-01-01T00:00:00Z"},
        {"start_utc": "2024-01-01T00:00:00Z", "end_utc": "2024-02-01T00:00:00Z", "limit": 0},
    ],
)
def test_get_transactions_rejects_bad_input(ctx, args):
    assert run(ctx, "get_transactions", args).error.code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("args", [{"year": 2024, "month": 13}, {"year": 2024, "month": 0}, {}])
def test_month_input_validated(ctx, args):
    assert run(ctx, "check_budgets", args).error.code == ErrorCode.INVALID_INPUT


def test_recategorize_blocked_without_approval(ctx):
    r = run(ctx, "recategorize_transaction", {"transaction_id": "t3", "new_category_id": "food"})
    assert r.error.code == ErrorCode.APPROVAL_REQUIRED
    assert get_transaction(ctx.conn, "u1", "t3").category_id is None
    assert list_events(ctx.conn, "u1", event_type="transaction_recategorized") == []


def test_recategorize_changes_totals_and_audits_before_after(ctx):
    args = {"transaction_id": "t3", "new_category_id": "food"}
    out = run(ctx, "recategorize_transaction", args, approved=True).data
    assert (out.previous_category_id, out.new_category_id) == (None, "food")

    moved = get_transaction(ctx.conn, "u1", "t3")
    assert (moved.category_id, moved.category_source, moved.category_confidence) == (
        "food",
        "user",
        1.0,
    )

    [event] = list_events(ctx.conn, "u1", event_type="transaction_recategorized")
    assert event.id == out.audit_event_id
    assert event.entity_id == "t3"
    assert event.before == {
        "category_confidence": None,
        "category_id": None,
        "category_source": "none",
        "needs_review": False,
    }
    assert event.after == {
        "category_confidence": 1.0,
        "category_id": "food",
        "category_source": "user",
        "needs_review": False,
    }

    totals = run(ctx, "aggregate_spend_by_category", {"year": 2024, "month": 1}).data
    assert {t.category_id: t.total_spend_paise for t in totals.totals} == {
        "food": 3300,
        "travel": 800,
    }
    assert totals.grand_total_spend_paise == 4100  # moving spend never changes the total


@pytest.mark.parametrize(
    "args",
    [
        {"transaction_id": "missing", "new_category_id": "food"},
        {"transaction_id": "t3", "new_category_id": "missing"},
        {"transaction_id": "t3", "new_category_id": "u2cat"},  # another user's category
    ],
)
def test_recategorize_not_found(ctx, args):
    r = run(ctx, "recategorize_transaction", args, approved=True)
    assert r.error.code == ErrorCode.NOT_FOUND
    assert get_transaction(ctx.conn, "u1", "t3").category_id is None


def test_recategorize_to_uncategorised(ctx):
    args = {"transaction_id": "t1", "new_category_id": None}
    assert run(ctx, "recategorize_transaction", args, approved=True).ok
    assert get_transaction(ctx.conn, "u1", "t1").category_id is None


def test_user_correction_resolves_review_flag_and_undo_restores_it(ctx):
    from copilot.tools.undo import (
        UNDO_TOOL,
        UndoInput,  # noqa: F401  (registered by the executor path)
    )

    ctx.conn.execute("UPDATE transactions SET needs_review = 1 WHERE id = 't3'")
    ctx.conn.commit()
    out = run(
        ctx,
        "recategorize_transaction",
        {"transaction_id": "t3", "new_category_id": "food"},
        approved=True,
    ).data
    assert get_transaction(ctx.conn, "u1", "t3").needs_review is False

    from copilot.tools.registry import get as get_tool
    from copilot.tools.registry import register

    if get_tool("undo") is None:
        register(UNDO_TOOL)
    ctx.policy = ctx.policy.model_copy(update={"tools": {**ctx.policy.tools, "undo": ctx.policy.tools.get("recategorize_transaction")}})
    result = run(ctx, "undo", {"audit_event_id": out.audit_event_id}, approved=True)
    assert result.ok, result.error
    restored = get_transaction(ctx.conn, "u1", "t3")
    assert (restored.category_id, restored.needs_review) == (None, True)
