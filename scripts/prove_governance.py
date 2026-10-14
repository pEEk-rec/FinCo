"""
Live proof of the safety claims, for the demo. Works on a throwaway copy of the database.

    python scripts/prove_governance.py --db frontend/.demo/demo.db

Each section tries to break a rule and prints what actually happened. Nothing is mocked: the
tool inventory is the real registry, the refusals come from the real executor and database
triggers, and the original database file is never modified.
"""

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.api.services import register_all_tools  # noqa: E402
from copilot.core.config import load_settings  # noqa: E402
from copilot.core.money import rupees_to_paise  # noqa: E402
from copilot.db.connection import get_connection, init_db  # noqa: E402
from copilot.governance.policy import load_policy  # noqa: E402
from copilot.models.domain import Transaction  # noqa: E402
from copilot.planner.capabilities import get_selectable_tools  # noqa: E402
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec  # noqa: E402
from copilot.tools.executor import ExecutionContext, execute_tool  # noqa: E402
from copilot.tools.registry import list_specs, register  # noqa: E402


def heading(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 72 - len(text)))


def line(ok: bool, text: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", required=True, help="demo database (it is copied, not modified)")
    args = parser.parse_args()
    source = Path(args.db)
    if not source.exists():
        print(f"No database at {source}. Run the demo and import first.")
        return 2

    work = Path(tempfile.mkdtemp()) / "copy.db"
    shutil.copy(source, work)
    conn = get_connection(str(work))
    init_db(conn)
    user = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    register_all_tools()
    policy = load_policy(load_settings().policy_path)
    failures = 0

    heading("1. What the agent is allowed to touch")
    specs = list_specs()
    selectable = set(get_selectable_tools())
    reads = [s.name for s in specs if s.side_effect is SideEffect.READ]
    writes = [s.name for s in specs if s.side_effect is SideEffect.WRITE_LOGICAL]
    print(f"  {len(specs)} tools registered: {len(reads)} read-only, {len(writes)} change data")
    print(f"  The planner may choose from {len(selectable)} tools, all read-only.")
    print(
        f"  Tools that change data and are available to the planner: {len(selectable & set(writes))}"
    )
    ok = not (selectable & set(writes)) and selectable <= set(reads)
    failures += not ok
    line(ok, "no data-changing tool is ever offered to the planner")
    money_words = ("transfer", "pay", "trade", "withdraw", "deposit", "send", "wire")
    # detect_transfers only labels moves between the user's own accounts so they are not
    # counted as spending; it cannot move anything (the repository's own test allows it too).
    movers = [
        s.name
        for s in specs
        if any(w in s.name for w in money_words) and s.name != "detect_transfers"
    ]
    failures += bool(movers)
    line(
        not movers,
        "no tool exists that could move money (name check; detect_transfers only labels)",
    )

    heading("2. Trying to rewrite history")
    audit_id = conn.execute("SELECT id FROM audit_events LIMIT 1").fetchone()[0]
    attempts = {
        "UPDATE an audit row": "UPDATE audit_events SET reason = 'edited' WHERE id = '%s'"
        % audit_id,
        "DELETE an audit row": "DELETE FROM audit_events WHERE id = '%s'" % audit_id,
        "overwrite with INSERT OR REPLACE": (
            "INSERT OR REPLACE INTO audit_events (id, user_id, occurred_at, actor, event_type, reason) "
            "VALUES ('%s', '%s', '2000-01-01T00:00:00Z', 'system', 'x', 'forged')"
            % (audit_id, user)
        ),
    }
    for name, sql in attempts.items():
        try:
            conn.execute(sql)
            failures += 1
            line(False, f"{name}: SUCCEEDED (this is a bug)")
        except sqlite3.IntegrityError as exc:
            line(True, f"{name}: refused by the database ({exc})")

    heading("3. Asking the agent for things it must not do")
    agent = ExecutionContext(conn, user, "proof", policy, None, actor="agent")
    tx = conn.execute(
        "SELECT id FROM transactions WHERE category_source = 'rule' LIMIT 1"
    ).fetchone()
    cases = [
        (
            "a tool that does not exist (transfer_money)",
            "transfer_money",
            {"amount": "5000"},
            "NOT_FOUND",
        ),
        (
            "recategorize without the user's approval",
            "recategorize_transaction",
            {"transaction_id": tx[0], "new_category_id": "food", "remember": False},
            "APPROVAL_REQUIRED",
        ),
        (
            "approve its own advice (user-only action)",
            "decide_advice",
            {"advice_id": "x", "decision": "approved"},
            "DENIED_BY_POLICY",
        ),
        (
            "revoke a consent (user-only action)",
            "revoke_consent",
            {"consent_id": "x"},
            "DENIED_BY_POLICY",
        ),
        (
            "malformed input to a read tool",
            "check_budgets",
            {"year": 2024, "month": 13},
            "INVALID_INPUT",
        ),
    ]
    for label, tool, payload, expected in cases:
        result = execute_tool(agent, tool, payload)
        got = result.error.code.value if result.error else "OK"
        failures += got != expected
        line(got == expected, f"{label}: {got}")

    class _In(ToolInput):
        pass

    class _Out(ToolOutput):
        pass

    wire = ToolSpec(
        "wire_funds", "Pretend external tool", _In, _Out, SideEffect.EXTERNAL, lambda ctx: {}
    )
    register(wire)
    permissive = policy.model_copy(
        update={"tools": {**policy.tools, "wire_funds": {"allow": "allow"}}}
    )
    result = execute_tool(
        ExecutionContext(conn, user, "proof", permissive, None, "agent"), "wire_funds", {}
    )
    got = result.error.code.value if result.error else "OK"
    failures += got != "DENIED_BY_POLICY"
    line(
        got == "DENIED_BY_POLICY",
        f"an external tool even when config allows it: {got} (blocked in code)",
    )

    heading("4. Money cannot be a float")
    for label, call in (
        ("rupees_to_paise(499.5)", lambda: rupees_to_paise(499.5)),
        (
            "a transaction of 1000.5 paise",
            lambda: Transaction(
                id="t",
                user_id=user,
                account_id="a",
                occurred_at="2024-01-01T00:00:00Z",
                amount_paise=1000.5,
                direction="debit",
                merchant_raw="m",
                description="d",
                created_at="2024-01-01T00:00:00Z",
            ),
        ),
        (
            "a debit with a negative amount",
            lambda: Transaction(
                id="t",
                user_id=user,
                account_id="a",
                occurred_at="2024-01-01T00:00:00Z",
                amount_paise=-5,
                direction="debit",
                merchant_raw="m",
                description="d",
                created_at="2024-01-01T00:00:00Z",
            ),
        ),
    ):
        try:
            call()
            failures += 1
            line(False, f"{label}: accepted (this is a bug)")
        except (TypeError, ValueError) as exc:
            line(True, f"{label}: rejected ({type(exc).__name__})")

    heading("Result")
    print(f"  {'All safety checks held.' if not failures else str(failures) + ' check(s) FAILED'}")
    print(f"  The demo database at {source} was not modified.\n")
    conn.close()
    shutil.rmtree(work.parent, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
