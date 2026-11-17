"""The cascade, calibration, questions and learning (A3 to A6)."""

import json
from datetime import datetime, timedelta

import pytest

from copilot.common.errors import ToolFailure
from copilot.common.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.models.domain import Account, Category, Transaction, User
from copilot.understand import learn
from copilot.understand.advisor import NoAdvisor
from copilot.understand.calibration import Calibrator
from copilot.understand.cascade import Cascade, Item
from copilot.understand.config import load_understand_config
from copilot.understand.rules import CategorizationRule

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=IST)
CATS = {"food": "Dining", "groceries": "Groceries", "travel": "Travel", "shopping": "Shopping",
        "bills": "Utilities", "entertainment": "Entertainment"}  # fmt: skip
RULES = [CategorizationRule("swiggy", True, "food", 0.95)]


class Spy:
    """An advisor that records exactly what it was sent."""

    def __init__(self, answer=("shopping", 8000)):
        self.calls = 0
        self.sent: list = []
        self.answer = answer

    def suggest_many(self, requests, categories):
        self.calls += 1
        self.sent.append((list(requests), dict(categories)))
        return [self.answer for _ in requests]


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc", user_id=USER, name="S", opening_balance_paise=0, created_at=T0)
    )
    for cid, name in CATS.items():
        insert_category(c, Category(id=cid, user_id=USER, name=name, created_at=T0))
    return c


_n = [0]


def tx(conn, raw, day=0, amount=30000):
    _n[0] += 1
    when = NOW + timedelta(days=day)
    t = Transaction(
        id=f"t{_n[0]}", user_id=USER, account_id="acc", occurred_at=to_utc_iso(when),
        amount_paise=amount, direction="debit", merchant_raw=raw, description="",
        created_at=to_utc_iso(when),
    )  # fmt: skip
    insert_transaction(conn, t)
    return Item(t.id, raw, amount, "debit")


def cascade(conn, advisor=None, level=None):
    cfg = load_understand_config()
    cfg = cfg.with_level(level) if level else cfg
    return Cascade(
        conn,
        USER,
        categories=dict(CATS),
        rules=RULES,
        advisor=advisor or NoAdvisor(),
        cfg=cfg,
        clock=NOW,
    )


LANTERN = "UPI/628912345678/LANTERN CAFE TRADERS/lantern@okaxis/HDFC"
LANTERN_CARD = "POS 4321 LANTERN CAFE TRADERS BANGALORE IN"


def one(c, item):
    return c.run([item])[0]


# ---- precedence --------------------------------------------------------------------------------
def test_a_rule_and_the_dictionary_label_known_things_without_asking(conn):
    c = cascade(conn)
    a = one(c, tx(conn, "UPI/628912345678/SWIGGY/swiggy@ybl/HDFC"))
    b = one(c, tx(conn, "UPI/628912345679/NETFLIX/netflix@ybl/HDFC"))
    assert (a.stage, a.category_id) == ("S1", "food")
    assert b.applied is False, (
        "subscriptions is not one of this user's categories: ask, do not invent"
    )


def test_the_users_answer_wins_over_everything_else(conn):
    c = cascade(conn)
    first = one(c, tx(conn, "UPI/628912345678/SWIGGY/swiggy@ybl/HDFC"))
    learn.answer_entity(conn, USER, first.entity_id, "groceries", clock=NOW)
    again = one(c, tx(conn, "POS 4321 SWIGGY BANGALORE IN"))
    assert (again.stage, again.category_id) == ("S0", "groceries")


def test_an_unknown_shop_is_asked_once_then_every_spelling_follows(conn):
    c = cascade(conn)
    d = one(c, tx(conn, LANTERN))
    assert d.applied is False and d.stage == "S5"
    out = learn.answer_entity(conn, USER, d.entity_id, "food", clock=NOW)
    assert out["settled"] == 1
    other = one(c, tx(conn, LANTERN_CARD, day=1))
    assert (other.stage, other.category_id) == ("S0", "food")


def test_one_odd_answer_is_not_trusted_until_two_agree(conn):
    c = cascade(conn)
    e = one(c, tx(conn, LANTERN)).entity_id
    learn.answer_entity(conn, USER, e, "food", clock=NOW)
    learn.answer_entity(conn, USER, e, "shopping", clock=NOW)
    d = one(c, tx(conn, LANTERN_CARD, day=1))
    assert d.applied is False and "disagree" in d.reason
    learn.answer_entity(conn, USER, e, "shopping", clock=NOW)
    assert one(c, tx(conn, LANTERN_CARD, day=2)).category_id == "shopping"


def test_a_person_is_never_labelled_automatically_nor_shown_to_the_model(conn):
    spy = Spy()
    c = cascade(conn, spy)
    p = tx(conn, "UPI/628912345678/RAMESH K/9876543210@ybl/SBI")
    d = one(c, p)
    assert d.kind == "person" and d.applied is False
    learn.answer_transaction(conn, USER, p.tx_id, "food", clock=NOW)
    d2 = one(c, tx(conn, "UPI/628912345679/RAMESH K/9876543210@ybl/SBI", day=1))
    assert d2.applied is False, "what a payment to a friend was for varies: ask every time"
    assert spy.calls == 0


# ---- the model ---------------------------------------------------------------------------------
def test_the_model_gets_one_request_for_all_new_names_and_only_cleaned_names(conn):
    spy = Spy()
    c = cascade(conn, spy)
    items = [
        tx(conn, "UPI/628912345678/ORBIT HUB/orbithub@ybl/HDFC", amount=123400),
        tx(conn, "UPI/628912345679/ZENITH CORNER/zenith@okaxis/HDFC", amount=567800),
        tx(conn, "UPI/628912345680/RAMESH K/9876543210@ybl/SBI"),
    ]
    c.run(items)
    assert spy.calls == 1, "a batch of names is one request"
    sent = json.dumps(spy.sent)
    assert "orbit hub" in sent and "zenith corner" in sent
    for secret in ("ramesh", "9876543210", "628912345678", "123400", "567800", "orbithub@ybl"):
        assert secret not in sent.lower(), secret


def test_a_confident_model_alone_never_applies_a_label(conn):
    c = cascade(conn, Spy(("shopping", 8500)))
    d = one(c, tx(conn, "UPI/628912345678/ORBIT HUB/orbithub@ybl/HDFC"))
    assert d.applied is False
    assert d.candidates and d.candidates[-1]["stage"] == "S4", (
        "its answer is kept as the first guess"
    )


def test_the_model_is_asked_once_per_shop_not_once_per_payment(conn):
    spy = Spy()
    c = cascade(conn, spy)
    c.run([tx(conn, "UPI/628912345678/ORBIT HUB/orbithub@ybl/HDFC")])
    c.run([tx(conn, "UPI/628912345679/ORBIT HUB/orbithub@ybl/HDFC", day=1)])
    assert spy.calls == 1


# ---- calibration -------------------------------------------------------------------------------
def test_calibration_never_says_a_higher_score_is_less_reliable(conn):
    cal = Calibrator(conn, USER)
    for _ in range(30):
        cal.update("S2", 9500, False)  # claims 95%, is always wrong
    p = [cal.apply("S2", raw) for raw in range(500, 10000, 1000)]
    assert p == sorted(p)
    assert cal.apply("S2", 9500) < 5000, "evidence beats the claim"


def test_a_stage_that_keeps_being_right_earns_the_right_to_apply(conn):
    cal = Calibrator(conn, USER)
    before = cal.apply("S2", 10000)
    for _ in range(30):
        cal.update("S2", 10000, True)
    assert (
        cal.apply("S2", 10000) > before
        and cal.apply("S2", 10000) >= load_understand_config().threshold_bp
    )


def test_a_stage_that_is_often_wrong_stops_applying(conn):
    cal = Calibrator(conn, USER)
    assert cal.apply("S1", 9500) >= load_understand_config().threshold_bp
    for _ in range(40):
        cal.update("S1", 9500, False)
    assert cal.apply("S1", 9500) < load_understand_config().threshold_bp


def test_the_ask_level_moves_the_line_and_reset_clears_evidence(conn):
    cfg = load_understand_config()
    assert (
        cfg.with_level("fewer_questions").threshold_bp
        < cfg.threshold_bp
        < cfg.with_level("more_questions").threshold_bp
    )
    cal = Calibrator(conn, USER)
    cal.update("S2", 9500, False)
    assert cal.reset() == 1


# ---- the neighbours ----------------------------------------------------------------------------
def test_a_shop_like_one_you_labelled_is_recognised_once_calibration_trusts_it(conn):
    c = cascade(conn)
    seed = one(c, tx(conn, "POS 4321 CAMPUS CANTEEN FOODS BANGALORE IN"))
    learn.answer_entity(conn, USER, seed.entity_id, "food", clock=NOW)
    cal = Calibrator(conn, USER)
    for raw in range(5500, 10000, 1000):
        for _ in range(80):
            cal.update("S2", raw, True)
    sibling = one(c, tx(conn, "POS 4321 CAMPUS CANTEEN BLOCK B BANGALORE IN", day=1))
    assert (sibling.stage, sibling.category_id) == ("S2", "food")
    assert "Campus Canteen Foods" in sibling.reason or "campus" in sibling.reason.lower()


# ---- questions, answers, undo ------------------------------------------------------------------
def test_questions_come_most_valuable_first_and_shops_are_batched_but_people_are_not(conn):
    c = cascade(conn)
    big = [
        tx(conn, "UPI/628912345678/ORBIT HUB/orbithub@ybl/HDFC", day=i, amount=250000)
        for i in range(3)
    ]
    small = tx(conn, "UPI/628912345679/ZENITH CORNER/zenith@okaxis/HDFC", amount=2000)
    people = [tx(conn, f"UPI/62891234568{i}/RAMESH K/9876543210@ybl/SBI", day=i) for i in range(2)]
    c.run([*big, small, *people])
    qs = learn.rank_questions(conn, USER, clock=NOW + timedelta(days=5))
    assert qs[0].display_name.lower() == "orbit hub" and qs[0].batch and len(qs[0].tx_ids) == 3
    person = next(q for q in qs if q.kind == "person")
    assert person.batch is False


def test_answering_a_shop_settles_all_its_payments_and_undo_puts_them_back(conn):
    from copilot.audit.events import get_event

    c = cascade(conn)
    items = [tx(conn, LANTERN, day=i) for i in range(3)]
    c.run(items)
    out = learn.answer_entity(
        conn,
        USER,
        c.store.resolve(
            __import__("copilot.understand.descriptor", fromlist=["x"]).parse_descriptor(LANTERN)
        ).entity_id,
        "food",
        clock=NOW,
    )
    assert out["settled"] == 3
    rows = conn.execute("SELECT category_id, category_source FROM transactions").fetchall()
    assert {tuple(r) for r in rows} == {("food", "user")}
    ev = get_event(conn, out["audit_event_id"])
    learn.undo_answer(conn, USER, ev.entity_id, ev.before, ev.after)
    assert {
        tuple(r) for r in conn.execute("SELECT category_id, category_source FROM transactions")
    } == {(None, "none")}
    assert conn.execute("SELECT COUNT(*) FROM entity_labels").fetchone()[0] == 0


def test_a_user_label_is_never_overwritten_by_the_cascade(conn):
    c = cascade(conn)
    item = tx(conn, LANTERN)
    conn.execute(
        "UPDATE transactions SET category_id = 'bills', category_source = 'user' WHERE id = ?",
        (item.tx_id,),
    )
    d = one(c, item)
    assert d.applied is False
    cat = conn.execute(
        "SELECT category_id FROM transactions WHERE id = ?", (item.tx_id,)
    ).fetchone()[0]
    assert cat == "bills"


def test_only_the_user_can_answer(conn):
    c = cascade(conn)
    d = one(c, tx(conn, LANTERN))
    for actor in ("agent", "system"):
        with pytest.raises(ToolFailure):
            learn.answer_entity(conn, USER, d.entity_id, "food", actor=actor, clock=NOW)


# ---- rules the agent proposes -------------------------------------------------------------------
def test_three_shops_with_the_same_first_word_and_answer_propose_a_rule_never_apply_it(conn):
    c = cascade(conn)
    names = ["MAPLE LANE CAFE", "MAPLE HILL BAKERY", "MAPLE GROVE DINER"]
    proposal = None
    for n in names:
        d = one(c, tx(conn, f"POS 4321 {n} BANGALORE IN"))
        out = learn.answer_entity(conn, USER, d.entity_id, "food", clock=NOW)
        proposal = out["rule_proposal"] or proposal
    assert proposal, "three shops that start the same and were answered the same way"
    assert conn.execute("SELECT status FROM rule_proposals").fetchone()[0] == "pending"
    fresh = one(c, tx(conn, "POS 4321 MAPLE STREET GRILL BANGALORE IN"))
    assert fresh.applied is False, "a proposal does nothing until you accept it"
    learn.decide_rule(conn, USER, proposal, True, clock=NOW)
    again = one(c, tx(conn, "POS 4321 MAPLE ROAD KITCHEN BANGALORE IN", day=1))
    assert (again.stage, again.category_id) == ("S1", "food")


def test_one_answer_never_proposes_a_rule_and_a_disagreeing_shop_blocks_it(conn):
    c = cascade(conn)
    d1 = one(c, tx(conn, "POS 4321 MAPLE LANE CAFE BANGALORE IN"))
    assert learn.answer_entity(conn, USER, d1.entity_id, "food", clock=NOW)["rule_proposal"] is None
    d2 = one(c, tx(conn, "POS 4321 MAPLE HILL BAKERY BANGALORE IN"))
    learn.answer_entity(conn, USER, d2.entity_id, "shopping", clock=NOW)
    d3 = one(c, tx(conn, "POS 4321 MAPLE GROVE DINER BANGALORE IN"))
    assert learn.answer_entity(conn, USER, d3.entity_id, "food", clock=NOW)["rule_proposal"] is None


def test_only_the_user_can_decide_a_rule(conn):
    c = cascade(conn)
    for n in ("MAPLE LANE CAFE", "MAPLE HILL BAKERY", "MAPLE GROVE DINER"):
        d = one(c, tx(conn, f"POS 4321 {n} BANGALORE IN"))
        out = learn.answer_entity(conn, USER, d.entity_id, "food", clock=NOW)
    with pytest.raises(ToolFailure):
        learn.decide_rule(conn, USER, out["rule_proposal"], True, actor="agent")


# ---- drift and spot checks ---------------------------------------------------------------------
def test_every_decision_keeps_its_stage_and_evidence(conn):
    c = cascade(conn)
    d = one(c, tx(conn, "UPI/628912345678/SWIGGY/swiggy@ybl/HDFC"))
    row = conn.execute(
        "SELECT stage, confidence_bp, evidence_json FROM category_decisions WHERE transaction_id = ?",
        (d.tx_id,),
    ).fetchone()
    assert row[0] == "S1" and row[1] >= load_understand_config().threshold_bp
    assert json.loads(row[2])["candidates"][0]["stage"] == "S1"


def test_spot_checks_ask_the_user_to_confirm_every_nth_automatic_label(conn):
    cfg = load_understand_config().model_copy(
        update={"audit": load_understand_config().audit.model_copy(update={"every": 2})}
    )
    c = Cascade(conn, USER, categories=dict(CATS), rules=RULES, cfg=cfg, clock=NOW)
    cal = Calibrator(conn, USER, cfg)
    for _ in range(30):
        cal.update("S3", 9200, True)
    got = [c.run([tx(conn, f"UPI/62891234567{i}/ZEPTO/zepto@ybl/HDFC")])[0] for i in range(4)]
    assert [d.audit for d in got] == [False, True, False, True]
    assert all(d.applied for d in got)
