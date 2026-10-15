"""
The weekly offer generator is driven by the offer policy (PLAN_PHASE4 sections 5.8 and 5.9).

It used to end with a temporary greedy pick, a random seed and a fixed propensity, so the
seeded reproducibility, the logged selection probabilities and the rest-week rule were only
true in the simulator. These tests pin the product path.
"""

import json
from datetime import datetime

import pytest

from copilot.core.baseline import generate_candidate_windows
from copilot.core.challenges import generate_challenge_offers
from copilot.core.policy import is_in_dismissal_quiet_period
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import insert_experiment, insert_offer, list_offers, update_offer_status
from copilot.governance.policy import load_policy
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import Experiment, Offer
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered

T0 = "2026-01-01T00:00:00Z"
USER = "user_alice"
WEEK = "2026-09-01"
CLOCK = datetime.fromisoformat("2026-09-01T10:00:00+05:30")


def _db():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(c, Account(id="acc_main", user_id=USER, name="Main", created_at=T0))
    for cid, name in [
        ("food", "Dining"),
        ("shopping", "Shopping"),
        ("entertainment", "Entertainment"),
        ("subscriptions", "Subscriptions"),
        ("housing", "Rent"),
    ]:
        insert_category(c, Category(id=cid, user_id=USER, name=name, created_at=T0))
    for cat, paise in (("food", 300000), ("shopping", 200000), ("entertainment", 150000)):
        for duration in (7, 14):
            for i, (start, _e) in enumerate(generate_candidate_windows(WEEK, duration, k=6), 1):
                c.execute(
                    "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise,"
                    " direction, merchant_raw, merchant_normalized, description, category_id,"
                    " category_source, created_at) VALUES (?, ?, 'acc_main', ?, ?, 'debit', 'M',"
                    " 'm', 'd', ?, 'rule', ?)",
                    (f"t_{cat}_{duration}_{i}", USER, f"{start}T10:00:00Z", paise, cat, T0),
                )
    return c


@pytest.fixture
def conn():
    c = _db()
    yield c
    c.close()


def _abandoned(conn, exp_id: str, ended: str) -> None:
    insert_experiment(
        conn,
        Experiment(
            id=exp_id,
            user_id=USER,
            title="t",
            template_code="x",
            hypothesis_json={},
            metric_def_json={"metric_code": "category_spend", "categories": ["food"]},
            params_json={},
            difficulty="medium",
            window_start="2026-08-01",
            window_end="2026-08-14",
            baseline_json={},
            target_value=1,
            status="abandoned",
            origin="offer",
            created_at=f"{ended}T00:00:00Z",
            ended_at=f"{ended}T00:00:00Z",
        ),
    )


def _past_offer(conn, off_id: str, week: str, status: str) -> None:
    rank = conn.execute(
        "SELECT COALESCE(MAX(rank), 0) + 1 FROM offers WHERE user_id = ? AND week_start = ?",
        (USER, week),
    ).fetchone()[0]
    insert_offer(
        conn,
        Offer(
            id=off_id,
            user_id=USER,
            week_start=week,
            template_code="weekday_home_cooking",
            difficulty="medium",
            params_json={},
            rank=rank,
            propensity_bp=5000,
            policy_version="t",
            rng_seed=1,
            reason_json={},
            status="shown",
            created_at=f"{week}T10:00:00Z",
        ),
    )
    update_offer_status(conn, USER, off_id, status, f"{week}T11:00:00Z")


def test_offers_come_from_the_policy_with_logged_propensities(conn):
    offers = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK)
    assert offers
    for o in offers:
        assert o.policy_version == "thompson_v1"
        assert 1 <= o.propensity_bp <= 10000


def test_each_offer_carries_the_selection_probability_the_policy_computed(conn, monkeypatch):
    """The stored propensity is whatever the policy returned, not a constant."""
    import copilot.core.challenges as challenges

    real = challenges.select_challenge_offers

    def fixed(conn_, user_id, candidates, **kwargs):
        selected, _props, status = real(conn_, user_id, candidates, **kwargs)
        return selected, [1111 + i for i in range(len(selected))], status

    monkeypatch.setattr(challenges, "select_challenge_offers", fixed)
    offers = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK)
    assert offers
    assert [o.propensity_bp for o in offers] == [1111 + i for i in range(len(offers))]


def test_same_user_and_week_give_the_same_offers_and_propensities():
    first = generate_challenge_offers(_db(), USER, week_start=WEEK, clock=CLOCK)
    second = generate_challenge_offers(_db(), USER, week_start=WEEK, clock=CLOCK)
    key = lambda offers: [(o.template_code, o.propensity_bp, o.rng_seed) for o in offers]  # noqa: E731
    assert key(first) == key(second)
    other_week = generate_challenge_offers(_db(), USER, week_start="2026-09-08", clock=CLOCK)
    assert {o.rng_seed for o in other_week} != {o.rng_seed for o in first}


def test_an_explicit_seed_is_used_and_recorded(conn):
    offers = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK, seed=12345)
    assert offers and {o.rng_seed for o in offers} == {12345}


def test_running_the_weekly_job_twice_does_not_duplicate_offers(conn):
    first = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK)
    again = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK)
    assert [o.id for o in first] == [o.id for o in again]
    assert len(list_offers(conn, USER, week_start=WEEK)) == len(first)


def test_rest_weeks_after_two_abandoned_experiments_offer_nothing_and_cost_no_model_call(conn):
    _abandoned(conn, "e1", "2026-08-25")
    _abandoned(conn, "e2", "2026-08-28")
    llm = FakeLLMClient([json.dumps({"specs": []})])
    offers = generate_challenge_offers(conn, USER, week_start=WEEK, clock=CLOCK, llm_client=llm)
    assert offers == []
    assert llm.prompts == [], "a withheld week must not spend a model call"
    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'offers_withheld'"
    ).fetchone()
    assert json.loads(event["metadata_json"])["reason"] == "rest_weeks"


def test_the_week_after_a_rest_the_offer_says_why_it_is_back(conn):
    _abandoned(conn, "e1", "2026-08-10")
    _abandoned(conn, "e2", "2026-08-11")
    # during the rest window: nothing offered, and the reason is recorded
    assert (
        generate_challenge_offers(
            conn,
            USER,
            week_start="2026-08-17",
            clock=datetime.fromisoformat("2026-08-17T10:00:00+05:30"),
        )
        == []
    )
    back = generate_challenge_offers(conn, USER, week_start="2026-09-01", clock=CLOCK)
    assert back and all("returning_note" in o.reason_json for o in back)


def test_a_run_of_dismissed_offers_gives_a_quiet_week_then_offers_return(conn):
    for i, week in enumerate(("2026-08-11", "2026-08-18")):
        for k in range(3):
            _past_offer(conn, f"o_{i}_{k}", week, "dismissed")
    from datetime import date

    assert is_in_dismissal_quiet_period(conn, USER, as_of=date(2026, 8, 25))  # the week after
    assert not is_in_dismissal_quiet_period(
        conn, USER, as_of=date(2026, 9, 1)
    )  # then it may return
    assert not is_in_dismissal_quiet_period(conn, USER, as_of=date(2026, 8, 18))  # not before


def test_an_accepted_offer_ends_the_dismissal_run(conn):
    from datetime import date

    for k in range(3):
        _past_offer(conn, f"a_{k}", "2026-08-11", "dismissed")
    _past_offer(conn, "acc", "2026-08-18", "accepted")
    for k in range(2):
        _past_offer(conn, f"b_{k}", "2026-08-18", "dismissed")
    # run since the accepted offer is only 2 (< 6): offers continue
    assert not is_in_dismissal_quiet_period(conn, USER, as_of=date(2026, 8, 25))


def test_five_dismissed_offers_are_not_yet_a_quiet_week(conn):
    from datetime import date

    for k in range(5):
        _past_offer(conn, f"d_{k}", "2026-08-18", "dismissed")
    assert not is_in_dismissal_quiet_period(conn, USER, as_of=date(2026, 8, 25))


def test_the_suggest_tool_hands_the_model_client_to_the_generator(conn):
    ensure_tools_registered()
    proposals = {
        "specs": [
            {
                "metric_code": "category_spend",
                "categories": ["food"],
                "duration_days": 14,
                "difficulty": "medium",
                "title": "Dine at home",
                "rationale": "r",
            }
        ]
    }
    llm = FakeLLMClient([json.dumps(proposals)])
    ctx = ExecutionContext(
        conn=conn,
        user_id=USER,
        run_id="r",
        clock=CLOCK,
        actor="agent",
        policy=load_policy("config/policy.yaml"),
        llm_client=llm,
    )
    result = execute_tool(ctx, "suggest_challenges", {"max_offers": 3})
    assert result.ok
    assert len(llm.prompts) == 1  # the model was asked once, through the tool path
