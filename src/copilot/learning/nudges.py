# ruff: noqa: E501  (SQL lines)
"""
How this person likes to be helped (PLAN_AGENTIC_V2, A10): which timing and tone of nudge they act on.

Nine arms (when: morning, evening, weekend; how: gentle, direct, numbers), each a Beta posterior kept in
`nudge_arms`. Deterministic by design: every arm is tried once, then the one with the best posterior
mean is used (ties break on a fixed order), so there is no randomness to explain. The user's own
stated style gives that tone a head start, not a guarantee. Responses move the posterior by a bounded
step; nothing here can make a nudge louder than the weekly budget allows. Resettable.
"""

from __future__ import annotations

import itertools
import sqlite3
import uuid
from datetime import datetime

from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.learning.beta import posterior_mean
from copilot.personal import profile as prof

TIMINGS = ("morning", "evening", "weekend")
TONES = ("gentle", "direct", "numbers")
ARMS = list(itertools.product(TIMINGS, TONES))
PRIOR_MILLI = 2000  # alpha = beta = 2 observations' worth
STYLE_HEAD_START_MILLI = 1000
STEP = {"acted": ("alpha", 1000), "dismissed": ("beta", 500), "not_useful": ("beta", 1000)}


def ensure_arms(conn: sqlite3.Connection, user_id: str, clock: datetime | None = None) -> None:
    style = prof.confirmed(conn, user_id, "nudge_style")
    now = to_utc_iso(now_utc(clock))
    for timing, tone in ARMS:
        alpha = PRIOR_MILLI + (STYLE_HEAD_START_MILLI if tone == style else 0)
        conn.execute(
            "INSERT OR IGNORE INTO nudge_arms (id, user_id, timing, tone, alpha_milli, beta_milli, trials, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (f"nga_{uuid.uuid4().hex[:12]}", user_id, timing, tone, alpha, PRIOR_MILLI, now),
        )


def posterior(alpha_milli: int, beta_milli: int) -> float:
    return posterior_mean(alpha_milli, beta_milli)


def table(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    ensure_arms(conn, user_id)
    rows = {
        (r["timing"], r["tone"]): r
        for r in conn.execute("SELECT * FROM nudge_arms WHERE user_id = ?", (user_id,))
    }
    return [
        {
            "timing": t, "tone": o, "trials": rows[(t, o)]["trials"],
            "p": round(posterior(rows[(t, o)]["alpha_milli"], rows[(t, o)]["beta_milli"]), 4),
        }
        for t, o in ARMS
    ]  # fmt: skip


def choose_arm(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> tuple[str, str]:
    ensure_arms(conn, user_id, clock)
    rows = {
        (r["timing"], r["tone"]): r
        for r in conn.execute("SELECT * FROM nudge_arms WHERE user_id = ?", (user_id,))
    }
    for arm in ARMS:  # try each once
        if rows[arm]["trials"] == 0:
            return arm
    return max(
        ARMS,
        key=lambda a: (posterior(rows[a]["alpha_milli"], rows[a]["beta_milli"]), -ARMS.index(a)),
    )


def record_response(
    conn: sqlite3.Connection,
    user_id: str,
    timing: str,
    tone: str,
    response: str,
    clock: datetime | None = None,
) -> None:
    ensure_arms(conn, user_id, clock)
    side, step = STEP[response]
    col = "alpha_milli" if side == "alpha" else "beta_milli"
    conn.execute(
        f"UPDATE nudge_arms SET {col} = {col} + ?, trials = trials + 1, updated_at = ?"
        " WHERE user_id = ? AND timing = ? AND tone = ?",
        (step, to_utc_iso(now_utc(clock)), user_id, timing, tone),
    )


def reset(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute("DELETE FROM nudge_arms WHERE user_id = ?", (user_id,)).rowcount
