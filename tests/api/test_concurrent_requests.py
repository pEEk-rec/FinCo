"""Several requests at once must not fail with "database is locked" (found by the For you screen)."""

import concurrent.futures as cf

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.db.connection import get_connection, savepoint
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}
READS = [
    "/api/checkins", "/api/profile", "/api/budget/proposal", "/api/budget/replan",
    "/api/subscriptions", "/api/categories", "/api/capture/inbox",
]  # fmt: skip


@pytest.fixture
def client(tmp_path):
    clear_registry()
    st = ApiState(db_path=tmp_path / "c.db", clock=DEMO_CLOCK, token="test-token", llm=None)
    ensure_demo(st, "imported")
    yield TestClient(create_app(st))
    clear_registry()


def test_a_page_load_that_asks_for_many_things_at_once_all_succeed(client):
    for _ in range(3):
        with cf.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda p: client.get(p, headers=AUTH).status_code, READS * 2))
        assert set(results) == {200}, results


def test_the_unit_of_work_commits_on_exit_and_rolls_back_on_error(tmp_path):
    conn = get_connection(str(tmp_path / "s.db"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    with savepoint(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    assert not conn.in_transaction, "the block committed"
    with pytest.raises(RuntimeError), savepoint(conn):
        conn.execute("INSERT INTO t VALUES (2)")
        raise RuntimeError("boom")
    assert not conn.in_transaction
    assert [r[0] for r in conn.execute("SELECT x FROM t")] == [1]


def test_inside_a_callers_transaction_it_nests_and_the_caller_decides(tmp_path):
    conn = get_connection(str(tmp_path / "n.db"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.execute("INSERT INTO t VALUES (1)")  # opens the caller's transaction
    with savepoint(conn):
        conn.execute("INSERT INTO t VALUES (2)")
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
