# ruff: noqa: E501  (SQL and prose lines)
"""
The check-in agent (PLAN_AGENTIC_V2, A11): observe, hypothesise, verify, propose, learn.

1. **Observe** signals from the user's own money: a category heading over its limit, a renewal coming
   up, a goal needing more than the surplus, an unusual payment, a cash-flow shortfall.
2. **Hypothesise** the one that matters most to *this* person (their priorities boost a signal).
3. **Verify** by recomputing its figures along a different path than the one that raised it. A signal
   that does not survive is dropped, kept in `checkin_drops`, and never shown.
4. **Propose** one insight and at most one suggestion, written from templates, and check every number in
   the text against the figures that came from the checks (`claim_check`). A message with a number
   nobody computed is not sent. An optional rewording step (a model) is held to the same check.
5. **Learn** from the reply through the nudge learner.

It speaks at most `weekly_budget` times in seven days, never in quiet hours, and only in the timing
window of the arm it chose. It reads and writes nothing about money except its own message.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from copilot.agents.kernel import Agent, run_agent
from copilot.audit.events import Actor, record_event
from copilot.capture.policy import in_quiet_hours
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import IST, month_bounds, now_utc, to_utc_iso
from copilot.config.capture import load_capture_config
from copilot.db.repo import list_goals, list_transactions
from copilot.domain.goals import monthly_surplus_estimate, required_monthly_paise
from copilot.learning import nudges
from copilot.personal import budget as bc
from copilot.personal import profile as prof
from copilot.verify.claims import NUMBER as _NUMBER  # noqa: F401  (kept for older callers)
from copilot.verify.claims import claim_check, numbers_in  # noqa: F401

CONFIG = Path(__file__).resolve().parents[3] / "config" / "checkin.yaml"


class CheckinConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekly_budget: int
    windows: dict[str, list[int]]
    subscription_lead_days: int
    min_overrun_paise: int
    shortfall_horizon_days: int
    min_history_months: int
    unusual_days: int
    priority_boost_pct: int


@lru_cache(maxsize=1)
def load_checkin_config(path: Path | None = None) -> CheckinConfig:
    return CheckinConfig.model_validate(yaml.safe_load((path or CONFIG).read_text("utf-8")))


@dataclass
class Signal:
    kind: str
    key: str
    severity_paise: int
    category_id: str | None
    figures: dict[str, Any]  # name -> display string, or int; every number the text may use
    options: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


# ---- observing ------------------------------------------------------------------------------------------
def _names(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    }


def _pace_signals(conn, user_id, clock, cfg) -> list[Signal]:
    names = _names(conn, user_id)
    out = []
    for r in bc.replan_options(conn, user_id, clock):
        if r.overrun_paise < cfg.min_overrun_paise:
            continue
        name = names.get(r.category_id, r.category_id)
        figures = {
            "category": name, "over": bc.rupees(r.overrun_paise), "projected": bc.rupees(r.projected_paise),
            "limit": bc.rupees(r.limit_paise),
        }  # fmt: skip
        out.append(Signal("pace_overrun", r.category_id, r.overrun_paise, r.category_id, figures,
                          [o.text for o in r.options],
                          {"overrun": r.overrun_paise, "limit": r.limit_paise}))  # fmt: skip
    return out


def _renewal_signals(conn, user_id, clock, cfg) -> list[Signal]:
    now = now_utc(clock)
    out = []
    for r in conn.execute(
        "SELECT * FROM recurring_series WHERE user_id = ? AND kind = 'subscription'", (user_id,)
    ):
        due = datetime.fromisoformat(r["next_expected"].replace("Z", "+00:00"))
        days = (due - now).days
        if 0 <= days <= cfg.subscription_lead_days:
            figures = {"name": r["merchant_normalized"].title(), "amount": bc.rupees(r["typical_amount_paise"]),
                       "days": days}  # fmt: skip
            out.append(Signal("renewal", r["id"], r["typical_amount_paise"], None, figures,
                              ["Mark it as unused if you no longer need it."], {"series": r["id"]}))  # fmt: skip
    return out


def _goal_signals(conn, user_id, clock, cfg) -> tuple[list[Signal], list[tuple[str, str]]]:
    today = now_utc(clock).astimezone(IST).date()
    est = monthly_surplus_estimate(conn, user_id, today)
    drops: list[tuple[str, str]] = []
    if est.status != "ok":
        return [], [("goal_drift", "not enough history to say what you can set aside")]
    out = []
    for g in list_goals(conn, user_id, "active"):
        need = required_monthly_paise(g, today) or 0
        if need > (est.expected_paise or 0) > 0 or (need > 0 and (est.expected_paise or 0) <= 0):
            usual = max(0, est.expected_paise or 0)
            gap = need - usual
            figures = {"goal": g.name, "needed": bc.rupees(need), "gap": bc.rupees(gap)}
            if usual:
                figures["usual"] = bc.rupees(usual)
            detail = {"goal": g.id, "need": need, "none": usual == 0}
            out.append(Signal("goal_drift", g.id, gap, None, figures, [], detail))
    return out, drops


def _unusual_signals(conn, user_id, clock, cfg) -> list[Signal]:
    since = to_utc_iso(now_utc(clock) - timedelta(days=cfg.unusual_days))
    out = []
    for r in conn.execute(
        "SELECT a.id, a.txn_id, t.amount_paise, t.merchant_normalized FROM anomalies a"
        " JOIN transactions t ON t.id = a.txn_id WHERE a.user_id = ? AND a.status = 'open' AND a.created_at >= ?",
        (user_id, since),
    ):
        figures = {
            "merchant": (r["merchant_normalized"] or "a payment").title(),
            "amount": bc.rupees(abs(r["amount_paise"])),
        }
        out.append(
            Signal(
                "unusual_payment",
                r["id"],
                abs(r["amount_paise"]),
                None,
                figures,
                [],
                {"txn": r["txn_id"]},
            )
        )
    return out


def _balance(conn: sqlite3.Connection, user_id: str) -> int:
    opening = conn.execute(
        "SELECT COALESCE(SUM(opening_balance_paise), 0) FROM accounts WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    moved = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE user_id = ? AND is_duplicate_of IS NULL",
        (user_id,),
    ).fetchone()[0]
    return opening - moved  # debits are stored positive, credits negative


def _history_months(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(DISTINCT substr(occurred_at, 1, 7)) FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]


def _cashflow(conn, user_id, clock, cfg) -> tuple[Signal | None, str | None]:
    """A forward look at the next weeks: the balance, what is expected in, what is due, a range for the rest."""
    if _history_months(conn, user_id) < cfg.min_history_months:
        return None, "not enough history to forecast cash flow"
    now = now_utc(clock).astimezone(IST)
    horizon = now.date() + timedelta(days=cfg.shortfall_horizon_days)
    values = prof.get_profile(conn, user_id).values
    income = values.get("income") or {}
    inflow = 0
    if income.get("kind") == "monthly" and income.get("day_of_month"):
        d = now.date()
        while d <= horizon:
            if d.day == income["day_of_month"] and d >= now.date():
                inflow += income["expected_paise"]
            d += timedelta(days=1)
    due = 0
    for r in conn.execute(
        "SELECT typical_amount_paise, next_expected FROM recurring_series WHERE user_id = ? AND kind IN ('bill', 'subscription')",
        (user_id,),
    ):
        nd = (
            datetime.fromisoformat(r["next_expected"].replace("Z", "+00:00")).astimezone(IST).date()
        )
        if now.date() <= nd <= horizon:
            due += r["typical_amount_paise"]
    start30 = to_utc_iso(now_utc(clock) - timedelta(days=30))
    spent30 = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE user_id = ? AND direction = 'debit'"
        " AND excluded_from_spend = 0 AND is_duplicate_of IS NULL AND occurred_at >= ?",
        (user_id, start30),
    ).fetchone()[0]
    days = cfg.shortfall_horizon_days
    base = spent30 * days // 30
    bal = _balance(conn, user_id)
    expected = bal + inflow - due - base
    low = bal + inflow - due - base * 120 // 100
    high = bal + inflow - due - base * 80 // 100
    if low >= 0:
        return None, None
    figures = {"days": days, "balance": bc.rupees(bal), "low": bc.rupees(abs(low)), "high": bc.rupees(abs(min(0, high))),
               "due": bc.rupees(due)}  # fmt: skip
    return Signal(
        "cashflow_shortfall",
        "cf",
        abs(low),
        None,
        figures,
        [],
        {"balance": bal, "inflow": inflow, "due": due, "base": base, "expected": expected},
    ), None


def observe(conn, user_id, clock=None) -> tuple[list[Signal], list[tuple[str, str]]]:
    cfg = load_checkin_config()
    signals: list[Signal] = []
    drops: list[tuple[str, str]] = []
    signals += _pace_signals(conn, user_id, clock, cfg)
    signals += _renewal_signals(conn, user_id, clock, cfg)
    goal, gdrops = _goal_signals(conn, user_id, clock, cfg)
    signals += goal
    drops += gdrops
    signals += _unusual_signals(conn, user_id, clock, cfg)
    cf, why = _cashflow(conn, user_id, clock, cfg)
    if cf:
        signals.append(cf)
    if why:
        drops.append(("cashflow_shortfall", why))
    return signals, drops


# ---- verifying ----------------------------------------------------------------------------------------------
def verify(
    conn: sqlite3.Connection, user_id: str, s: Signal, clock: datetime | None = None
) -> tuple[bool, str]:
    """Recompute the signal's key figure along a different path. True only if it holds."""
    now = now_utc(clock).astimezone(IST)
    d = now.date()
    if s.kind == "pace_overrun":
        start, end = month_bounds(d.year, d.month)
        txs = [t for t in list_transactions(conn, user_id, start, end)
               if t.category_id == s.category_id and t.direction == "debit" and not t.excluded_from_spend and not t.is_duplicate_of]  # fmt: skip
        dim = calendar.monthrange(d.year, d.month)[1]
        projected = sum(t.amount_paise for t in txs) * dim // max(1, d.day)
        over = projected - s.detail["limit"]
        return (over == s.detail["overrun"], f"recomputed overrun {over}")
    if s.kind == "renewal":
        r = conn.execute(
            "SELECT * FROM recurring_series WHERE user_id = ? AND id = ?",
            (user_id, s.detail["series"]),
        ).fetchone()
        if r is None:
            return False, "the regular payment no longer exists"
        paid_since = conn.execute(
            "SELECT 1 FROM transactions WHERE user_id = ? AND merchant_normalized = ? AND occurred_at > ? LIMIT 1",
            (user_id, r["merchant_normalized"], r["last_seen"]),
        ).fetchone()
        return (paid_since is None, "already paid since" if paid_since else "not yet paid")
    if s.kind == "goal_drift":
        g = next((g for g in list_goals(conn, user_id, "active") if g.id == s.detail["goal"]), None)
        if g is None:
            return False, "the goal is no longer active"
        return ((required_monthly_paise(g, d) or 0) == s.detail["need"], "recomputed monthly need")
    if s.kind == "unusual_payment":
        row = conn.execute(
            "SELECT 1 FROM anomalies WHERE user_id = ? AND id = ? AND status = 'open'",
            (user_id, s.key),
        ).fetchone()
        return (row is not None, "still open" if row else "no longer open")
    if s.kind == "cashflow_shortfall":
        cfg = load_checkin_config()
        again, why = _cashflow(conn, user_id, clock, cfg)
        return (
            again is not None and again.severity_paise == s.severity_paise,
            why or "recomputed forecast",
        )
    return False, "unknown signal"


# ---- writing --------------------------------------------------------------------------------------------------
TEMPLATES: dict[str, dict[str, str]] = {
    "pace_overrun": {
        "gentle": "A gentle heads-up: {category} is heading about {over} over its {limit} limit this month.",
        "direct": "{category} is on track to finish {over} over budget ({projected} against {limit}).",
        "numbers": "{category}: projected {projected}, limit {limit}, over by {over}.",
    },
    "renewal": {
        "gentle": "{name} renews in {days} days for {amount}. Worth a thought if you still use it.",
        "direct": "{name} renews in {days} days: {amount}.",
        "numbers": "{name}: {amount} in {days} days.",
    },
    "goal_drift": {
        "gentle": "{goal} needs {needed} a month, and you usually set aside about {usual}. A small nudge could close the {gap} gap.",
        "direct": "{goal} needs {needed} a month; your usual is {usual}. Gap: {gap}.",
        "numbers": "{goal}: needs {needed}, usual {usual}, gap {gap}.",
    },
    "goal_drift_none": {
        "gentle": "{goal} needs {needed} a month, and a usual month leaves nothing spare yet. Even a small amount set aside would start closing the gap.",
        "direct": "{goal} needs {needed} a month; a usual month leaves nothing spare.",
        "numbers": "{goal}: needs {needed} a month, nothing spare in a usual month.",
    },
    "unusual_payment": {
        "gentle": "One payment looked unusual: {merchant}, {amount}. Was that you?",
        "direct": "Unusual payment: {merchant}, {amount}. Check it.",
        "numbers": "{merchant}: {amount}, flagged unusual.",
    },
    "cashflow_shortfall": {
        "gentle": "Looking {days} days ahead, money could run short by about {high} to {low}, after bills of {due}.",
        "direct": "Cash may run short within {days} days: between {high} and {low} short.",
        "numbers": "{days}-day outlook: balance {balance}, bills {due}, short by {high} to {low}.",
    },
}
HEADLINES = {
    "pace_overrun": "A category is heading over", "renewal": "A renewal is coming",
    "goal_drift": "A goal needs a nudge", "unusual_payment": "An unusual payment",
    "cashflow_shortfall": "Cash may run short",
}  # fmt: skip


class Checkin(BaseModel):
    id: str
    signal: str
    headline: str
    body: str
    options: list[str]
    status: str
    timing: str | None
    tone: str | None
    created_at: str


@dataclass
class Outcome:
    checkin: Checkin | None
    reason: str
    dropped: list[tuple[str, str]] = field(default_factory=list)


def _in_window(arm_timing: str, local: datetime, cfg: CheckinConfig) -> bool:
    lo, hi = cfg.windows[arm_timing]
    if arm_timing == "weekend" and local.weekday() < 5:
        return False
    return lo <= local.hour < hi


class CheckinAgent(Agent[Signal]):
    """The weekly check-in on the agent kernel: observe, rank, verify, propose, commit."""

    name = "checkin"
    nothing_outcome = "nothing_worth_saying"
    done_outcome = "sent"

    def __init__(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        *,
        actor: Actor,
        run_id: str | None,
        clock: datetime | None,
        ignore_timing: bool,
        reword: Callable[[str], str] | None,
    ) -> None:
        self.conn, self.user_id, self.actor, self.run_id = conn, user_id, actor, run_id
        self.clock, self.ignore_timing, self.reword = clock, ignore_timing, reword
        self.cfg = load_checkin_config()
        self.now = now_utc(clock)
        self.week_ago = to_utc_iso(self.now - timedelta(days=7))
        self.timing = self.tone = ""

    # -- when to speak at all
    def precheck(self) -> str | None:
        local = self.now.astimezone(IST)
        q = load_capture_config().prompts.quiet_hours
        if in_quiet_hours(local, q.start, q.end):
            return "quiet_hours"
        sent = self.conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE user_id = ? AND created_at >= ?",
            (self.user_id, self.week_ago),
        ).fetchone()[0]
        if sent >= self.cfg.weekly_budget:
            return "weekly_budget"
        self.timing, self.tone = nudges.choose_arm(self.conn, self.user_id, self.clock)
        if not self.ignore_timing and not _in_window(self.timing, local, self.cfg):
            return "not_the_time"
        return None

    # -- what might be worth saying
    def perceive(self) -> tuple[list[Signal], list[tuple[str, str]]]:
        return observe(self.conn, self.user_id, self.clock)

    def rank(self, candidates: list[Signal]) -> list[Signal]:
        priorities = prof.confirmed(self.conn, self.user_id, "priorities", [])

        def score(s: Signal) -> int:
            mine = s.category_id and s.category_id in priorities[:3]
            return s.severity_paise * (self.cfg.priority_boost_pct if mine else 100) // 100

        return sorted(candidates, key=lambda s: (-score(s), s.kind, s.key))

    def skip(self, candidate: Signal) -> bool:
        said = {
            r[0]
            for r in self.conn.execute(
                "SELECT signal || ':' || json_extract(figures_json, '$._key') FROM checkins"
                " WHERE user_id = ? AND created_at >= ?",
                (self.user_id, self.week_ago),
            )
        }
        return f"{candidate.kind}:{candidate.key}" in said

    def label(self, candidate: Signal) -> str:
        return candidate.kind

    def verify(self, candidate: Signal) -> tuple[bool, str]:
        return verify(self.conn, self.user_id, candidate, self.clock)

    # -- what to say, checked number by number
    def propose(self, candidate: Signal, checked: str) -> tuple[str | None, str]:
        variant = "_none" if candidate.detail.get("none") else ""
        text = TEMPLATES[candidate.kind + variant][self.tone].format(**candidate.figures)
        sources = [str(v) for v in candidate.figures.values()] + candidate.options
        if self.reword is not None:
            try:
                reworded = self.reword(text)
            except Exception:  # noqa: BLE001 - the model is optional
                reworded = text
            text = reworded if not claim_check(reworded, sources) else text
        bad = claim_check(text, sources)
        if bad:
            return None, f"a number nobody computed: {bad[0]}"
        return text, checked

    def commit(self, candidate: Signal, text: str, checked: str) -> Checkin:
        options = candidate.options[:3]
        cid = f"chk_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO checkins (id, user_id, signal, headline, body, figures_json, options_json, verified_json,"
            " arm_timing, arm_tone, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?)",
            (cid, self.user_id, candidate.kind, HEADLINES[candidate.kind], text,
             json.dumps({**candidate.figures, "_key": candidate.key}), json.dumps(options),
             json.dumps({"ok": True, "how": checked}), self.timing, self.tone, to_utc_iso(self.now)),
        )  # fmt: skip
        record_event(
            self.conn, user_id=self.user_id, actor=self.actor, event_type="checkin_sent",
            reason=f"Check-in about {candidate.kind}", run_id=self.run_id, entity_type="checkin",
            entity_id=cid, metadata={"signal": candidate.kind, "timing": self.timing, "tone": self.tone},
            clock=self.now,
        )  # fmt: skip
        return Checkin(id=cid, signal=candidate.kind, headline=HEADLINES[candidate.kind], body=text,
                       options=options, status="sent", timing=self.timing, tone=self.tone,
                       created_at=to_utc_iso(self.now))  # fmt: skip

    def finish(self, run) -> None:
        if run.steps and run.steps[0].name != "precheck":
            _log_drops(self.conn, self.user_id, run.dropped, self.now)


def run_checkin(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
    ignore_timing: bool = False,
    reword: Callable[[str], str] | None = None,
) -> Outcome:
    agent = CheckinAgent(conn, user_id, actor=actor, run_id=run_id, clock=clock,
                         ignore_timing=ignore_timing, reword=reword)  # fmt: skip
    run = run_agent(agent)
    dropped = run.dropped if run.steps and run.steps[0].name != "precheck" else []
    return Outcome(run.result, run.outcome, dropped)


def _log_drops(conn, user_id, dropped, now) -> None:
    for kind, why in dropped:
        conn.execute(
            "INSERT INTO checkin_drops (id, user_id, signal, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"cdr_{uuid.uuid4().hex[:12]}", user_id, kind, why[:200], to_utc_iso(now)),
        )


def respond(
    conn: sqlite3.Connection,
    user_id: str,
    checkin_id: str,
    response: str,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> dict:
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can answer a check-in.")
    if response not in ("acted", "dismissed", "not_useful"):
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Answer acted, dismissed or not_useful.")
    row = conn.execute(
        "SELECT * FROM checkins WHERE user_id = ? AND id = ?", (user_id, checkin_id)
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "No such check-in.")
    if row["status"] != "sent":
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"That check-in was already {row['status']}.")
    conn.execute(
        "UPDATE checkins SET status = ?, responded_at = ? WHERE user_id = ? AND id = ?",
        (response, to_utc_iso(now_utc(clock)), user_id, checkin_id),
    )
    if row["arm_timing"]:
        nudges.record_response(conn, user_id, row["arm_timing"], row["arm_tone"], response, clock)
    record_event(
        conn, user_id=user_id, actor=actor, event_type="checkin_answered",
        reason=f"Check-in answered {response}", entity_type="checkin", entity_id=checkin_id, clock=clock,
    )  # fmt: skip
    return {"id": checkin_id, "status": response}


def list_checkins(conn: sqlite3.Connection, user_id: str, limit: int = 20) -> list[Checkin]:
    rows = conn.execute(
        "SELECT * FROM checkins WHERE user_id = ? ORDER BY created_at DESC, id LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [
        Checkin(id=r["id"], signal=r["signal"], headline=r["headline"], body=r["body"], options=json.loads(r["options_json"]),
                status=r["status"], timing=r["arm_timing"], tone=r["arm_tone"], created_at=r["created_at"])
        for r in rows
    ]  # fmt: skip


def verification_rate(conn: sqlite3.Connection, user_id: str) -> dict:
    """How many hypotheses survived their own check (sent) against how many were dropped."""
    sent = conn.execute("SELECT COUNT(*) FROM checkins WHERE user_id = ?", (user_id,)).fetchone()[0]
    dropped = conn.execute(
        "SELECT COUNT(*) FROM checkin_drops WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    return {
        "sent": sent,
        "dropped": dropped,
        "pass_rate": sent / (sent + dropped) if sent + dropped else None,
    }


__all__ = ["date"]
