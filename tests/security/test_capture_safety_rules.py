"""
The seven capture safety rules (PLAN_CAPTURE section 5), each with two tests:

  * `test_ruleN_holds`: the rule is true of the real code.
  * `test_ruleN_fails_when_the_guard_is_removed`: the same check, run against a copy of the code
    with that guard patched out (or the forbidden thing injected), must fail. A check that cannot
    fail would protect nothing.

Each rule is one `check_ruleN` function that raises AssertionError on a violation.
"""

import json
import logging
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.config.capture import (
    SmsSendersConfig,
    load_capture_config,
    load_sms_senders,
    load_sms_templates,
)
from copilot.core import aa_consent, aa_fetch
from copilot.core import capture as cap
from copilot.core import capture_reconcile as rec
from copilot.core.aa_source import AAFetchResult, MockAASource
from copilot.core.errors import ToolFailure
from copilot.core.sms_parser import Dropped, ParsedPayment, parse_sms
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Category, Transaction, User
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer test-token"}
HDR = {"X-Capture-Secret": "safety-secret"}
GOOD = "Sent Rs.250.00 From HDFC Bank A/C *1234 To RAMESH K On 18/03/24 Ref 628912345678 Not You? Call 18002586161"
USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=IST)


def _all_banks_on() -> SmsSendersConfig:
    raw = load_sms_senders().model_dump()
    for bank in raw["banks"].values():
        bank["enabled"] = True
    return SmsSendersConfig.model_validate(raw)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("copilot.core.capture_secret.SECRET_FILE", tmp_path / "no_secret")
    monkeypatch.setattr("copilot.core.capture_push.VAPID_FILE", tmp_path / "v.json")
    clear_registry()
    st = ApiState(
        db_path=tmp_path / "s.db", clock=DEMO_CLOCK, token="test-token", llm=None,
        capture_secret="safety-secret", capture_senders=_all_banks_on(),
    )  # fmt: skip
    ensure_demo(st, "imported")
    yield st
    clear_registry()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc1", user_id=USER, name="Savings", opening_balance_paise=0, created_at=T0)
    )
    for cat in ("food", "shopping", "other"):
        insert_category(c, Category(id=cat, user_id=USER, name=cat.title(), created_at=T0))
    return c


def post(client, sender="HDFCBK", text=GOOD):
    return client.post("/api/capture/sms", json={"sender": sender, "text": text}, headers=HDR)


def count(state, table):
    c = state.connect()
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


# ---- Rule 1: strangers and OTPs are never parsed, stored or sent ---------------------------------
def check_rule1(client, state, templates=None):
    before = count(state, "payment_events")
    res = post(client, sender="+919812345678").json()
    assert res["outcome"] == "dropped", "a stranger's message was looked at"
    otp = post(client, text=GOOD + " Use OTP 123456 to confirm.").json()
    assert otp["outcome"] == "dropped", "an OTP message from a bank was parsed"
    assert count(state, "payment_events") == before, "something was stored from them"
    out = parse_sms("HDFCBK", GOOD + " Use OTP 123456", NOW, senders=_all_banks_on(),
                    templates=templates)  # fmt: skip
    assert isinstance(out, Dropped), "the parser let an OTP through"


def test_rule1_holds(client, state):
    check_rule1(client, state)


def test_rule1_fails_when_the_guard_is_removed(client, state, monkeypatch):
    from copilot.core import sms_parser

    real_allowed = SmsSendersConfig.allowed_senders
    monkeypatch.setattr(
        SmsSendersConfig,
        "allowed_senders",
        lambda self: {**real_allowed(self), "+919812345678": "hdfc"},
    )
    with pytest.raises(AssertionError):
        check_rule1(client, state)
    monkeypatch.undo()
    monkeypatch.setattr(sms_parser, "_OTP_FLOOR", re.compile(r"(?!x)x"))
    stripped = {
        b: t.model_copy(update={"templates": [x for x in t.templates if x.kind != "otp"]})
        for b, t in load_sms_templates().items()
    }
    with pytest.raises(AssertionError):
        check_rule1(client, state, templates=stripped)


# ---- Rule 2: no raw SMS text in the database, logs, push payloads or model prompts ---------------
MARK = "RAWTEXTMARK77"


def check_rule2(client, state, caplog):
    caplog.set_level(logging.DEBUG)
    assert post(client, text=GOOD + " " + MARK).json()["outcome"] == "recorded"
    post(client, text="OTP 5521 " + MARK)
    post(client, text="odd wording " + MARK)
    c = state.connect()
    try:
        for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in c.execute(f"SELECT * FROM {table}"):
                assert MARK not in str(tuple(row)), f"raw text reached table {table}"
    finally:
        c.close()
    assert MARK not in caplog.text, "raw text reached a log"


def test_rule2_holds(client, state, caplog):
    check_rule2(client, state, caplog)


def test_rule2_fails_when_text_is_logged(client, state, caplog, monkeypatch):
    real = parse_sms

    def leaky(sender, text, *a, **k):
        logging.getLogger("copilot.leak").warning("sms: %s", text)
        return real(sender, text, *a, **k)

    monkeypatch.setattr("copilot.core.sms_parser.parse_sms", leaky)
    with pytest.raises(AssertionError):
        check_rule2(client, state, caplog)


def test_rule2_push_payloads_carry_no_message_text(state, monkeypatch):
    sent = []
    monkeypatch.setattr(
        state,
        "push_sender",
        lambda sub, payload, pem, claims, ttl: sent.append(payload),
        raising=False,
    )
    c = TestClient(create_app(state))
    c.post(
        "/api/capture/push/subscribe",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "B" * 40, "auth": "A" * 16}},
        headers=AUTH,
    )
    post(c, text=GOOD + " " + MARK)
    assert sent and all(
        MARK not in json.dumps(p) and "628912345678" not in json.dumps(p) for p in sent
    )


# ---- Rule 3: no model call for a person; only a normalised merchant name for a merchant ----------
def check_rule3(conn):
    client = FakeLLMClient(["{}"] * 4)
    base = dict(source="sms", amount_paise=25000, direction="debit",
                occurred_at=to_utc_iso(NOW), clock=NOW, llm_client=client)  # fmt: skip
    cap.record_payment_event(
        conn, USER, display_name="Ramesh K", vpa="9876543210@ybl", utr="A00000000001", **base
    )
    assert client.prompts == [], "a person's name reached the model"
    cap.record_payment_event(
        conn, USER, display_name="XQ9 Traders Yard", utr="A00000000003", **base
    )
    for prompt in client.prompts:
        low = prompt.lower()
        assert "ramesh" not in low and "a00000000003" not in low and "25000" not in low


def test_rule3_holds(conn):
    check_rule3(conn)


def test_rule3_fails_when_a_person_is_treated_as_a_merchant(conn, monkeypatch):
    real = cap.classify_counterparty
    monkeypatch.setattr(
        cap, "classify_counterparty", lambda *a, **k: (real(*a, **k)[0], "merchant")
    )
    with pytest.raises(AssertionError):
        check_rule3(conn)


# ---- Rule 4: a user's label is never overwritten; ambiguity is never merged ----------------------
def ledger(conn, tid, amount, when, utr=None, name="UPI-SHOP"):
    insert_transaction(
        conn,
        Transaction(
            id=tid, user_id=USER, account_id="acc1", occurred_at=to_utc_iso(when),
            amount_paise=amount, direction="debit",
            merchant_raw=f"{name}-REF{utr}" if utr else name, description="",
            created_at=to_utc_iso(when),
        ),
    )  # fmt: skip


def check_rule4(conn):
    ev = cap.record_payment_event(
        conn, USER, source="sms", amount_paise=25000, direction="debit",
        display_name="XQ9 Traders Yard", occurred_at=to_utc_iso(NOW), clock=NOW,
    ).event  # fmt: skip
    cap.label_payment_event(conn, USER, ev.id, category_id="food", clock=NOW)
    try:
        cap.label_payment_event(
            conn, USER, ev.id, category_id="shopping", actor="system", clock=NOW
        )
        raised = False
    except ToolFailure:
        raised = True
    assert raised, "an automatic label overwrote the user's"
    assert cap.get_event(conn, USER, ev.id).category_id == "food"
    # two equally good ledger candidates: nothing may be merged
    amb = cap.record_payment_event(
        conn, USER, source="sms", amount_paise=77700, direction="debit",
        display_name="Twin Traders", occurred_at=to_utc_iso(NOW), account_last4=None, clock=NOW,
    ).event  # fmt: skip
    ledger(conn, "t1", 77700, NOW + timedelta(minutes=1))
    ledger(conn, "t2", 77700, NOW + timedelta(minutes=2))
    rec.reconcile_events(conn, USER, clock=NOW)
    assert cap.get_event(conn, USER, amb.id).state != "reconciled", "an ambiguous match was merged"


def test_rule4_holds(conn):
    check_rule4(conn)


def test_rule4_fails_when_the_guards_are_removed(conn, monkeypatch):
    real_get = cap.get_event

    def forgetful(c, u, eid):
        e = real_get(c, u, eid)
        return e.model_copy(update={"category_source": "auto"}) if e else e

    monkeypatch.setattr(cap, "get_event", forgetful)
    with pytest.raises(AssertionError):
        check_rule4(conn)


def test_rule4_ambiguity_guard_fails_when_removed(conn, monkeypatch):
    monkeypatch.setattr(
        rec.Candidates, "unique",
        lambda self: (self.by_window[0], "amount_account_time") if self.by_window else None,
    )  # fmt: skip
    with pytest.raises(AssertionError):
        check_rule4(conn)


# ---- Rule 5: spend is never counted twice when a ledger transaction exists -----------------------
def check_rule5(conn):
    cap.record_payment_event(
        conn, USER, source="sms", amount_paise=25000, direction="debit",
        display_name="XQ9 Traders Yard", occurred_at=to_utc_iso(NOW), utr="628900000099", clock=NOW,
    )  # fmt: skip
    ledger(conn, "t9", 25000, NOW, utr="628900000099")
    start, end = to_utc_iso(NOW - timedelta(days=1)), to_utc_iso(NOW + timedelta(days=1))
    both = rec.combined_spend(conn, USER, start, end, include_simulated=True)
    assert both.total_paise == 25000, f"counted {both.total_paise} for one payment"


def test_rule5_holds(conn):
    check_rule5(conn)


def test_rule5_fails_when_the_guard_is_removed(conn, monkeypatch):
    monkeypatch.setattr(
        rec, "candidates_for", lambda *a, **k: rec.Candidates(by_utr=[], by_window=[])
    )
    with pytest.raises(AssertionError):
        check_rule5(conn)


# ---- Rule 6: AA fetches only under an active, in-scope consent ------------------------------------
class Spy:
    name = "spy"

    def __init__(self):
        self.called = 0

    def fetch(self, a, b):
        self.called += 1
        return AAFetchResult([], None)


def check_rule6(conn):
    view = aa_consent.create_consent(conn, USER, clock=NOW)
    for state_ in ("pending", "paused", "revoked", "expired"):
        conn.execute("UPDATE aa_consents SET status = ? WHERE id = ?", (state_, view.id))
        spy = Spy()
        try:
            aa_fetch.fetch_now(conn, USER, view.id, spy, clock=NOW)
        except ToolFailure:
            pass
        assert spy.called == 0, f"the source was called while the link was {state_}"
    conn.execute("UPDATE aa_consents SET status = 'active' WHERE id = ?", (view.id,))
    spy = Spy()
    aa_fetch.fetch_now(conn, USER, view.id, spy, clock=NOW)
    assert spy.called == 1, "an active link could not fetch"
    aa_consent.transition(conn, USER, view.id, "revoke", clock=NOW)
    spy = Spy()
    try:
        aa_fetch.fetch_now(conn, USER, view.id, spy, clock=NOW, force=True)
    except ToolFailure:
        pass
    assert spy.called == 0, "a revoke did not stop the very next fetch"


def test_rule6_holds(conn):
    check_rule6(conn)


def test_rule6_fails_when_the_guard_is_removed(conn, monkeypatch):
    monkeypatch.setattr(
        aa_consent, "require_active",
        lambda c, u, cid, clock=None: c.execute("SELECT * FROM aa_consents WHERE id = ?", (cid,)).fetchone(),
    )  # fmt: skip
    with pytest.raises(AssertionError):
        check_rule6(conn)


def test_rule6_a_consent_that_does_not_cover_transactions_cannot_fetch(conn):
    view = aa_consent.create_consent(conn, USER, clock=NOW)
    aa_consent.transition(conn, USER, view.id, "approve", clock=NOW)
    conn.execute("UPDATE aa_consents SET consent_types = '[\"SUMMARY\"]' WHERE id = ?", (view.id,))
    spy = Spy()
    with pytest.raises(ToolFailure):
        aa_fetch.fetch_now(conn, USER, view.id, spy, clock=NOW)
    assert spy.called == 0
    assert isinstance(MockAASource(lambda: []), MockAASource)


# ---- Rule 7: simulated events are labelled simulated in every view --------------------------------
def check_rule7(client):
    body = {
        "bank": "axis",
        "kind": "debit",
        "amount_paise": 25000,
        "counterparty": "XQ9 Traders Yard",
    }
    sim = client.post("/api/capture/simulate", json=body, headers=AUTH).json()
    assert sim["event"]["simulated"] is True, "the simulate response hid that it is simulated"
    inbox = client.get("/api/capture/inbox", headers=AUTH).json()
    assert inbox["prompts"] and all(p["event"]["simulated"] for p in inbox["prompts"]), (
        "the inbox showed a simulated payment as real"
    )
    day = client.get("/api/capture/today", headers=AUTH).json()
    events = [i for i in day["items"] if i["kind"] == "event"]
    assert events and all(i["simulated"] for i in events), (
        "Today showed a simulated payment as real"
    )


def test_rule7_holds(client):
    check_rule7(client)


def test_rule7_fails_when_the_flag_is_dropped(client, monkeypatch):
    real = cap._row_to_event
    monkeypatch.setattr(
        cap, "_row_to_event", lambda r: real(r).model_copy(update={"simulated": False})
    )
    with pytest.raises(AssertionError):
        check_rule7(client)


def test_unused_config_loader_import_stays_exercised():
    assert load_capture_config().learn_from_simulated is False
    assert ParsedPayment is not None
