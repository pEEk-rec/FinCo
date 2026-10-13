"""
Phase 0 walkthrough: runs the whole stack once and prints what happens at each step.

    python scripts/demo.py                 # in-memory database, seed 42
    python scripts/demo.py --seed 7        # different synthetic data
    python scripts/demo.py --db data/demo.db   # keep the database to inspect afterwards

Not part of the product (Phase 0 has no UI); it only calls the public modules.
"""

import argparse
import sqlite3
from datetime import datetime

from copilot.bank.loader import ingest_transactions

from copilot.audit.events import list_events
from copilot.bank.mock_bank import MockBankConnector
from copilot.bank.synth import generate_transactions
from copilot.core.config import load_settings
from copilot.core.money import paise_to_rupees_str as rs
from copilot.core.timeutil import IST, month_bounds
from copilot.db.connection import get_connection, init_db, savepoint
from copilot.db.repo import insert_account, insert_budget, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, Budget, Category, User
from copilot.models.run_state import RunState
from copilot.planner.router import TrivialRouter
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.financial import register_financial_tools

T0 = "2024-01-01T00:00:00Z"
ALL_TIME = ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
FOOD_WORDS = ("SWIGGY", "ZOMATO", "HOSTELMESS", "CANTEEN")


def heading(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 70 - len(text)))


def show(label: str, result) -> None:
    """Print a ToolResult in one line."""
    if result.ok:
        print(f"  {label}: OK")
    else:
        print(
            f"  {label}: {result.error.code.value} - {' '.join(result.error.message.split())[:90]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args()

    settings = load_settings()
    conn = get_connection(args.db)
    init_db(conn)
    register_financial_tools()
    clock = datetime(2024, 2, 15, 12, 0, tzinfo=IST)  # pretend "now" is mid-February

    heading("1. Set up a user, an account and categories")
    with savepoint(conn):
        insert_user(conn, User(id="u1", created_at=T0))
        insert_account(
            conn,
            Account(
                id="a1",
                user_id="u1",
                name="Student savings",
                created_at=T0,
                opening_balance_paise=2_500_000,
            ),
        )
        for cat in ("food", "travel"):
            insert_category(conn, Category(id=cat, user_id="u1", name=cat.title(), created_at=T0))
        insert_budget(
            conn,
            Budget(
                id="b1",
                user_id="u1",
                category_id="food",
                limit_paise=600_000,
                warn_threshold_pct=settings.default_warn_threshold_pct,
            ),
        )
    print("  user u1, account a1 (opening balance Rs 25000.00), food budget Rs 6000.00/month")

    heading(f"2. Sync 2 months from the mock bank (seed {args.seed})")
    synth = generate_transactions(args.seed, 2, "u1", "a1")
    report = ingest_transactions(conn, MockBankConnector(synth.transactions), "u1", "a1", *ALL_TIME)
    print(f"  fetched {report.fetched}, inserted {report.inserted}")
    for tx in synth.transactions[:4]:
        print(f"    {tx.occurred_at}  {rs(tx.amount_paise):>10}  {tx.merchant_raw}")
    print("  planted anomalies (ground truth):")
    for a in synth.ground_truth:
        print(f"    - {a.kind}: {a.note}")
    again = ingest_transactions(conn, MockBankConnector(synth.transactions), "u1", "a1", *ALL_TIME)
    print(f"  re-sync inserted {again.inserted}, skipped {again.skipped_existing} (idempotent)")

    ctx = ExecutionContext(conn, "u1", "demo-run", load_policy(settings.policy_path), clock)

    heading("3. Recategorise food merchants (write tool, needs approval)")
    jan_feb = (month_bounds(2024, 1)[0], month_bounds(2024, 2)[1])
    txs = execute_tool(ctx, "get_transactions", {"start_utc": jan_feb[0], "end_utc": jan_feb[1]})
    food = [t for t in txs.data.transactions if any(w in t.merchant_raw for w in FOOD_WORDS)]
    first = {"transaction_id": food[0].id, "new_category_id": "food"}
    show("without approval", execute_tool(ctx, "recategorize_transaction", first))
    moved = sum(
        execute_tool(
            ctx,
            "recategorize_transaction",
            {"transaction_id": t.id, "new_category_id": "food"},
            approved=True,
        ).ok
        for t in food
    )
    print(f"  with approval: moved {moved} transactions to food")

    heading("4. Read tools (deterministic money math)")
    bal = execute_tool(ctx, "get_balance", {}).data
    print(f"  balance as of {bal.as_of_utc}: Rs {rs(bal.balance_paise)}")
    agg = execute_tool(ctx, "aggregate_spend_by_category", {"year": 2024, "month": 1}).data
    print("  January spend by category:")
    for t in agg.totals:
        print(f"    {t.category_id or 'uncategorised':<14} Rs {rs(t.total_spend_paise):>10}")
    print(f"    {'total':<14} Rs {rs(agg.grand_total_spend_paise):>10}")
    for b in execute_tool(ctx, "check_budgets", {"year": 2024, "month": 2}).data.statuses:
        pct = b.pct_used if b.pct_used is not None else "-"
        print(
            f"  February {b.category_id} budget: spent Rs {rs(b.spent_paise)} of "
            f"Rs {rs(b.limit_paise)} ({pct}%) -> {b.status}"
        )
    fc = execute_tool(
        ctx, "forecast_category_spend", {"year": 2024, "month": 2, "category_id": "food"}
    ).data
    print(
        f"  February food forecast: Rs {rs(fc.projected_spend_paise)} "
        f"(spent Rs {rs(fc.spent_so_far_paise)} in {fc.days_elapsed}/{fc.days_in_month} days)"
    )

    heading("5. Governance: things that must be refused")
    show(
        "transfer_money (does not exist)",
        execute_tool(ctx, "transfer_money", {"to": "x@upi", "amount": "5000"}, approved=True),
    )
    show("bad month", execute_tool(ctx, "check_budgets", {"year": 2024, "month": 13}))
    show(
        "made-up parameter",
        execute_tool(ctx, "get_balance", {"account_id": "a1", "include_loans": True}),
    )
    show("someone else's data", execute_tool(ctx, "get_balance", {"account_id": "b9"}))

    heading("6. Trivial router (Phase 2 placeholder)")
    for intent in ("what is my balance", "am I over budget", "recategorize t1 to food"):
        state = RunState(run_id="r", user_id="u1", intent=intent, created_at=T0)
        print(f"  {intent!r:32} -> {TrivialRouter().plan(state)}")

    heading("7. Audit log (append-only)")
    events = list_events(conn, "u1")
    counts: dict[str, int] = {}
    for e in events:
        key = (
            e.event_type
            if e.event_type != "tool_call"
            else (f"tool_call/{e.metadata['error_code'] or 'OK'}")
        )
        counts[key] = counts.get(key, 0) + 1
    for key, n in sorted(counts.items()):
        print(f"  {n:4}  {key}")
    try:
        conn.execute("UPDATE audit_events SET reason = 'tampered'")
    except sqlite3.IntegrityError as exc:
        print(f"  attempt to edit history -> blocked: {exc}")

    conn.commit()
    if args.db != ":memory:":
        print(f"\nDatabase kept at {args.db} (open it with any SQLite browser).")


if __name__ == "__main__":
    main()
