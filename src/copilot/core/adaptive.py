"""
Stage 4.5: Adaptive Challenge Detectors (PLAN_PHASE4 Section 5.5)

Detectors run daily (lazily or via runtime job) over active experiments.
Each detector inspects deterministic signals and, if triggered, creates an
AdjustmentProposal with a reason_code.  No automatic changes are made --
every proposal is opt-in except auto-pause for declared contextual exceptions
(which is still shown and reversible).

Detector                               | Proposal kind
---------------------------------------|-------------------------------
Two consecutive 'behind' check-ins     | ease_target or end_early
User check-in response want_to_pause   | pause
Pace ahead wide margin at midpoint     | raise_target_optional (never auto)
New firm commitment inside window      | ease_target
Contextual exception covers window     | auto_applied_pause + extend
"""

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from copilot.config.phase4 import load_experiments_config
from copilot.core.exception_windows import active_exceptions
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.repo_phase4 import (
    get_adjustment_proposal,
    get_experiment,
    insert_adjustment_proposal,
    list_adjustment_proposals,
    list_experiment_checkins,
    list_experiments,
    update_adjustment_status,
    update_experiment_params,
    update_experiment_status,
    update_experiment_window,
)
from copilot.models.phase4 import AdjustmentProposal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_dt(clock: datetime | None) -> datetime:
    return clock or datetime.now(tz=IST)


def _today(clock: datetime | None) -> date:
    return _now_dt(clock).astimezone(IST).date()


def _to_utc(dt: datetime) -> str:
    return to_utc_iso(dt)


def _has_open_proposal(
    conn: sqlite3.Connection, user_id: str, experiment_id: str, kind: str
) -> bool:
    """Return True if a 'proposed' or 'auto_applied_pause' proposal of the given kind exists."""
    props = list_adjustment_proposals(conn, user_id, experiment_id=experiment_id)
    return any(p.kind == kind and p.status in ("proposed", "auto_applied_pause") for p in props)


def _make_proposal(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    kind: str,
    reason_code: str,
    params_json: dict[str, Any],
    clock: datetime | None,
    status: str = "proposed",
) -> AdjustmentProposal:
    """Create and persist an AdjustmentProposal."""
    now_dt = _now_dt(clock)
    prop = AdjustmentProposal(
        id=f"adj_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        experiment_id=experiment_id,
        kind=kind,  # type: ignore[arg-type]
        reason_code=reason_code,
        params_json=params_json,
        status=status,  # type: ignore[arg-type]
        created_at=_to_utc(now_dt),
        decided_at=None,
    )
    insert_adjustment_proposal(conn, prop)
    return prop


# ---------------------------------------------------------------------------
# 1. Detector: two consecutive "behind" check-ins
# ---------------------------------------------------------------------------


def detect_consecutive_behind(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """
    If the two most recent check-ins both have pace_status='behind', propose
    ease_target (or end_early if beyond 80% of window elapsed).

    ONE 'behind' alone does NOT trigger -- boundary tested in Stage 4.5 tests.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None or exp.status != "active":
        return []

    checkins = list_experiment_checkins(conn, user_id, experiment_id=experiment_id)
    if len(checkins) < 2:
        return []

    sorted_cis = sorted(checkins, key=lambda c: c.checkin_date, reverse=True)
    last_two = sorted_cis[:2]
    if not all(c.pace_status == "behind" for c in last_two):
        return []

    today = _today(clock)
    w_start = date.fromisoformat(exp.window_start)
    w_end = date.fromisoformat(exp.window_end)
    total_days = (w_end - w_start).days + 1
    elapsed = (today - w_start).days

    proposals: list[AdjustmentProposal] = []

    if total_days > 0 and elapsed > 0 and elapsed / total_days > 0.80:
        if not _has_open_proposal(conn, user_id, experiment_id, "end_early"):
            proposals.append(
                _make_proposal(
                    conn,
                    user_id,
                    experiment_id,
                    kind="end_early",
                    reason_code="two_consecutive_behind_late",
                    params_json={
                        "message": (
                            "Pace has been behind for two check-ins and the window is nearly over."
                        )
                    },
                    clock=clock,
                )
            )
    else:
        if not _has_open_proposal(conn, user_id, experiment_id, "ease_target"):
            proposals.append(
                _make_proposal(
                    conn,
                    user_id,
                    experiment_id,
                    kind="ease_target",
                    reason_code="two_consecutive_behind",
                    params_json={"message": "Pace has been behind for two consecutive check-ins."},
                    clock=clock,
                )
            )

    return proposals


# ---------------------------------------------------------------------------
# 2. Detector: user responded "want_to_pause"
# ---------------------------------------------------------------------------


def detect_want_to_pause(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """If the most recent check-in has user_response='want_to_pause', create a pause proposal."""
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None or exp.status != "active":
        return []

    checkins = list_experiment_checkins(conn, user_id, experiment_id=experiment_id)
    if not checkins:
        return []

    latest = max(checkins, key=lambda c: c.checkin_date)
    if latest.user_response != "want_to_pause":
        return []

    if _has_open_proposal(conn, user_id, experiment_id, "pause"):
        return []

    return [
        _make_proposal(
            conn,
            user_id,
            experiment_id,
            kind="pause",
            reason_code="user_requested_pause",
            params_json={"message": "You indicated in your check-in that you would like to pause."},
            clock=clock,
        )
    ]


# ---------------------------------------------------------------------------
# 3. Detector: pace ahead wide margin at midpoint (raise_target_optional -- NEVER auto)
# ---------------------------------------------------------------------------

_WIDE_MARGIN_BP = 3000  # 30% ahead of pace = wide margin


def detect_ahead_at_midpoint(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """
    If the halfway check-in shows pace='ahead' by a wide margin (>= 30%),
    offer raise_target_optional.  This proposal is NEVER auto-applied.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None or exp.status != "active":
        return []

    today = _today(clock)
    w_start = date.fromisoformat(exp.window_start)
    w_end = date.fromisoformat(exp.window_end)
    total_days = (w_end - w_start).days + 1
    elapsed = (today - w_start).days

    if elapsed < total_days // 2:
        return []

    checkins = list_experiment_checkins(conn, user_id, experiment_id=experiment_id)
    if not checkins:
        return []

    latest = max(checkins, key=lambda c: c.checkin_date)
    if latest.pace_status != "ahead":
        return []

    direction = exp.metric_def_json.get("direction", "lower")
    # Pace expected by the day of that check-in. Comparing with the whole-window target would
    # call anyone who is merely on pace at the halfway point "far ahead".
    elapsed_at_checkin = (date.fromisoformat(latest.checkin_date) - w_start).days + 1
    expected = (exp.target_value * elapsed_at_checkin * 2 + total_days) // (2 * total_days)
    obs = latest.observed_value

    if expected <= 0:
        margin_bp = 0
    elif direction == "lower":
        margin_bp = ((expected - obs) * 10000) // expected
    else:
        margin_bp = ((obs - expected) * 10000) // expected

    if margin_bp < _WIDE_MARGIN_BP:
        return []

    if _has_open_proposal(conn, user_id, experiment_id, "raise_target_optional"):
        return []

    return [
        _make_proposal(
            conn,
            user_id,
            experiment_id,
            kind="raise_target_optional",
            reason_code="ahead_at_midpoint_wide_margin",
            params_json={
                "message": (
                    "You are noticeably ahead of pace at the halfway point. "
                    "If you would like, you may raise your target -- this is entirely optional."
                ),
                "margin_bp": margin_bp,
            },
            clock=clock,
        )
    ]


# ---------------------------------------------------------------------------
# 4. Detector: new firm commitment inside window
# ---------------------------------------------------------------------------


def detect_new_commitment(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """
    If a new firm commitment was added after the experiment started and its
    due_date falls inside the experiment window, propose ease_target.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None or exp.status != "active":
        return []

    if exp.started_at is None:
        return []

    try:
        rows = conn.execute(
            """
            SELECT id, name, due_date, amount_paise
            FROM commitments
            WHERE user_id = ? AND created_at >= ? AND due_date >= ? AND due_date <= ?
              AND status = 'active'
            """,
            (user_id, exp.started_at, exp.window_start, exp.window_end),
        ).fetchall()
    except Exception:
        return []

    if not rows:
        return []

    if _has_open_proposal(conn, user_id, experiment_id, "ease_target"):
        return []

    total_amount = sum(r["amount_paise"] for r in rows)
    names = ", ".join(r["name"] for r in rows)

    return [
        _make_proposal(
            conn,
            user_id,
            experiment_id,
            kind="ease_target",
            reason_code="new_commitment_in_window",
            params_json={
                "message": (
                    f"New commitment(s) ({names}) totalling "
                    f"Rs {total_amount // 100} fall within the experiment window."
                ),
                "commitment_ids": [r["id"] for r in rows],
                "total_amount_paise": total_amount,
            },
            clock=clock,
        )
    ]


# ---------------------------------------------------------------------------
# 5. Detector: contextual exception overlaps experiment window
# ---------------------------------------------------------------------------


def detect_exception_overlap(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """
    If a declared contextual exception (memory_items.kind='contextual_exception')
    overlaps the active experiment window, create:
    1. An 'auto_applied_pause' proposal (immediately shown, reversible).
    2. An 'extend' proposal to compensate the overlap days.
    """
    exp = get_experiment(conn, user_id, experiment_id)
    if exp is None or exp.status != "active":
        return []

    proposals: list[AdjustmentProposal] = []

    w_start = date.fromisoformat(exp.window_start)
    w_end = date.fromisoformat(exp.window_end)

    # Exceptions that apply to this experiment's categories, as day ranges (a month-level
    # exception from the memory observers covers every day of that month).
    covered: set[date] = set()
    exception_ids: list[str] = []
    categories = (exp.metric_def_json or {}).get("categories", [])
    for mem_id, ex_from, ex_to, _reason in active_exceptions(conn, user_id, categories):
        overlap_start = max(ex_from, w_start)
        overlap_end = min(ex_to, w_end)
        if overlap_end >= overlap_start:
            covered.update(
                overlap_start + timedelta(days=i)
                for i in range((overlap_end - overlap_start).days + 1)
            )
            exception_ids.append(mem_id)
    overlap_days = len(covered)  # a day covered by two exceptions counts once
    if overlap_days:
        # The pause itself: those days stop counting toward the measurement. It is shown to the
        # user as an auto-applied proposal, which they can reverse.
        params = dict(exp.params_json or {})
        already = set(params.get("paused_days", []))
        params["paused_days"] = sorted(already | {d.isoformat() for d in covered})
        update_experiment_params(conn, user_id, experiment_id, params)

    if overlap_days <= 0:
        return []

    # 5a. Auto-pause
    if not _has_open_proposal(conn, user_id, experiment_id, "pause"):
        proposals.append(
            _make_proposal(
                conn,
                user_id,
                experiment_id,
                kind="pause",
                reason_code="exception_overlap_auto_pause",
                params_json={
                    "message": (
                        f"A contextual exception covers {overlap_days} day(s) of your "
                        "experiment window. The experiment has been paused for that period."
                    ),
                    "overlap_days": overlap_days,
                    "exception_ids": exception_ids,
                    "covered_days": sorted(d.isoformat() for d in covered),
                },
                clock=clock,
                status="auto_applied_pause",
            )
        )

    # 5b. Extend proposal
    if not _has_open_proposal(conn, user_id, experiment_id, "extend"):
        new_end = w_end + timedelta(days=overlap_days)
        proposals.append(
            _make_proposal(
                conn,
                user_id,
                experiment_id,
                kind="extend",
                reason_code="exception_overlap_extend",
                params_json={
                    "message": (
                        f"Your window can be extended by {overlap_days} day(s) to "
                        f"{new_end.isoformat()} to compensate for the exception."
                    ),
                    "extend_days": overlap_days,
                    "proposed_new_end": new_end.isoformat(),
                },
                clock=clock,
            )
        )

    return proposals


# ---------------------------------------------------------------------------
# 6. Main runner
# ---------------------------------------------------------------------------


def run_adaptive_detectors(
    conn: sqlite3.Connection,
    user_id: str,
    experiment_id: str | None = None,
    clock: datetime | None = None,
) -> list[AdjustmentProposal]:
    """
    Run all adaptive detectors for a user's active experiments.
    If experiment_id is given, restrict to that experiment.
    Returns all new AdjustmentProposal rows created in this run.
    """
    if experiment_id:
        targets = [
            e for e in list_experiments(conn, user_id, status="active") if e.id == experiment_id
        ]
    else:
        targets = list_experiments(conn, user_id, status="active")

    all_proposals: list[AdjustmentProposal] = []
    for exp in targets:
        all_proposals.extend(detect_consecutive_behind(conn, user_id, exp.id, clock))
        all_proposals.extend(detect_want_to_pause(conn, user_id, exp.id, clock))
        all_proposals.extend(detect_ahead_at_midpoint(conn, user_id, exp.id, clock))
        all_proposals.extend(detect_new_commitment(conn, user_id, exp.id, clock))
        all_proposals.extend(detect_exception_overlap(conn, user_id, exp.id, clock))

    return all_proposals


# ---------------------------------------------------------------------------
# 7. Accept / Reject / Expire tools
# ---------------------------------------------------------------------------


def _apply_ease_target(
    conn: sqlite3.Connection, user_id: str, prop: AdjustmentProposal, now_iso: str
) -> None:
    """
    Accepting an ease: the target moves to one difficulty level gentler. It never tightens, and
    the judge at the end is the target in force then (PLAN_PHASE4 section 5.5).
    """
    exp = get_experiment(conn, user_id, prop.experiment_id)
    if exp is None or exp.status not in ("active", "paused"):
        return
    cfg = load_experiments_config()
    order = ["hard", "medium", "easy"]
    current = exp.difficulty if exp.difficulty in order else "medium"
    easier = order[min(order.index(current) + 1, len(order) - 1)]
    direction = exp.metric_def_json.get("direction", "lower")
    base = exp.baseline_json or {}
    if direction == "lower" and base.get("median"):
        share_bp = cfg.difficulties[easier].reduction_share_bp
        raw = base["median"] - base["median"] * share_bp // 10000
        step = cfg.target_round_paise
        floor = base["median"] * cfg.min_target_share_bp // 10000
        new_target = max((raw + step // 2) // step * step, floor)
        eased = max(new_target, exp.target_value)  # never tighter than it is now
    elif direction == "lower":
        eased = exp.target_value + exp.target_value // 10
    else:
        eased = exp.target_value - exp.target_value // 10
    params = dict(exp.params_json or {})
    history = list(params.get("target_history", []))
    history.append({"from": exp.target_value, "to": eased, "at": now_iso, "proposal": prop.id})
    params["target_history"] = history
    update_experiment_params(conn, user_id, exp.id, params)
    update_experiment_window(conn, user_id, exp.id, exp.window_end, target_value=eased)
    if easier != current:
        conn.execute(
            "UPDATE experiments SET difficulty = ? WHERE user_id = ? AND id = ?",
            (easier, user_id, exp.id),
        )


def _apply_extension(
    conn: sqlite3.Connection, user_id: str, prop: AdjustmentProposal, now_iso: str
) -> None:
    """Accepting an extension moves the window end later, within the longest allowed duration."""
    exp = get_experiment(conn, user_id, prop.experiment_id)
    if exp is None or exp.status not in ("active", "paused"):
        return
    cfg = load_experiments_config()
    start = date.fromisoformat(exp.window_start)
    end = date.fromisoformat(exp.window_end)
    wanted = int(prop.params_json.get("extend_days", 0))
    room = max(0, cfg.duration_days_max - ((end - start).days + 1))
    days = min(wanted, room)
    if days <= 0:
        return
    params = dict(exp.params_json or {})
    extensions = list(params.get("extensions", []))
    extensions.append({"days": days, "at": now_iso, "proposal": prop.id})
    params["extensions"] = extensions
    update_experiment_params(conn, user_id, exp.id, params)
    update_experiment_window(conn, user_id, exp.id, (end + timedelta(days=days)).isoformat())


def _apply_raise_target(
    conn: sqlite3.Connection, user_id: str, prop: AdjustmentProposal, now_iso: str
) -> None:
    """
    The user chose to raise the target one level. Never automatic; only on acceptance.
    The target stays at or above the floor and is never made gentler by this.
    """
    exp = get_experiment(conn, user_id, prop.experiment_id)
    if exp is None or exp.status not in ("active", "paused"):
        return
    base = exp.baseline_json or {}
    if exp.metric_def_json.get("direction", "lower") != "lower" or not base.get("median"):
        return  # nothing sensible to compute without a baseline; leave the target alone
    cfg = load_experiments_config()
    order = ["easy", "medium", "hard"]
    current = exp.difficulty if exp.difficulty in order else "medium"
    harder = order[min(order.index(current) + 1, len(order) - 1)]
    share_bp = cfg.difficulties[harder].reduction_share_bp
    step = cfg.target_round_paise
    raw = base["median"] - base["median"] * share_bp // 10000
    floor = base["median"] * cfg.min_target_share_bp // 10000
    raised = min(max((raw + step // 2) // step * step, floor), exp.target_value)
    params = dict(exp.params_json or {})
    history = list(params.get("target_history", []))
    history.append({"from": exp.target_value, "to": raised, "at": now_iso, "proposal": prop.id})
    params["target_history"] = history
    update_experiment_params(conn, user_id, exp.id, params)
    update_experiment_window(conn, user_id, exp.id, exp.window_end, target_value=raised)
    if harder != current:
        conn.execute(
            "UPDATE experiments SET difficulty = ? WHERE user_id = ? AND id = ?",
            (harder, user_id, exp.id),
        )


def accept_adjustment(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_id: str,
    clock: datetime | None = None,
) -> AdjustmentProposal:
    """
    User accepts an adjustment proposal.  Side effects:
    - pause    -> experiment transitions to paused
    - resume   -> experiment transitions to active
    - end_early -> experiment transitions to completed
    - ease_target / raise_target_optional / extend -> recorded only

    'raise_target_optional' is NEVER auto-applied even here.
    """
    prop = get_adjustment_proposal(conn, user_id, proposal_id)
    if prop is None:
        raise ValueError(f"Adjustment proposal not found: {proposal_id}")
    if prop.status not in ("proposed", "auto_applied_pause"):
        raise ValueError(f"Cannot accept proposal in status: {prop.status}")

    now_dt = _now_dt(clock)
    now_iso = _to_utc(now_dt)
    update_adjustment_status(conn, user_id, proposal_id, "accepted", now_iso)

    if prop.kind == "pause":
        try:
            exp = get_experiment(conn, user_id, prop.experiment_id)
            if exp and exp.status == "active":
                update_experiment_status(conn, user_id, prop.experiment_id, "paused")
        except Exception:
            pass

    elif prop.kind == "resume":
        try:
            exp = get_experiment(conn, user_id, prop.experiment_id)
            if exp and exp.status == "paused":
                update_experiment_status(conn, user_id, prop.experiment_id, "active")
        except Exception:
            pass

    elif prop.kind == "end_early":
        try:
            exp = get_experiment(conn, user_id, prop.experiment_id)
            if exp and exp.status == "active":
                update_experiment_status(
                    conn, user_id, prop.experiment_id, "completed", ended_at=now_iso
                )
        except Exception:
            pass

    elif prop.kind == "ease_target":
        _apply_ease_target(conn, user_id, prop, now_iso)

    elif prop.kind == "extend":
        _apply_extension(conn, user_id, prop, now_iso)

    elif prop.kind == "raise_target_optional":
        _apply_raise_target(conn, user_id, prop, now_iso)

    updated = get_adjustment_proposal(conn, user_id, proposal_id)
    assert updated is not None
    return updated


def reject_adjustment(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_id: str,
    clock: datetime | None = None,
) -> AdjustmentProposal:
    """
    User rejects an adjustment proposal.
    An auto-applied exception pause can be rejected too: that reverses it.
    """
    prop = get_adjustment_proposal(conn, user_id, proposal_id)
    if prop is None:
        raise ValueError(f"Adjustment proposal not found: {proposal_id}")
    if prop.status not in ("proposed", "auto_applied_pause"):
        raise ValueError(f"Cannot reject proposal in status: {prop.status}")

    now_dt = _now_dt(clock)
    if prop.status == "auto_applied_pause":
        # The one automatic change is reversible: those days count toward the measurement again
        exp = get_experiment(conn, user_id, prop.experiment_id)
        if exp is not None:
            params = dict(exp.params_json or {})
            covered = set(prop.params_json.get("covered_days", []))
            params["paused_days"] = sorted(set(params.get("paused_days", [])) - covered)
            update_experiment_params(conn, user_id, exp.id, params)
    update_adjustment_status(conn, user_id, proposal_id, "rejected", _to_utc(now_dt))

    updated = get_adjustment_proposal(conn, user_id, proposal_id)
    assert updated is not None
    return updated


def expire_stale_proposals(
    conn: sqlite3.Connection,
    user_id: str,
    expiry_days: int = 14,
    clock: datetime | None = None,
) -> list[str]:
    """
    Expire proposals that are still 'proposed' and older than expiry_days.
    Returns list of expired proposal IDs.
    """
    cutoff = _now_dt(clock) - timedelta(days=expiry_days)
    cutoff_iso = _to_utc(cutoff)
    now_iso = _to_utc(_now_dt(clock))

    rows = conn.execute(
        """
        SELECT id FROM adjustment_proposals
        WHERE user_id = ? AND status = 'proposed' AND created_at <= ?
        """,
        (user_id, cutoff_iso),
    ).fetchall()

    expired_ids: list[str] = []
    for row in rows:
        pid = row[0]
        update_adjustment_status(conn, user_id, pid, "expired", now_iso)
        expired_ids.append(pid)

    return expired_ids
