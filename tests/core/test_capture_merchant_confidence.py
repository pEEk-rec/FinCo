"""One odd answer must not silently flip a shop (found by `copilot eval --capture`)."""

from datetime import datetime, timedelta

import pytest

from copilot.core import capture as cap
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.models.domain import Account, Category, User

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
START = datetime(2026, 10, 1, 12, 0, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc1", user_id=USER, name="S", opening_balance_paise=0, created_at=T0)
    )
    for cat in ("food", "shopping", "other"):
        insert_category(c, Category(id=cat, user_id=USER, name=cat.title(), created_at=T0))
    return c


def pay(conn, day, answer=None):
    when = START + timedelta(days=day)
    rec = cap.record_payment_event(
        conn, USER, source="sms", amount_paise=30000, direction="debit",
        display_name="Lantern Cafe Traders", occurred_at=to_utc_iso(when), clock=when,
    )  # fmt: skip
    if answer and rec.decision.action in ("ask", "inbox"):
        cap.label_payment_event(conn, USER, rec.event.id, category_id=answer, clock=when)
    return rec.decision.action


def test_a_shop_is_trusted_once_the_last_two_answers_agree(conn):
    assert pay(conn, 0, "food") in ("ask", "inbox")
    assert pay(conn, 1) == "auto_label"


def test_one_odd_answer_makes_the_shop_ask_again_until_two_agree(conn):
    pay(conn, 0, "food")
    pay(conn, 1, "food")
    assert pay(conn, 2) == "auto_label"
    assert pay(conn, 3, "other") == "auto_label"  # auto-tagged; the user changes it afterwards
    cap.label_payment_event(conn, USER, _last_event(conn), category_id="other", clock=START)
    assert pay(conn, 4, "food") in ("ask", "inbox"), "the odd answer must not be trusted yet"
    assert pay(conn, 5, "food") in ("ask", "inbox")
    assert pay(conn, 6) == "auto_label", "two agreeing answers earn the silence back"


def _last_event(conn):
    return conn.execute(
        "SELECT id FROM payment_events ORDER BY occurred_at DESC LIMIT 1"
    ).fetchone()[0]
