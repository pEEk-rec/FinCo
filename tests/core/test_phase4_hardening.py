"""
Failure handling for Phase 4 (PLAN_PHASE4 Stage 4.13).

Each test is one thing that goes wrong in real use: a window that spans a year end, a category
or goal that changes under an active experiment, weeks of missed jobs, offers that are ignored
for months, an empty history, two runners of the weekly job at once, and what ends up in logs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import date, timedelta

import pytest

from copilot.bank.synth_v5 import generate_persona_data
from copilot.core.baseline import generate_candidate_windows
from copilot.core.challenges import evaluate_triggers, generate_challenge_offers
from copilot.core.experiments import (
    create_checkins,
    create_due_reviews,
    design_experiment,
    start_experiment,
)
from copilot.core.learning_loop import record_experiment_outcome_memory
from copilot.core.rewards import get_user_progress
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_goal, insert_user
from copilot.db.repo_phase4 import list_experiment_checkins, list_offers, update_offer_status
from copilot.eval.harness_phase4 import CATEGORIES, T0, USER, _clock, _insert_txn, _load, _new_db
from copilot.models.agentic import Goal
from copilot.models.domain import Account, Category, User
from copilot.workflow.nodes import ensure_tools_registered

START = "2026-09-01"


@pytest.fixture(autouse=True)
def _tools():
    ensure_tools_registered()


def _history(conn, categories=(("food", 300000), ("shopping", 200000), ("entertainment", 150000))):
    for cid, paise in categories:
        for duration in (7, 14):
            for i, (start, _e) in enumerate(generate_candidate_windows(START, duration, k=6), 1):
                _insert_txn(conn, f"h_{cid}_{duration}_{i}", f"{start}T10:00:00Z", paise, cid)


def _active_experiment(conn, start=START, **extra):
    clock = _clock(start)
    params = {"metric_code": "category_spend", "categories": ["food"], "duration_days": 14}
    params.update(extra)
    exp = design_experiment(conn, USER, params=params, clock=clock)
    return start_experiment(conn, USER, exp.id, clock=clock)


# --- a category cannot vanish under an active experiment -----------------------------------------
def test_a_category_in_use_cannot_be_deleted_so_an_experiment_never_loses_its_metric():
    conn = _new_db()
    _load(conn, generate_persona_data(11, "null"))
    exp = _active_experiment(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM categories WHERE id = 'food'")
    review = create_due_reviews(conn, USER, clock=_clock("2026-09-16"))[0]
    assert review.experiment_id == exp.id


def test_a_category_with_no_spending_in_the_window_is_measured_as_zero_not_an_error():
    conn = _new_db()
    _history(conn, (("food", 300000),))
    exp = _active_experiment(conn, categories=["entertainment"], target_value=1000)
    review = create_due_reviews(conn, USER, clock=_clock("2026-09-16"))[0]
    assert review.experiment_id == exp.id and review.observed_value == 0


# --- a goal can disappear -------------------------------------------------------------------------
def test_a_goal_removed_mid_experiment_only_drops_the_goal_line_from_the_review():
    conn = _new_db()
    _load(conn, generate_persona_data(12, "reducer"))
    insert_goal(
        conn,
        Goal(
            id="g1",
            user_id=USER,
            name="Trip",
            kind="savings",
            target_paise=5_000_000,
            current_paise=0,
            priority=1,
            created_at=T0,
            updated_at=T0,
        ),
    )
    exp = _active_experiment(conn, goal_id="g1")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM goals WHERE id = 'g1'")
    review = create_due_reviews(conn, USER, clock=_clock("2026-09-16"))[0]
    assert review.experiment_id == exp.id
    assert review.data_quality_json["goal_link_narrative"] is None


# --- weeks of missed jobs -------------------------------------------------------------------------
def test_a_clock_that_jumps_over_weeks_catches_up_once_and_not_twice():
    conn = _new_db()
    _load(conn, generate_persona_data(13, "null"))
    exp = _active_experiment(conn)
    far = _clock("2026-10-20")  # seven weeks later; no job ran in between
    made = create_checkins(conn, USER, clock=far)
    assert len(made) == 1  # a 14-day window has one weekly check-in (day 8); none beyond the end
    assert create_checkins(conn, USER, clock=far) == []
    reviews = create_due_reviews(conn, USER, clock=far)
    assert [r.experiment_id for r in reviews] == [exp.id]
    assert create_due_reviews(conn, USER, clock=far) == []
    assert len(list_experiment_checkins(conn, USER, exp.id)) == 1


# --- offers ignored for months --------------------------------------------------------------------
def test_offers_that_are_always_dismissed_thin_out_instead_of_nagging():
    conn = _new_db()
    _history(conn)
    shown_weeks: list[int] = []
    week0 = date(2026, 9, 1)
    for n in range(12):
        week = (week0 + timedelta(days=7 * n)).isoformat()
        offers = generate_challenge_offers(conn, USER, week_start=week, clock=_clock(week))
        if offers:
            shown_weeks.append(n)
        for o in offers:
            update_offer_status(conn, USER, o.id, "dismissed", f"{week}T12:00:00Z")
    assert shown_weeks[:3] == [0, 1, 3]  # two weeks, a quiet week, then offers may return
    consecutive = [b - a for a, b in zip(shown_weeks, shown_weeks[1:], strict=False)]
    assert max(consecutive[1:], default=2) <= 2 and len(shown_weeks) <= 8


# --- no history at all ----------------------------------------------------------------------------
def test_an_empty_history_degrades_quietly_everywhere():
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at=T0))
    insert_account(conn, Account(id="acc_main", user_id=USER, name="M", created_at=T0))
    for cid, name in CATEGORIES:
        insert_category(conn, Category(id=cid, user_id=USER, name=name, created_at=T0))
    assert generate_challenge_offers(conn, USER, week_start=START, clock=_clock(START)) == []
    assert evaluate_triggers(conn, USER, clock=_clock(START)) <= {"low_tagging_completeness"}
    with pytest.raises(ValueError, match="Baseline unavailable"):
        design_experiment(
            conn,
            USER,
            clock=_clock(START),
            params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
        )
    assert get_user_progress(conn, USER, clock=_clock(START)).total_xp == 0


# --- two runners of the weekly job at once --------------------------------------------------------
def test_two_runners_of_the_weekly_job_leave_exactly_one_set_of_offers(tmp_path):
    path = tmp_path / "shared.db"
    setup = get_connection(str(path), check_same_thread=False)
    init_db(setup)
    insert_user(setup, User(id=USER, created_at=T0))
    insert_account(setup, Account(id="acc_main", user_id=USER, name="M", created_at=T0))
    for cid, name in CATEGORIES:
        insert_category(setup, Category(id=cid, user_id=USER, name=name, created_at=T0))
    _history(setup)
    setup.commit()
    setup.close()

    counts: list[int] = []
    errors: list[str] = []
    barrier = threading.Barrier(4)

    def runner() -> None:
        conn = get_connection(str(path), check_same_thread=False)
        try:
            barrier.wait()
            offers = generate_challenge_offers(conn, USER, week_start=START, clock=_clock(START))
            conn.commit()
            counts.append(len(offers))
        except Exception as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            conn.close()

    threads = [threading.Thread(target=runner) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check = get_connection(str(path))
    assert errors == []
    stored = list_offers(check, USER, week_start=START)
    assert len(stored) == max(counts) and len(stored) >= 1
    assert len({o.rank for o in stored}) == len(stored)
    check.close()


# --- what reaches the logs ------------------------------------------------------------------------
def test_private_text_never_reaches_logs_spans_or_audit_metadata(caplog):
    """Run the real tool path and look at everything it leaves behind."""
    from copilot.eval.harness_phase4 import _ctx
    from copilot.tools.executor import execute_tool

    secret_merchant = "ZXQSECRETSHOP"
    secret_note = "my very private note about money"
    conn = _new_db()
    _load(conn, generate_persona_data(21, "reducer"))
    conn.execute(
        "UPDATE transactions SET merchant_raw = ?, merchant_normalized = ?",
        (secret_merchant, secret_merchant.lower()),
    )

    def run(name, clock, **args):
        result = execute_tool(_ctx(conn, _clock(clock), "user"), name, args)
        assert result.ok, (name, result.error)
        return result

    with caplog.at_level(logging.DEBUG):
        designed = run(
            "design_experiment", START,
            metric_code="category_spend", categories=["food"], duration_days=14,
        )
        exp_id = designed.data.experiment.id
        run("start_experiment", START, experiment_id=exp_id)
        run("create_checkins", "2026-09-09")
        run("create_due_reviews", "2026-09-16")
        run("submit_review_feedback", "2026-09-17", experiment_id=exp_id, user_helpful=True,
            feedback_text=secret_note)
        memory = record_experiment_outcome_memory(conn, USER, exp_id, clock=_clock("2026-09-18"))
        run("suggest_challenges", "2026-09-22")
        run("award_xp_and_badges", "2026-09-23")
    logged = " ".join(r.getMessage() for r in caplog.records)
    spans = " ".join(
        str(row[0]) for row in conn.execute("SELECT attrs_json FROM trace_spans").fetchall()
    )
    assert spans, "no spans were recorded, so there is nothing to inspect"
    audit_meta = " ".join(
        str(r[0]) + str(r[1])
        for r in conn.execute("SELECT metadata_json, after_json FROM audit_events").fetchall()
    )
    for private in (secret_merchant, secret_merchant.lower(), secret_note):
        assert private not in logged
        assert private not in spans
        assert private not in audit_meta
    assert secret_merchant.lower() not in json.dumps(memory.statement_json).lower()
