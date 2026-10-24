"""
Account Aggregator consent and fetch (PLAN_CAPTURE Stage C7). Safety rule 6: a fetch only ever
happens under an active, in-scope consent, and a revoke takes effect on the next check.
"""

import json
from datetime import datetime, timedelta

import pytest

from copilot.core import aa_consent, aa_fetch
from copilot.core import capture as cap
from copilot.core.aa_source import (
    AAFetchResult,
    MockAASource,
    bank_side_feed,
    rebit_deposit_payload,
)
from copilot.core.errors import ToolFailure
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.live.aa import parse_fi_data
from copilot.models.domain import Account, Category, User

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc1", user_id=USER, name="Savings", opening_balance_paise=0, created_at=T0)
    )
    for cat in ("food", "other"):
        insert_category(c, Category(id=cat, user_id=USER, name=cat.title(), created_at=T0))
    return c


def make(conn, approve=True):
    view = aa_consent.create_consent(conn, USER, clock=NOW)
    if approve:
        view = aa_consent.transition(conn, USER, view.id, "approve", clock=NOW)
    return view


def txn(utr, amount="250.00", kind="DEBIT", when=None, name="XQ9 TRADERS"):
    stamp = to_utc_iso(when or NOW - timedelta(hours=5))
    return {
        "txnId": utr, "type": kind, "mode": "UPI", "amount": amount, "currentBalance": "0.00",
        "transactionTimestamp": stamp, "valueDate": stamp[:10],
        "narration": f"UPI/{utr}/{name}", "reference": utr,
    }  # fmt: skip


def source(*txns):
    return MockAASource(lambda: list(txns))


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---- state machine ---------------------------------------------------------------------------
LEGAL = [
    ("pending", "approve", "active"),
    ("pending", "revoke", "revoked"),
    ("active", "pause", "paused"),
    ("active", "revoke", "revoked"),
    ("paused", "resume", "active"),
    ("paused", "revoke", "revoked"),
]
LEGAL_PAIRS = {(s, a) for s, a, _ in LEGAL}
STATES = ["pending", "active", "paused", "revoked", "expired"]
ILLEGAL = [(s, a) for s in STATES for a in ("approve", "pause", "resume", "revoke")
           if (s, a) not in LEGAL_PAIRS]  # fmt: skip


def put_in_state(conn, cid, state):
    conn.execute("UPDATE aa_consents SET status = ? WHERE id = ?", (state, cid))


@pytest.mark.parametrize(("start", "action", "end"), LEGAL)
def test_every_legal_transition_lands_where_it_should(conn, start, action, end):
    cid = make(conn, approve=False).id
    put_in_state(conn, cid, start)
    assert aa_consent.transition(conn, USER, cid, action, clock=NOW).status == end


@pytest.mark.parametrize(("start", "action"), ILLEGAL)
def test_every_illegal_transition_is_refused_and_changes_nothing(conn, start, action):
    cid = make(conn, approve=False).id
    put_in_state(conn, cid, start)
    with pytest.raises(ToolFailure):
        aa_consent.transition(conn, USER, cid, action, clock=NOW)
    assert aa_consent.get_consent(conn, USER, cid).status == start


def test_only_one_live_link_at_a_time_but_a_new_one_after_revoking(conn):
    first = make(conn)
    with pytest.raises(ToolFailure):
        aa_consent.create_consent(conn, USER, clock=NOW)
    aa_consent.transition(conn, USER, first.id, "revoke", clock=NOW)
    assert aa_consent.create_consent(conn, USER, clock=NOW).status == "pending"


def test_the_artefact_is_stated_in_plain_language_from_config(conn):
    v = make(conn, approve=False)
    assert v.how_often == "Every day."
    assert "6 months" in v.how_long and "180 days" in v.data_kept
    assert v.can == ["approve", "revoke"]


def test_expiry_ends_a_consent_that_reached_its_date(conn):
    cid = make(conn).id
    later = NOW + timedelta(days=200)
    expired, _ = aa_consent.expire_due(conn, USER, clock=later)
    assert expired == 1 and aa_consent.get_consent(conn, USER, cid).status == "expired"
    with pytest.raises(ToolFailure):
        aa_consent.require_active(conn, USER, cid, later)


# ---- scope and revoke (safety rule 6) ----------------------------------------------------------
def test_a_fetch_needs_an_approved_consent(conn):
    cid = make(conn, approve=False).id
    with pytest.raises(ToolFailure, match="pending"):
        aa_fetch.fetch_now(conn, USER, cid, source(txn("628900000001")), clock=NOW)
    assert count(conn, "transactions") == 0


@pytest.mark.parametrize("state", ["paused", "revoked", "expired"])
def test_no_fetch_in_any_inactive_state(conn, state):
    cid = make(conn).id
    put_in_state(conn, cid, state)
    called = []

    class Spy:
        name = "spy"

        def fetch(self, a, b):
            called.append(1)
            return AAFetchResult([], None)

    with pytest.raises(ToolFailure):
        aa_fetch.fetch_now(conn, USER, cid, Spy(), clock=NOW)
    assert called == [], "the source must never be called outside an active consent"


def test_a_revoke_that_lands_mid_fetch_discards_the_result(conn):
    cid = make(conn).id

    class RevokedWhileAnswering:
        name = "slow"

        def fetch(self, a, b):
            aa_consent.transition(conn, USER, cid, "revoke", clock=NOW)
            return MockAASource(lambda: [txn("628900000002")]).fetch(a, b)

    with pytest.raises(ToolFailure):
        aa_fetch.fetch_now(conn, USER, cid, RevokedWhileAnswering(), clock=NOW)
    assert count(conn, "transactions") == 0 and count(conn, "aa_raw") == 0


def test_a_consent_without_transactions_in_scope_cannot_fetch(conn):
    cid = make(conn).id
    conn.execute("UPDATE aa_consents SET consent_types = ? WHERE id = ?", ('["SUMMARY"]', cid))
    with pytest.raises(ToolFailure, match="transactions"):
        aa_consent.require_active(conn, USER, cid, NOW)


def test_rows_outside_the_consented_range_are_dropped(conn):
    cid = make(conn).id
    old = txn("628900000003", when=NOW - timedelta(days=400))
    new = txn("628900000004")
    rep = aa_fetch.fetch_now(conn, USER, cid, source(old, new), clock=NOW)
    assert rep.fetched == 2 and rep.out_of_range == 1 and rep.inserted == 1


def test_revoking_also_deletes_what_was_fetched_under_it(conn):
    cid = make(conn).id
    aa_fetch.fetch_now(conn, USER, cid, source(txn("628900000005")), clock=NOW)
    assert count(conn, "aa_raw") == 1
    aa_consent.transition(conn, USER, cid, "revoke", clock=NOW)
    assert count(conn, "aa_raw") == 0


# ---- schema parsing --------------------------------------------------------------------------
def test_a_rebit_deposit_reply_parses_to_rows_in_integer_paise():
    payload = rebit_deposit_payload(
        [txn("628900000006", "1,234.50"), txn("628900000007", "99.00", "CREDIT")],
        "XXXX1234", NOW - timedelta(days=30), NOW,
    )  # fmt: skip
    rows = parse_fi_data(payload)
    assert [(r.amount_paise, r.direction) for r in rows] == [(123450, "debit"), (9900, "credit")]
    assert rows[0].reference == "628900000006" and "628900000006" in rows[0].narration


def test_the_payload_is_valid_json_with_the_deposit_shape():
    p = rebit_deposit_payload([txn("628900000008")], "XXXX1234", NOW, NOW)
    t = json.loads(json.dumps(p))["fi"][0]["Account"]["Transactions"]["Transaction"][0]
    assert {"txnId", "type", "mode", "amount", "transactionTimestamp", "narration"} <= set(t)


# ---- reconciliation with captured events -------------------------------------------------------
def heard(conn, utr, amount=25000, hours_ago=5, name="XQ9 Traders Yard"):
    return cap.record_payment_event(
        conn, USER, source="sms", amount_paise=amount, direction="debit", display_name=name,
        occurred_at=to_utc_iso(NOW - timedelta(hours=hours_ago)), utr=utr, clock=NOW,
    )  # fmt: skip


def test_an_aa_fetch_reconciles_with_the_alert_and_carries_the_users_label(conn):
    rec = heard(conn, "628900000010")
    cap.label_payment_event(conn, USER, rec.event.id, category_id="food", clock=NOW)
    cid = make(conn).id
    feed = MockAASource(bank_side_feed(conn, USER, NOW))
    rep = aa_fetch.fetch_now(conn, USER, cid, feed, clock=NOW)
    assert rep.inserted == 1 and rep.matched == 1
    cat, src = conn.execute("SELECT category_id, category_source FROM transactions").fetchone()
    assert (cat, src) == ("food", "user")
    assert cap.get_event(conn, USER, rec.event.id).state == "reconciled"


def test_a_second_fetch_adds_nothing_and_never_double_counts(conn):
    heard(conn, "628900000011")
    cid = make(conn).id
    feed = source(txn("628900000011"))  # a bank repeats what it already told us
    aa_fetch.fetch_now(conn, USER, cid, feed, clock=NOW)
    again = aa_fetch.fetch_now(conn, USER, cid, feed, clock=NOW, force=True)
    assert again.inserted == 0 and again.already_known == 1
    assert count(conn, "transactions") == 1


def test_a_payment_too_recent_for_the_bank_is_not_fetched_yet(conn):
    heard(conn, "628900000012", hours_ago=0)
    cid = make(conn).id
    feed = MockAASource(bank_side_feed(conn, USER, NOW))
    assert aa_fetch.fetch_now(conn, USER, cid, feed, clock=NOW).fetched == 0


# ---- data life and the daily cycle -------------------------------------------------------------
def test_fetched_copies_are_deleted_when_their_data_life_ends(conn):
    cid = make(conn).id
    aa_fetch.fetch_now(conn, USER, cid, source(txn("628900000013")), clock=NOW)
    days = conn.execute("SELECT data_life_days FROM aa_consents").fetchone()[0]
    assert aa_consent.expire_due(conn, USER, clock=NOW + timedelta(days=days - 1))[1] == 0
    assert aa_consent.expire_due(conn, USER, clock=NOW + timedelta(days=days + 1))[1] == 1
    assert count(conn, "transactions") == 1, "the ledger rows are the user's and stay"


def test_the_daily_cycle_fetches_once_a_day_and_skips_when_not_due(conn):
    heard(conn, "628900000014")
    make(conn)
    first = aa_fetch.run_cycle(conn, USER, clock=NOW)
    again = aa_fetch.run_cycle(conn, USER, clock=NOW + timedelta(hours=3))
    next_day = aa_fetch.run_cycle(conn, USER, clock=NOW + timedelta(hours=25))
    assert first.fetches[0].inserted == 1
    assert again.fetches[0].skipped == "not due yet"
    assert next_day.fetches[0].skipped is None


def test_the_cycle_does_nothing_for_a_revoked_link(conn):
    cid = make(conn).id
    aa_consent.transition(conn, USER, cid, "revoke", clock=NOW)
    assert aa_fetch.run_cycle(conn, USER, clock=NOW).fetches == []
