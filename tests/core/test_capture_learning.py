"""
Learning from labels (PLAN_CAPTURE Stage C8): bounded updates, reset, nothing learned from
simulated events by default, a person's policy untouched by single labels, and the Phase 3
memory seeing real merchant habits but not pretend ones.
"""

from datetime import datetime, timedelta

import pytest

from copilot.config.capture import load_capture_config
from copilot.config.phase3 import load_learning_config
from copilot.core import capture as cap
from copilot.core import capture_learning as cl
from copilot.core.capture_logic import HistoryRow
from copilot.core.learning import list_tenant_learning_stats, reset_learning
from copilot.core.memory import observe_merchant_habits
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.models.domain import Account, Category, User

USER = "u1"
T0 = "2026-01-01T00:00:00Z"
NOW = datetime(2026, 10, 18, 21, 30, tzinfo=IST)
CFG = load_capture_config()


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


def history():
    """Payee X was always food, but at this hour the user mostly buys shopping."""
    row = lambda key, label, days: HistoryRow(  # noqa: E731
        key, label, 20000, NOW - timedelta(days=days), "debit"
    )
    return [row("x", "food", 3), *[row(f"y{i}", "shopping", 10 + i) for i in range(6)]]


def learn(conn, label="food", **kw):
    args = dict(
        counterparty="x", direction="debit", amount_paise=20000, when=NOW, label=label,
        history=history(), cfg=CFG, simulated=False, actor="user", clock=NOW,
    )  # fmt: skip
    return cl.learn_from_label(conn, USER, **{**args, **kw})


def test_with_no_labels_the_weights_are_exactly_the_configured_ones(conn):
    assert cl.effective_weights(conn, USER, CFG) == CFG.ranking.weights


def test_a_signal_that_keeps_being_right_gains_weight_and_one_that_is_wrong_loses_it(conn):
    for _ in range(12):
        learn(conn)
    eff = cl.effective_weights(conn, USER, CFG)
    base = CFG.ranking.weights
    assert eff.counterparty_history > base.counterparty_history
    assert eff.time_pattern < base.time_pattern


def test_learning_is_bounded_and_the_weights_stay_a_partition_of_10000(conn):
    for _ in range(300):
        learn(conn)
    eff = cl.effective_weights(conn, USER, CFG)
    assert sum(eff.model_dump().values()) == 10000
    assert all(v > 0 for v in eff.model_dump().values()), "no signal is ever switched off"
    lim = load_learning_config()
    for row in cl.summary(conn, USER, CFG):
        assert lim.m_min <= row["multiplier"] <= lim.m_max


def test_the_ranking_really_uses_the_learned_weights(conn):
    for _ in range(12):
        learn(conn)
    learned = cl.with_learned_weights(conn, USER, CFG)
    assert learned.ranking.weights != CFG.ranking.weights
    assert learned.ranking.guess_count == CFG.ranking.guess_count


def test_reset_restores_the_configured_weights(conn):
    for _ in range(12):
        learn(conn)
    assert reset_learning(conn, USER, subject_kind="capture_signal") > 0
    assert cl.effective_weights(conn, USER, CFG) == CFG.ranking.weights


def test_stats_show_up_in_the_learners_own_listing(conn):
    learn(conn)
    kinds = {s["subject_kind"] for s in list_tenant_learning_stats(conn, USER)}
    assert "capture_signal" in kinds


def stats(conn):
    return conn.execute("SELECT COUNT(*) FROM feedback_stats").fetchone()[0]


def test_simulated_events_teach_nothing_unless_a_demo_says_so(conn):
    assert learn(conn, simulated=True) == {} and stats(conn) == 0
    flagged = CFG.model_copy(update={"learn_from_simulated": True})
    assert learn(conn, simulated=True, cfg=flagged) != {} and stats(conn) > 0


def test_an_automatic_label_teaches_nothing(conn):
    assert learn(conn, actor="system") == {} and learn(conn, actor="agent") == {}
    assert stats(conn) == 0


def test_undo_takes_the_lesson_back(conn):
    before = cl.effective_weights(conn, USER, CFG)
    learned = learn(conn)
    assert cl.effective_weights(conn, USER, CFG) != before
    cl.unlearn(conn, USER, learned)
    assert cl.effective_weights(conn, USER, CFG) == before


# ---- through the real labelling path ----------------------------------------------------------
def pay(conn, name, label=None, simulated=False, hours=0, vpa=None):
    rec = cap.record_payment_event(
        conn, USER, source="simulator" if simulated else "sms", amount_paise=30000,
        direction="debit", display_name=name,
        occurred_at=to_utc_iso(NOW - timedelta(hours=hours)), simulated=simulated, vpa=vpa, clock=NOW,
    )  # fmt: skip
    if label:
        cap.label_payment_event(conn, USER, rec.event.id, category_id=label, clock=NOW)
    return rec.event


def test_labelling_a_real_payment_teaches_and_labelling_a_simulated_one_does_not(conn):
    pay(conn, "Sharma Stationers", "shopping", simulated=True)
    assert stats(conn) == 0
    pay(conn, "Lantern Cafe", "food", hours=30)
    pay(conn, "Lantern Cafe", "food", hours=1)
    assert stats(conn) > 0


def test_one_label_does_not_change_a_persons_policy(conn):
    pay(conn, "Ramesh K", "food", vpa="9876543210@ybl")
    key = cap.get_event(conn, USER, pay(conn, "Ramesh K", vpa="9876543210@ybl", hours=5).id)
    profile = cap.get_profile(conn, USER, key.counterparty_key)
    assert profile.policy == "learn" and profile.policy_category_id is None


def test_a_real_merchant_label_becomes_memory_evidence_but_a_simulated_one_does_not(conn):
    pay(conn, "Lantern Cafe", "food")
    pay(conn, "Pretend Traders Yard", "shopping", simulated=True)
    subjects = {c.subject_key for c in observe_merchant_habits(conn, USER, NOW)}
    assert any("lantern" in s for s in subjects)
    assert not any("pretend" in s for s in subjects)


def test_a_demo_flag_lets_a_simulated_merchant_into_memory(conn, monkeypatch):
    pay(conn, "Pretend Traders Yard", "shopping", simulated=True)
    flagged = CFG.model_copy(update={"learn_from_simulated": True})
    monkeypatch.setattr("copilot.config.capture.load_capture_config", lambda *a, **k: flagged)
    subjects = {c.subject_key for c in observe_merchant_habits(conn, USER, NOW)}
    assert any("pretend" in s for s in subjects)
