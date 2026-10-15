"""
Phase 4 golden scenarios (PLAN_PHASE4 Stage 4.12).

Each scenario is a short story run through the real code: the synthetic personas of
`copilot.bank.synth_v5`, the executor with the real policy, and the real review wording. The
seeds are fixed fixtures (found once by scanning, then frozen), so every scenario is exact.

 1. Essential categories are never offered, designed or proposed
 2. The target never falls below half of the usual value
 3. A null window is reported as within the usual range
 4. A genuine cut is reported beyond the usual range, with the exact rank
 5. Two windows of history is "no baseline", and says so
 6. A festival is set aside; the exception pause is real and reversible
 7. A recategorisation-assisted win asks for confirmation before it earns XP
 8. An abandoned experiment still earns learning XP and a kind review
 9. XP is never awarded twice
10. Raising a target is never automatic
11. Two unhelpful experiments in a row start rest weeks (and cost no model call)
12. Offers are reproducible by seed, with logged propensities
13. A money bet with a friend is refused
14. An outcome is cited without causal words
15. A personal best is recognised, and scoped to its category
16. A grace day keeps a streak
17. Nothing compares the user with anyone else
18. The MCP server shows no write tool
19. The planner cannot reach a write tool
20. Accepted extensions and easings change the experiment, and never tighten
21. An experiment across a year boundary is measured whole
22. The review waits for its delay
23. The weekly job run twice makes one set of offers
24. No review ever says the challenge caused the result
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from copilot.bank.synth_v5 import generate_persona_data
from copilot.core.adaptive import (
    accept_adjustment,
    detect_ahead_at_midpoint,
    detect_exception_overlap,
    reject_adjustment,
)
from copilot.core.baseline import generate_candidate_windows
from copilot.core.challenges import generate_challenge_offers
from copilot.core.essentials import essential_category_ids
from copilot.core.experiments import (
    abandon_experiment,
    create_checkins,
    create_due_reviews,
    design_experiment,
    observed_value,
    start_experiment,
    submit_review_feedback,
)
from copilot.core.intent import check_input_gate
from copilot.core.learning_loop import (
    assert_no_causal_claims,
    format_outcome_memory_advice_evidence,
    record_experiment_outcome_memory,
)
from copilot.core.review_wording import describe_review
from copilot.core.rewards import get_user_progress, scan_copy_safety
from copilot.core.self_competition import (
    FORBIDDEN_SHAME_TERMS,
    assert_no_social_comparison,
    calculate_streak_from_daily_series,
    compute_personal_bests,
)
from copilot.db.repo_phase4 import (
    get_experiment,
    get_experiment_review,
    insert_experiment,
    insert_experiment_review,
    list_offers,
    list_xp_events,
)
from copilot.eval.harness_phase4 import (
    USER,
    _clock,
    _ctx,
    _declare_exception,
    _insert_txn,
    _load,
    _new_db,
)
from copilot.governance.policy import decide, load_policy
from copilot.llm.client import FakeLLMClient
from copilot.models.phase4 import Experiment, ExperimentReview
from copilot.tools.executor import execute_tool
from copilot.tools.registry import get as get_tool
from copilot.workflow.nodes import ensure_tools_registered

ROOT = Path(__file__).resolve().parents[3]
START = "2026-09-01"
T_START = _clock(START)

# Fixed fixtures: found by scanning seeds once, then frozen.
SEED_NULL_WITHIN = 3001  # null persona, outcome within the usual range, rank 42.85%
SEED_REDUCER_BEYOND = 3003  # genuine cut, lower than all six earlier fortnights
SEED_RECATEGORISER = 3000  # moves payments out of the category, target met


@pytest.fixture(autouse=True)
def _tools():
    ensure_tools_registered()


def _run(
    persona, seed, *, difficulty="medium", history_windows=8, target=None, hist_exception=False
):
    data = generate_persona_data(seed, persona, history_windows=history_windows)
    conn = _new_db()
    _load(conn, data)
    if hist_exception and data.truth.historic_exception:
        _declare_exception(conn, "ex_hist", *data.truth.historic_exception)
    params = {
        "metric_code": "category_spend",
        "categories": ["food"],
        "duration_days": 14,
        "difficulty": difficulty,
    }
    if target is not None:
        params["target_value"] = target
    exp = design_experiment(conn, USER, params=params, clock=T_START)
    exp = start_experiment(conn, USER, exp.id, clock=T_START)
    return conn, data, exp


def _review_clock(window_end: str, days: int = 2) -> datetime:
    return _clock((date.fromisoformat(window_end) + timedelta(days=days)).isoformat())


def _finish(conn, exp):
    reviews = create_due_reviews(conn, USER, clock=_review_clock(exp.window_end))
    return next(r for r in reviews if r.experiment_id == exp.id)


def _job(conn, clock=None):
    ctx = _ctx(conn, clock or _clock("2026-09-20"), "user")
    result = execute_tool(ctx, "award_xp_and_badges", {})
    assert result.ok, result.error
    conn.commit()
    return {e.rule_code for e in list_xp_events(conn, USER)}


# 1 ------------------------------------------------------------------------------------------
def test_01_essential_categories_are_never_offered_designed_or_proposed():
    conn = _new_db()
    essential = essential_category_ids(conn, USER)
    assert {"housing", "bills", "flat_rent", "groceries", "travel", "education"} <= essential
    for cat in ("housing", "bills", "flat_rent", "groceries", "travel", "education"):
        with pytest.raises(ValueError, match="essential"):
            design_experiment(
                conn,
                USER,
                clock=T_START,
                params={"metric_code": "category_spend", "categories": [cat], "duration_days": 14},
            )
    for cid in ("food", "shopping", "housing", "bills", "flat_rent", "groceries", "travel"):
        for i, (start, _end) in enumerate(generate_candidate_windows(START, 14, k=6), 1):
            _insert_txn(conn, f"h_{cid}_{i}", f"{start}T10:00:00Z", 200000, cid)
    specs = [
        {
            "metric_code": m,
            "categories": [cid],
            "duration_days": 14,
            "difficulty": "hard",
            "title": "t",
            "rationale": "r",
            "proposed_target": 1,
        }
        for cid in ("housing", "bills", "flat_rent", "groceries", "travel", "food")
        for m in ("category_spend", "no_spend_days", "txn_count")
    ]
    llm = FakeLLMClient([json.dumps({"specs": specs})])
    offers = generate_challenge_offers(conn, USER, week_start=START, llm_client=llm, clock=T_START)
    assert offers, "the non-essential proposal should survive"
    assert all(not set(o.params_json["categories"]) & essential for o in offers)
    rejected = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = 'challenge_spec_rejected'"
    ).fetchone()[0]
    assert rejected >= 15


# 2 ------------------------------------------------------------------------------------------
def test_02_the_target_never_falls_below_half_of_the_usual_value():
    conn, _data, exp = _run("null", SEED_NULL_WITHIN, difficulty="hard")
    median = exp.baseline_json["median"]
    assert exp.target_value >= median * 50 // 100
    assert exp.target_value % 5000 == 0  # rounded to the nearest 50 rupees
    conn2 = _new_db()
    _load(conn2, generate_persona_data(SEED_NULL_WITHIN, "null"))
    with pytest.raises(ValueError, match="below 50%"):
        design_experiment(
            conn2,
            USER,
            clock=T_START,
            params={
                "metric_code": "category_spend",
                "categories": ["food"],
                "duration_days": 14,
                "target_value": median * 50 // 100 - 1,
            },
        )


# 3 ------------------------------------------------------------------------------------------
def test_03_a_null_window_is_reported_within_the_usual_range():
    conn, _data, exp = _run("null", SEED_NULL_WITHIN)
    review = _finish(conn, exp)
    assert review.outcome == "within_usual_range" and review.rank_p_bp == 4285
    words = describe_review(get_experiment(conn, USER, exp.id), review)
    assert "within your usual range" in words.headline
    assert_no_causal_claims(words.text())
    scan_copy_safety(words.text())


# 4 ------------------------------------------------------------------------------------------
def test_04_a_genuine_cut_is_beyond_the_usual_range_with_the_exact_rank():
    conn, _data, exp = _run("reducer", SEED_REDUCER_BEYOND)
    review = _finish(conn, exp)
    assert review.outcome == "beyond_usual_range"
    assert review.rank_p_bp == 10000 // 7  # lower than all 6 earlier windows: 1/(K+1)
    assert review.target_met is True
    words = describe_review(get_experiment(conn, USER, exp.id), review)
    assert "lower than all 6 of your previous comparable fortnights" in words.headline
    assert "usual range" in words.headline
    assert_no_causal_claims(words.text())


# 5 ------------------------------------------------------------------------------------------
def test_05_two_windows_of_history_is_no_baseline_and_says_so():
    data = generate_persona_data(SEED_NULL_WITHIN, "null", history_windows=2)
    conn = _new_db()
    _load(conn, data)
    with pytest.raises(ValueError, match="Baseline unavailable"):
        design_experiment(
            conn,
            USER,
            clock=T_START,
            params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
        )
    exp = design_experiment(
        conn,
        USER,
        clock=T_START,
        params={
            "metric_code": "category_spend",
            "categories": ["food"],
            "duration_days": 14,
            "target_value": 150000,
        },
    )
    exp = start_experiment(conn, USER, exp.id, clock=T_START)
    review = _finish(conn, exp)
    assert review.outcome == "no_baseline"
    words = describe_review(get_experiment(conn, USER, exp.id), review)
    assert "not enough earlier history" in words.text()


# 6 ------------------------------------------------------------------------------------------
def test_06_a_festival_is_set_aside_and_the_pause_is_real_and_reversible():
    conn, data, exp = _run("festival", SEED_RECATEGORISER, hist_exception=True)
    assert exp.baseline_json["k"] == 5  # the declared historic festival window is left out
    assert any("contextual_exception" in e["reason"] for e in exp.baseline_json["excluded_windows"])
    days = data.truth.exception_days
    _declare_exception(conn, "ex_window", days[0], days[-1])
    proposals = detect_exception_overlap(conn, USER, exp.id, clock=_clock(days[0]))
    pause = next(p for p in proposals if p.kind == "pause")
    assert pause.status == "auto_applied_pause" and any(p.kind == "extend" for p in proposals)
    assert get_experiment(conn, USER, exp.id).params_json["paused_days"] == days
    # measured value leaves the festival days out
    whole = observed_value(conn, USER, get_experiment(conn, USER, exp.id), exp.window_end)
    reject_adjustment(conn, USER, pause.id, clock=_clock(days[0]))
    restored = observed_value(conn, USER, get_experiment(conn, USER, exp.id), exp.window_end)
    assert restored > whole  # the festival spending counts again once the pause is reversed


# 7 ------------------------------------------------------------------------------------------
def test_07_a_recategorisation_assisted_win_asks_for_confirmation_before_xp():
    data = generate_persona_data(SEED_RECATEGORISER, "recategoriser")
    conn = _new_db()
    _load(conn, data)
    exp = design_experiment(
        conn,
        USER,
        clock=T_START,
        params={
            "metric_code": "category_spend",
            "categories": ["food"],
            "duration_days": 14,
            "difficulty": "medium",
        },
    )
    exp = start_experiment(conn, USER, exp.id, clock=T_START)
    ctx = _ctx(conn, _clock(data.truth.window_end, 20), "user")
    for row in data.rows:  # the user moves those payments to another category, one by one
        if row["move_to"]:
            assert execute_tool(
                ctx,
                "recategorize_transaction",
                {"transaction_id": row["id"], "new_category_id": row["move_to"]},
            ).ok
    review = _finish(conn, exp)
    assert review.target_met is True
    assert review.integrity_json["confirmation_required"] is True
    words = describe_review(get_experiment(conn, USER, exp.id), review)
    assert words.needs_confirmation and "genuine corrections" in words.confirmation_prompt
    assert "target_met" not in _job(conn)  # no XP for the target until the user confirms
    conn.execute("UPDATE experiments SET status = 'completed' WHERE id = ?", (exp.id,))
    confirmed = execute_tool(
        _ctx(conn, _clock("2026-09-17"), "user"),
        "confirm_review_integrity",
        {"experiment_id": exp.id},
    )
    assert confirmed.ok
    conn.commit()
    assert "target_met" in _job(conn)  # the same job, now that the user vouched for it
    agent = _ctx(conn, _clock("2026-09-17"), "agent")
    denied = execute_tool(agent, "confirm_review_integrity", {"experiment_id": exp.id})
    assert not denied.ok  # an agent can never vouch on the user's behalf


# 8 ------------------------------------------------------------------------------------------
def test_08_an_abandoned_experiment_still_earns_learning_xp_and_a_kind_review():
    conn, _data, exp = _run("null", SEED_NULL_WITHIN)
    stopped, review = abandon_experiment(conn, USER, exp.id, clock=_clock("2026-09-06"))
    words = describe_review(stopped, review)
    assert words.headline.startswith("You stopped this early, which is fine")
    scan_copy_safety(words.text())
    for term in FORBIDDEN_SHAME_TERMS:
        assert term not in words.text().lower()
    submit_review_feedback(conn, USER, review.id, user_helpful=True, clock=_clock("2026-09-07"))
    conn.commit()
    rules = _job(conn, _clock("2026-09-08"))
    assert "experiment_reviewed_abandoned" in rules
    assert "experiment_completed" not in rules  # stopping early is not "completing"


# 9 ------------------------------------------------------------------------------------------
def test_09_xp_is_never_awarded_twice():
    conn, _data, exp = _run("reducer", SEED_REDUCER_BEYOND)
    _finish(conn, exp)
    conn.commit()
    _job(conn, _clock("2026-09-20"))
    total_once = get_user_progress(conn, USER, clock=_clock("2026-09-20")).total_xp
    for day in ("2026-09-20", "2026-09-21", "2026-09-30"):
        _job(conn, _clock(day))
    assert get_user_progress(conn, USER, clock=_clock("2026-09-30")).total_xp == total_once
    assert total_once > 0


# 10 -----------------------------------------------------------------------------------------
def test_10_raising_a_target_is_never_automatic():
    data = generate_persona_data(SEED_REDUCER_BEYOND, "reducer")
    conn = _new_db()
    _load(conn, data)
    median = design_experiment(
        conn,
        USER,
        clock=T_START,
        params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
    ).baseline_json["median"]
    exp = design_experiment(
        conn,
        USER,
        clock=T_START,
        params={
            "metric_code": "category_spend",
            "categories": ["food"],
            "duration_days": 14,
            "target_value": median,
            "difficulty": "easy",
        },
    )
    exp = start_experiment(conn, USER, exp.id, clock=T_START)
    create_checkins(conn, USER, clock=_clock("2026-09-09"))
    proposals = detect_ahead_at_midpoint(conn, USER, exp.id, clock=_clock("2026-09-09"))
    assert [p.kind for p in proposals] == ["raise_target_optional"]
    assert proposals[0].status == "proposed"
    assert get_experiment(conn, USER, exp.id).target_value == median  # detection changed nothing
    accept_adjustment(conn, USER, proposals[0].id, clock=_clock("2026-09-09"))
    raised = get_experiment(conn, USER, exp.id).target_value
    assert median * 50 // 100 <= raised <= median  # one level harder, never below the floor


# 11 -----------------------------------------------------------------------------------------
def test_11_two_unhelpful_experiments_start_rest_weeks_at_no_model_cost():
    conn = _new_db()
    _insert_txn(conn, "any", "2026-08-20T10:00:00Z", 1000, "food")  # there is spending on record
    for i, ended in enumerate(("2026-08-25", "2026-08-28")):
        exp = Experiment(
            id=f"e{i}",
            user_id=USER,
            title="t",
            template_code="x",
            hypothesis_json={},
            metric_def_json={"metric_code": "category_spend", "categories": ["food"]},
            params_json={},
            difficulty="medium",
            window_start="2026-08-10",
            window_end="2026-08-23",
            baseline_json={},
            target_value=1,
            status="reviewed",
            origin="offer",
            created_at=f"{ended}T00:00:00Z",
            ended_at=f"{ended}T00:00:00Z",
        )
        insert_experiment(conn, exp)
        insert_experiment_review(
            conn,
            ExperimentReview(
                id=f"r{i}",
                user_id=USER,
                experiment_id=f"e{i}",
                observed_value=1,
                outcome="within_usual_range",
                rank_p_bp=5000,
                effect_value=0,
                target_met=False,
                integrity_json={},
                data_quality_json={},
                user_helpful=False,
                created_at=f"{ended}T00:00:00Z",
            ),
        )
    llm = FakeLLMClient([json.dumps({"specs": []})])
    assert (
        generate_challenge_offers(conn, USER, week_start=START, clock=T_START, llm_client=llm) == []
    )
    assert llm.prompts == []
    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'offers_withheld'"
    ).fetchone()
    assert json.loads(event["metadata_json"])["reason"] == "rest_weeks"


# 12 -----------------------------------------------------------------------------------------
def _offer_world():
    conn = _new_db()
    for cid, paise in (("food", 300000), ("shopping", 200000), ("entertainment", 150000)):
        for duration in (7, 14):
            for i, (start, _e) in enumerate(generate_candidate_windows(START, duration, k=6), 1):
                _insert_txn(conn, f"o_{cid}_{duration}_{i}", f"{start}T10:00:00Z", paise, cid)
    return conn


def test_12_offers_are_reproducible_by_seed_with_logged_propensities():
    first = generate_challenge_offers(_offer_world(), USER, week_start=START, clock=T_START)
    second = generate_challenge_offers(_offer_world(), USER, week_start=START, clock=T_START)
    key = lambda offers: [(o.template_code, o.propensity_bp, o.rng_seed) for o in offers]  # noqa: E731
    assert first and key(first) == key(second)
    assert all(1 <= o.propensity_bp <= 10000 and o.policy_version == "thompson_v1" for o in first)


# 13 -----------------------------------------------------------------------------------------
def test_13_a_money_bet_with_a_friend_is_refused():
    for text in (
        "I want to bet 500 rupees with my friend on who spends less",
        "can I challenge my coworker for money",
    ):
        refused, kind, reply = check_input_gate(text)
        assert refused and kind == "BETTING_GAMBLING"
        assert "self-competition" in reply


# 14 -----------------------------------------------------------------------------------------
def test_14_an_outcome_is_cited_without_causal_words():
    conn, _data, exp = _run("reducer", SEED_REDUCER_BEYOND)
    _finish(conn, exp)
    memory = record_experiment_outcome_memory(conn, USER, exp.id, clock=_clock("2026-09-20"))
    citation = format_outcome_memory_advice_evidence(memory)
    assert_no_causal_claims(citation)
    scan_copy_safety(citation)


# 15 -----------------------------------------------------------------------------------------
def test_15_a_personal_best_is_recognised_and_scoped_to_its_category():
    conn, _data, exp = _run("reducer", SEED_REDUCER_BEYOND)
    review = _finish(conn, exp)
    bests = compute_personal_bests(conn, USER)
    assert [(b.metric_code, b.scope, b.best_value) for b in bests] == [
        ("category_spend", "food", review.observed_value)
    ]
    # a second experiment in another category must not be compared with the food best
    other = Experiment(
        id="other",
        user_id=USER,
        title="t",
        template_code="x",
        hypothesis_json={},
        metric_def_json={"metric_code": "category_spend", "categories": ["shopping"]},
        params_json={},
        difficulty="medium",
        window_start="2026-09-20",
        window_end="2026-10-03",
        baseline_json={},
        target_value=1,
        status="reviewed",
        origin="user",
        created_at="2026-09-20T00:00:00Z",
    )
    insert_experiment(conn, other)
    insert_experiment_review(
        conn,
        ExperimentReview(
            id="rother",
            user_id=USER,
            experiment_id="other",
            observed_value=10,
            outcome="within_usual_range",
            rank_p_bp=5000,
            effect_value=0,
            target_met=True,
            integrity_json={},
            data_quality_json={},
            created_at="2026-10-04T00:00:00Z",
        ),
    )
    assert {(b.scope, b.best_value) for b in compute_personal_bests(conn, USER)} == {
        ("food", review.observed_value),
        ("shopping", 10),
    }


# 16 -----------------------------------------------------------------------------------------
def test_16_a_grace_day_keeps_a_streak():
    start = date(2026, 9, 1)
    days = {start + timedelta(days=i): True for i in range(6)}
    days[start + timedelta(days=6)] = False  # one missed day inside seven
    kept = calculate_streak_from_daily_series(days, set(), start + timedelta(days=6))
    assert kept.current_streak == 7 and kept.is_active
    days[start + timedelta(days=7)] = False  # a second miss straight after breaks it
    broken = calculate_streak_from_daily_series(days, set(), start + timedelta(days=7))
    assert not broken.is_active and broken.display_text == "Longest streak: 7 days"


# 17 -----------------------------------------------------------------------------------------
def test_17_nothing_compares_the_user_with_anyone_else():
    conn, _data, exp = _run("reducer", SEED_REDUCER_BEYOND)
    review = _finish(conn, exp)
    # someone else has far more XP; nothing the user sees may mention them
    from copilot.db.repo import insert_account, insert_user
    from copilot.models.domain import Account, User

    insert_user(conn, User(id="someone_else", created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(id="acc_x", user_id="someone_else", name="X", created_at="2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO xp_events (id, user_id, rule_code, points, ref_kind, ref_id, period_day,"
        " created_at) VALUES ('x1', 'someone_else', 'target_met', 30, 'experiment', 'z', '2026-09-01',"
        " '2026-09-01T00:00:00Z')"
    )
    outputs = [
        describe_review(get_experiment(conn, USER, exp.id), review).text(),
        get_user_progress(conn, USER, clock=_clock("2026-09-20")).model_dump_json(),
        json.dumps([b.model_dump() for b in compute_personal_bests(conn, USER)]),
    ]
    for text in outputs:
        assert_no_social_comparison(text)
        assert "someone_else" not in text
    assert get_user_progress(conn, USER, clock=_clock("2026-09-20")).total_xp == 0


# 18 -----------------------------------------------------------------------------------------
def test_18_the_mcp_server_shows_no_write_tool():
    exposed = set(
        yaml.safe_load((ROOT / "config" / "mcp.yaml").read_text("utf-8"))["exposed_tools"]
    )
    ensure_tools_registered()
    for name in exposed:
        spec = get_tool(name)
        assert spec is not None and spec.side_effect.name == "READ", f"{name} is not read-only"
    assert not exposed & {
        "start_experiment",
        "accept_offer",
        "dismiss_offer",
        "answer_checkin",
        "abandon_experiment",
        "confirm_review_integrity",
        "award_xp_and_badges",
        "weekly_offers",
        "accept_adjustment",
    }


# 19 -----------------------------------------------------------------------------------------
def test_19_the_planner_cannot_reach_a_write_tool():
    policy = load_policy(ROOT / "config" / "policy.yaml")
    capabilities = yaml.safe_load(
        (ROOT / "config" / "planner_capabilities.yaml").read_text("utf-8")
    )
    for name in (
        "start_experiment",
        "pause_experiment",
        "abandon_experiment",
        "answer_checkin",
        "submit_review_feedback",
        "confirm_review_integrity",
        "accept_offer",
        "dismiss_offer",
        "accept_adjustment",
        "reject_adjustment",
    ):
        spec = get_tool(name)
        assert spec is not None
        assert decide(policy, spec, actor="agent").outcome == "deny", name
        assert capabilities["tools"][name]["planner_selectable"] is False, name


# 20 -----------------------------------------------------------------------------------------
def test_20_accepted_extensions_and_easings_change_the_experiment_and_never_tighten():
    conn, _data, exp = _run("null", SEED_NULL_WITHIN, difficulty="hard")
    start_target, start_end = exp.target_value, exp.window_end
    from copilot.core.adaptive import _make_proposal

    ease = _make_proposal(conn, USER, exp.id, "ease_target", "test", {}, _clock("2026-09-05"))
    extend = _make_proposal(
        conn, USER, exp.id, "extend", "test", {"extend_days": 3}, _clock("2026-09-05")
    )
    accept_adjustment(conn, USER, ease.id, clock=_clock("2026-09-05"))
    accept_adjustment(conn, USER, extend.id, clock=_clock("2026-09-05"))
    after = get_experiment(conn, USER, exp.id)
    assert after.target_value >= start_target  # gentler (a higher spending cap), never tighter
    assert after.difficulty == "medium"
    assert date.fromisoformat(after.window_end) == date.fromisoformat(start_end) + timedelta(days=3)


# 21 -----------------------------------------------------------------------------------------
def test_21_an_experiment_across_a_year_boundary_is_measured_whole():
    start = "2026-12-24"
    data = generate_persona_data(5150, "null", start_date=start)
    conn = _new_db()
    _load(conn, data)
    clock = _clock(start)
    exp = design_experiment(
        conn,
        USER,
        clock=clock,
        params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
    )
    exp = start_experiment(conn, USER, exp.id, clock=clock)
    assert exp.window_end == "2027-01-06"
    review = create_due_reviews(conn, USER, clock=_clock("2027-01-08"))[0]
    assert review.observed_value == sum(
        r["amount_paise"]
        for r in data.rows
        if "2026-12-24" <= r["occurred_at"][:10] <= "2027-01-06"
    )
    assert exp.baseline_json["k"] == 6


# 22 -----------------------------------------------------------------------------------------
def test_22_the_review_waits_for_its_delay():
    conn, _data, exp = _run("null", SEED_NULL_WITHIN)  # window 1 to 14 September, delay 2 days
    assert create_due_reviews(conn, USER, clock=_clock("2026-09-14")) == []
    assert create_due_reviews(conn, USER, clock=_clock("2026-09-15")) == []
    assert len(create_due_reviews(conn, USER, clock=_clock("2026-09-16"))) == 1


# 23 -----------------------------------------------------------------------------------------
def test_23_the_weekly_job_run_twice_makes_one_set_of_offers():
    conn = _offer_world()
    ctx = _ctx(conn, T_START, "agent")
    first = execute_tool(ctx, "weekly_offers", {})
    again = execute_tool(ctx, "weekly_offers", {})
    assert first.ok and again.ok
    assert first.data.offers_created >= 1
    assert len(list_offers(conn, USER)) == first.data.offers_created


# 24 -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "persona, seed", [("reducer", 3003), ("null", 3001), ("null", 3002), ("reducer", 3004)]
)
def test_24_no_review_ever_says_the_challenge_caused_the_result(persona, seed):
    conn, _data, exp = _run(persona, seed)
    review = _finish(conn, exp)
    text = describe_review(get_experiment(conn, USER, exp.id), review).text()
    assert_no_causal_claims(text)
    scan_copy_safety(text)
    assert get_experiment_review(conn, USER, exp.id) is not None
