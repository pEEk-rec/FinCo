"""
Parallel specialists share one database connection and register tools on first use.

Two races used to make a specialist intermittently lose its findings (the multi-agent
"same facts with the critic on or off" test failed one run in several):

* `execute_tool` opens and releases a savepoint per call; calls from different threads on one
  connection interleaved and raised "no such savepoint".
* `ensure_tools_registered` let two threads both register the same tool, and one failed with
  "already registered".
"""

import threading
from pathlib import Path

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import Account, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry
from copilot.workflow.nodes import ensure_tools_registered

ROOT = Path(__file__).resolve().parents[2]
T0 = "2026-01-01T00:00:00Z"


def _ctx():
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id="u1", created_at=T0))
    insert_account(conn, Account(id="a1", user_id="u1", name="Main", created_at=T0))
    return ExecutionContext(
        conn=conn, user_id="u1", run_id="r1", policy=load_policy(ROOT / "config" / "policy.yaml")
    )


def test_concurrent_tool_calls_on_one_connection_never_break_each_other():
    ensure_tools_registered()
    ctx = _ctx()
    failures: list[str] = []

    def worker() -> None:
        for _ in range(25):
            result = execute_tool(ctx, "list_goals", {})
            if not result.ok:
                failures.append(str(result.error))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []


def test_registering_tools_from_many_threads_at_once_is_safe():
    clear_registry()  # the suite restores the registry after each test
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            ensure_tools_registered()
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever it raised
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
