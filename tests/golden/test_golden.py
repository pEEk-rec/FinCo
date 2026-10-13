"""
Runs every scenario in scenarios.json through the real stack: models -> DB -> executor ->
governance (repo config/policy.yaml) -> financial tools -> audit.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from copilot.audit.events import list_events
from copilot.bank.ingest import ingest_statements
from copilot.bank.mock_bank import MockAAConnector
from copilot.bank.synth import generate_transactions
from copilot.core.config import load_settings
from copilot.core.errors import ToolFailure
from copilot.core.money import rupees_to_paise
from copilot.core.timeutil import IST, month_bounds, month_of, to_utc_iso
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
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import clear_registry

GOLDEN = json.loads((Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8"))
SCENARIOS = GOLDEN["scenarios"]
T0 = "2024-01-01T00:00:00Z"
ALL_TIME = ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")


def ist(text: str) -> datetime:
    """Parse an IST wall-clock string like '2024-03-15T12:00'."""
    return datetime.fromisoformat(text).replace(tzinfo=IST)


def make_tx(spec: dict[str, Any]) -> Transaction:
    paise = rupees_to_paise(spec["rupees"])
    at = to_utc_iso(ist(spec["at_ist"]))
    return Transaction(
        id=spec["id"],
        user_id="u1",
        account_id="a1",
        occurred_at=at,
        amount_paise=paise,
        direction="debit" if paise > 0 else "credit",
        merchant_raw=spec["merchant"],
        description=spec["id"],
        category_id=spec["category"],
        created_at=at,
    )


@pytest.fixture(autouse=True)
def tools():
    clear_registry()
    register_financial_tools()
    yield
    clear_registry()


def build_ctx(scenario: dict[str, Any]) -> ExecutionContext:
    conn = get_connection(":memory:")
    init_db(conn)
    base = GOLDEN["base"]
    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="Savings", created_at=T0))
    for cat in base["categories"]:
        insert_category(conn, Category(id=cat, user_id="u1", name=cat.title(), created_at=T0))
    for spec in base["transactions"] + scenario.get("extra_transactions", []):
        insert_transaction(conn, make_tx(spec))
    for b in base["budgets"]:
        insert_budget(
            conn,
            Budget(
                id=f"b_{b['category']}",
                user_id="u1",
                category_id=b["category"],
                limit_paise=rupees_to_paise(b["limit"]),
                warn_threshold_pct=b["warn_pct"],
            ),
        )
    conn.commit()
    policy = load_policy(load_settings().policy_path)
    return ExecutionContext(conn, "u1", scenario["id"], policy, ist(GOLDEN["clock_ist"]))


def assert_months(ctx: ExecutionContext, months: dict[str, Any]) -> None:
    for key, expected in months.items():
        year, month = map(int, key.split("-"))
        out = execute_tool(ctx, "aggregate_spend_by_category", {"year": year, "month": month}).data
        # JSON cannot key on null, so the uncategorised bucket is written as "null".
        got = {t.category_id or "null": t.total_spend_paise for t in out.totals}
        want = {k: rupees_to_paise(v) for k, v in expected["totals"].items()}
        assert got == want, key
        assert out.grand_total_spend_paise == rupees_to_paise(expected["grand_total"]), key
        assert out.grand_total_spend_paise == sum(want.values()), f"{key}: JSON is inconsistent"


def run_aggregate(s: dict[str, Any]) -> None:
    assert_months(build_ctx(s), s["months"])


def run_check_budgets(s: dict[str, Any]) -> None:
    ctx = build_ctx(s)
    out = execute_tool(ctx, "check_budgets", {"year": 2024, "month": 3}).data
    statuses = {b.category_id: b for b in out.statuses}
    for category, want in s["expected"].items():
        got = statuses[category]
        assert got.spent_paise == rupees_to_paise(want["spent"]), category
        assert got.pct_used == want["pct_used"], category
        assert got.status == want["status"], category


def run_forecast(s: dict[str, Any]) -> None:
    ctx = build_ctx(s)
    args = {"year": 2024, "month": 3, "category_id": s["category"]}
    out = execute_tool(ctx, "forecast_category_spend", args).data
    want = s["expected"]
    assert out.spent_so_far_paise == rupees_to_paise(want["spent"])
    assert (out.days_elapsed, out.days_in_month) == (want["days_elapsed"], want["days_in_month"])
    assert out.projected_spend_paise == rupees_to_paise(want["projected"])


def run_recategorize(s: dict[str, Any]) -> None:
    ctx = build_ctx(s)
    tx_id = s["input"]["transaction_id"]
    before = get_transaction(ctx.conn, "u1", tx_id)
    result = execute_tool(ctx, "recategorize_transaction", s["input"], approved=s["approved"])
    [call] = list_events(ctx.conn, "u1", event_type="tool_call")
    assert call.entity_id == "recategorize_transaction"
    assert call.metadata["approved"] is s["approved"]

    if "error_code" in s:
        assert result.error.code.value == s["error_code"]
        assert get_transaction(ctx.conn, "u1", tx_id) == before
        assert list_events(ctx.conn, "u1", event_type="transaction_recategorized") == []
    else:
        assert result.ok
        [change] = list_events(ctx.conn, "u1", event_type="transaction_recategorized")
        assert (change.entity_id, change.before, change.after) == (
            tx_id,
            s["audit_before"],
            s["audit_after"],
        )
    assert_months(ctx, s["months"])


def run_unknown_tool(s: dict[str, Any]) -> None:
    ctx = build_ctx(s)
    result = execute_tool(ctx, s["tool_name"], s["input"], approved=True)
    assert result.error.code.value == s["error_code"]
    [event] = list_events(ctx.conn, "u1", run_id=s["id"])
    assert (event.entity_id, event.before) == (s["tool_name"], s["input"])


def insert_mock_consent(conn, cid, user_id="u1", account_ids='["a1"]'):
    conn.execute(
        "INSERT INTO consents (id, user_id, purpose, fi_types, account_ids, date_range_from, date_range_to, status, expires_at, created_at) "
        "VALUES (?, ?, 'sync', 'DEPOSIT', ?, ?, ?, 'active', ?, ?)",
        (
            cid,
            user_id,
            account_ids,
            ALL_TIME[0],
            ALL_TIME[1],
            "2030-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
        ),
    )


def run_bank_failure(s: dict[str, Any]) -> None:
    ctx = build_ctx(s)
    before = ctx.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    bank = MockAAConnector.from_seed(GOLDEN["seed"], s["months"], "u1", "a1", fail=True)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(ctx.conn, cid)
    with pytest.raises(ToolFailure) as info:
        ingest_statements(ctx.conn, bank, "u1", "a1", cid)
    assert info.value.error.code.value == s["error_code"]
    assert info.value.error.retryable is s["retryable"]
    assert ctx.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before


def run_duplicate_visible(s: dict[str, Any]) -> None:
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="Savings", created_at=T0))
    synth = generate_transactions(GOLDEN["seed"], s["months"], "u1", "a1")
    bank = MockAAConnector(synth.transactions)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    ingest_statements(conn, bank, "u1", "a1", cid)
    [dup] = [a for a in synth.ground_truth if a.kind == "duplicate_charge"]
    first = next(t for t in synth.transactions if t.id == dup.transaction_ids[0])
    ctx = ExecutionContext(conn, "u1", s["id"], load_policy(load_settings().policy_path))
    start, end = month_bounds(*month_of(first.occurred_at))
    out = execute_tool(ctx, "get_transactions", {"start_utc": start, "end_utc": end}).data
    listed = [t for t in out.transactions if t.merchant_raw == first.merchant_raw]
    assert [t.id for t in listed] == list(dup.transaction_ids)
    assert len({(t.amount_paise, t.merchant_raw) for t in listed}) == 1


RUNNERS = {
    "aggregate": run_aggregate,
    "check_budgets": run_check_budgets,
    "forecast": run_forecast,
    "recategorize": run_recategorize,
    "unknown_tool": run_unknown_tool,
    "bank_failure": run_bank_failure,
    "duplicate_visible": run_duplicate_visible,
}


def test_there_are_about_ten_scenarios_with_unique_ids():
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids)) >= 10


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_golden(scenario):
    RUNNERS[scenario["kind"]](scenario)
