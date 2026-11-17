"""
Pure capture logic (PLAN_CAPTURE Stage C1): who a counterparty is, whether to ask, and the three
guesses to offer. No database, no clock, no network: everything it needs comes in as arguments,
so every branch can be tested at its boundary and the same inputs always give the same answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from copilot.config.capture import CaptureConfig

Kind = Literal["merchant", "person", "self", "cash", "unknown"]
Action = Literal["ask", "inbox", "auto_label", "guess_only", "no_ask"]

_TOKEN = re.compile(r"[a-z0-9]+")
_PHONE_VPA = re.compile(r"^\+?\d{10}$")


# ---------------------------------------------------------------------------------------------
# 1. Who is the counterparty?
# ---------------------------------------------------------------------------------------------
def normalise_name(text: str) -> str:
    """Lower-case words only: 'RAMESH  K.' and 'ramesh k' are the same counterparty."""
    return " ".join(_TOKEN.findall(text.lower()))


def counterparty_key(display_name: str, vpa: str | None) -> str:
    """A stable key: the VPA when there is one, otherwise the normalised name."""
    if vpa and "@" in vpa:
        return vpa.strip().lower()
    return normalise_name(display_name) or "unknown"


def classify_counterparty(
    display_name: str,
    vpa: str | None,
    channel: str,
    cfg: CaptureConfig,
    own_keys: frozenset[str] = frozenset(),
    known_merchant_names: frozenset[str] = frozenset(),
) -> tuple[str, Kind]:
    """(key, kind). Cash comes from the channel, own accounts from the user's own keys."""
    key = counterparty_key(display_name, vpa)
    c = cfg.classify
    name = normalise_name(display_name)
    if channel == "atm":
        return "cash:atm", "cash"
    if key in own_keys or any(p in name for p in c.own_account_phrases):
        return key, "self"
    if key in known_merchant_names or name in known_merchant_names:
        return key, "merchant"
    if vpa and "@" in vpa:
        local = vpa.split("@", 1)[0].lower()
        if _PHONE_VPA.match(local):
            return key, "person"
        if any(m in local for m in c.merchant_vpa_markers):
            return key, "merchant"
    tokens = name.split()
    if any(t in c.business_words for t in tokens):
        return key, "merchant"
    if tokens and len(tokens) <= c.person_max_name_tokens and all(t.isalpha() for t in tokens):
        return key, "person"
    return key, "unknown"


# ---------------------------------------------------------------------------------------------
# 2. Should we ask?
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class EventFacts:
    """What the policy needs to know about the payment itself."""

    amount_paise: int
    direction: Literal["debit", "credit"]
    kind: Kind
    channel: str


@dataclass(frozen=True)
class AskContext:
    """What the policy needs to know about the world around it (read by the caller)."""

    local_time: datetime  # in the user's own timezone: quiet hours are wall-clock
    prompts_today: int
    minutes_since_counterparty_prompt: int | None = None
    known_merchant_category: str | None = None
    known_merchant_confidence_bp: int = 0
    recurring_category: str | None = None  # an AutoPay or recurring series for this counterparty
    refund_of_event_id: str | None = None  # a credit that reverses an earlier debit
    known_inflow_kind: str | None = None  # salary or allowance from a recurring inflow
    policy: Literal["learn", "always_ask", "always_category"] = "learn"
    policy_category: str | None = None
    recent_categories: tuple[str, ...] = ()  # newest last


@dataclass(frozen=True)
class AskDecision:
    action: Action
    reason: str
    category_id: str | None = None
    credit_kind: str | None = None
    linked_event_id: str | None = None
    priority: Literal["normal", "low"] = "normal"


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(local_time: datetime, start: str, end: str) -> bool:
    """True inside [start, end), including a window that crosses midnight (23:00 to 07:30)."""
    now = local_time.hour * 60 + local_time.minute
    s, e = _minutes(start), _minutes(end)
    if s == e:
        return False
    return s <= now < e if s < e else (now >= s or now < e)


def _person_rule(ctx: AskContext, cfg: CaptureConfig) -> str | None:
    """The category when the last n labels for this person agree k or more times."""
    n, k = cfg.ask.person_policy.n, cfg.ask.person_policy.k
    recent = ctx.recent_categories[-n:]
    if len(recent) < n:
        return None
    top = max(set(recent), key=lambda c: (recent.count(c), c))
    return top if recent.count(top) >= k else None


def _gate_ask(
    reason: str, ctx: AskContext, cfg: CaptureConfig, priority: Literal["normal", "low"] = "normal"
) -> AskDecision:
    """An ask that passes the fatigue rules is a prompt; otherwise it waits in the inbox."""
    p = cfg.prompts
    if in_quiet_hours(ctx.local_time, p.quiet_hours.start, p.quiet_hours.end):
        return AskDecision("inbox", "quiet_hours", priority=priority)
    if ctx.prompts_today >= p.max_per_day:
        return AskDecision("inbox", "daily_budget", priority=priority)
    since = ctx.minutes_since_counterparty_prompt
    if since is not None and since < p.per_counterparty_cooldown_hours * 60:
        return AskDecision("inbox", "counterparty_cooldown", priority=priority)
    return AskDecision("ask", reason, priority=priority)


def decide_ask(event: EventFacts, ctx: AskContext, cfg: CaptureConfig) -> AskDecision:
    """ADR-0001 D3, for money going out and for money coming in."""
    if event.kind == "self":
        return AskDecision("no_ask", "own_transfer")

    if event.direction == "credit":
        if ctx.refund_of_event_id:
            return AskDecision(
                "auto_label", "refund_matched", credit_kind="refund",
                linked_event_id=ctx.refund_of_event_id,
            )  # fmt: skip
        if ctx.known_inflow_kind and cfg.credits.auto_label_known_inflows:
            return AskDecision("auto_label", "known_inflow", credit_kind=ctx.known_inflow_kind)
        if event.amount_paise < cfg.ask.min_ask_amount_paise:
            return AskDecision("guess_only", "below_min_amount")
        return _gate_ask("credit_needs_you", ctx, cfg)

    # money going out
    if ctx.recurring_category or event.channel == "autopay":
        return AskDecision("auto_label", "recurring", category_id=ctx.recurring_category)
    if ctx.policy == "always_category" and ctx.policy_category:
        return AskDecision("auto_label", "person_always_category", category_id=ctx.policy_category)
    if ctx.policy != "always_ask":
        if (
            event.kind == "merchant"
            and ctx.known_merchant_category
            and ctx.known_merchant_confidence_bp >= cfg.ask.auto_accept_min_confidence_bp
        ):
            return AskDecision(
                "auto_label", "known_merchant", category_id=ctx.known_merchant_category
            )
        if event.kind == "person":
            agreed = _person_rule(ctx, cfg)
            if agreed:
                return AskDecision("auto_label", "person_k_of_n", category_id=agreed)
    if event.kind == "cash":
        if not cfg.ask.ask_about_cash:
            return AskDecision("guess_only", "cash_not_asked")
        return _gate_ask("cash_purpose", ctx, cfg, priority="low")
    if event.amount_paise < cfg.ask.min_ask_amount_paise:
        return AskDecision("guess_only", "below_min_amount")
    reason = "person_unclear" if event.kind == "person" else "unknown_merchant"
    return _gate_ask(reason, ctx, cfg)


# ---------------------------------------------------------------------------------------------
# 3. The three guesses
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class HistoryRow:
    """One earlier labelled event."""

    counterparty_key: str
    label: str  # a category id for debits, a credit kind for credits
    amount_paise: int
    occurred_at: datetime  # local time, so hour and weekday mean what the user lives
    direction: Literal["debit", "credit"]


@dataclass(frozen=True)
class Guess:
    label: str
    score_bp: int
    reasons: tuple[str, ...] = field(default=())


_BANDS = (
    (0, 6, "night"),
    (6, 11, "morning"),
    (11, 16, "midday"),
    (16, 21, "evening"),
    (21, 24, "night"),
)


def _band(hour: int) -> str:
    return next(name for lo, hi, name in _BANDS if lo <= hour < hi)


def _share(rows: list[HistoryRow], weights: list[float]) -> dict[str, float]:
    total = sum(weights)
    out: dict[str, float] = {}
    if total <= 0:
        return out
    for r, w in zip(rows, weights, strict=True):
        out[r.label] = out.get(r.label, 0.0) + w / total
    return out


def signal_shares(
    *,
    counterparty: str,
    direction: Literal["debit", "credit"],
    amount_paise: int,
    when: datetime,
    history: list[HistoryRow],
    cfg: CaptureConfig,
    hint_label: str | None = None,
) -> list[tuple[str, dict[str, float], str]]:
    """
    What each of the six ranking signals says on its own: (weight name, share per label, why).
    The ranking adds them up with their weights; the learner asks each one whether it would have
    picked what the user chose.
    """
    rc = cfg.ranking
    rows = [r for r in history if r.direction == direction]
    out: list[tuple[str, dict[str, float], str]] = []

    mine = [r for r in rows if r.counterparty_key == counterparty]
    decay = [
        0.5
        ** (max(0.0, (when - r.occurred_at).total_seconds()) / 86400 / rc.history_half_life_days)
        for r in mine
    ]
    out.append(("counterparty_history", _share(mine, decay), "you labelled this payee before"))

    band = _band(when.hour)
    same_band = [r for r in rows if _band(r.occurred_at.hour) == band]
    out.append(
        ("time_pattern", _share(same_band, [1.0] * len(same_band)), f"typical for the {band}")
    )

    near_amount = [
        r for r in rows if r.amount_paise and 0.5 <= amount_paise / r.amount_paise <= 2.0
    ]
    out.append(
        ("amount_band", _share(near_amount, [1.0] * len(near_amount)), "usual for this amount")
    )

    near_day = [r for r in rows if abs(r.occurred_at.day - when.day) <= 2]
    out.append(("day_of_month", _share(near_day, [1.0] * len(near_day)), "usual around this date"))

    hint = {hint_label: 1.0} if hint_label else {}
    out.append(("merchant_hint", hint, "the name suggests it"))

    recent: dict[str, float] = {}
    if rows:
        latest = max(rows, key=lambda r: (r.occurred_at, r.label))
        if 0 <= (when - latest.occurred_at).total_seconds() <= 7200:
            recent = {latest.label: 1.0}
    out.append(("recency", recent, "the one you just used"))
    return out


def signal_votes(**kwargs) -> dict[str, str]:
    """The label each signal would put first (ties break on the label), for signals with a view."""
    votes: dict[str, str] = {}
    for name, share, _why in signal_shares(**kwargs):
        if share:
            votes[name] = sorted(share.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return votes


def rank_guesses(
    *,
    counterparty: str,
    direction: Literal["debit", "credit"],
    amount_paise: int,
    when: datetime,
    history: list[HistoryRow],
    cfg: CaptureConfig,
    hint_label: str | None = None,
    fallback_labels: list[str] | None = None,
) -> list[Guess]:
    """
    Top `guess_count` distinct labels by a weighted sum of six explainable signals
    (ADR-0001 D4). Deterministic: ties break on the label itself.
    """
    rc = cfg.ranking
    w = rc.weights
    rows = [r for r in history if r.direction == direction]
    scores: dict[str, float] = {}
    reasons: dict[str, set[str]] = {}
    for name, share, why in signal_shares(
        counterparty=counterparty, direction=direction, amount_paise=amount_paise, when=when,
        history=history, cfg=cfg, hint_label=hint_label,
    ):  # fmt: skip
        for label, frac in share.items():
            scores[label] = scores.get(label, 0.0) + frac * getattr(w, name)
            reasons.setdefault(label, set()).add(why)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    guesses = [Guess(label, round(score), tuple(sorted(reasons[label]))) for label, score in ranked]

    # Fill up to the guess count with the user's most used labels, then the given fallbacks.
    have = {g.label for g in guesses}
    frequent: dict[str, int] = {}
    for r in rows:
        frequent[r.label] = frequent.get(r.label, 0) + 1
    for label, _ in sorted(frequent.items(), key=lambda kv: (-kv[1], kv[0])):
        if label not in have:
            guesses.append(Guess(label, 0, ("one you use often",)))
            have.add(label)
    for label in fallback_labels or []:
        if label not in have:
            guesses.append(Guess(label, 0, ()))
            have.add(label)
    return guesses[: rc.guess_count]
