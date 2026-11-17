"""
The personal model (PLAN_AGENTIC_V2 A8 to A12): profile, budget co-pilot, nudges, the check-in agent,
shared expenses and subscriptions. Rules 6 to 10 of the plan each have a twin that fails when the
guard is removed.
"""

import json
from datetime import datetime, timedelta

import pytest

from copilot.agents import checkin as ck
from copilot.common.errors import ToolFailure
from copilot.common.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_budget,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.learning import nudges
from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.personal import budget as bc
from copilot.personal import profile as prof
from copilot.personal import splits as sp
from copilot.personal import subscriptions as subs

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=IST)  # a Sunday morning
CATS = {
    "food": "Dining",
    "shopping": "Shopping",
    "travel": "Travel",
    "bills": "Utilities",
    "housing": "Rent",
}
_n = [0]
REAL_CFG = ck.load_checkin_config()


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc", user_id=USER, name="S", opening_balance_paise=5_000_000, created_at=T0)
    )
    for cid, name in CATS.items():
        insert_category(c, Category(id=cid, user_id=USER, name=name, created_at=T0))
    return c


def tx(conn, cat, paise, when, merchant="shop", direction="debit"):
    _n[0] += 1
    insert_transaction(
        conn,
        Transaction(
            id=f"t{_n[0]}", user_id=USER, account_id="acc", occurred_at=to_utc_iso(when),
            amount_paise=paise if direction == "debit" else -paise, direction=direction,
            merchant_raw=merchant, merchant_normalized=merchant, description="", category_id=cat,
            category_source="user", created_at=to_utc_iso(when),
        ),
    )  # fmt: skip


def history(conn, months=3):
    """Three steady months: food 6000, shopping 3000, travel 2000, utilities 1500 (rupees)."""
    for k in range(1, months + 1):
        base = (NOW.replace(day=1) - timedelta(days=30 * k)).replace(day=10)
        for cat, rupees in (("food", 6000), ("shopping", 3000), ("travel", 2000), ("bills", 1500)):
            tx(conn, cat, rupees * 100, base, merchant=f"{cat}_shop")


def set_profile(conn, income=60_000, savings=5_000, priorities=("food", "travel")):
    prof.set_field(
        conn,
        USER,
        "income",
        {"kind": "monthly", "expected_paise": income * 100, "day_of_month": 1},
        clock=NOW,
    )
    prof.set_field(conn, USER, "savings_intent_paise", savings * 100, clock=NOW)
    prof.set_field(conn, USER, "priorities", list(priorities), clock=NOW)
    prof.set_field(
        conn,
        USER,
        "fixed_commitments",
        [{"name": "Rent", "category_id": "housing", "amount_paise": 1_500_000, "day_of_month": 1}],
        clock=NOW,
    )


# ---- A8: the profile ---------------------------------------------------------------------------------------
def test_a_stated_value_is_confirmed_and_used_an_inferred_one_is_not(conn):
    prof.set_field(conn, USER, "nudge_style", "gentle", clock=NOW)
    prof.set_field(
        conn,
        USER,
        "income",
        {"kind": "monthly", "expected_paise": 100, "day_of_month": 1},
        provenance="inferred",
        actor="system",
        clock=NOW,
    )
    view = prof.get_profile(conn, USER)
    assert view.values == {"nudge_style": "gentle"} and "income" in view.suggestions
    assert prof.confirmed(conn, USER, "income") is None
    prof.confirm_field(conn, USER, "income", clock=NOW)
    assert prof.confirmed(conn, USER, "income")["expected_paise"] == 100


def test_a_suggestion_never_replaces_what_you_said(conn):
    prof.set_field(conn, USER, "nudge_style", "direct", clock=NOW)
    res = prof.set_field(
        conn, USER, "nudge_style", "numbers", provenance="inferred", actor="system", clock=NOW
    )
    assert res.get("kept") == "stated" and prof.confirmed(conn, USER, "nudge_style") == "direct"


def test_only_the_user_can_state_confirm_or_delete(conn):
    for fn in (
        lambda: prof.set_field(conn, USER, "nudge_style", "gentle", actor="agent"),
        lambda: prof.confirm_field(conn, USER, "income", actor="agent"),
        lambda: prof.delete_field(conn, USER, "income", actor="agent"),
    ):
        with pytest.raises(ToolFailure):
            fn()


def test_unknown_or_malformed_fields_are_refused(conn):
    for field, value in (
        ("religion", "x"),
        ("income", {"kind": "monthly"}),
        ("nudge_style", "loud"),
        ("checkin_weekday", 9),
    ):
        with pytest.raises(ToolFailure):
            prof.set_field(conn, USER, field, value, clock=NOW)


def test_delete_removes_the_field_and_its_evidence(conn):
    prof.set_field(
        conn,
        USER,
        "income",
        {"kind": "none", "expected_paise": 0},
        provenance="inferred",
        actor="system",
        evidence={"from": "x"},
        clock=NOW,
    )
    assert prof.delete_field(conn, USER, "income") == 1
    assert conn.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0] == 0


def test_inferred_suggestions_come_from_regular_credits_and_monthly_bills(conn):
    conn.execute(
        "INSERT INTO recurring_series (id, user_id, merchant_normalized, typical_amount_paise, cadence_days, last_seen, next_expected, confidence, kind)"
        " VALUES ('r1', ?, 'acme payroll', 4000000, 30, '2026-09-01T00:00:00Z', '2026-11-01T00:00:00Z', 0.9, 'income')", (USER,))  # fmt: skip
    got = prof.infer_suggestions(conn, USER)
    assert got["income"]["value"]["expected_paise"] == 4000000
    assert prof.store_inferred(conn, USER, NOW) == ["income"]
    assert prof.confirmed(conn, USER, "income") is None


# Rule 8: no sensitive attribute is ever stored
def check_rule8():
    names = list(prof.FIELDS)
    assert not any(
        t.startswith(w) for f in names for t in f.split("_") for w in prof.FORBIDDEN_WORDS
    ), "a profile field names something sensitive"
    with pytest.raises(ToolFailure):
        prof.validate("religion", "x")


def test_rule8_holds():
    check_rule8()


def test_rule8_fails_when_a_sensitive_field_is_added(monkeypatch):
    monkeypatch.setitem(prof.FIELDS, "marital_status", str)
    monkeypatch.setitem(prof._ADAPTERS, "marital_status", prof.TypeAdapter(str))
    with pytest.raises(AssertionError):
        check_rule8()


# ---- A9: the budget co-pilot --------------------------------------------------------------------------------
def test_without_a_confirmed_income_it_asks_instead_of_guessing(conn):
    history(conn)
    plan = bc.propose_budget(conn, USER, NOW)
    assert plan.status == "needs_profile" and plan.lines == []


def test_the_plan_adds_up_to_the_income_exactly_in_paise(conn):
    history(conn)
    set_profile(conn)
    p = bc.propose_budget(conn, USER, NOW)
    assert p.status == "ok"
    non_fixed_limits = sum(ln.limit_paise - ln.fixed_paise for ln in p.lines)
    assert (
        p.fixed_paise + non_fixed_limits + p.goals_paise + p.savings_paise + p.unallocated_paise
        == p.income_paise
    )


def test_every_category_stays_within_half_to_one_and_a_half_times_its_usual(conn):
    history(conn)
    set_profile(conn)
    for ln in bc.propose_budget(conn, USER, NOW).lines:
        if ln.usual_paise and ln.category_id not in ("bills", "housing"):
            assert ln.usual_paise // 2 <= ln.limit_paise <= ln.usual_paise * 3 // 2


def test_a_priority_gets_a_larger_share_of_its_usual_than_the_rest(conn):
    history(conn)
    set_profile(conn, income=32_000, savings=2_000, priorities=("shopping",))
    lines = {ln.category_id: ln for ln in bc.propose_budget(conn, USER, NOW).lines}
    ratio = {c: lines[c].limit_paise / lines[c].usual_paise for c in ("food", "shopping")}
    assert ratio["shopping"] > ratio["food"]


def test_essentials_are_kept_at_their_usual_cost(conn):
    history(conn)
    set_profile(conn)
    lines = {ln.category_id: ln for ln in bc.propose_budget(conn, USER, NOW).lines}
    assert lines["bills"].limit_paise == lines["bills"].usual_paise


def test_when_commitments_exceed_income_it_says_so_and_plans_nothing(conn):
    history(conn)
    set_profile(conn, income=10_000, savings=5_000)
    p = bc.propose_budget(conn, USER, NOW)
    assert p.status == "shortfall" and p.shortfall_paise > 0 and p.lines == []


def test_applying_recomputes_and_writes_budgets_and_only_the_user_can(conn):
    history(conn)
    set_profile(conn)
    with pytest.raises(ToolFailure):
        bc.apply_plan(conn, USER, actor="agent", clock=NOW)
    res = bc.apply_plan(conn, USER, clock=NOW)
    rows = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT category_id, limit_paise FROM budgets WHERE user_id = ?", (USER,)
        )
    }
    assert res["lines"] == len(rows) > 0
    plan = bc.propose_budget(conn, USER, NOW)
    assert {ln.category_id: ln.limit_paise for ln in plan.lines} == rows


def overrun(conn):
    """Food: Rs 3000 limit, Rs 2400 spent by the 18th, so heading to about Rs 4100."""
    insert_budget(
        conn,
        Budget(
            id="b1", user_id=USER, category_id="food", limit_paise=300_000, warn_threshold_pct=80
        ),
    )
    insert_budget(
        conn,
        Budget(
            id="b2",
            user_id=USER,
            category_id="shopping",
            limit_paise=500_000,
            warn_threshold_pct=80,
        ),
    )
    tx(conn, "food", 240_000, NOW - timedelta(days=3), merchant="cafe")
    tx(conn, "shopping", 50_000, NOW - timedelta(days=2), merchant="mart")


def test_replan_offers_exact_tradeoffs_for_a_category_heading_over(conn):
    set_profile(conn)
    overrun(conn)
    plans = bc.replan_options(conn, USER, NOW)
    assert [p.category_id for p in plans] == ["food"]
    p = plans[0]
    assert p.overrun_paise == p.projected_paise - p.limit_paise > 0
    kinds = {o.kind: o for o in p.options}
    assert (
        kinds["move"].from_category == "shopping"
        and 0 < kinds["move"].amount_paise <= p.overrun_paise
    )
    assert kinds["trim"].per_day_paise * (31 - 18) >= p.overrun_paise


def test_a_move_changes_budgets_only_when_the_user_applies_it(conn):
    set_profile(conn)
    overrun(conn)
    before = {r[0]: r[1] for r in conn.execute("SELECT category_id, limit_paise FROM budgets")}
    opt = next(o for o in bc.replan_options(conn, USER, NOW)[0].options if o.kind == "move")
    assert {
        r[0]: r[1] for r in conn.execute("SELECT category_id, limit_paise FROM budgets")
    } == before
    bc.apply_move(conn, USER, "shopping", "food", opt.amount_paise, clock=NOW)
    after = {r[0]: r[1] for r in conn.execute("SELECT category_id, limit_paise FROM budgets")}
    assert after["food"] == before["food"] + opt.amount_paise and sum(after.values()) == sum(
        before.values()
    )
    with pytest.raises(ToolFailure):
        bc.apply_move(conn, USER, "shopping", "food", 1, actor="agent")


# ---- A10: how you like to be helped --------------------------------------------------------------------------
def test_every_arm_is_tried_once_then_the_best_is_used_and_it_is_deterministic(conn):
    seen = []
    for _ in range(len(nudges.ARMS)):
        arm = nudges.choose_arm(conn, USER)
        seen.append(arm)
        nudges.record_response(conn, USER, *arm, "dismissed")
    assert set(seen) == set(nudges.ARMS)
    nudges.record_response(conn, USER, "evening", "direct", "acted")
    nudges.record_response(conn, USER, "evening", "direct", "acted")
    assert nudges.choose_arm(conn, USER) == ("evening", "direct") == nudges.choose_arm(conn, USER)


def test_a_dismissed_tone_is_chosen_less_and_reset_forgets(conn):
    for arm in nudges.ARMS:
        nudges.record_response(conn, USER, *arm, "acted")
    for _ in range(4):
        nudges.record_response(conn, USER, "morning", "gentle", "not_useful")
    assert nudges.choose_arm(conn, USER) != ("morning", "gentle")
    assert nudges.reset(conn, USER) == len(nudges.ARMS)


def test_the_stated_style_gives_its_tone_a_head_start_not_a_guarantee(conn):
    prof.set_field(conn, USER, "nudge_style", "numbers", clock=NOW)
    p = {(r["timing"], r["tone"]): r["p"] for r in nudges.table(conn, USER)}
    assert p[("morning", "numbers")] > p[("morning", "gentle")]


# ---- A11: the check-in agent ---------------------------------------------------------------------------------
def checkin_world(conn):
    history(conn)
    set_profile(conn)
    overrun(conn)


def test_it_finds_the_one_thing_that_matters_verifies_it_and_says_it_with_backed_numbers(conn):
    checkin_world(conn)
    out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert out.checkin and out.checkin.signal == "pace_overrun"
    row = conn.execute("SELECT figures_json, verified_json FROM checkins").fetchone()
    assert json.loads(row[1])["ok"] is True
    figures = json.loads(row[0])
    assert (
        ck.claim_check(out.checkin.body, [str(v) for v in figures.values()] + out.checkin.options)
        == []
    )


def test_a_signal_that_fails_its_own_check_is_dropped_and_never_shown(conn, monkeypatch):
    checkin_world(conn)
    monkeypatch.setattr(ck, "verify", lambda *a, **k: (False, "the figures did not hold"))
    out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert out.checkin is None and out.reason == "nothing_worth_saying"
    assert conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM checkin_drops").fetchone()[0] >= 1


def test_it_says_when_it_cannot_forecast_instead_of_inventing(conn):
    set_profile(conn)  # no history at all
    out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert out.checkin is None
    assert any("not enough history" in why for _kind, why in out.dropped)


# Rule 6: every number in a message comes from a computed figure
def check_rule6(conn):
    checkin_world(conn)
    out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert out.checkin, "nothing was sent"
    figures = json.loads(conn.execute("SELECT figures_json FROM checkins").fetchone()[0])
    stray = ck.claim_check(
        out.checkin.body, [str(v) for v in figures.values()] + out.checkin.options
    )
    assert not stray, f"a number nobody computed was sent: {stray}"


def test_rule6_holds(conn):
    check_rule6(conn)


def test_rule6_fails_when_the_claim_check_is_removed_and_a_number_is_invented(conn, monkeypatch):
    monkeypatch.setitem(
        ck.TEMPLATES["pace_overrun"],
        "gentle",
        "Heads-up: {category} is about {over} over, 97 percent sure.",
    )
    monkeypatch.setitem(
        ck.TEMPLATES["pace_overrun"],
        "direct",
        "Heads-up: {category} is about {over} over, 97 percent sure.",
    )
    monkeypatch.setitem(
        ck.TEMPLATES["pace_overrun"],
        "numbers",
        "Heads-up: {category} is about {over} over, 97 percent sure.",
    )
    monkeypatch.setattr(ck, "claim_check", lambda text, sources: [])
    with pytest.raises(AssertionError):
        # the sent text carries a number no figure supports; the stricter test-side check catches it
        checkin_world(conn)
        out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
        assert out.checkin
        real = {m.replace(",", "") for m in ck._NUMBER.findall(out.checkin.body)}
        figures = json.loads(conn.execute("SELECT figures_json FROM checkins").fetchone()[0])
        allowed = set().union(
            *(ck.numbers_in(str(v)) for v in figures.values()),
            *(ck.numbers_in(o) for o in out.checkin.options),
        )
        assert real <= allowed, f"a number nobody computed was sent: {sorted(real - allowed)}"


def test_a_rewording_that_adds_a_number_is_ignored(conn):
    checkin_world(conn)
    out = ck.run_checkin(
        conn,
        USER,
        clock=NOW,
        ignore_timing=True,
        reword=lambda t: t + " Ninety nine percent of people do worse (99).",
    )
    assert out.checkin and "99" not in out.checkin.body


# Rule 9: the weekly budget and quiet hours hold
def check_rule9(conn):
    checkin_world(conn)
    quiet = NOW.replace(hour=2)
    assert ck.run_checkin(conn, USER, clock=quiet, ignore_timing=True).reason == "quiet_hours"
    cfg = REAL_CFG  # the real budget, whatever the code under test is using
    first = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert first.checkin
    for i in range(cfg.weekly_budget):
        conn.execute("INSERT INTO checkins (id, user_id, signal, headline, body, figures_json, options_json, verified_json, status, created_at)"
                     " VALUES (?, ?, 'x', 'h', 'b', '{}', '[]', '{}', 'sent', ?)", (f"c{i}", USER, to_utc_iso(NOW - timedelta(days=1))))  # fmt: skip
    assert ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True).reason == "weekly_budget", (
        "it spoke past its weekly budget"
    )


def test_rule9_holds(conn):
    check_rule9(conn)


def test_rule9_fails_when_the_budget_is_not_enforced(conn, monkeypatch):
    cfg = ck.load_checkin_config()
    monkeypatch.setattr(
        ck,
        "load_checkin_config",
        lambda path=None: cfg.model_copy(update={"weekly_budget": 10_000}),
    )
    with pytest.raises(AssertionError):
        check_rule9(conn)


def test_it_only_speaks_in_its_arms_timing_window_unless_forced(conn):
    checkin_world(conn)
    arm = nudges.choose_arm(conn, USER)
    window = ck.load_checkin_config().windows[arm[0]]
    wrong = NOW.replace(hour=(window[1] + 1) % 24 or 12)
    if ck.in_quiet_hours(wrong, "23:00", "07:30"):
        wrong = NOW.replace(hour=15)
    assert ck.run_checkin(conn, USER, clock=wrong).reason in ("not_the_time", "quiet_hours")


def test_answering_teaches_the_nudge_learner_and_only_the_user_may_answer(conn):
    checkin_world(conn)
    c = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True).checkin
    with pytest.raises(ToolFailure):
        ck.respond(conn, USER, c.id, "acted", actor="agent")
    ck.respond(conn, USER, c.id, "acted", clock=NOW)
    arm = {(r["timing"], r["tone"]): r["trials"] for r in nudges.table(conn, USER)}
    assert arm[(c.timing, c.tone)] == 1
    with pytest.raises(ToolFailure):
        ck.respond(conn, USER, c.id, "dismissed")


def test_a_renewal_check_in_names_the_subscription_and_the_days(conn):
    history(conn)
    set_profile(conn)
    due = (NOW + timedelta(days=2)).astimezone(tz=None)
    conn.execute(
        "INSERT INTO recurring_series (id, user_id, merchant_normalized, typical_amount_paise, cadence_days, last_seen, next_expected, confidence, kind)"
        " VALUES ('s1', ?, 'netflix', 64900, 30, ?, ?, 0.9, 'subscription')",
        (USER, to_utc_iso(NOW - timedelta(days=28)), to_utc_iso(due)),
    )
    out = ck.run_checkin(conn, USER, clock=NOW, ignore_timing=True)
    assert out.checkin and out.checkin.signal == "renewal" and "Netflix" in out.checkin.body


# ---- A12: shared expenses and subscriptions -----------------------------------------------------------------
def test_a_group_always_balances_to_zero_and_splits_are_exact(conn):
    gid = sp.create_group(conn, USER, "Flat", ["Asha", "Ravi"], clock=NOW)
    me, asha, ravi = (m["id"] for m in sp.members(conn, USER, gid))
    sp.add_expense(conn, USER, gid, me, 10_000, "groceries", clock=NOW)  # 3 ways: 3334 3333 3333
    sp.add_expense(conn, USER, gid, asha, 5_000, "power", weights={me: 1, asha: 1}, clock=NOW)
    view = sp.balances(conn, USER, gid)
    assert sum(b.net_paise for b in view.balances) == 0 and view.total_paise == 15_000
    rows = conn.execute("SELECT amount_paise, shares_json FROM split_expenses").fetchall()
    assert len(rows) == 2 and all(sum(json.loads(r[1]).values()) == r[0] for r in rows)


def test_settle_up_suggestions_clear_every_balance_with_the_fewest_payments(conn):
    gid = sp.create_group(conn, USER, "Trip", ["Asha", "Ravi", "Meera"], clock=NOW)
    ids = [m["id"] for m in sp.members(conn, USER, gid)]
    sp.add_expense(conn, USER, gid, ids[0], 40_000, "hotel", clock=NOW)
    sp.add_expense(conn, USER, gid, ids[1], 20_000, "cab", clock=NOW)
    view = sp.balances(conn, USER, gid)
    assert len(view.settle_up) <= len(ids) - 1
    for s in view.settle_up:
        sp.record_settlement(conn, USER, gid, s.from_member, s.to_member, s.amount_paise, clock=NOW)
    assert all(b.net_paise == 0 for b in sp.balances(conn, USER, gid).balances)


def test_only_the_user_can_share_settle_or_start_a_group_and_bad_input_is_refused(conn):
    with pytest.raises(ToolFailure):
        sp.create_group(conn, USER, "x", ["a"], actor="agent")
    gid = sp.create_group(conn, USER, "Flat", ["Asha"], clock=NOW)
    me, asha = (m["id"] for m in sp.members(conn, USER, gid))
    for fn in (
        lambda: sp.add_expense(conn, USER, gid, me, 0, "x"),
        lambda: sp.add_expense(conn, USER, gid, "nobody", 100, "x"),
        lambda: sp.add_expense(conn, USER, gid, me, 100, "x", actor="agent"),
        lambda: sp.record_settlement(conn, USER, gid, me, me, 100),
        lambda: sp.record_settlement(conn, USER, gid, me, asha, 100, actor="agent"),
    ):
        with pytest.raises(ToolFailure):
            fn()


def test_subscriptions_show_renewal_monthly_cost_and_price_changes_and_can_be_marked(conn):
    conn.execute(
        "INSERT INTO recurring_series (id, user_id, merchant_normalized, typical_amount_paise, cadence_days, last_seen, next_expected, confidence, kind)"
        " VALUES ('s1', ?, 'spotify', 11900, 30, ?, ?, 0.9, 'subscription')",
        (USER, to_utc_iso(NOW - timedelta(days=20)), to_utc_iso(NOW + timedelta(days=10))),
    )
    tx(conn, "bills", 11900, NOW - timedelta(days=50), merchant="spotify")
    tx(conn, "bills", 13900, NOW - timedelta(days=20), merchant="spotify")
    s = subs.list_subscriptions(conn, USER, NOW)[0]
    assert (
        s.name == "Spotify"
        and s.monthly_paise == 11900
        and s.days_until_renewal in (9, 10)
        and s.price_change_bp > 1000
    )
    subs.mark(conn, USER, "s1", "unused", clock=NOW)
    assert subs.list_subscriptions(conn, USER, NOW)[0].note == "unused"
    with pytest.raises(ToolFailure):
        subs.mark(conn, USER, "s1", "unused", actor="agent")
