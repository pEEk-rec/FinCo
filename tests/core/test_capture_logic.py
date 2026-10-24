"""
The capture decisions, tested at their boundaries (PLAN_CAPTURE Stage C1): who a payee is,
whether to ask, and which three guesses to offer. Pure functions: same inputs, same answer.
"""

from datetime import datetime

import pytest

from copilot.config.capture import load_capture_config
from copilot.core.capture_logic import (
    AskContext,
    EventFacts,
    HistoryRow,
    classify_counterparty,
    decide_ask,
    in_quiet_hours,
    rank_guesses,
)
from copilot.core.timeutil import IST

CFG = load_capture_config()
NOON = datetime(2026, 10, 18, 12, 30, tzinfo=IST)


def ctx(**over) -> AskContext:
    return AskContext(
        local_time=over.pop("local_time", NOON), prompts_today=over.pop("prompts_today", 0), **over
    )


def debit(kind, amount=25000, channel="upi") -> EventFacts:
    return EventFacts(amount, "debit", kind, channel)


# ---- who is the counterparty ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "vpa", "channel", "kind"),
    [
        ("RAMESH K", "9876543210@ybl", "upi", "person"),
        ("Ramesh Kumar", None, "upi", "person"),
        ("PAYTMQR28100505@paytm", "paytmqr28100505@paytm", "upi", "merchant"),
        ("SHARMA STATIONERS", None, "upi", "merchant"),
        ("Sai General Store", "saigs@ybl", "upi", "merchant"),
        ("ATM CASH WDL", None, "atm", "cash"),
        ("XQ9 7T", None, "upi", "unknown"),
        ("Self transfer to savings", None, "imps", "self"),
    ],
)
def test_counterparty_kinds(name, vpa, channel, kind):
    assert classify_counterparty(name, vpa, channel, CFG)[1] == kind


def test_own_accounts_and_known_merchants_beat_the_name_heuristics():
    key, _ = classify_counterparty("Ramesh K", "ramesh@ybl", "upi", CFG)
    assert (
        classify_counterparty("Ramesh K", "ramesh@ybl", "upi", CFG, own_keys=frozenset({key}))[1]
        == "self"
    )
    assert (
        classify_counterparty(
            "Ramesh K", "ramesh@ybl", "upi", CFG, known_merchant_names=frozenset({key})
        )[1]
        == "merchant"
    )


def test_the_same_payee_always_gets_the_same_key():
    a = classify_counterparty("RAMESH  K.", None, "upi", CFG)[0]
    b = classify_counterparty("ramesh k", None, "upi", CFG)[0]
    assert a == b
    assert classify_counterparty("x", "Ramesh@YBL", "upi", CFG)[0] == "ramesh@ybl"


# ---- quiet hours ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("hh", "mm", "inside"),
    [(22, 59, False), (23, 0, True), (3, 0, True), (7, 29, True), (7, 30, False), (12, 0, False)],
)
def test_quiet_hours_cross_midnight_and_are_half_open(hh, mm, inside):
    t = datetime(2026, 10, 18, hh, mm, tzinfo=IST)
    assert in_quiet_hours(t, "23:00", "07:30") is inside


# ---- the ask policy: every branch ---------------------------------------------------------------
def test_own_transfer_is_never_asked_in_either_direction():
    for d in ("debit", "credit"):
        out = decide_ask(EventFacts(25000, d, "self", "imps"), ctx(), CFG)
        assert (out.action, out.reason) == ("no_ask", "own_transfer")


def test_known_merchant_is_silent_only_at_or_above_the_confidence_line():
    line = CFG.ask.auto_accept_min_confidence_bp
    ok = decide_ask(
        debit("merchant"),
        ctx(known_merchant_category="food", known_merchant_confidence_bp=line),
        CFG,
    )
    assert (ok.action, ok.category_id) == ("auto_label", "food")
    low = decide_ask(
        debit("merchant"),
        ctx(known_merchant_category="food", known_merchant_confidence_bp=line - 1),
        CFG,
    )
    assert low.action == "ask"


def test_recurring_and_autopay_never_ask():
    assert decide_ask(debit("merchant"), ctx(recurring_category="bills"), CFG).reason == "recurring"
    assert decide_ask(debit("merchant", channel="autopay"), ctx(), CFG).action == "auto_label"


def test_unknown_merchant_asks_once_then_the_override_makes_it_known():
    assert decide_ask(debit("unknown"), ctx(), CFG).reason == "unknown_merchant"


def test_a_person_is_asked_until_k_of_n_labels_agree():
    n = CFG.ask.person_policy.n
    agree = tuple(["rent"] * n)
    out = decide_ask(debit("person"), ctx(recent_categories=agree), CFG)
    assert (out.action, out.reason, out.category_id) == ("auto_label", "person_k_of_n", "rent")
    mixed = tuple(["rent"] * (n - 1) + ["food"])
    assert decide_ask(debit("person"), ctx(recent_categories=mixed), CFG).action == "ask"
    too_few = tuple(["rent"] * (n - 1))
    assert decide_ask(debit("person"), ctx(recent_categories=too_few), CFG).action == "ask"


def test_a_person_is_never_remembered_like_a_merchant():
    """Rent and dinner go to the same friend: a known-merchant answer must not apply to people."""
    out = decide_ask(
        debit("person"),
        ctx(known_merchant_category="food", known_merchant_confidence_bp=10000),
        CFG,
    )
    assert out.action == "ask"


def test_always_ask_and_always_category_are_the_users_own_words():
    n = CFG.ask.person_policy.n
    agree = tuple(["rent"] * n)
    forced = decide_ask(debit("person"), ctx(recent_categories=agree, policy="always_ask"), CFG)
    assert forced.action == "ask"
    always = decide_ask(
        debit("person"), ctx(policy="always_category", policy_category="gifts"), CFG
    )
    assert (always.action, always.category_id) == ("auto_label", "gifts")


def test_below_the_minimum_amount_only_a_guess_is_applied():
    floor = CFG.ask.min_ask_amount_paise
    assert decide_ask(debit("unknown", amount=floor - 1), ctx(), CFG).action == "guess_only"
    assert decide_ask(debit("unknown", amount=floor), ctx(), CFG).action == "ask"


def test_cash_is_a_low_priority_question_or_none_at_all():
    out = decide_ask(debit("cash", channel="atm"), ctx(), CFG)
    assert (out.action, out.priority) == ("ask", "low")
    quiet = CFG.model_copy(update={"ask": CFG.ask.model_copy(update={"ask_about_cash": False})})
    assert decide_ask(debit("cash", channel="atm"), ctx(), quiet).action == "guess_only"


def test_the_prompt_budget_quiet_hours_and_cooldown_send_asks_to_the_inbox():
    p = CFG.prompts
    assert decide_ask(debit("unknown"), ctx(prompts_today=p.max_per_day - 1), CFG).action == "ask"
    full = decide_ask(debit("unknown"), ctx(prompts_today=p.max_per_day), CFG)
    assert (full.action, full.reason) == ("inbox", "daily_budget")
    night = decide_ask(
        debit("unknown"), ctx(local_time=datetime(2026, 10, 18, 2, 0, tzinfo=IST)), CFG
    )
    assert (night.action, night.reason) == ("inbox", "quiet_hours")
    edge = p.per_counterparty_cooldown_hours * 60
    assert (
        decide_ask(debit("unknown"), ctx(minutes_since_counterparty_prompt=edge - 1), CFG).reason
        == "counterparty_cooldown"
    )
    assert (
        decide_ask(debit("unknown"), ctx(minutes_since_counterparty_prompt=edge), CFG).action
        == "ask"
    )


def test_credits_refund_known_inflow_and_the_rest_asks():
    cred = EventFacts(25000, "credit", "person", "upi")
    r = decide_ask(cred, ctx(refund_of_event_id="pev_1"), CFG)
    assert (r.action, r.credit_kind, r.linked_event_id) == ("auto_label", "refund", "pev_1")
    s = decide_ask(cred, ctx(known_inflow_kind="salary"), CFG)
    assert (s.action, s.credit_kind) == ("auto_label", "salary")
    assert decide_ask(cred, ctx(), CFG).reason == "credit_needs_you"
    tiny = EventFacts(CFG.ask.min_ask_amount_paise - 1, "credit", "person", "upi")
    assert decide_ask(tiny, ctx(), CFG).action == "guess_only"


# ---- the guesses ------------------------------------------------------------------------------
def row(cp, label, hours_ago=48, amount=25000, direction="debit") -> HistoryRow:
    when = NOON.replace(day=18) - __import__("datetime").timedelta(hours=hours_ago)
    return HistoryRow(cp, label, amount, when, direction)


def guess(history, **over):
    args = {
        "counterparty": "ramesh@ybl", "direction": "debit", "amount_paise": 25000, "when": NOON,
        "history": history, "cfg": CFG, "fallback_labels": ["food", "other", "travel"],
    }  # fmt: skip
    return rank_guesses(**{**args, **over})


def test_the_payees_own_history_leads_and_ranking_is_deterministic():
    h = [
        row("ramesh@ybl", "rent", 100),
        row("ramesh@ybl", "rent", 300),
        row("shop@ybl", "food", 200),
    ]
    first = guess(h)
    assert first[0].label == "rent"
    assert [g.label for g in guess(h)] == [g.label for g in first]
    assert len(first) == CFG.ranking.guess_count


def test_recent_history_outweighs_old_history():
    old = [row("ramesh@ybl", "rent", 24 * 400)] * 3
    new = [row("ramesh@ybl", "food", 24 * 2)]
    assert guess(old + new)[0].label == "food"


def test_ties_break_on_the_label_and_fill_comes_from_the_fallbacks():
    out = guess([], fallback_labels=["travel", "food", "other"])
    assert [g.label for g in out] == ["travel", "food", "other"]
    assert all(g.score_bp == 0 for g in out)


def test_fewer_than_three_with_evidence_are_filled_with_frequent_labels():
    h = [row("a@ybl", "food"), row("b@ybl", "food"), row("c@ybl", "travel")]
    labels = [g.label for g in guess(h, counterparty="new@ybl")]
    assert labels[:2] == ["food", "travel"] and len(labels) == 3


def test_a_name_hint_joins_the_candidates_but_history_still_ranks():
    h = [row("ramesh@ybl", "rent", 50), row("ramesh@ybl", "rent", 80)]
    out = guess(h, hint_label="groceries")
    assert out[0].label == "rent" and "groceries" in [g.label for g in out]


def test_credits_rank_credit_kinds_not_categories():
    h = [row("boss@ybl", "salary", 24 * 30, 5000000, "credit"), row("shop@ybl", "food", 10)]
    out = guess(
        h,
        counterparty="boss@ybl",
        direction="credit",
        amount_paise=5000000,
        fallback_labels=["gift"],
    )
    assert out[0].label == "salary" and "food" not in [g.label for g in out]


def test_every_guess_explains_itself_when_it_has_evidence():
    h = [row("ramesh@ybl", "rent", 100)]
    top = guess(h)[0]
    assert top.reasons and top.score_bp > 0
