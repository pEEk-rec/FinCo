"""
The understanding tools through `execute_tool`, and the safety rules of the categorisation pillar
(PLAN_AGENTIC_V2 section 5, rules 1 to 5), each with a twin that fails when its guard is removed.
"""

import json
from datetime import datetime, timedelta

import pytest

from copilot.common.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.governance.policy import load_policy
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry, register
from copilot.tools.understand import register_understand_tools
from copilot.tools.undo import UNDO_TOOL
from copilot.understand import cascade as cascade_mod
from copilot.understand import learn
from copilot.understand.cascade import Cascade, Item
from copilot.understand.entities import EntityStore

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=IST)
CATS = {"food": "Dining", "shopping": "Shopping", "bills": "Utilities"}
LANTERN = "UPI/628912345678/LANTERN CAFE TRADERS/lantern@okaxis/HDFC"
BATCH_REPLY = json.dumps(
    {"decisions": [{"merchant": "lantern cafe traders", "category_id": "food", "confidence": 0.9}]}
)


@pytest.fixture
def make_ctx():
    clear_registry()
    register_understand_tools()
    register(UNDO_TOOL)
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at=T0))
    insert_account(
        conn, Account(id="acc", user_id=USER, name="S", opening_balance_paise=0, created_at=T0)
    )
    for cid, name in CATS.items():
        insert_category(conn, Category(id=cid, user_id=USER, name=name, created_at=T0))
    policy = load_policy("config/policy.yaml")

    def make(actor="user", llm=None):
        return ExecutionContext(
            conn=conn,
            user_id=USER,
            run_id="run_u",
            policy=policy,
            actor=actor,
            clock=NOW,
            llm_client=llm,
        )

    make.conn = conn
    yield make
    clear_registry()


_n = [0]


def add_tx(conn, raw, day=0):
    _n[0] += 1
    when = NOW + timedelta(days=day)
    insert_transaction(
        conn,
        Transaction(
            id=f"x{_n[0]}", user_id=USER, account_id="acc", occurred_at=to_utc_iso(when),
            amount_paise=40000, direction="debit", merchant_raw=raw, description="",
            created_at=to_utc_iso(when),
        ),
    )  # fmt: skip
    return f"x{_n[0]}"


# ---- through the choke point -------------------------------------------------------------------
def test_run_cascade_asks_when_unsure_and_the_agent_may_run_it(make_ctx):
    add_tx(make_ctx.conn, LANTERN)
    res = execute_tool(make_ctx("agent"), "run_cascade", {})
    assert res.ok, res.error
    assert res.data.considered == 1 and res.data.applied == 0 and res.data.asked == 1
    row = make_ctx.conn.execute("SELECT category_id, needs_review FROM transactions").fetchone()
    assert row[0] is None, "nothing is invented"


def test_only_the_user_can_answer_merge_split_or_decide_rules(make_ctx):
    for tool, args in [
        ("answer_shop", {"category_id": "food", "entity_id": "x"}),
        ("merge_entities", {"keep": "a", "absorb": "b"}),
        ("split_entity", {"entity_id": "a", "alias_ids": ["x"]}),
        ("decide_rule_proposal", {"proposal_id": "p", "accept": True}),
        ("undo_entity_merge", {"log_id": "l"}),
    ]:
        res = execute_tool(make_ctx("agent"), tool, args)
        assert not res.ok and res.error.code.value == "DENIED_BY_POLICY", tool


def test_answering_through_the_tool_settles_the_ledger_and_undo_restores_it(make_ctx):
    tid = add_tx(make_ctx.conn, LANTERN)
    execute_tool(make_ctx("agent"), "run_cascade", {})
    q = execute_tool(make_ctx("user"), "entity_questions", {}).data.questions
    assert len(q) == 1 and q[0].payments == 1
    ans = execute_tool(
        make_ctx("user"), "answer_shop", {"entity_id": q[0].entity_id, "category_id": "food"}
    )
    assert ans.ok and ans.data.settled == 1
    row = make_ctx.conn.execute("SELECT category_id, category_source FROM transactions").fetchone()
    assert tuple(row) == ("food", "user")
    why = execute_tool(make_ctx("user"), "explain_decision", {"transaction_id": tid}).data
    assert why.stage == "S0" and why.category_id == "food"
    undo = execute_tool(make_ctx("user"), "undo", {"audit_event_id": ans.data.audit_event_id})
    assert undo.ok, undo.error
    assert make_ctx.conn.execute("SELECT category_id FROM transactions").fetchone()[0] is None


def test_a_payment_answered_alone_is_undoable_too(make_ctx):
    tid = add_tx(make_ctx.conn, "UPI/628912345678/RAMESH K/9876543210@ybl/SBI")
    execute_tool(make_ctx("agent"), "run_cascade", {})
    ans = execute_tool(
        make_ctx("user"), "answer_shop", {"transaction_id": tid, "category_id": "food"}
    )
    assert ans.ok and ans.data.settled == 1
    assert execute_tool(make_ctx("user"), "undo", {"audit_event_id": ans.data.audit_event_id}).ok
    assert make_ctx.conn.execute("SELECT category_id FROM transactions").fetchone()[0] is None


def test_an_answer_needs_exactly_one_target(make_ctx):
    assert not execute_tool(make_ctx("user"), "answer_shop", {"category_id": "food"}).ok
    assert not execute_tool(
        make_ctx("user"),
        "answer_shop",
        {"category_id": "food", "entity_id": "a", "transaction_id": "b"},
    ).ok


def test_the_model_is_used_through_the_tool_and_only_for_the_first_guess(make_ctx):
    add_tx(make_ctx.conn, LANTERN)
    llm = FakeLLMClient([BATCH_REPLY])
    res = execute_tool(make_ctx("agent", llm), "run_cascade", {})
    assert res.ok and res.data.model_calls == 1 and res.data.applied == 0
    q = execute_tool(make_ctx("user"), "entity_questions", {}).data.questions[0]
    assert q.best_guess == "food"
    assert "628912345678" not in llm.prompts[0] and "lantern@okaxis" not in llm.prompts[0]


# ---- Rule 1: a user's label, merge or split is never overwritten automatically -------------------
def check_rule1(conn):
    tid = add_tx(conn, LANTERN)
    conn.execute(
        "UPDATE transactions SET category_id = 'bills', category_source = 'user' WHERE id = ?",
        (tid,),
    )
    c = Cascade(conn, USER, categories=dict(CATS), rules=[], clock=NOW)
    c.run([Item(tid, LANTERN, 40000, "debit")])
    eid = conn.execute("SELECT entity_id FROM category_decisions").fetchone()[0]
    learn.answer_entity(conn, USER, eid, "food", clock=NOW)
    assert (
        conn.execute("SELECT category_id FROM transactions WHERE id = ?", (tid,)).fetchone()[0]
        == "bills"
    ), "an answer for the shop changed a payment the user had already set"


def test_rule1_holds(make_ctx):
    check_rule1(make_ctx.conn)


def test_rule1_fails_when_the_guard_is_removed(make_ctx, monkeypatch):
    monkeypatch.setattr(learn, "_PROTECTED", ())
    with pytest.raises(AssertionError):
        check_rule1(make_ctx.conn)


# ---- Rule 2: below the calibrated threshold nothing is applied ----------------------------------
def check_rule2(conn):
    tid = add_tx(conn, LANTERN)
    c = Cascade(conn, USER, categories=dict(CATS), rules=[], advisor=_SureModel(), clock=NOW)
    d = c.run([Item(tid, LANTERN, 40000, "debit")])[0]
    assert not d.applied, "a confident model alone applied a label"


class _SureModel:
    calls = 0

    def suggest_many(self, requests, categories):
        self.calls += 1
        return [("food", 8500) for _ in requests]


def test_rule2_holds(make_ctx):
    check_rule2(make_ctx.conn)


def test_rule2_fails_when_calibration_is_bypassed(make_ctx, monkeypatch):
    monkeypatch.setattr(cascade_mod.Calibrator, "apply", lambda self, stage, raw: 10000)
    with pytest.raises(AssertionError):
        check_rule2(make_ctx.conn)


# ---- Rule 3: only cleaned merchant names reach a model; persons never ---------------------------
class _Recorder:
    calls = 0

    def __init__(self):
        self.sent = []

    def suggest_many(self, requests, categories):
        self.calls += 1
        self.sent.append(json.dumps([r[0] for r in requests]))
        return [(None, 0) for _ in requests]


def check_rule3(conn):
    rec = _Recorder()
    c = Cascade(conn, USER, categories=dict(CATS), rules=[], advisor=rec, clock=NOW)
    c.run([
        Item(add_tx(conn, LANTERN), LANTERN, 40000, "debit"),
        Item(add_tx(conn, "UPI/628912345679/RAMESH K/9876543210@ybl/SBI"), "UPI/628912345679/RAMESH K/9876543210@ybl/SBI", 40000, "debit"),
    ])  # fmt: skip
    seen = " ".join(rec.sent).lower()
    assert "ramesh" not in seen and "9876543210" not in seen, "a person reached the model"
    assert "628912345678" not in seen and "lantern@okaxis" not in seen, (
        "a reference or VPA reached the model"
    )
    assert "lantern cafe traders" in seen


def test_rule3_holds(make_ctx):
    check_rule3(make_ctx.conn)


def test_rule3_fails_when_persons_are_sent_to_the_model(make_ctx, monkeypatch):
    monkeypatch.setattr(EntityStore, "_kind", lambda self, desc: "merchant")
    with pytest.raises(AssertionError):
        check_rule3(make_ctx.conn)


# ---- Rule 4: a person is never merged with a shop, nor two people automatically -----------------
def check_rule4(conn):
    s = EntityStore(conn, USER)
    from copilot.understand.descriptor import parse_descriptor as pd

    p1 = s.resolve(pd("UPI/628912345678/RAMESH K/9876543210@ybl/SBI")).entity_id
    p2 = s.resolve(pd("UPI/628912345679/RAMESH K/9123456789@ybl/SBI")).entity_id
    shop = s.resolve(pd("POS 4321 RAMESH K STORES BANGALORE IN")).entity_id
    assert len({p1, p2, shop}) == 3, "two different people, or a person and a shop, were joined"


def test_rule4_holds(make_ctx):
    check_rule4(make_ctx.conn)


def test_rule4_fails_when_people_merge_on_name(make_ctx, monkeypatch):
    real = EntityStore._exact

    def by_name(self, desc):
        found = real(self, desc)
        row = self.conn.execute(
            "SELECT id FROM merchant_entities WHERE user_id = ? AND kind = 'person' AND display_name = ?",
            (self.user_id, desc.name.title()),
        ).fetchone()
        if row:
            found[self.canonical(row[0])] = 9000
        return found

    monkeypatch.setattr(EntityStore, "_exact", by_name)
    with pytest.raises(AssertionError):
        check_rule4(make_ctx.conn)


# ---- Rule 5: every merge and split is audited and can be undone ---------------------------------
def check_rule5(conn):
    from copilot.understand.descriptor import parse_descriptor as pd

    s = EntityStore(conn, USER)
    a = s.resolve(pd("POS 4321 LANTERN CAFE TRADERS BANGALORE IN")).entity_id
    b = s.resolve(pd("POS 4321 GREEN LEAF JUICE CENTRE BANGALORE IN")).entity_id
    before = {r["id"] for r in s.aliases(b)}
    log = s.merge(a, b)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'entity_merged'"
        ).fetchone()[0]
        == 1
    )
    s.undo(log)
    assert {r["id"] for r in s.aliases(b)} == before and s.canonical(b) == b, "undo did not restore"


def test_rule5_holds(make_ctx):
    check_rule5(make_ctx.conn)


def test_rule5_fails_when_undo_does_not_restore(make_ctx, monkeypatch):
    monkeypatch.setattr(EntityStore, "undo", lambda self, log_id, actor="user": None)
    with pytest.raises(AssertionError):
        check_rule5(make_ctx.conn)
