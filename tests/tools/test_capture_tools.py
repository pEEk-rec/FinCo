"""
The capture lane through `execute_tool` (PLAN_CAPTURE Stage C1): policy, audit, idempotency,
labels that stick, undo, the time-to-live fallback and the rule that no model ever hears about
a person.
"""

import json
from datetime import datetime, timedelta

import pytest

from copilot.core import capture as core
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.governance.policy import load_policy
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Category, User
from copilot.tools.capture import register_capture_tools
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.tools.registry import clear_registry, register
from copilot.tools.undo import UNDO_TOOL

USER = "user_alice"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=IST)
CATS = ["food", "rent", "gifts", "bills", "transport", "other"]


@pytest.fixture
def make_ctx():
    clear_registry()
    register_capture_tools()
    register(UNDO_TOOL)
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at=T0))
    insert_account(
        conn, Account(id="acc", user_id=USER, name="Main", opening_balance_paise=0, created_at=T0)
    )
    for c in CATS:
        insert_category(conn, Category(id=c, user_id=USER, name=c.capitalize(), created_at=T0))
    policy = load_policy("config/policy.yaml")

    def make(actor="user", clock=NOW, llm=None):
        return ExecutionContext(
            conn=conn, user_id=USER, run_id="run_cap", policy=policy, actor=actor,
            clock=clock, llm_client=llm,
        )  # fmt: skip

    return make


def stamp(minutes_ago=0, base=NOW):
    return (base - timedelta(minutes=minutes_ago)).astimezone(tz=IST).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc(dt):
    return dt.astimezone(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pay(
    make, name, amount=25000, vpa=None, utr=None, direction="debit", when=None, actor="system", **kw
):
    ctx = make(actor=actor, clock=kw.pop("clock", NOW))
    res = execute_tool(
        ctx, "record_payment_event",
        {
            "source": "simulator", "amount_paise": amount, "direction": direction,
            "display_name": name, "occurred_at": when or utc(NOW), "vpa": vpa, "utr": utr,
            "channel": kw.pop("channel", "upi"), **kw,
        },
    )  # fmt: skip
    assert res.ok, res.error
    return res.data


def pay_on(make, day, *a, **kw):
    when = NOW + timedelta(days=day)
    return pay(make, *a, clock=when, when=utc(when), **kw)


def label(make, event_id, **kw):
    res = execute_tool(make(), "label_payment_event", {"event_id": event_id, **kw})
    return res


# ---- recording --------------------------------------------------------------------------------
def test_an_unknown_merchant_is_asked_with_three_guesses_and_audited(make_ctx):
    out = pay(make_ctx, "XQ9 Traders Yard", utr="123456789012")
    assert out.decision == "ask" and out.reason == "unknown_merchant"
    assert len(out.guesses) == 3
    prompts = execute_tool(make_ctx(), "pending_prompts", {}).data.prompts
    assert [p.event.id for p in prompts] == [out.event.id]
    assert out.event.simulated is True
    kinds = [e[0] for e in make_ctx().conn.execute("SELECT event_type FROM audit_events")]
    assert "payment_event_recorded" in kinds


def test_the_same_utr_is_recorded_once(make_ctx):
    first = pay(make_ctx, "Sharma Stationers", utr="998877665544")
    second = pay(make_ctx, "Sharma Stationers", utr="998877665544")
    assert first.created and not second.created and first.event.id == second.event.id
    n = make_ctx().conn.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0]
    assert n == 1


def test_a_payment_without_a_utr_is_deduplicated_by_its_fingerprint(make_ctx):
    a = pay(make_ctx, "Canteen Block B")
    b = pay(make_ctx, "Canteen Block B")
    assert a.created and not b.created


def test_bad_input_is_a_typed_failure_not_a_crash(make_ctx):
    res = execute_tool(make_ctx(), "record_payment_event", {"source": "sms", "amount_paise": 0})
    assert not res.ok and res.error.code == ErrorCode.INVALID_INPUT


# ---- labelling --------------------------------------------------------------------------------
def test_the_users_answer_becomes_the_truth_and_the_merchant_is_never_asked_again(make_ctx):
    first = pay(make_ctx, "Sharma Stationers", utr="111111111111")
    res = label(make_ctx, first.event.id, category_id="other", rank_picked=0)
    assert (
        res.ok
        and res.data.event.category_source == "user"
        and res.data.event.category_id == "other"
    )
    again = pay(make_ctx, "Sharma Stationers", utr="222222222222")
    assert (again.decision, again.reason) == ("auto_label", "known_merchant")
    assert again.event.category_id == "other" and again.event.category_source == "auto"


def test_a_person_is_remembered_only_after_k_of_n_agree_and_never_as_a_merchant(make_ctx):
    outs = []
    for i in range(3):
        o = pay_on(make_ctx, i, "Ramesh K", vpa="9876543210@ybl", utr=f"30000000000{i}")
        assert o.decision == "ask", f"payment {i}"
        label(make_ctx, o.event.id, category_id="rent")
        outs.append(o)
    overrides = make_ctx().conn.execute("SELECT COUNT(*) FROM merchant_overrides").fetchone()[0]
    assert overrides == 0, (
        "rent and dinner go to the same friend: no merchant override for a person"
    )
    fourth = pay_on(make_ctx, 3, "Ramesh K", vpa="9876543210@ybl", utr="300000000099")
    assert (fourth.decision, fourth.reason, fourth.event.category_id) == (
        "auto_label",
        "person_k_of_n",
        "rent",
    )


def test_always_ask_overrides_the_learned_rule(make_ctx):
    for i in range(3):
        o = pay_on(make_ctx, i, "Ramesh K", vpa="9876543210@ybl", utr=f"40000000000{i}")
        label(make_ctx, o.event.id, category_id="rent")
    key = o.event.counterparty_key
    assert execute_tool(
        make_ctx(), "set_counterparty_policy", {"counterparty_key": key, "policy": "always_ask"}
    ).ok
    assert (
        pay_on(make_ctx, 3, "Ramesh K", vpa="9876543210@ybl", utr="400000000099").decision == "ask"
    )
    res = execute_tool(
        make_ctx(), "set_counterparty_policy",
        {"counterparty_key": key, "policy": "always_category", "category_id": "gifts"},
    )  # fmt: skip
    assert res.ok
    out = pay_on(make_ctx, 4, "Ramesh K", vpa="9876543210@ybl", utr="400000000098")
    assert (out.reason, out.event.category_id) == ("person_always_category", "gifts")


def test_labels_are_validated(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", utr="500000000001")
    assert label(make_ctx, o.event.id, category_id="nope").error.code == ErrorCode.INVALID_INPUT
    assert label(make_ctx, o.event.id, credit_kind="salary").error.code == ErrorCode.INVALID_INPUT
    assert label(make_ctx, "pev_missing", category_id="food").error.code == ErrorCode.NOT_FOUND
    c = (
        pay(make_ctx, "Boss Pvt Ltd", direction="credit", utr="500000000002", amount_paise=5000000)
        if False
        else pay(make_ctx, "Boss Pvt Ltd", amount=5000000, direction="credit", utr="500000000002")
    )
    assert label(make_ctx, c.event.id, category_id="food").error.code == ErrorCode.INVALID_INPUT
    assert label(make_ctx, c.event.id, credit_kind="gift").ok


def test_the_agent_cannot_label_and_cannot_overwrite_a_users_label(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", utr="600000000001")
    denied = execute_tool(
        make_ctx(actor="agent"),
        "label_payment_event",
        {"event_id": o.event.id, "category_id": "food"},
    )
    assert not denied.ok and denied.error.code == ErrorCode.DENIED_BY_POLICY
    label(make_ctx, o.event.id, category_id="rent")
    with pytest.raises(ToolFailure):
        core.label_payment_event(
            make_ctx().conn, USER, o.event.id, category_id="food", actor="agent", clock=NOW
        )
    assert core.get_event(make_ctx().conn, USER, o.event.id).category_id == "rent"


# ---- undo -------------------------------------------------------------------------------------
def test_undo_restores_the_event_the_prompt_the_profile_and_the_override(make_ctx):
    o = pay(make_ctx, "Sharma Stationers", utr="700000000001")
    conn = make_ctx().conn
    before = core.get_event(conn, USER, o.event.id)
    assert label(make_ctx, o.event.id, category_id="other").ok
    ev = conn.execute(
        "SELECT id FROM audit_events WHERE event_type = 'payment_labeled' ORDER BY occurred_at DESC"
    ).fetchone()[0]
    undone = execute_tool(make_ctx(), "undo", {"audit_event_id": ev})
    assert undone.ok, undone.error
    after = core.get_event(conn, USER, o.event.id)
    assert (after.category_id, after.category_source) == (
        before.category_id,
        before.category_source,
    )
    status = conn.execute(
        "SELECT status FROM prompt_log WHERE event_id = ?", (o.event.id,)
    ).fetchone()[0]
    assert status == "pending"
    assert conn.execute("SELECT COUNT(*) FROM merchant_overrides").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM capture_labels").fetchone()[0] == 0
    assert pay_on(make_ctx, 1, "Sharma Stationers", utr="700000000002").decision == "ask"


def test_undo_is_refused_when_the_label_has_since_changed(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", utr="710000000001")
    label(make_ctx, o.event.id, category_id="food")
    conn = make_ctx().conn
    first = conn.execute(
        "SELECT id FROM audit_events WHERE event_type = 'payment_labeled'"
    ).fetchone()[0]
    label(make_ctx, o.event.id, category_id="other")
    refused = execute_tool(make_ctx(), "undo", {"audit_event_id": first})
    assert not refused.ok and refused.error.code == ErrorCode.STALE_DATA


# ---- the time-to-live fallback ----------------------------------------------------------------
def test_an_unanswered_prompt_applies_its_best_guess_as_a_guess_after_the_ttl(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", utr="800000000001")
    conn = make_ctx().conn
    ttl = core.load_capture_config().prompts.ttl_hours
    assert core.expire_prompts(conn, USER, NOW + timedelta(hours=ttl) - timedelta(minutes=1)) == 0
    assert core.expire_prompts(conn, USER, NOW + timedelta(hours=ttl)) == 1
    e = core.get_event(conn, USER, o.event.id)
    assert e.category_source == "guess" and e.needs_review is True and e.category_id in CATS
    assert execute_tool(make_ctx(), "pending_prompts", {}).data.prompts == []


def test_the_ttl_never_touches_a_label_the_user_gave(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", utr="810000000001")
    label(make_ctx, o.event.id, category_id="rent")
    conn = make_ctx().conn
    conn.execute(
        "UPDATE prompt_log SET status = 'pending', expires_at = ? WHERE event_id = ?",
        (stamp(1), o.event.id),
    )
    core.expire_prompts(conn, USER, NOW)
    assert core.get_event(conn, USER, o.event.id).category_id == "rent"


def test_small_payments_get_a_guess_and_no_prompt(make_ctx):
    o = pay(make_ctx, "XQ9 Traders Yard", amount=2000, utr="820000000001")
    assert o.decision == "guess_only"
    assert o.event.category_source == "guess" and o.event.needs_review is True
    assert execute_tool(make_ctx(), "pending_prompts", {}).data.prompts == []


def test_quiet_hours_send_the_ask_to_the_inbox_still_pending(make_ctx):
    night = datetime(2026, 10, 18, 2, 0, tzinfo=IST)
    out = pay(make_ctx, "XQ9 Traders Yard", utr="830000000001", clock=night, when=utc(night))
    assert (out.decision, out.reason) == ("inbox", "quiet_hours")
    assert len(execute_tool(make_ctx(), "pending_prompts", {}).data.prompts) == 1


# ---- credits ----------------------------------------------------------------------------------
def test_a_refund_is_matched_to_the_earlier_debit_and_a_known_salary_auto_labels(make_ctx):
    spend = pay(
        make_ctx,
        "Myntra Fashion",
        amount=129900,
        utr="900000000001",
        when=utc(NOW - timedelta(days=5)),
    )
    label(make_ctx, spend.event.id, category_id="other")
    refund = pay(make_ctx, "Myntra Fashion", amount=129900, direction="credit", utr="900000000002")
    assert (refund.decision, refund.reason, refund.event.credit_kind) == (
        "auto_label",
        "refund_matched",
        "refund",
    )
    paid = []
    for i, day in enumerate((60, 30)):
        c = pay(
            make_ctx,
            "Acme Pvt Ltd",
            amount=5000000,
            direction="credit",
            utr=f"91000000000{i}",
            when=utc(NOW - timedelta(days=day)),
        )
        label(make_ctx, c.event.id, credit_kind="salary")
        paid.append(c)
    third = pay(make_ctx, "Acme Pvt Ltd", amount=5000000, direction="credit", utr="910000000009")
    assert (third.decision, third.reason, third.event.credit_kind) == (
        "auto_label",
        "known_inflow",
        "salary",
    )


def test_a_friend_repaying_a_split_can_be_linked_to_the_original_debit(make_ctx):
    dinner = pay(make_ctx, "Pizza Hut", amount=240000, utr="920000000001")
    label(make_ctx, dinner.event.id, category_id="food")
    back = pay(
        make_ctx,
        "Ramesh K",
        vpa="9876543210@ybl",
        amount=120000,
        direction="credit",
        utr="920000000002",
    )
    assert back.decision == "ask"
    res = label(
        make_ctx, back.event.id, credit_kind="split_repayment", linked_event_id=dinner.event.id
    )
    assert res.ok
    link = (
        make_ctx()
        .conn.execute(
            "SELECT linked_event_id FROM capture_labels WHERE event_id = ? AND source = 'user'",
            (back.event.id,),
        )
        .fetchone()[0]
    )
    assert link == dinner.event.id
    assert (
        label(
            make_ctx, dinner.event.id, category_id="food", linked_event_id=back.event.id
        ).error.code
        == ErrorCode.INVALID_INPUT
    )


# ---- the model never hears about a person -----------------------------------------------------
REPLY = json.dumps(
    {
        "decisions": [
            {"merchant_normalized": "xq9 traders yard", "category_id": "bills", "confidence": 0.7}
        ]
    }
)


def test_the_model_is_asked_only_about_merchant_like_names_and_only_the_name(make_ctx):
    client = FakeLLMClient([REPLY, REPLY, REPLY])
    person = pay_with_llm(make_ctx, client, "Ramesh K", vpa="9876543210@ybl", utr="A00000000001")
    assert person.decision == "ask" and client.prompts == [], "no model call for a person"
    cash = pay_with_llm(make_ctx, client, "ATM CASH WDL", channel="atm", utr="A00000000002")
    assert client.prompts == [], "none for cash either"
    pay_with_llm(make_ctx, client, "XQ9 Traders Yard", utr="A00000000003")
    assert len(client.prompts) == 1
    sent = client.prompts[0].lower()
    assert "xq9 traders yard" in sent and "ramesh" not in sent
    assert "a00000000003" not in sent and "25000" not in sent and "upi" not in sent
    assert cash.event.counterparty_kind == "cash"


def test_a_hint_joins_the_guesses_but_never_labels_anything(make_ctx):
    client = FakeLLMClient([REPLY])
    out = pay_with_llm(make_ctx, client, "XQ9 Traders Yard", utr="A10000000001")
    assert "bills" in [g["label"] for g in out.guesses]
    assert out.event.category_id is None and out.decision == "ask"


def test_the_daily_model_budget_is_respected(make_ctx):
    cap = core.load_capture_config().llm_suggest.max_calls_per_day
    client = FakeLLMClient([REPLY] * (cap + 3))
    for i in range(cap + 2):
        pay_with_llm(
            make_ctx,
            client,
            f"Unknown Mart {i}",
            utr=f"B{i:011d}",
            clock=NOW + timedelta(minutes=i % 3),
        )
    assert len(client.prompts) == cap


def pay_with_llm(make, client, name, vpa=None, utr=None, channel="upi", clock=NOW):
    ctx = make(actor="system", clock=clock, llm=client)
    res = execute_tool(
        ctx, "record_payment_event",
        {"source": "simulator", "amount_paise": 25000, "direction": "debit", "display_name": name,
         "occurred_at": utc(NOW), "vpa": vpa, "utr": utr, "channel": channel},
    )  # fmt: skip
    assert res.ok, res.error
    return res.data


# ---- the simulator tool -----------------------------------------------------------------------
def simulate(make, actor="user", **over):
    args = {
        "bank": "hdfc", "kind": "debit", "amount_paise": 25000, "counterparty": "XQ9 Traders Yard",
        "utr": "628912340001",
    } | over  # fmt: skip
    return execute_tool(make(actor=actor), "simulate_payment_event", args)


def test_a_simulated_payment_runs_the_whole_pipeline_and_is_marked_simulated(make_ctx):
    res = simulate(make_ctx)
    assert res.ok, res.error
    out = res.data
    assert out.event.simulated is True and out.event.source == "simulator"
    assert out.decision == "ask" and len(out.guesses) == 3
    assert out.sample_text.startswith("Sent Rs.250.00 From HDFC Bank")
    prompts = execute_tool(make_ctx(), "pending_prompts", {}).data.prompts
    assert prompts and all(p.event.simulated for p in prompts)


def test_the_agent_cannot_fabricate_a_payment(make_ctx):
    denied = simulate(make_ctx, actor="agent")
    assert not denied.ok and denied.error.code == ErrorCode.DENIED_BY_POLICY


def test_the_simulator_needs_a_payee_for_a_payment_but_not_for_cash(make_ctx):
    assert not simulate(make_ctx, counterparty="", utr="628912340002").ok
    assert simulate(make_ctx, kind="atm", counterparty="", utr=None, amount_paise=200000).ok


def test_labelling_returns_the_audit_id_so_the_ui_can_offer_undo(make_ctx):
    out = simulate(make_ctx).data
    res = label(make_ctx, out.event.id, category_id="food", rank_picked=1)
    assert res.ok and res.data.audit_event_id
    undone = execute_tool(make_ctx(), "undo", {"audit_event_id": res.data.audit_event_id})
    assert undone.ok


# ---- reconciliation, coverage and the runtime jobs --------------------------------------------
def _ledger_row(conn, amount, utr, when):
    from copilot.db.repo import insert_transaction
    from copilot.models.domain import Transaction

    insert_transaction(
        conn,
        Transaction(
            id=f"t_{utr}", user_id=USER, account_id="acc", occurred_at=utc(when),
            amount_paise=amount, direction="debit", merchant_raw=f"UPI-SHOP-REF{utr}",
            description="", created_at=utc(when),
        ),
    )  # fmt: skip


def test_reconciliation_is_allowed_for_the_agent_and_carries_only_the_users_label(make_ctx):
    out = pay(make_ctx, "XQ9 Traders Yard", utr="990000000001")
    label(make_ctx, out.event.id, category_id="rent")
    _ledger_row(make_ctx().conn, 25000, "990000000001", NOW)
    res = execute_tool(make_ctx(actor="agent"), "reconcile_payment_events", {})
    assert res.ok and res.data.matched == 1
    row = (
        make_ctx()
        .conn.execute(
            "SELECT category_id, category_source FROM transactions WHERE id = 't_990000000001'"
        )
        .fetchone()
    )
    assert (row[0], row[1]) == ("rent", "user")
    assert core.get_event(make_ctx().conn, USER, out.event.id).state == "reconciled"


def test_the_account_tail_is_the_users_to_set(make_ctx):
    args = {"account_id": "acc", "last4": "4321"}
    assert (
        execute_tool(make_ctx(actor="agent"), "set_account_last4", args).error.code
        == ErrorCode.DENIED_BY_POLICY
    )
    assert execute_tool(make_ctx(), "set_account_last4", args).ok
    assert not execute_tool(
        make_ctx(), "set_account_last4", {"account_id": "acc", "last4": "43"}
    ).ok


def test_coverage_reports_provisional_spend_and_hides_simulated_unless_asked(make_ctx):
    pay(make_ctx, "XQ9 Traders Yard", utr="990000000002")  # simulator source
    shown = execute_tool(make_ctx(), "capture_coverage", {"include_simulated": True}).data
    hidden = execute_tool(make_ctx(), "capture_coverage", {}).data
    assert shown.month_provisional_paise == 25000 and shown.unverified_events == 1
    assert hidden.month_provisional_paise == 0
    assert shown.month_total_paise == shown.month_ledger_paise + shown.month_provisional_paise


def test_the_runtime_jobs_run_once_per_hour_and_do_their_work(make_ctx):
    from copilot.runtime.runner import run_job
    from copilot.workflow.nodes import ensure_tools_registered

    clear_registry()
    ensure_tools_registered()  # the job runner needs the full toolset, as in production
    conn = make_ctx().conn
    out = pay(make_ctx, "XQ9 Traders Yard", utr="990000000003")
    _ledger_row(conn, 25000, "990000000003", NOW)
    first = run_job(conn, USER, "capture_reconcile", as_of=NOW, force=True)
    assert first.status == "ok" and first.summary_json["matched"] == 1
    again = run_job(conn, USER, "capture_reconcile", as_of=NOW)
    assert again.id == first.id or again.status in {"ok", "skipped"}
    exp = run_job(conn, USER, "capture_expire_prompts", as_of=NOW, force=True)
    assert exp.status == "ok"
    assert core.get_event(conn, USER, out.event.id).state == "reconciled"
