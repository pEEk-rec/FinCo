"""
Reconciliation, reversals, the provisional ledger and coverage health
(PLAN_CAPTURE Stage C4). The headline rules: a UTR match first, never merge on ambiguity,
a user's label becomes the ledger's, and no spend view ever counts a payment twice.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from copilot.core import capture as cap
from copilot.core.capture_reconcile import (
    combined_spend,
    coverage_health,
    reconcile_events,
    set_account_last4,
)
from copilot.core.errors import ToolFailure
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.models.domain import Account, Category, Transaction, User

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=IST)
UTC = UTC
CATS = ["food", "rent", "gifts", "other"]


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc1", user_id=USER, name="Savings", opening_balance_paise=0, created_at=T0)
    )
    for cat in CATS:
        insert_category(c, Category(id=cat, user_id=USER, name=cat.title(), created_at=T0))
    return c


def utc(dt: datetime) -> str:
    return to_utc_iso(dt)


def ledger(
    conn,
    amount,
    utr=None,
    when=NOW,
    account="acc1",
    direction="debit",
    category=None,
    source="none",
    name="UPI-SHOP",
):
    txn = Transaction(
        id=f"t_{uuid.uuid4().hex[:8]}", user_id=USER, account_id=account, occurred_at=utc(when),
        amount_paise=amount if direction == "debit" else -amount, direction=direction,
        merchant_raw=f"{name}-REF{utr}" if utr else name, description="", category_id=category,
        category_source=source, created_at=utc(when),
    )  # fmt: skip
    insert_transaction(conn, txn)
    return txn.id


def event(
    conn,
    amount,
    utr=None,
    name="XQ9 Traders Yard",
    when=NOW,
    last4=None,
    direction="debit",
    simulated=False,
    **kw,
):
    return cap.record_payment_event(
        conn, USER, source="simulator" if simulated else "sms", amount_paise=amount, direction=direction,
        display_name=name, occurred_at=utc(when), utr=utr, account_last4=last4, simulated=simulated,
        clock=when, **kw,
    ).event  # fmt: skip


def state(conn, event_id):
    return cap.get_event(conn, USER, event_id)


# ---- matching ---------------------------------------------------------------------------------
def test_a_utr_match_links_the_event_and_carries_the_users_label(conn):
    ev = event(conn, 25000, utr="628912345678")
    cap.label_payment_event(conn, USER, ev.id, category_id="gifts", clock=NOW)
    txn = ledger(conn, 25000, utr="628912345678", category="other", source="rule")
    report = reconcile_events(conn, USER, clock=NOW)
    assert report.matched == 1 and report.ambiguous == 0
    assert state(conn, ev.id).state == "reconciled"
    row = conn.execute(
        "SELECT category_id, category_source, needs_review FROM transactions WHERE id = ?", (txn,)
    ).fetchone()
    assert (row[0], row[1], row[2]) == ("gifts", "user", 0)
    link = conn.execute(
        "SELECT txn_id, method FROM event_links WHERE event_id = ?", (ev.id,)
    ).fetchone()
    assert (link[0], link[1]) == (txn, "utr")


def test_a_guess_is_not_carried_to_the_ledger_only_a_users_choice_is(conn):
    ev = event(conn, 2000, utr="628900000001")  # small: a guess, not asked
    assert state(conn, ev.id).category_source == "guess"
    txn = ledger(conn, 2000, utr="628900000001", category="food", source="rule")
    reconcile_events(conn, USER, clock=NOW)
    row = conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = ?", (txn,)
    ).fetchone()
    assert (row[0], row[1]) == ("food", "rule")


def test_the_utr_must_come_with_the_same_amount(conn):
    ev = event(conn, 25000, utr="628912345678")
    ledger(conn, 25100, utr="628912345678")
    assert reconcile_events(conn, USER, clock=NOW).matched == 0
    assert state(conn, ev.id).state == "posted"


def test_two_ledger_rows_with_the_same_utr_are_never_merged_by_guessing(conn):
    ev = event(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    report = reconcile_events(conn, USER, clock=NOW)
    assert (report.matched, report.ambiguous) == (0, 1)
    assert state(conn, ev.id).state == "posted"
    assert conn.execute("SELECT COUNT(*) FROM event_links").fetchone()[0] == 0


def test_without_a_utr_amount_account_and_time_can_match_when_unique(conn):
    set_account_last4(conn, USER, "acc1", "1234", clock=NOW)
    ev = event(conn, 25000, last4="1234", when=NOW)
    txn = ledger(conn, 25000, when=NOW + timedelta(minutes=5))
    assert reconcile_events(conn, USER, clock=NOW).matched == 1
    assert conn.execute(
        "SELECT txn_id, method FROM event_links WHERE event_id = ?", (ev.id,)
    ).fetchone()[:] == (txn, "amount_account_time")


def test_the_time_window_has_an_edge(conn):
    set_account_last4(conn, USER, "acc1", "1234", clock=NOW)
    window = 20
    inside = event(conn, 25000, last4="1234", when=NOW, name="Alpha Traders")
    ledger(conn, 25000, when=NOW + timedelta(minutes=window))
    outside = event(conn, 31000, last4="1234", when=NOW, name="Beta Traders")
    ledger(conn, 31000, when=NOW + timedelta(minutes=window + 1))
    reconcile_events(conn, USER, clock=NOW)
    assert state(conn, inside.id).state == "reconciled"
    assert state(conn, outside.id).state == "posted"


def test_two_equal_payments_at_the_same_time_are_left_unmerged(conn):
    set_account_last4(conn, USER, "acc1", "1234", clock=NOW)
    ev = event(conn, 25000, last4="1234")
    ledger(conn, 25000, when=NOW + timedelta(minutes=2))
    ledger(conn, 25000, when=NOW + timedelta(minutes=3))
    assert reconcile_events(conn, USER, clock=NOW).ambiguous == 1
    assert state(conn, ev.id).state == "posted"


def test_a_ledger_row_is_claimed_by_one_event_only(conn):
    first = event(conn, 25000, utr="628911111111", name="Alpha Traders")
    ledger(conn, 25000, utr="628911111111")
    reconcile_events(conn, USER, clock=NOW)
    # a second alert for an equal amount and a different UTR must not steal the claimed row
    second = event(conn, 25000, utr="628922222222", name="Alpha Traders", when=NOW)
    reconcile_events(conn, USER, clock=NOW)
    assert state(conn, first.id).state == "reconciled"
    assert state(conn, second.id).state == "posted"
    assert conn.execute("SELECT COUNT(*) FROM event_links").fetchone()[0] == 1


def test_a_users_earlier_choice_on_the_ledger_row_is_not_overwritten(conn):
    ev = event(conn, 25000, utr="628912345678")
    cap.label_payment_event(conn, USER, ev.id, category_id="gifts", clock=NOW)
    txn = ledger(conn, 25000, utr="628912345678", category="rent", source="user")
    report = reconcile_events(conn, USER, clock=NOW)
    assert report.label_conflicts == 1
    row = conn.execute("SELECT category_id FROM transactions WHERE id = ?", (txn,)).fetchone()
    assert row[0] == "rent"


def test_reconciling_twice_changes_nothing_more(conn):
    event(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    first = reconcile_events(conn, USER, clock=NOW)
    second = reconcile_events(conn, USER, clock=NOW)
    assert first.matched == 1 and second.matched == 0
    assert conn.execute("SELECT COUNT(*) FROM event_links").fetchone()[0] == 1


def test_an_unmatched_event_becomes_unverified_after_the_wait_and_can_still_match_later(conn):
    ev = event(conn, 25000, utr="628912345678", when=NOW - timedelta(hours=80))
    assert reconcile_events(conn, USER, clock=NOW).orphaned == 1
    assert state(conn, ev.id).state == "orphaned"
    ledger(conn, 25000, utr="628912345678", when=NOW - timedelta(hours=79))
    assert reconcile_events(conn, USER, clock=NOW).matched == 1
    assert state(conn, ev.id).state == "reconciled"


def test_own_transfers_are_never_reconciled_as_spend(conn):
    ev = event(conn, 500000, name="Self transfer to savings", utr="628900000009")
    assert ev.counterparty_kind == "self"
    ledger(conn, 500000, utr="628900000009")
    assert reconcile_events(conn, USER, clock=NOW).matched == 0


def test_a_label_the_agent_makes_is_never_the_users_and_is_not_carried_to_the_ledger(conn):
    ev = event(conn, 25000, utr="628912345678")
    labelled = cap.label_payment_event(
        conn, USER, ev.id, category_id="gifts", actor="agent", clock=NOW
    )
    assert labelled.category_source == "auto"
    txn = ledger(conn, 25000, utr="628912345678", category="food", source="rule")
    reconcile_events(conn, USER, clock=NOW)
    row = conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = ?", (txn,)
    ).fetchone()
    assert (row[0], row[1]) == ("food", "rule")
    # and the user can still say what it was, after which the agent can no longer change it
    cap.label_payment_event(conn, USER, ev.id, category_id="rent", clock=NOW)
    with pytest.raises(ToolFailure):
        cap.label_payment_event(conn, USER, ev.id, category_id="gifts", actor="agent", clock=NOW)


# ---- reversals --------------------------------------------------------------------------------
def test_a_reversal_cancels_the_payment_it_undoes_and_its_question(conn):
    pay = event(conn, 25000, utr="628912345678")
    assert (
        conn.execute("SELECT status FROM prompt_log WHERE event_id = ?", (pay.id,)).fetchone()[0]
        == "pending"
    )
    rev = cap.record_payment_event(
        conn, USER, source="sms", amount_paise=25000, direction="credit", display_name="Reversal",
        occurred_at=utc(NOW + timedelta(minutes=30)), reversal_of_utr="628912345678", clock=NOW,
    )  # fmt: skip
    assert state(conn, pay.id).state == "reversed"
    assert (
        conn.execute("SELECT status FROM prompt_log WHERE event_id = ?", (pay.id,)).fetchone()[0]
        == "dismissed"
    )
    assert (rev.decision.action, rev.event.credit_kind) == ("auto_label", "refund")
    link = conn.execute(
        "SELECT linked_event_id FROM capture_labels WHERE event_id = ?", (rev.event.id,)
    ).fetchone()
    assert link[0] == pay.id


def test_a_reversed_payment_adds_no_spend_and_a_repeated_reversal_is_ignored(conn):
    pay = event(conn, 25000, utr="628912345678", when=NOW)
    args = dict(
        source="sms", amount_paise=25000, direction="credit", display_name="Reversal",
        occurred_at=utc(NOW), reversal_of_utr="628912345678", clock=NOW,
    )  # fmt: skip
    first = cap.record_payment_event(conn, USER, **args)
    again = cap.record_payment_event(conn, USER, **args)
    assert first.created and not again.created
    start, end = utc(NOW - timedelta(days=1)), utc(NOW + timedelta(days=1))
    assert combined_spend(conn, USER, start, end).provisional_paise == 0
    assert state(conn, pay.id).state == "reversed"


def test_a_reversal_with_no_earlier_event_is_still_recorded_and_asked_about(conn):
    rev = cap.record_payment_event(
        conn, USER, source="sms", amount_paise=25000, direction="credit", display_name="Reversal",
        occurred_at=utc(NOW), reversal_of_utr="628900009999", clock=NOW,
    )  # fmt: skip
    assert rev.created and rev.decision.action in {"ask", "inbox"}


# ---- no double counting -----------------------------------------------------------------------
def span():
    return utc(NOW - timedelta(days=2)), utc(NOW + timedelta(days=2))


def test_an_event_in_the_ledger_is_counted_once(conn):
    event(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    start, end = span()
    before = combined_spend(conn, USER, start, end)
    assert (before.ledger_paise, before.provisional_paise) == (25000, 0), "a candidate exists"
    reconcile_events(conn, USER, clock=NOW)
    after = combined_spend(conn, USER, start, end)
    assert after.total_paise == 25000


def test_an_event_with_no_ledger_candidate_is_provisional_and_counted(conn):
    event(conn, 25000, utr="628912345678")
    start, end = span()
    out = combined_spend(conn, USER, start, end)
    assert (out.ledger_paise, out.provisional_paise, out.unverified_events) == (0, 25000, 1)


def test_ambiguous_candidates_are_not_counted_twice(conn):
    event(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    ledger(conn, 25000, utr="628912345678")
    start, end = span()
    out = combined_spend(conn, USER, start, end)
    assert out.provisional_paise == 0 and out.ledger_paise == 50000


def test_simulated_events_stay_out_of_real_spend_unless_asked_for(conn):
    event(conn, 25000, utr="628912345678", simulated=True)
    start, end = span()
    assert combined_spend(conn, USER, start, end).provisional_paise == 0
    assert combined_spend(conn, USER, start, end, include_simulated=True).provisional_paise == 25000


def test_no_double_counting_in_any_random_mix_of_events_and_ledger_rows(conn):
    """Property: total = ledger + provisional, and provisional never includes an event the
    ledger already holds, whatever order things arrive in."""
    rng = random.Random(11)
    expected_ledger = 0
    for i in range(60):
        amount = rng.choice([10000, 25000, 40000, 70000])
        utr = f"6289{i:08d}"
        when = NOW - timedelta(minutes=rng.randint(0, 600))
        roll = rng.random()
        if roll < 0.35:
            event(conn, amount, utr=utr, when=when, name=f"Shop {i % 7} Traders")
            ledger(conn, amount, utr=utr, when=when)
            expected_ledger += amount
        elif roll < 0.55:
            ledger(conn, amount, utr=utr, when=when)
            expected_ledger += amount
        elif roll < 0.8:
            event(conn, amount, utr=utr, when=when, name=f"Shop {i % 7} Traders")
        else:  # a duplicated alert for the same payment
            event(conn, amount, utr=utr, when=when, name=f"Shop {i % 7} Traders")
            event(conn, amount, utr=utr, when=when, name=f"Shop {i % 7} Traders")
        if i % 9 == 0:
            reconcile_events(conn, USER, clock=NOW)
    start, end = utc(NOW - timedelta(days=1)), utc(NOW + timedelta(days=1))
    out = combined_spend(conn, USER, start, end)
    assert out.ledger_paise == expected_ledger
    reconcile_events(conn, USER, clock=NOW)
    final = combined_spend(conn, USER, start, end)
    # recompute, independently, which unlinked events still have a ledger row they could be
    free_rows = {
        (r[0], r[1])
        for r in conn.execute(
            "SELECT ABS(amount_paise), merchant_raw FROM transactions WHERE id NOT IN"
            " (SELECT txn_id FROM event_links)"
        )
    }
    expected_provisional = 0
    for amount, utr in conn.execute(
        "SELECT amount_paise, utr FROM payment_events WHERE direction = 'debit'"
        " AND state IN ('posted', 'orphaned')"
    ):
        if not any(a == amount and utr in raw for a, raw in free_rows):
            expected_provisional += amount
    assert final.provisional_paise == expected_provisional
    assert final.total_paise == final.ledger_paise + final.provisional_paise
    # a payment that is in the ledger is never also provisional
    linked = conn.execute(
        "SELECT COUNT(*) FROM payment_events e JOIN event_links l ON l.event_id = e.id"
        " WHERE e.state != 'reconciled'"
    ).fetchone()[0]
    assert linked == 0


# ---- coverage health --------------------------------------------------------------------------
def test_the_coverage_message_appears_only_past_its_thresholds(conn):
    from copilot.config.capture import load_reconcile_config

    cfg = load_reconcile_config().coverage
    now = NOW
    for i in range(cfg.min_ledger_txns - 1):
        ledger(conn, 1000 + i, when=now - timedelta(days=1, minutes=i))
    row = coverage_health(conn, USER, now)[0]
    assert row.warn is False and "Not enough" in row.message
    ledger(conn, 1999, when=now - timedelta(days=1, minutes=50))
    row = coverage_health(conn, USER, now)[0]
    assert row.warn is True and "another phone" in row.message
    assert row.ledger_txns == cfg.min_ledger_txns and row.alerts == 0


def test_alerts_that_kept_up_clear_the_warning(conn):
    from copilot.config.capture import load_reconcile_config

    n = load_reconcile_config().coverage.min_ledger_txns
    for i in range(n):
        utr = f"6289{i:08d}"
        when = NOW - timedelta(days=1, minutes=i * 7)
        event(conn, 5000 + i, utr=utr, when=when, name=f"Shop {i} Traders")
        ledger(conn, 5000 + i, utr=utr, when=when)
    reconcile_events(conn, USER, clock=NOW)
    row = coverage_health(conn, USER, NOW)[0]
    assert row.warn is False and row.alerts == n and row.share_bp == 10000
    assert "keeping up" in row.message


def test_account_tails_are_validated(conn):
    with pytest.raises(ToolFailure):
        set_account_last4(conn, USER, "acc1", "12a4")
    with pytest.raises(ToolFailure):
        set_account_last4(conn, USER, "nope", "1234")
