"""
Unit tests for Stage 4.5: Adaptive Challenge Detectors (PLAN_PHASE4 Section 5.5)

Tests:
- each detector at its boundary
- two consecutive 'behind' check-ins needed (one is not enough)
- raise_target_optional never auto-applied
- auto-pause only for a declared exception and reversible
- target in force at the end used for target_met
- proposals expire
"""

import json
import uuid
from datetime import datetime

import pytest

from copilot.core.adaptive import (
    accept_adjustment,
    detect_ahead_at_midpoint,
    detect_consecutive_behind,
    detect_exception_overlap,
    detect_want_to_pause,
    expire_stale_proposals,
    reject_adjustment,
    run_adaptive_detectors,
)
from copilot.core.timeutil import IST
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import (
    get_experiment,
    insert_experiment_checkin,
    list_adjustment_proposals,
    update_experiment_status,
)
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import Experiment, ExperimentCheckin

T0 = "2026-01-01T00:00:00Z"
# Experiment window: 2026-09-01 to 2026-09-14 (14 days)
EXP_START = "2026-09-01"
EXP_END = "2026-09-14"
# Clock at day 7 (midpoint)
CLOCK_MID = datetime(2026, 9, 8, 10, 0, tzinfo=IST)
# Clock at day 12 (> 80%)
CLOCK_LATE = datetime(2026, 9, 13, 10, 0, tzinfo=IST)
# Clock well before start
CLOCK_BEFORE = datetime(2026, 8, 15, 10, 0, tzinfo=IST)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u_alice", created_at=T0))
    insert_account(c, Account(id="acc_a", user_id="u_alice", name="Checking", created_at=T0))
    insert_category(
        c, Category(id="dining_out", user_id="u_alice", name="Dining Out", created_at=T0)
    )
    yield c
    c.close()


def _make_active_experiment(conn, *, target_value: int = 100000) -> Experiment:
    """Insert a pre-built active experiment directly (bypassing baseline requirement)."""
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    conn.execute(
        """
        INSERT INTO experiments (
            id, user_id, title, template_code, hypothesis_json, metric_def_json,
            params_json, difficulty, window_start, window_end,
            baseline_json, target_value, status, origin, created_at, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exp_id,
            "u_alice",
            "Test Experiment",
            "weekday_home_cooking",
            json.dumps({"statement": "test hypothesis"}),
            json.dumps(
                {
                    "metric_code": "category_spend",
                    "direction": "lower",
                    "categories": ["dining_out"],
                    "merchants": [],
                    "weekdays_only": False,
                }
            ),
            json.dumps({"metric_code": "category_spend", "categories": ["dining_out"]}),
            "medium",
            EXP_START,
            EXP_END,
            json.dumps(
                {
                    "k": 6,
                    "window_values": [120000] * 6,
                    "median": 120000,
                    "low": 110000,
                    "high": 130000,
                    "excluded_windows": [],
                }
            ),
            target_value,
            "active",
            "user",
            T0,
            T0,
        ),
    )
    return get_experiment(conn, "u_alice", exp_id)


def _make_checkin(
    conn,
    experiment_id: str,
    checkin_date: str,
    pace_status: str,
    observed_value: int = 80000,
    user_response: str | None = None,
) -> ExperimentCheckin:
    ci = ExperimentCheckin(
        id=f"ci_{uuid.uuid4().hex[:8]}",
        user_id="u_alice",
        experiment_id=experiment_id,
        checkin_date=checkin_date,
        observed_value=observed_value,
        pace_status=pace_status,  # type: ignore
        user_response=user_response,  # type: ignore
        created_at=T0,
    )
    insert_experiment_checkin(conn, ci)
    return ci


# ===========================================================================
# 1. detect_consecutive_behind
# ===========================================================================


class TestDetectConsecutiveBehind:
    def test_one_behind_does_not_trigger(self, conn):
        """A single 'behind' check-in must NOT trigger a proposal."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == [], "One behind check-in must not trigger a proposal"

    def test_two_behind_trigger_ease_target(self, conn):
        """Two consecutive 'behind' check-ins must trigger ease_target (not late in window)."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        assert len(proposals) == 1
        assert proposals[0].kind == "ease_target"
        assert proposals[0].reason_code == "two_consecutive_behind"

    def test_two_behind_late_triggers_end_early(self, conn):
        """Two consecutive 'behind' when > 80% elapsed must suggest end_early."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        _make_checkin(conn, exp.id, "2026-09-10", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_LATE)
        assert len(proposals) == 1
        assert proposals[0].kind == "end_early"

    def test_behind_then_on_pace_does_not_trigger(self, conn):
        """behind → on_pace must NOT trigger."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "on_pace")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []

    def test_idempotent_on_open_proposal(self, conn):
        """Running detector twice does not duplicate proposals."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        p1 = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        p2 = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        assert len(p1) == 1
        assert len(p2) == 0, "Second run should not create duplicate proposal"

    def test_not_active_experiment_skipped(self, conn):
        """Paused experiment is not processed."""
        exp = _make_active_experiment(conn)
        update_experiment_status(conn, "u_alice", exp.id, "paused")
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []


# ===========================================================================
# 2. detect_want_to_pause
# ===========================================================================


class TestDetectWantToPause:
    def test_want_to_pause_response_triggers_pause(self, conn):
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-07", "on_pace", user_response="want_to_pause")
        proposals = detect_want_to_pause(conn, "u_alice", exp.id, CLOCK_MID)
        assert len(proposals) == 1
        assert proposals[0].kind == "pause"
        assert proposals[0].reason_code == "user_requested_pause"

    def test_other_responses_do_not_trigger(self, conn):
        exp = _make_active_experiment(conn)
        for resp in ("going_well", "hard", "skip"):
            _make_checkin(
                conn, exp.id, f"2026-09-0{resp.__hash__() % 7 + 1}", "on_pace", user_response=resp
            )
        # Clear and insert the last one
        conn.execute("DELETE FROM experiment_checkins WHERE experiment_id = ?", (exp.id,))
        _make_checkin(conn, exp.id, "2026-09-07", "on_pace", user_response="going_well")
        proposals = detect_want_to_pause(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []

    def test_no_checkin_does_not_trigger(self, conn):
        exp = _make_active_experiment(conn)
        assert detect_want_to_pause(conn, "u_alice", exp.id, CLOCK_MID) == []


# ===========================================================================
# 3. detect_ahead_at_midpoint
# ===========================================================================


class TestDetectAheadAtMidpoint:
    def test_ahead_wide_margin_at_mid_triggers_optional(self, conn):
        """A wide margin ahead at midpoint creates raise_target_optional proposal."""
        # Target 100000 over 14 days: by day 7 the pace is 50000. Observed 20000 is 60% under it.
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-07", "ahead", observed_value=20000)
        proposals = detect_ahead_at_midpoint(conn, "u_alice", exp.id, CLOCK_MID)
        assert len(proposals) == 1
        assert proposals[0].kind == "raise_target_optional"
        assert proposals[0].status == "proposed"  # NEVER auto-applied

    def test_ahead_narrow_margin_does_not_trigger(self, conn):
        """A narrow margin ahead (< 30%) must NOT trigger."""
        # Pace by day 7 is 50000; observed 40000 is only 20% under it (< 30%)
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-07", "ahead", observed_value=40000)
        proposals = detect_ahead_at_midpoint(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []

    def test_before_midpoint_does_not_trigger(self, conn):
        """Before the midpoint, the detector must stay silent."""
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-03", "ahead", observed_value=50000)
        # Clock at day 3 (before midpoint of 14-day window)
        clock_early = datetime(2026, 9, 4, 10, 0, tzinfo=IST)
        proposals = detect_ahead_at_midpoint(conn, "u_alice", exp.id, clock_early)
        assert proposals == []

    def test_raise_target_optional_never_auto_applied(self, conn):
        """The proposal status must be 'proposed', never auto_applied_pause."""
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-07", "ahead", observed_value=40000)
        proposals = detect_ahead_at_midpoint(conn, "u_alice", exp.id, CLOCK_MID)
        for p in proposals:
            assert p.status != "auto_applied_pause", (
                "raise_target_optional must NEVER be auto-applied"
            )


# ===========================================================================
# 4. detect_exception_overlap
# ===========================================================================


class TestDetectExceptionOverlap:
    def _insert_exception(self, conn, from_date: str, to_date: str) -> str:
        mem_id = f"mem_{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO memory_items (
                id, user_id, kind, subject_key, statement_json,
                source, status, prior_bp, user_confirmed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mem_id,
                "u_alice",
                "contextual_exception",
                f"exception:{from_date}..{to_date}",
                json.dumps({"from_date": from_date, "to_date": to_date, "reason": "festival"}),
                "user_stated",
                "active",
                10000,
                1,
                T0,
            ),
        )
        return mem_id

    def test_exception_overlap_creates_auto_pause_and_extend(self, conn):
        """Contextual exception overlapping window -> auto_applied_pause + extend proposals."""
        exp = _make_active_experiment(conn)
        # Exception covers 5 days of the window
        self._insert_exception(conn, "2026-09-02", "2026-09-06")
        proposals = detect_exception_overlap(conn, "u_alice", exp.id, CLOCK_MID)
        kinds = {p.kind for p in proposals}
        statuses = {p.status for p in proposals}
        assert "pause" in kinds
        assert "extend" in kinds
        assert "auto_applied_pause" in statuses  # auto-pause was applied

    def test_exception_overlap_reversible(self, conn):
        """Auto-pause is reversible: user can accept to acknowledge or resume the experiment."""
        exp = _make_active_experiment(conn)
        self._insert_exception(conn, "2026-09-02", "2026-09-06")
        proposals = detect_exception_overlap(conn, "u_alice", exp.id, CLOCK_MID)
        auto_pause = next(p for p in proposals if p.status == "auto_applied_pause")

        # Accepting the auto-pause proposal is how user acknowledges it
        accepted = accept_adjustment(conn, "u_alice", auto_pause.id, CLOCK_MID)
        assert accepted.status == "accepted"

    def test_no_exception_no_proposal(self, conn):
        """No exception in memory -> no proposals created."""
        exp = _make_active_experiment(conn)
        proposals = detect_exception_overlap(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []

    def test_exception_outside_window_no_proposal(self, conn):
        """Exception entirely outside the window must not trigger."""
        exp = _make_active_experiment(conn)
        # Exception is after the experiment ends
        self._insert_exception(conn, "2026-09-20", "2026-09-25")
        proposals = detect_exception_overlap(conn, "u_alice", exp.id, CLOCK_MID)
        assert proposals == []

    def test_auto_pause_is_real_and_reversible(self, conn):
        """
        The exception pause sets the covered days aside (it is the one automatic change), and
        rejecting it puts those days back.
        """
        exp = _make_active_experiment(conn)
        self._insert_exception(conn, "2026-09-02", "2026-09-06")
        proposals = detect_exception_overlap(conn, "u_alice", exp.id, CLOCK_MID)
        auto_pause = next(p for p in proposals if p.status == "auto_applied_pause")
        paused = get_experiment(conn, "u_alice", exp.id).params_json["paused_days"]
        assert paused == [f"2026-09-0{d}" for d in range(2, 7)]
        reversed_ = reject_adjustment(conn, "u_alice", auto_pause.id, CLOCK_MID)
        assert reversed_.status == "rejected"
        assert get_experiment(conn, "u_alice", exp.id).params_json["paused_days"] == []


# ===========================================================================
# 5. run_adaptive_detectors (integration)
# ===========================================================================


class TestRunAdaptiveDetectors:
    def test_run_over_multiple_active_experiments(self, conn):
        """run_adaptive_detectors runs over all active experiments."""
        exp1 = _make_active_experiment(conn)
        exp2 = _make_active_experiment(conn)
        # Give both two consecutive behind check-ins
        for eid in (exp1.id, exp2.id):
            _make_checkin(conn, eid, "2026-09-03", "behind")
            _make_checkin(conn, eid, "2026-09-07", "behind")
        proposals = run_adaptive_detectors(conn, "u_alice", clock=CLOCK_MID)
        exp_ids = {p.experiment_id for p in proposals}
        assert exp1.id in exp_ids
        assert exp2.id in exp_ids

    def test_run_filtered_to_specific_experiment(self, conn):
        """run_adaptive_detectors with experiment_id restricts to that experiment."""
        exp1 = _make_active_experiment(conn)
        exp2 = _make_active_experiment(conn)
        for eid in (exp1.id, exp2.id):
            _make_checkin(conn, eid, "2026-09-03", "behind")
            _make_checkin(conn, eid, "2026-09-07", "behind")
        proposals = run_adaptive_detectors(conn, "u_alice", experiment_id=exp1.id, clock=CLOCK_MID)
        assert all(p.experiment_id == exp1.id for p in proposals)


# ===========================================================================
# 6. Accept / Reject / Expire
# ===========================================================================


class TestAcceptRejectExpire:
    def test_accept_pause_pauses_experiment(self, conn):
        """Accepting a pause proposal transitions experiment to paused."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-07", "on_pace", user_response="want_to_pause")
        proposals = detect_want_to_pause(conn, "u_alice", exp.id, CLOCK_MID)
        pause_prop = proposals[0]
        accepted = accept_adjustment(conn, "u_alice", pause_prop.id, CLOCK_MID)
        assert accepted.status == "accepted"
        updated_exp = get_experiment(conn, "u_alice", exp.id)
        assert updated_exp.status == "paused"

    def test_reject_proposed_proposal(self, conn):
        """Rejecting a proposed proposal records 'rejected'."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        prop = proposals[0]
        rejected = reject_adjustment(conn, "u_alice", prop.id, CLOCK_MID)
        assert rejected.status == "rejected"
        # Experiment stays active
        assert get_experiment(conn, "u_alice", exp.id).status == "active"

    def test_expire_stale_proposals(self, conn):
        """Proposals older than expiry_days are expired."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        prop = proposals[0]
        # Expire with clock 15 days ahead
        clock_future = datetime(2026, 9, 23, 10, 0, tzinfo=IST)
        expired = expire_stale_proposals(conn, "u_alice", expiry_days=14, clock=clock_future)
        assert prop.id in expired
        # Check status in DB
        props = list_adjustment_proposals(conn, "u_alice")
        p = next(p for p in props if p.id == prop.id)
        assert p.status == "expired"

    def test_proposals_not_yet_old_not_expired(self, conn):
        """Proposals newer than expiry_days are NOT expired."""
        exp = _make_active_experiment(conn)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        # Only 5 days later, expiry_days=14 -> should not expire
        clock_soon = datetime(2026, 9, 13, 10, 0, tzinfo=IST)
        expired = expire_stale_proposals(conn, "u_alice", expiry_days=14, clock=clock_soon)
        assert expired == []

    def test_raise_target_optional_changes_the_target_only_when_the_user_accepts(self, conn):
        """
        Detecting a wide lead never changes the target. Only the user's own acceptance raises it,
        one level, and never below the floor of half the usual value.
        """
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-07", "ahead", observed_value=20000)
        proposals = detect_ahead_at_midpoint(conn, "u_alice", exp.id, CLOCK_MID)
        assert len(proposals) == 1
        prop = proposals[0]
        assert get_experiment(conn, "u_alice", exp.id).target_value == 100000  # nothing yet
        accepted = accept_adjustment(conn, "u_alice", prop.id, CLOCK_MID)
        assert accepted.status == "accepted"
        updated = get_experiment(conn, "u_alice", exp.id)
        assert 60000 <= updated.target_value <= 100000  # harder than before, above the floor
        assert updated.params_json["target_history"][0]["from"] == 100000

    def test_target_in_force_at_end_determines_target_met(self, conn):
        """
        The target that is in force at experiment end (not any mid-experiment
        proposal) is used to determine target_met in the review.
        This test verifies that an ease_target proposal, if not explicitly applied,
        changes the stored target_value only once the user accepts it, and only gentler.
        """
        exp = _make_active_experiment(conn, target_value=100000)
        _make_checkin(conn, exp.id, "2026-09-03", "behind")
        _make_checkin(conn, exp.id, "2026-09-07", "behind")
        proposals = detect_consecutive_behind(conn, "u_alice", exp.id, CLOCK_MID)
        # The user accepts the ease: the target moves one level gentler and never tightens
        accept_adjustment(conn, "u_alice", proposals[0].id, CLOCK_MID)
        updated = get_experiment(conn, "u_alice", exp.id)
        assert updated.target_value >= 100000
        assert updated.params_json["target_history"][0]["from"] == 100000
        assert updated.params_json["target_history"][0]["to"] == updated.target_value
