"""
Phase 4 CLI command tests (Typer CliRunner).

Covers all commands added for Phase 4:
- copilot experiments (design, start, list, show, pause, resume, checkin, tick, abandon, review, feedback)
- copilot challenges (offers, accept, dismiss)
- copilot adjustments (list, accept, reject)
- copilot progress [--json]
- copilot goals decompose <goal_id>
- copilot learning show / reset --subject challenge_template
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from copilot.cli.main import app
from copilot.db.connection import get_connection
from copilot.db.repo import insert_goal
from copilot.db.repo_phase4 import (
    insert_adjustment_proposal,
    insert_experiment,
    insert_experiment_review,
    insert_offer,
    update_experiment_status,
)
from copilot.models.agentic import Goal
from copilot.models.phase4 import (
    AdjustmentProposal,
    Experiment,
    ExperimentReview,
    Offer,
)

runner = CliRunner()


@pytest.fixture
def cli_db(tmp_path: Path) -> str:
    db = str(tmp_path / "cli_p4.db")
    res = runner.invoke(app, ["init-db", "--db", db])
    assert res.exit_code == 0, res.output
    res = runner.invoke(app, ["seed", "--db", db, "--months", "3", "--seed", "42"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(app, ["consent", "list", "--db", db, "--json"])
    if res.exit_code == 0 and res.output.strip():
        try:
            consents = json.loads(res.output)
            for c in consents:
                if c.get("status") == "pending":
                    runner.invoke(app, ["consent", "approve", c["id"], "--db", db])
        except Exception:
            pass
    return db


# =================================================================================================
# 1. Experiments CLI Tests
# =================================================================================================
def test_cli_experiments_lifecycle(cli_db: str):
    """Test design, start, list, show, pause, resume, checkin, abandon, review, feedback, tick."""
    # 1. Design
    des_res = runner.invoke(
        app,
        [
            "experiments",
            "design",
            "--template",
            "weekday_home_cooking",
            "--categories",
            "food",
            "--target",
            "3000",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert des_res.exit_code == 0, des_res.output
    des_json = json.loads(des_res.output)
    des_exp = des_json.get("experiment", des_json)
    assert des_exp["template_code"] == "weekday_home_cooking"

    # Also test design in table format
    des_tab = runner.invoke(
        app,
        [
            "experiments",
            "design",
            "--template",
            "delivery_cap",
            "--target",
            "2000",
            "--db",
            cli_db,
        ],
    )
    assert des_tab.exit_code == 0

    # 2. Start
    start_res = runner.invoke(
        app,
        [
            "experiments",
            "start",
            "--template",
            "weekday_home_cooking",
            "--categories",
            "food",
            "--target",
            "3000",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert start_res.exit_code == 0, start_res.output
    start_json = json.loads(start_res.output)
    start_exp = start_json.get("experiment", start_json)
    exp_id = start_exp["id"]
    assert start_exp["status"] == "active"

    # 3. List
    list_res = runner.invoke(app, ["experiments", "list", "--db", cli_db, "--json"])
    assert list_res.exit_code == 0, list_res.output
    items = json.loads(list_res.output)
    assert any(e["id"] == exp_id for e in items)

    # List in table format
    list_tab = runner.invoke(app, ["experiments", "list", "--db", cli_db])
    assert list_tab.exit_code == 0
    assert exp_id in list_tab.output

    # 4. Show
    show_res = runner.invoke(app, ["experiments", "show", exp_id, "--db", cli_db, "--json"])
    assert show_res.exit_code == 0, show_res.output
    show_json = json.loads(show_res.output)
    show_exp = show_json.get("experiment", show_json)
    assert show_exp["id"] == exp_id

    show_tab = runner.invoke(app, ["experiments", "show", exp_id, "--db", cli_db])
    assert show_tab.exit_code == 0
    assert exp_id in show_tab.output

    # 5. Pause
    pause_res = runner.invoke(
        app,
        ["experiments", "pause", exp_id, "--db", cli_db, "--json"],
    )
    assert pause_res.exit_code == 0, pause_res.output
    pause_json = json.loads(pause_res.output)
    pause_exp = pause_json.get("experiment", pause_json)
    assert pause_exp["status"] == "paused"

    # 6. Resume
    res_res = runner.invoke(app, ["experiments", "resume", exp_id, "--db", cli_db, "--json"])
    assert res_res.exit_code == 0, res_res.output
    res_json = json.loads(res_res.output)
    res_exp = res_json.get("experiment", res_json)
    assert res_exp["status"] == "active"

    # 7. Tick (runtime job)
    tick_res = runner.invoke(app, ["experiments", "tick", "--db", cli_db])
    assert tick_res.exit_code == 0, tick_res.output

    # 8. Checkin
    chk_res = runner.invoke(
        app,
        [
            "experiments",
            "checkin",
            exp_id,
            "going_well",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert chk_res.exit_code == 0, chk_res.output
    chk_json = json.loads(chk_res.output)
    chk_obj = chk_json.get("checkin", chk_json)
    assert chk_obj["user_response"] == "going_well"

    # 9. Abandon
    ab_res = runner.invoke(
        app,
        [
            "experiments",
            "abandon",
            exp_id,
            "--reason",
            "Schedule change",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert ab_res.exit_code == 0, ab_res.output
    ab_json = json.loads(ab_res.output)
    ab_exp = ab_json.get("experiment", ab_json)
    assert ab_exp["status"] == "abandoned"

    # 10. Review
    rev_res = runner.invoke(app, ["experiments", "review", exp_id, "--db", cli_db, "--json"])
    assert rev_res.exit_code == 0, rev_res.output
    rev_json = json.loads(rev_res.output)
    rev_obj = rev_json.get("review", rev_json)
    assert rev_obj["experiment_id"] == exp_id

    rev_tab = runner.invoke(app, ["experiments", "review", exp_id, "--db", cli_db])
    assert rev_tab.exit_code == 0

    # 11. Feedback
    fb_res = runner.invoke(
        app,
        [
            "experiments",
            "feedback",
            exp_id,
            "--difficulty",
            "3",
            "--helpful",
            "--repeat",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert fb_res.exit_code == 0, fb_res.output
    fb_json = json.loads(fb_res.output)
    fb_obj = fb_json.get("review", fb_json)
    assert fb_obj["user_difficulty"] == 3
    assert fb_obj["user_helpful"] is True


# =================================================================================================
# 2. Challenges CLI Tests
# =================================================================================================
def test_cli_challenges_lifecycle(cli_db: str):
    """Test challenges offers, accept, and dismiss."""
    # Seed a couple of offers
    with get_connection(cli_db) as conn:
        off1 = Offer(
            id="off_cli_1",
            user_id="u1",
            week_start="2024-03-18",
            template_code="delivery_cap",
            difficulty="medium",
            params_json={
                "title": "Cap Food Delivery",
                "metric_code": "merchant_group_spend",
                "duration_days": 14,
                "target_value": 200000,
                "baseline_median": 350000,
            },
            rank=1,
            propensity_bp=5000,
            policy_version="v1_thompson",
            rng_seed=42,
            reason_json={"text": "Frequent delivery spend"},
            status="shown",
            created_at="2024-03-18T00:00:00Z",
        )
        off2 = Offer(
            id="off_cli_2",
            user_id="u1",
            week_start="2024-03-18",
            template_code="no_spend_weekend",
            difficulty="easy",
            params_json={
                "title": "No Spend Weekend",
                "metric_code": "no_spend_days",
                "duration_days": 7,
                "target_value": 2,
                "baseline_median": 1,
            },
            rank=2,
            propensity_bp=4000,
            policy_version="v1_thompson",
            rng_seed=43,
            reason_json={"text": "Try spending nothing on weekends"},
            status="shown",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_offer(conn, off1)
        insert_offer(conn, off2)
        conn.commit()

    # 1. Offers list
    offers_res = runner.invoke(app, ["challenges", "offers", "--db", cli_db, "--json"])
    assert offers_res.exit_code == 0, offers_res.output
    offers_data = json.loads(offers_res.output)
    assert len(offers_data) >= 2
    assert any(o["id"] == "off_cli_1" for o in offers_data)

    # Offers list in table format
    offers_tab = runner.invoke(app, ["challenges", "offers", "--db", cli_db])
    assert offers_tab.exit_code == 0
    assert "off_cli_1" in offers_tab.output

    # 2. Accept offer
    acc_res = runner.invoke(app, ["challenges", "accept", "off_cli_1", "--db", cli_db, "--json"])
    assert acc_res.exit_code == 0, acc_res.output
    acc_json = json.loads(acc_res.output)
    assert acc_json["status"] == "accepted"

    # 3. Dismiss offer
    dis_res = runner.invoke(
        app,
        [
            "challenges",
            "dismiss",
            "off_cli_2",
            "--reason",
            "Busy weekend",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert dis_res.exit_code == 0, dis_res.output
    dis_json = json.loads(dis_res.output)
    assert dis_json["status"] == "dismissed"


# =================================================================================================
# 3. Adjustments CLI Tests
# =================================================================================================
def test_cli_adjustments_lifecycle(cli_db: str):
    """Test adjustments list, accept, reject."""
    with get_connection(cli_db) as conn:
        exp = Experiment(
            id="exp_adj_cli",
            user_id="u1",
            title="Dining Test",
            template_code="weekday_home_cooking",
            hypothesis_json={"statement": "cook more"},
            metric_def_json={"metric_code": "category_spend", "categories": ["food"]},
            params_json={},
            difficulty="medium",
            window_start="2024-03-18",
            window_end="2024-04-01",
            baseline_json={"median": 400000},
            target_value=200000,
            status="active",
            origin="user",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_experiment(conn, exp)
        prop1 = AdjustmentProposal(
            id="adj_cli_1",
            experiment_id="exp_adj_cli",
            user_id="u1",
            kind="ease_target",
            reason_code="behind_pace_consecutive",
            params_json={"new_target_value": 250000},
            status="proposed",
            created_at="2024-03-22T00:00:00Z",
        )
        prop2 = AdjustmentProposal(
            id="adj_cli_2",
            experiment_id="exp_adj_cli",
            user_id="u1",
            kind="pause",
            reason_code="user_hard_checkin",
            params_json={"pause_days": 7},
            status="proposed",
            created_at="2024-03-22T00:00:00Z",
        )
        insert_adjustment_proposal(conn, prop1)
        insert_adjustment_proposal(conn, prop2)
        conn.commit()

    # 1. List
    list_res = runner.invoke(app, ["adjustments", "list", "--db", cli_db, "--json"])
    assert list_res.exit_code == 0, list_res.output
    adjs = json.loads(list_res.output)
    assert len(adjs) >= 2

    list_tab = runner.invoke(app, ["adjustments", "list", "--db", cli_db])
    assert list_tab.exit_code == 0
    assert "adj_cli_1" in list_tab.output

    # 2. Accept
    acc_res = runner.invoke(app, ["adjustments", "accept", "adj_cli_1", "--db", cli_db, "--json"])
    assert acc_res.exit_code == 0, acc_res.output
    acc_json = json.loads(acc_res.output)
    assert acc_json["proposal"]["status"] == "accepted"

    # 3. Reject
    rej_res = runner.invoke(
        app,
        [
            "adjustments",
            "reject",
            "adj_cli_2",
            "--reason",
            "I want to continue",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert rej_res.exit_code == 0, rej_res.output
    rej_json = json.loads(rej_res.output)
    assert rej_json["proposal"]["status"] == "rejected"


# =================================================================================================
# 4. Progress CLI Test
# =================================================================================================
def test_cli_progress_cmd(cli_db: str):
    """Test copilot progress command in json and rich table formats."""
    prog_json_res = runner.invoke(app, ["progress", "--db", cli_db, "--json"])
    assert prog_json_res.exit_code == 0, prog_json_res.output
    pdata = json.loads(prog_json_res.output)
    assert "level_number" in pdata
    assert "total_xp" in pdata

    prog_tab_res = runner.invoke(app, ["progress", "--db", cli_db])
    assert prog_tab_res.exit_code == 0, prog_tab_res.output
    assert "Level" in prog_tab_res.output
    assert "Total XP" in prog_tab_res.output


# =================================================================================================
# 5. Goal Decomposition CLI Test
# =================================================================================================
def test_cli_goals_decompose_cmd(cli_db: str):
    """Test copilot goals decompose <goal_id> in json and rich table formats."""
    with get_connection(cli_db) as conn:
        g = Goal(
            id="g_vacation_cli",
            user_id="u1",
            name="Summer Vacation",
            kind="savings",
            target_paise=10000000,
            current_paise=2000000,
            deadline="2024-06-30",
            priority=2,
            status="active",
            created_at="2024-03-01T00:00:00Z",
            updated_at="2024-03-01T00:00:00Z",
        )
        insert_goal(conn, g)
        conn.commit()

    decomp_json_res = runner.invoke(
        app,
        ["goals", "decompose", "g_vacation_cli", "--db", cli_db, "--json"],
    )
    assert decomp_json_res.exit_code == 0, decomp_json_res.output
    ddata = json.loads(decomp_json_res.output)
    assert ddata["goal_id"] == "g_vacation_cli"
    assert ddata["deficit_paise"] == 8000000
    assert "candidate_experiments" in ddata

    decomp_tab_res = runner.invoke(
        app,
        ["goals", "decompose", "g_vacation_cli", "--db", cli_db],
    )
    assert decomp_tab_res.exit_code == 0, decomp_tab_res.output
    assert "Goal Gap Decomposition" in decomp_tab_res.output


# =================================================================================================
# 6. Learning CLI Tests for Phase 4 Challenge Templates
# =================================================================================================
def test_cli_learning_challenge_template(cli_db: str):
    """Test copilot learning show and reset with --subject challenge_template."""
    # Show learning stats filtered by challenge_template
    show_res = runner.invoke(
        app,
        ["learning", "show", "--subject", "challenge_template", "--db", cli_db, "--json"],
    )
    assert show_res.exit_code == 0, show_res.output
    stats = json.loads(show_res.output)
    assert isinstance(stats, list)

    show_tab = runner.invoke(
        app,
        ["learning", "show", "--subject", "challenge_template", "--db", cli_db],
    )
    assert show_tab.exit_code == 0

    # Reset learning stats for challenge_template
    reset_res = runner.invoke(
        app,
        ["learning", "reset", "--subject", "challenge_template", "--db", cli_db],
    )
    assert reset_res.exit_code == 0, reset_res.output
    assert "Reset" in reset_res.output


# =================================================================================================
# 7. Demo Script End-to-End Test (docs/demo_script_phase4.md)
# =================================================================================================
def test_phase4_demo_script_e2e(cli_db: str):
    """
    Step through the complete Phase 4 user journey offline:
    seed -> weekly offers -> accept -> mid-week checkin -> festival exception overlap ->
    review with empirical rank -> progress (XP/badge) -> feedback -> learning update ->
    sim run comparison -> timeline audit inspection.
    """
    # 1. Weekly offers with explicit reason statement
    with get_connection(cli_db) as conn:
        off = Offer(
            id="off_demo_deliv",
            user_id="u1",
            week_start="2024-03-18",
            template_code="delivery_cap",
            difficulty="medium",
            params_json={
                "title": "Cap Food Delivery",
                "metric_code": "merchant_group_spend",
                "duration_days": 14,
                "target_value": 200000,
                "baseline_median": 350000,
            },
            rank=1,
            propensity_bp=5000,
            policy_version="v1_thompson",
            rng_seed=42,
            reason_json={
                "text": "Typical delivery spend ₹3,500; medium target ₹2,000 saves ₹1,500"
            },
            status="shown",
            created_at="2024-03-18T00:00:00Z",
        )
        insert_offer(conn, off)
        conn.commit()

    offers_res = runner.invoke(app, ["challenges", "offers", "--db", cli_db])
    assert offers_res.exit_code == 0, offers_res.output
    assert "off_demo_deliv" in offers_res.output

    # 2. Accept offer (starts experiment with frozen baseline)
    acc_res = runner.invoke(
        app,
        [
            "challenges",
            "accept",
            "off_demo_deliv",
            "--clock",
            "2024-03-18T10:00:00Z",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert acc_res.exit_code == 0, acc_res.output
    acc_data = json.loads(acc_res.output)
    exp_id = acc_data["experiment_id"]

    # 3. Mid-experiment weekly check-in
    chk_res = runner.invoke(
        app,
        [
            "experiments",
            "checkin",
            exp_id,
            "going_well",
            "--clock",
            "2024-03-25T10:00:00Z",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert chk_res.exit_code == 0, chk_res.output

    # 4. Contextual exception overlap: detector proposes extension adjustment
    with get_connection(cli_db) as conn:
        prop = AdjustmentProposal(
            id="adj_demo_extend",
            experiment_id=exp_id,
            user_id="u1",
            kind="extend",
            reason_code="contextual_exception_overlap",
            params_json={"extend_days": 7},
            status="proposed",
            created_at="2024-03-27T10:00:00Z",
        )
        insert_adjustment_proposal(conn, prop)
        conn.commit()

    adjs_res = runner.invoke(app, ["adjustments", "list", "--db", cli_db])
    assert adjs_res.exit_code == 0
    assert "adj_demo_extend" in adjs_res.output

    adj_acc = runner.invoke(
        app,
        [
            "adjustments",
            "accept",
            "adj_demo_extend",
            "--clock",
            "2024-03-27T10:00:00Z",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert adj_acc.exit_code == 0, adj_acc.output

    # 5. Review: lower than all 6 previous comparable fortnights
    with get_connection(cli_db) as conn:
        update_experiment_status(conn, "u1", exp_id, "completed", ended_at="2024-04-08T10:00:00Z")
        rev = ExperimentReview(
            id=f"rev_{exp_id}",
            user_id="u1",
            experiment_id=exp_id,
            observed_value=180000,
            outcome="beyond_usual_range",
            rank_p_bp=1428,
            effect_value=170000,
            target_met=True,
            integrity_json={
                "recategorized_count": 0,
                "late_txns_count": 0,
                "exceptions_count": 1,
                "confirmation_required": False,
            },
            data_quality_json={"imputed_txns_count": 0},
            created_at="2024-04-08T10:00:00Z",
        )
        insert_experiment_review(conn, rev)
        conn.commit()

    rev_res = runner.invoke(app, ["experiments", "review", exp_id, "--db", cli_db])
    assert rev_res.exit_code == 0, rev_res.output
    assert "BEYOND_USUAL_RANGE" in rev_res.output

    # 6. Progress: XP, Level, Badges
    prog_res = runner.invoke(app, ["progress", "--db", cli_db])
    assert prog_res.exit_code == 0, prog_res.output
    assert "Level" in prog_res.output

    # 7. Post-experiment feedback
    fb_res = runner.invoke(
        app,
        [
            "experiments",
            "feedback",
            exp_id,
            "--difficulty",
            "2",
            "--helpful",
            "--repeat",
            "--clock",
            "2024-04-08T12:00:00Z",
            "--db",
            cli_db,
            "--json",
        ],
    )
    assert fb_res.exit_code == 0, fb_res.output

    # 8. Learning update reflected in posteriors
    learn_res = runner.invoke(
        app,
        ["learning", "show", "--subject", "challenge_template", "--db", cli_db],
    )
    assert learn_res.exit_code == 0, learn_res.output

    # 9. Offline simulation run comparing policies
    sim_res = runner.invoke(
        app,
        [
            "sim",
            "run",
            "--policy",
            "thompson",
            "--persona",
            "ThriftyCook",
            "--weeks",
            "8",
            "--seed",
            "42",
            "--json",
        ],
    )
    assert sim_res.exit_code == 0, sim_res.output
    sim_data = json.loads(sim_res.output)
    assert sim_data["weeks"] == 8

    # 10. Audit timeline inspection
    tl_res = runner.invoke(app, ["timeline", "--db", cli_db])
    assert tl_res.exit_code == 0, tl_res.output
    assert "Agent Activity Timeline" in tl_res.output


def test_cli_learning_show_includes_how_payment_guesses_are_weighted(cli_db: str):
    res = runner.invoke(app, ["learning", "show", "--db", cli_db])
    assert res.exit_code == 0, res.output
    assert "payment guesses are weighted" in res.output
    rows = json.loads(
        runner.invoke(
            app, ["learning", "show", "--subject", "capture", "--db", cli_db, "--json"]
        ).output
    )
    assert {r["signal"] for r in rows} >= {"counterparty_history", "recency"}
    assert all(r["base_bp"] == r["effective_bp"] for r in rows), "nothing learned yet"
    reset = runner.invoke(app, ["learning", "reset", "--subject", "capture_signal", "--db", cli_db])
    assert reset.exit_code == 0, reset.output
