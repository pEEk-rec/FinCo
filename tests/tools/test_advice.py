from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_user
from copilot.governance.policy import load_policy
from copilot.models.domain import User
from copilot.models.findings import Finding, FindingNumber
from copilot.tools.advice import decide_advice_handler, draft_advice_handler
from copilot.tools.executor import ExecutionContext

T0 = "2024-01-01T00:00:00Z"
POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.yaml")


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    return c


@pytest.fixture
def exec_ctx(conn):
    return ExecutionContext(
        conn=conn,
        user_id="u1",
        actor="user",
        run_id="r1",
        clock=datetime(2024, 1, 15, tzinfo=UTC),
        policy=POLICY,
    )


def test_draft_and_decide_advice(conn, exec_ctx):
    f = Finding(
        id="f1",
        kind="category_spend",
        numbers=[FindingNumber(label="spend", value=100000, unit="paise")],
        reference_ids=[],
        period="2024-01",
        description="High spend",
    )

    # Draft advice uses fallback
    out = draft_advice_handler(exec_ctx, [f])
    assert len(out.advice_items) == 1

    aid = out.advice_items[0]["id"]

    # Check DB
    row = conn.execute("SELECT status FROM advice_items WHERE id = ?", (aid,)).fetchone()
    assert row[0] == "draft"

    # Decide
    decide_out = decide_advice_handler(exec_ctx, aid, "approved")
    assert decide_out.status == "approved"

    # Check DB again
    row2 = conn.execute("SELECT status FROM advice_items WHERE id = ?", (aid,)).fetchone()
    assert row2[0] == "approved"

    # Check audit
    audit = conn.execute(
        "SELECT event_type, before_json, after_json FROM audit_events WHERE entity_id = ?", (aid,)
    ).fetchone()
    assert audit[0] == "advice_decided"
    assert '"draft"' in audit[1]
    assert '"approved"' in audit[2]
