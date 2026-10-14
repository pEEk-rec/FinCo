"""
Natural-language answers for the Ask screen, built from tool results and nothing else.

Two stages, with a hard rule between them:

1. `compose_answer` reads the observations the agent produced and writes a plain answer.
   Every number in it passes through `Facts`, so the answer carries the exact list of figures
   it is allowed to contain.
2. `narrate` (optional) lets a language model reword that draft in a friendlier voice. Its
   output is accepted only if, after removing the allowed facts, no digit is left, it makes no
   forbidden claim (investment, moving money, guarantees) and it uses causal words only when
   the investigation actually explained the change. Otherwise the deterministic draft is shown.

So a model can change how an answer sounds, never what its numbers are.
"""

import re
import sqlite3
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from copilot.core.advice import _CAUSAL_CLAIM, _FORBIDDEN, format_inr, period_label
from copilot.core.timeutil import IST, from_utc_iso, now_utc, previous_months
from copilot.llm.client import LLMClient, StructuredOutputError, structured_call

_MONTHS = (
    "January February March April May June July August September October November December"
).split()

HYPOTHESIS_PHRASE = {
    "one_off_large": "one unusually large payment",
    "more_frequent": "buying more often",
    "higher_ticket": "paying more per purchase",
    "new_merchant": "spending at merchants you had not used before",
    "recurring_change": "a change in a repeating payment",
    "miscategorization": "payments being filed under a different category",
    "duplicate_or_refund": "duplicate charges or refunds",
    "seasonal_or_timing": "the timing of payments within the month",
}
ANOMALY_PHRASE = {
    "duplicate_charge": "looks like a duplicate charge",
    "new_merchant": "first time paying this merchant",
    "large_transaction": "much larger than your usual payments",
}
STATUS_PHRASE = {
    "ok": "on track",
    "warning": "close to the limit",
    "exceeded": "over the limit",
    "projected_exceed": "on course to go over",
    "off_track": "off track",
    "at_risk": "at risk",
    "on_track": "on track",
    "unknown": "not enough data",
}


class AnswerFact(BaseModel):
    """One figure the answer is allowed to contain, exactly as it appears in the text."""

    model_config = ConfigDict(frozen=True)

    label: str
    text: str


class Answer(BaseModel):
    """What the user reads. `facts` is the complete list of numbers it may contain."""

    headline: str
    points: list[str]
    followups: list[str]
    facts: list[AnswerFact]
    confidence: str | None = None
    written_by: Literal["rules", "ai"] = "rules"
    #: True only when the cited investigation explained the change with enough confidence.
    causal_ok: bool = False


class Facts:
    """Collects every figure used in an answer and returns its display text."""

    def __init__(self) -> None:
        self._items: dict[str, AnswerFact] = {}

    def _add(self, label: str, text: str) -> str:
        self._items.setdefault(text, AnswerFact(label=label, text=text))
        return text

    def money(self, label: str, paise: int) -> str:
        return self._add(label, format_inr(paise))

    def abs_money(self, label: str, paise: int) -> str:
        return self._add(label, format_inr(abs(paise)))

    def percent(self, label: str, value: int) -> str:
        return self._add(label, f"{value}%")

    def count(self, label: str, value: int, unit: str = "") -> str:
        return self._add(label, f"{value} {unit}".strip())

    def period(self, period: str) -> str:
        return self._add("period", period_label(period))

    def day(self, utc_iso: str) -> str:
        d = from_utc_iso(utc_iso).astimezone(IST).date()
        return self._add("date", f"{d.day} {_MONTHS[d.month - 1]} {d.year}")

    def date_text(self, d: date) -> str:
        return self._add("date", f"{d.day} {_MONTHS[d.month - 1]} {d.year}")

    def all(self) -> list[AnswerFact]:
        return list(self._items.values())


# ---------------------------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------------------------

_DIGITS = re.compile(r"\d[\d,.]*")


def ungrounded_numbers(text: str, facts: list[AnswerFact]) -> list[str]:
    """Numbers in `text` that are not one of the allowed facts (empty list = grounded)."""
    remaining = text
    for fact in sorted(facts, key=lambda f: len(f.text), reverse=True):
        remaining = remaining.replace(fact.text, " ")
    return [m.group(0).strip(".,") for m in _DIGITS.finditer(remaining) if m.group(0).strip(".,")]


def check_text(text: str, facts: list[AnswerFact], *, causal_ok: bool) -> list[str]:
    """All reasons `text` may not be shown (empty list = fine)."""
    problems = [f"number not in the computed facts: {n}" for n in ungrounded_numbers(text, facts)]
    for reason, pattern in _FORBIDDEN:
        hit = pattern.search(text)
        if hit:
            problems.append(f"{reason}: '{hit.group(0)}'")
    hit_causal = _CAUSAL_CLAIM.search(text)
    if hit_causal and not causal_ok:
        problems.append(f"causal claim without an explained investigation: '{hit_causal.group(0)}'")
    return problems


def validate_answer(answer: Answer) -> list[str]:
    """Check an Answer's headline and points against its own facts."""
    return check_text(
        " ".join([answer.headline, *answer.points]), answer.facts, causal_ok=answer.causal_ok
    )


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _obs(observations: list[dict[str, Any]], tool: str) -> dict[str, Any] | None:
    for o in observations:
        if o.get("tool_name") == tool and o.get("ok") and o.get("data_summary"):
            return o["data_summary"]
    return None


def _previous(period: str) -> str:
    year, month = (int(p) for p in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


_ONE_MONTH = re.compile(r"^\d{4}-\d{2}$")
_SPAN = re.compile(r"^last_(\d+)_months$")


def _period_of(intent: dict[str, Any], clock: datetime | None) -> str:
    """The single month the answer is about. A relative span falls back to the current month."""
    if intent.get("period") and _ONE_MONTH.match(str(intent["period"])):
        return str(intent["period"])
    now = now_utc(clock).astimezone(IST)
    return f"{now.year:04d}-{now.month:02d}"


def _span_months(intent: dict[str, Any], clock: datetime | None) -> list[str]:
    """The months of a "last N months" question (capped like the plan), oldest first."""
    m = _SPAN.match(str(intent.get("period") or ""))
    if not m or intent.get("type") != "summarize_period":
        return []
    now = now_utc(clock).astimezone(IST)
    return previous_months(now.year, now.month, min(int(m.group(1)), 6))


def _summary_span(
    observations: list[dict[str, Any]], names: dict[str, str], months: list[str]
) -> Answer | None:
    """One spend summary across several months, from one aggregate result per month."""
    results = [
        o["data_summary"]
        for o in observations
        if o.get("tool_name") == "aggregate_spend_by_category"
        and o.get("ok")
        and o.get("data_summary")
    ]
    if len(results) != len(months):
        return None  # some month failed; better no answer than a partial total
    f = Facts()
    grand = sum(r["grand_total_spend_paise"] for r in results)
    span = f"{f.period(months[0])} to {f.period(months[-1])}"
    if grand <= 0:
        return _build(f, f"No spending is recorded from {span}.", [], [])
    by_category: dict[str | None, int] = {}
    for r in results:
        for t in r["totals"]:
            by_category[t["category_id"]] = (
                by_category.get(t["category_id"], 0) + t["total_spend_paise"]
            )
    points = [
        f"{f.period(m)}: {f.money('month', r['grand_total_spend_paise'])}"
        for m, r in zip(months, results, strict=True)
    ]
    for cat, paise in sorted(by_category.items(), key=lambda kv: -kv[1])[:3]:
        points.append(
            f"{_name(names, cat)}: {f.money('amount', paise)} "
            f"({f.percent('share', paise * 100 // grand)} of the total)"
        )
    return _build(
        f,
        f"You spent {f.money('total', grand)} over the last "
        f"{f.count('months', len(months), 'months')}, {span}.",
        points,
        ["How is my budget doing this month?", "Forecast my spending this month"],
    )


def _name(names: dict[str, str], category_id: str | None) -> str:
    return names.get(category_id, category_id) if category_id else "Uncategorised"


def _words(status: str) -> str:
    return STATUS_PHRASE.get(status, status.replace("_", " "))


def _build(
    facts: Facts,
    headline: str,
    points: list[str],
    followups: list[str],
    confidence: str | None = "high",
    causal_ok: bool = False,
) -> Answer:
    return Answer(
        headline=headline,
        points=points,
        followups=followups,
        facts=facts.all(),
        confidence=confidence,
        causal_ok=causal_ok,
    )


# ---------------------------------------------------------------------------------------------
# One composer per kind of result
# ---------------------------------------------------------------------------------------------


def _budgets(data: dict[str, Any], names: dict[str, str], period: str) -> Answer:
    f = Facts()
    rows = [s for s in data["statuses"] if s["limit_paise"] > 0]
    if not rows:
        return _build(f, "You have not set any budgets yet.", [], [], "high")
    spent = sum(r["spent_paise"] for r in rows)
    limit = sum(r["limit_paise"] for r in rows)
    used = spent * 100 // limit
    over = [r for r in rows if r["status"] == "exceeded"]
    headline = (
        f"You've used {f.percent('used', used)} of your {f.period(period)} budgets: "
        f"{f.money('spent', spent)} of {f.money('limit', limit)}."
    )
    points = []
    for r in sorted(rows, key=lambda r: -(r["pct_used"] or 0))[:6]:
        line = (
            f"{_name(names, r['category_id'])}: {f.money('spent', r['spent_paise'])} of "
            f"{f.money('limit', r['limit_paise'])} ({f.percent('used', r['pct_used'] or 0)})"
        )
        if r["status"] == "exceeded":
            line += f", over by {f.money('over', r['spent_paise'] - r['limit_paise'])}"
        else:
            line += f", {_words(r['status'])}"
        points.append(line)
    if over:
        headline += (
            f" {f.count('over', len(over))} {'is' if len(over) == 1 else 'are'} over the limit."
        )
    top = _name(names, rows[0]["category_id"]) if rows else "spending"
    return _build(
        f,
        headline,
        points,
        ["Forecast my spending this month", f"Why did my {top.lower()} spend change?"],
    )


def _summary(data: dict[str, Any], names: dict[str, str], period: str) -> Answer:
    f = Facts()
    grand = data["grand_total_spend_paise"]
    if grand <= 0:
        return _build(f, f"No spending is recorded for {f.period(period)}.", [], [])
    totals = sorted(data["totals"], key=lambda t: -t["total_spend_paise"])
    points = [
        f"{_name(names, t['category_id'])}: {f.money('amount', t['total_spend_paise'])} "
        f"({f.percent('share', t['total_spend_paise'] * 100 // grand)} of the total)"
        for t in totals[:5]
    ]
    return _build(
        f,
        f"You spent {f.money('total', grand)} in {f.period(period)}.",
        points,
        ["How is my budget doing this month?", "Forecast my spending this month"],
    )


def _forecast(data: dict[str, Any], period: str) -> Answer:
    f = Facts()
    if data.get("insufficient_data"):
        return _build(
            f,
            f"It's too early to forecast {f.period(period)}: I need at least "
            f"{f.count('days', 3, 'days')} of spending first.",
            [],
            ["How is my budget doing this month?"],
            "low",
        )
    low, high = data["projected_range"]
    points = [
        f"Spent so far: {f.money('spent', data['spent_so_far'])}",
        f"Likely range: {f.money('low', low)} to {f.money('high', high)}",
    ]
    pending = data.get("breakdown", {}).get("pending_fixed", 0)
    if pending > 0:
        points.append(f"Regular payments still due: {f.money('pending', pending)}")
    return _build(
        f,
        f"At this pace, {f.period(period)} will end at about {f.money('projected', data['projected_total'])}.",
        points,
        ["How is my budget doing this month?", "What did I spend by category?"],
        "medium",
    )


def _explain(
    obs: list[dict[str, Any]],
    names: dict[str, str],
    intent: dict[str, Any],
    period: str,
) -> Answer | None:
    data = _obs(obs, "explain_change")
    if not data:
        return None
    f = Facts()
    inv = data["investigation"]
    decomp = data["decomposition"]
    change = decomp.get("total_change_paise", 0)
    cat = intent.get("category_id")
    label = _name(names, cat) if cat else "Your spending"
    agg = _obs(obs, "aggregate_spend_by_category")
    current = None
    if agg:
        if cat:
            current = next(
                (t["total_spend_paise"] for t in agg["totals"] if t["category_id"] == cat), 0
            )
        else:
            current = agg["grand_total_spend_paise"]
    prev_label = f.period(_previous(period))
    if current is not None:
        headline = f"{label} was {f.money('now', current)} in {f.period(period)}"
        if change == 0:
            headline += f", the same as {prev_label}."
        else:
            direction = "up" if change > 0 else "down"
            headline += (
                f", {direction} {f.abs_money('change', change)} from "
                f"{prev_label} ({f.money('before', current - change)})."
            )
    else:
        headline = f"{label} changed by {f.abs_money('change', change)} versus {prev_label}."
    parts = [
        (
            "new_merchant_paise",
            "from merchants you had not used before",
            "from merchants you had not used before",
        ),
        (
            "stopped_merchant_paise",
            "from merchants you used before",
            "from merchants you did not use this time",
        ),
        ("ticket_effect_paise", "from paying more per purchase", "from paying less per purchase"),
        ("volume_effect_paise", "from buying more often", "from buying less often"),
        ("residual_paise", "that I cannot attribute", "that I cannot attribute"),
    ]
    points = []
    for key, up, down in parts:
        amount = decomp.get(key, 0)
        if amount:
            sign = "+" if amount > 0 else "-"
            points.append(f"{sign}{f.abs_money(key, amount)} {up if amount > 0 else down}")
    supported = [h for h in inv["hypotheses"] if h["status"] == "supported"]
    explained = inv["outcome"] == "explained" and inv["confidence_label"] in {"medium", "high"}
    if supported:
        top = max(supported, key=lambda h: h["contribution_paise"])
        points.append(
            f"Main factor: {HYPOTHESIS_PHRASE.get(top['code'], top['code'])}"
            + (
                f" ({f.abs_money('factor', top['contribution_paise'])})"
                if top["contribution_paise"]
                else ""
            )
        )
    if not explained:
        points.append(
            "I can't point to a single clear cause: "
            f"{f.abs_money('unexplained', inv['unexplained_paise'])} of the change has no "
            "explanation with enough evidence."
        )
    return _build(
        f,
        headline,
        points,
        ["How is my budget doing this month?", "Show me unusual spending"],
        inv["confidence_label"],
        causal_ok=explained,
    )


def _whatif(
    obs: list[dict[str, Any]],
    names: dict[str, str],
    conn: sqlite3.Connection,
    user_id: str,
) -> Answer | None:
    data = _obs(obs, "compare_options")
    if not data:
        return None
    cmp = data["comparison"]
    rows = cmp.get("side_by_side") or []
    if not cmp["scenarios"] or not rows:
        return None
    f = Facts()
    sc = cmp["scenarios"][0]["scenario"]
    months = int(sc["months"])
    last = rows[-1]
    base, scen = last["baseline_surplus_paise"], last["scenario_1_surplus_paise"]
    more = sc["kind"] == "add_spend"
    cat = _name(names, sc["category_id"])
    amount = f.money("amount", sc["amount_paise"])
    headline = (
        f"Spending {amount} {'more' if more else 'less'} on {cat} each month for "
        f"{f.count('months', months, 'months')} would "
        f"{'cut' if more else 'raise'} your monthly surplus from {f.money('now', base)} to "
        f"{f.money('then', scen)}."
    )
    points = []
    if base < 0:
        points.append(
            f"Right now you're {f.abs_money('short', base)} short each month (spending more than comes in)."
        )
    else:
        points.append(f"Right now you're {f.money('ahead', base)} ahead each month.")
    total = sc["amount_paise"] * months
    points.append(
        f"Over {f.count('months', months, 'months')} that is {f.money('total', total)} "
        f"{'extra spending' if more else 'saved'}."
    )
    last_month = rows[-1]["month"]
    key = f"{sc['category_id']}:{last_month}"
    base_status = cmp["baseline"]["budget_statuses"].get(key)
    scen_status = cmp["scenarios"][0]["budget_statuses"].get(key)
    if base_status and scen_status and base_status != scen_status:
        points.append(
            f"{cat} budget: {_words(base_status)} now, {_words(scen_status)} with this change."
        )
    elif scen_status and scen_status != "ok":
        points.append(f"{cat} budget stays {_words(scen_status)}.")
    for gid_month, status in cmp["scenarios"][0]["goal_impacts"].items():
        gid, month = gid_month.rsplit(":", 1)
        if month != last_month:
            continue
        row = conn.execute(
            "SELECT name FROM goals WHERE id = ? AND user_id = ?", (gid, user_id)
        ).fetchone()
        base_goal = cmp["baseline"]["goal_impacts"].get(gid_month, "unknown")
        points.append(
            f"{row[0] if row else 'Your goal'}: {_words(base_goal)} now, {_words(status)} with this change."
        )
    return _build(
        f,
        headline,
        points,
        ["How is my budget doing this month?", "Am I on track for my goal?"],
        "medium",
    )


def _goals(
    obs: list[dict[str, Any]], intent: dict[str, Any], clock: datetime | None
) -> Answer | None:
    data = _obs(obs, "list_goals")
    if data is None:
        return None
    f = Facts()
    goals = [g for g in data["goals"] if g["status"] == "active"]
    if intent.get("goal_id"):
        goals = [g for g in goals if g["id"] == intent["goal_id"]] or goals
    if not goals:
        return _build(f, "You haven't set a goal yet.", [], [])
    goals.sort(key=lambda g: g["priority"])
    g = goals[0]
    pct = g["current_paise"] * 100 // g["target_paise"] if g["target_paise"] else 0
    headline = (
        f"{g['name']}: {f.money('saved', g['current_paise'])} of {f.money('target', g['target_paise'])} "
        f"saved ({f.percent('progress', pct)})."
    )
    remaining = max(0, g["target_paise"] - g["current_paise"])
    points = []
    if g.get("deadline") and remaining > 0:
        due = datetime.fromisoformat(g["deadline"]).date()
        today = now_utc(clock).astimezone(IST).date()
        months_left = max(1, (due.year - today.year) * 12 + due.month - today.month)
        need = (remaining + months_left - 1) // months_left
        points.append(
            f"Deadline: {f.date_text(due)}, about {f.count('left', months_left, 'months')} away."
        )
        points.append(f"To get there, set aside about {f.money('need', need)} a month.")
    elif remaining == 0:
        points.append("You've reached the target.")
    bal = _obs(obs, "get_balance")
    if bal:
        points.append(f"Your current balance is {f.money('balance', bal['balance_paise'])}.")
    return _build(
        f,
        headline,
        points,
        ["What if I spend less on dining?", "How is my budget doing this month?"],
        "high",
    )


def _anomalies(obs: list[dict[str, Any]], conn: sqlite3.Connection, user_id: str) -> Answer | None:
    data = _obs(obs, "detect_anomalies")
    if data is None:
        return None
    f = Facts()
    items = data["anomalies"]
    if not items:
        return _build(f, "I found nothing unusual in your spending.", [], [])
    order = {"large_transaction": 0, "duplicate_charge": 1, "new_merchant": 2}
    items = sorted(items, key=lambda a: order.get(a["kind"], 9))
    points, seen = [], set()
    for a in items:
        tx_id = a["transaction_ids"][-1]
        if tx_id in seen:
            continue
        seen.add(tx_id)
        row = conn.execute(
            "SELECT amount_paise, merchant_raw, merchant_normalized, occurred_at FROM transactions "
            "WHERE id = ? AND user_id = ?",
            (tx_id, user_id),
        ).fetchone()
        if not row:
            continue
        merchant = (row["merchant_normalized"] or row["merchant_raw"]).split(" upi")[0].title()
        points.append(
            f"{merchant}, {f.abs_money('amount', row['amount_paise'])} on {f.day(row['occurred_at'])}: "
            f"{ANOMALY_PHRASE.get(a['kind'], a['kind'].replace('_', ' '))}"
        )
        if len(points) == 4:
            break
    return _build(
        f,
        f"I found {f.count('found', len(items))} unusual transactions. The most notable:",
        points,
        ["How is my budget doing this month?"],
        "medium",
    )


def _recurring(conn: sqlite3.Connection, user_id: str) -> Answer:
    f = Facts()
    rows = conn.execute(
        "SELECT merchant_normalized, typical_amount_paise, cadence_days, next_expected "
        "FROM recurring_series WHERE user_id = ? AND kind != 'income' "
        "ORDER BY typical_amount_paise DESC",
        (user_id,),
    ).fetchall()
    if not rows:
        return _build(f, "I haven't found any repeating payments yet.", [], [])
    points = []
    for r in rows[:6]:
        line = f"{r['merchant_normalized'].title()}: about {f.money('amount', r['typical_amount_paise'])}"
        if r["cadence_days"]:
            line += f" every {f.count('cadence', r['cadence_days'], 'days')}"
        if r["next_expected"]:
            line += f", next around {f.day(r['next_expected'])}"
        points.append(line)
    return _build(
        f,
        f"I found {f.count('series', len(rows))} repeating payments.",
        points,
        ["How is my budget doing this month?"],
        "medium",
    )


# ---------------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------------


def compose_answer(
    conn: sqlite3.Connection,
    user_id: str,
    intent: dict[str, Any] | None,
    observations: list[dict[str, Any]],
    names: dict[str, str],
    clock: datetime | None = None,
) -> Answer | None:
    """
    Write the answer from the tools that ran, choosing the most specific result available.

    Dispatch is by which tool results exist (not by intent), so it also works when a model
    planner picks a different set of tools than the templates would.
    """
    intent = intent or {}
    period = _period_of(intent, clock)
    answer: Answer | None = None
    if _obs(observations, "compare_options"):
        answer = _whatif(observations, names, conn, user_id)
    if answer is None and _obs(observations, "explain_change"):
        answer = _explain(observations, names, intent, period)
    if answer is None and _obs(observations, "list_goals") is not None:
        answer = _goals(observations, intent, clock)
    if answer is None and _obs(observations, "detect_anomalies") is not None:
        answer = _anomalies(observations, conn, user_id)
    if answer is None and intent.get("type") == "list_recurring":
        answer = _recurring(conn, user_id)
    if answer is None and (d := _obs(observations, "forecast_month")):
        answer = _forecast(d, period)
    if answer is None and (d := _obs(observations, "check_budgets")):
        answer = _budgets(d, names, period)
    if answer is None and (span := _span_months(intent, clock)):
        answer = _summary_span(observations, names, span)
    elif answer is None and (d := _obs(observations, "aggregate_spend_by_category")):
        answer = _summary(d, names, period)
        if intent.get("period") == "this_week":
            answer.points.insert(0, "I look at whole months, so this is the month so far.")
    if answer is None:
        return None
    problems = validate_answer(answer)
    if problems:  # a bug in a composer must never show an ungrounded number
        return Answer(
            headline="I found the figures below but could not phrase them safely.",
            points=[],
            followups=[],
            facts=answer.facts,
            confidence=answer.confidence,
        )
    return answer


class NarrationDraft(BaseModel):
    """The model's rewrite."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    points: list[str]


_NARRATE_PROMPT = """You rewrite answers for a personal finance assistant so they sound natural \
and answer the user's question directly.

Rules:
- Use ONLY the facts in the draft. Copy every amount, percentage, count, month and date EXACTLY \
as written in the draft.
- Never add a number, a cause, advice, a prediction, or a product name that is not in the draft.
- Keep the same number of points or fewer (at most 5), one short sentence each.
- Plain English, second person ("you"), no emojis.

User question: {question}

Draft headline: {headline}
Draft points:
{points}
{correction}
Reply with JSON: {{"headline": "...", "points": ["...", "..."]}}"""


def narrate(client: LLMClient, question: str, draft: Answer) -> Answer | None:
    """
    Ask the model to reword `draft`. Returns the reworded Answer, or None to keep the draft.

    At most two attempts; the second names the violation. Any failure returns None.
    """
    correction = ""
    for _ in range(2):
        prompt = _NARRATE_PROMPT.format(
            question=question.strip()[:300],
            headline=draft.headline,
            points="\n".join(f"- {p}" for p in draft.points) or "- (none)",
            correction=correction,
        )
        try:
            out = structured_call(
                client, prompt, NarrationDraft, max_retries=0, purpose="narration"
            )
        except (StructuredOutputError, Exception):  # noqa: BLE001 - the draft is the fallback
            return None
        text = " ".join([out.headline, *out.points])
        problems = check_text(text, draft.facts, causal_ok=draft.causal_ok)
        if not problems and out.headline.strip():
            return draft.model_copy(
                update={
                    "headline": out.headline.strip(),
                    "points": [p.strip() for p in out.points[:5]],
                    "written_by": "ai",
                }
            )
        correction = (
            "\nYour previous reply was rejected: "
            + "; ".join(problems[:3])
            + ". Fix exactly that.\n"
        )
    return None
