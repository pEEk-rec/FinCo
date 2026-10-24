"""
Evaluation of payment capture (PLAN_CAPTURE Stage C9): `copilot eval --capture`.

Two parts, both deterministic and offline:

1. The redacted SMS corpus (`tests/sms_corpus`): parse accuracy per bank, the share of alerts that
   should parse and did not, and whether everything that must be dropped (OTPs, strangers) is.
2. A seeded simulated history through the real pipeline (simulator, ask policy, guesses, labels),
   then a mock Account Aggregator fetch: ask rate, prompts per day, how often the right category
   was in the guesses on the held-out last part of the history, how often an automatic tag was
   right, the reconciliation rate, and the number of times spend was counted twice (must be 0).

Targets for the real-use metrics are the starting assumptions in ADR-0001; this report measures
the system on simulated behaviour and says so. Real values need weeks of real use.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from copilot.config.capture import load_capture_config, load_sms_senders, load_sms_templates
from copilot.core import aa_consent, aa_fetch
from copilot.core import capture as cap
from copilot.core.aa_source import MockAASource, bank_side_feed
from copilot.core.capture_reconcile import combined_spend
from copilot.core.capture_sim import SENDERS, _all_enabled, simulate_alert
from copilot.core.sms_parser import Dropped, ParsedPayment, Unparsed, parse_sms
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.models.domain import Account, Category, User

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORPUS = PROJECT_ROOT / "tests" / "sms_corpus"
USER = "u1"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=IST)
DAYS = 120
HELD_OUT_FROM_DAY = 72  # the last 40% of the history is what guesses are scored on
SEEDS = (20261018, 7, 42, 2024, 99)  # several personas: one lucky or unlucky run proves nothing

CATEGORIES = ["food", "shopping", "travel", "bills", "entertainment", "other"]
MERCHANTS = [  # (name, category, typical rupees, weight)
    ("Lantern Cafe Traders", "food", 240, 5),
    ("Campus Canteen Foods", "food", 90, 6),
    ("Metro Mart Stores", "shopping", 780, 3),
    ("BookNest Stationers", "shopping", 310, 2),
    ("City Cab Services", "travel", 190, 4),
    ("Cineplex Entertainment", "entertainment", 420, 1),
    ("PowerGrid Utilities", "bills", 1450, 1),
]
# What a payment to a person was for varies, so the truth is drawn from their usual reasons.
PERSONS = [
    ("Ramesh K", ["food", "food", "other", "travel"], 300, 3),
    ("Priya S", ["other", "food"], 500, 2),
]
BANKS = ["hdfc", "sbi", "icici", "axis", "kotak"]


@dataclass
class Check:
    name: str
    measured: str
    target: str
    passed: bool
    note: str = ""


@dataclass
class CaptureReport:
    generated_at: str
    sections: dict[str, dict] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


# ---- 1. the corpus -------------------------------------------------------------------------------
def evaluate_corpus() -> dict:
    senders = _all_enabled()
    templates = load_sms_templates()
    per_bank: dict[str, list[bool]] = {}
    should_parse = failed_to_parse = must_drop = dropped_ok = 0
    for path in sorted(CORPUS.glob("*.json")):
        for case in json.loads(path.read_text(encoding="utf-8")):
            out = parse_sms(case["sender"], case["text"], NOW, senders=senders, templates=templates)
            expect = case["expect"]
            if isinstance(expect, dict):
                should_parse += 1
                ok = isinstance(out, ParsedPayment) and (
                    out.amount_paise == expect["amount_paise"]
                    and out.direction == expect["direction"]
                    and out.utr == expect["utr"]
                    and out.account_last4 == expect["account_last4"]
                )
                failed_to_parse += int(isinstance(out, Unparsed))
                per_bank.setdefault(path.stem, []).append(ok)
            elif isinstance(expect, str) and expect.startswith("dropped:"):
                must_drop += 1
                dropped_ok += int(isinstance(out, Dropped))
    return {
        "accuracy_by_bank": {b: sum(v) / len(v) for b, v in sorted(per_bank.items())},
        "cases_by_bank": {b: len(v) for b, v in sorted(per_bank.items())},
        "should_parse": should_parse,
        "unparsed": failed_to_parse,
        "must_drop": must_drop,
        "dropped": dropped_ok,
    }


# ---- 2. a simulated history ----------------------------------------------------------------------
def _db():
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    t0 = "2026-01-01T00:00:00Z"
    insert_user(conn, User(id=USER, created_at=t0))
    insert_account(
        conn,
        Account(id="acc1", user_id=USER, name="Savings", opening_balance_paise=0, created_at=t0),
    )
    for c in CATEGORIES:
        insert_category(conn, Category(id=c, user_id=USER, name=c.title(), created_at=t0))
    return conn


def _pick(rng: random.Random, pool: list[tuple]) -> tuple:
    return rng.choices(pool, weights=[p[3] for p in pool])[0]


def evaluate_simulated(seed: int) -> dict:
    rng = random.Random(seed)
    conn = _db()
    cfg = load_capture_config()
    asked_per_day: dict[int, int] = {}
    total = asked = auto = auto_right = 0
    held = hit1 = hit3 = 0
    by_reason: dict[str, list[int]] = {}
    for day in range(DAYS, 0, -1):
        index = DAYS - day
        for _ in range(rng.choice([1, 1, 2, 2, 3])):
            name, category, rupees, _w = _pick(rng, MERCHANTS + PERSONS)
            person = isinstance(category, list)
            if person:
                category = rng.choice(category)
            elif rng.random() < 0.05:
                category = "other"  # the odd one that does not fit the usual
            hour = rng.choice([8, 9, 13, 14, 19, 20, 21])
            when = (NOW - timedelta(days=day)).replace(hour=hour, minute=rng.randrange(60))
            amount = max(1, round(rupees * rng.uniform(0.6, 1.5))) * 100
            parsed, _text = simulate_alert(
                rng.choice(BANKS), "debit", amount, name, when,
                vpa=f"{name.split()[0].lower()}@ybl" if person else None,
            )  # fmt: skip
            rec = cap.record_payment_event(
                conn, USER, **cap.record_args_from_parsed(parsed, source="simulator", simulated=True),
                clock=when + timedelta(minutes=1), cfg=cfg,
            )  # fmt: skip
            total += 1
            if rec.decision.action in ("ask", "inbox"):
                asked += 1
                asked_per_day[index] = asked_per_day.get(index, 0) + 1
                if index >= HELD_OUT_FROM_DAY:
                    held += 1
                    labels = [g.label for g in rec.guesses]
                    hit1 += int(labels[:1] == [category])
                    hit3 += int(category in labels[:3])
                cap.label_payment_event(
                    conn, USER, rec.event.id, category_id=category,
                    clock=when + timedelta(minutes=5), cfg=cfg,
                )  # fmt: skip
            else:
                auto += 1
                got = cap.get_event(conn, USER, rec.event.id)
                right = int(got is not None and got.category_id == category)
                auto_right += right
                tally = by_reason.setdefault(rec.decision.reason, [0, 0])
                tally[0] += right
                tally[1] += 1
    conn.commit()

    days_active = sorted(asked_per_day.values())

    # Reconciliation through a mock Account Aggregator, then the double-count checks.
    end = to_utc_iso(NOW + timedelta(days=1))
    start = to_utc_iso(NOW - timedelta(days=DAYS + 2))
    before = combined_spend(conn, USER, start, end, include_simulated=True)
    expected = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) FROM payment_events WHERE user_id = ?"
        " AND direction = 'debit' AND state != 'reversed'",
        (USER,),
    ).fetchone()[0]
    violations = int(before.total_paise != expected)
    link = aa_consent.create_consent(conn, USER, clock=NOW - timedelta(days=DAYS + 1))
    aa_consent.transition(conn, USER, link.id, "approve", clock=NOW - timedelta(days=DAYS + 1))
    feed = MockAASource(bank_side_feed(conn, USER, NOW))
    first = aa_fetch.fetch_now(conn, USER, link.id, feed, clock=NOW, force=True)
    second = aa_fetch.fetch_now(conn, USER, link.id, feed, clock=NOW, force=True)
    after = combined_spend(conn, USER, start, end, include_simulated=True)
    violations += int(after.total_paise != expected)
    violations += int(second.inserted != 0)
    reconciled = conn.execute(
        "SELECT COUNT(*) FROM payment_events WHERE user_id = ? AND state = 'reconciled'", (USER,)
    ).fetchone()[0]
    events = conn.execute(
        "SELECT COUNT(*) FROM payment_events WHERE user_id = ?", (USER,)
    ).fetchone()[0]
    return {
        "payments": total,
        "asked": asked,
        "auto_tagged": auto,
        "auto_right": auto_right,
        "auto_by_reason": by_reason,
        "prompts_per_active_day": days_active,
        "held_out_asked": held,
        "hit1": hit1,
        "hit3": hit3,
        "events": events,
        "reconciled": reconciled,
        "fetched": first.fetched,
        "double_count_violations": violations,
    }


def aggregate(runs: list[dict]) -> dict:
    """Pool the runs: counts add up, so a rate is over all payments, not a mean of means."""
    total = sum(r["payments"] for r in runs)
    auto = sum(r["auto_tagged"] for r in runs)
    held = sum(r["held_out_asked"] for r in runs)
    events = sum(r["events"] for r in runs)
    days = sorted(d for r in runs for d in r["prompts_per_active_day"])
    reasons: dict[str, list[int]] = {}
    for r in runs:
        for reason, (right, n) in r["auto_by_reason"].items():
            t = reasons.setdefault(reason, [0, 0])
            t[0] += right
            t[1] += n
    return {
        "runs": len(runs),
        "payments": total,
        "asked": sum(r["asked"] for r in runs),
        "auto_tagged": auto,
        "ask_per_100": round(100 * sum(r["asked"] for r in runs) / total, 1),
        "median_prompts_per_active_day": statistics.median(days) if days else 0,
        "auto_tag_accuracy": sum(r["auto_right"] for r in runs) / auto if auto else 1.0,
        "auto_tag_by_reason": {k: f"{v[0]} of {v[1]}" for k, v in sorted(reasons.items())},
        "held_out_asked": held,
        "guess_hit_rank1": sum(r["hit1"] for r in runs) / held if held else 0.0,
        "guess_hit_top3": sum(r["hit3"] for r in runs) / held if held else 0.0,
        "reconciliation_rate": sum(r["reconciled"] for r in runs) / events if events else 0.0,
        "double_count_violations": sum(r["double_count_violations"] for r in runs),
    }


# ---- the report ----------------------------------------------------------------------------------
def run_capture_evaluation() -> CaptureReport:
    report = CaptureReport(generated_at=to_utc_iso(NOW))
    corpus = evaluate_corpus()
    sim = aggregate([evaluate_simulated(seed) for seed in SEEDS])
    report.sections = {"corpus": corpus, "simulated": sim}
    c = report.checks
    for bank, acc in corpus["accuracy_by_bank"].items():
        c.append(
            Check(
                f"Parse accuracy: {bank}",
                f"{acc:.0%} of {corpus['cases_by_bank'][bank]}",
                "100% (golden corpus)",
                acc == 1.0,
            )
        )
    c.append(
        Check(
            "Unparsed rate (alerts that should parse)",
            f"{corpus['unparsed']} of {corpus['should_parse']}",
            "0",
            corpus["unparsed"] == 0,
        )
    )
    c.append(
        Check(
            "OTPs and strangers dropped",
            f"{corpus['dropped']} of {corpus['must_drop']}",
            "all",
            corpus["dropped"] == corpus["must_drop"],
        )
    )
    c.append(
        Check(
            "Reconciliation rate (AA-linked)",
            f"{sim['reconciliation_rate']:.1%}",
            ">= 95% (ADR-0001)",
            sim["reconciliation_rate"] >= 0.95,
        )
    )
    c.append(
        Check(
            "Double-count violations",
            str(sim["double_count_violations"]),
            "0",
            sim["double_count_violations"] == 0,
        )
    )
    c.append(
        Check(
            "Prompts per active day (median)",
            str(sim["median_prompts_per_active_day"]),
            "<= 3 (ADR-0001)",
            sim["median_prompts_per_active_day"] <= 3,
        )
    )
    c.append(
        Check(
            "Guess hit rate, rank 1 (held out)",
            f"{sim['guess_hit_rank1']:.0%} of {sim['held_out_asked']}",
            ">= 50% (ADR-0001)",
            sim["guess_hit_rank1"] >= 0.5,
            "simulated behaviour: a steady persona, easier than a real person",
        )
    )
    c.append(
        Check(
            "Guess hit rate, any of top 3 (held out)",
            f"{sim['guess_hit_top3']:.0%}",
            ">= 85% (ADR-0001)",
            sim["guess_hit_top3"] >= 0.85,
            "simulated behaviour",
        )
    )
    c.append(
        Check(
            "Automatic tags that were right (informational)",
            f"{sim['auto_tag_accuracy']:.0%} of {sim['auto_tagged']}",
            "reported, no target in ADR-0001",
            True,
            "; ".join(f"{k}: {v}" for k, v in sim["auto_tag_by_reason"].items())
            + ". A person paid for different reasons is the hard case",
        )
    )
    c.append(
        Check(
            "Ask rate (informational)",
            f"{sim['ask_per_100']} per 100 payments, over {sim['runs']} simulated personas",
            "reported, no target",
            True,
        )
    )
    report.pending = [
        "Real-use metrics (answer rate within an hour, time to answer, month-end review queue): "
        "need about four weeks of the owner's own use. Nothing here stands in for them.",
        "Parse accuracy on the owner's real, redacted SMS export "
        "(`scripts/redact_sms.py`): the corpus above is invented in the banks' styles.",
        "Sender IDs in `config/sms_senders.yaml` are unverified until the owner confirms them "
        f"(banks configured: {', '.join(sorted(load_sms_senders().banks))}).",
    ]
    return report


def render_markdown(r: CaptureReport) -> str:
    lines = [
        "# Capture evaluation",
        "",
        "Generated by `copilot eval --capture`. Offline and deterministic: the redacted SMS corpus "
        "plus a seeded simulated history through the real pipeline, then a mock Account "
        "Aggregator fetch.",
        "",
        "| Check | Measured | Target | Result |",
        "| --- | --- | --- | --- |",
    ]
    for c in r.checks:
        note = f" ({c.note})" if c.note else ""
        lines.append(
            f"| {c.name} | {c.measured}{note} | {c.target} | {'PASS' if c.passed else 'FAIL'} |"
        )
    lines += ["", "## Not measured here", ""]
    lines += [f"- {p}" for p in r.pending]
    lines.append("")
    return "\n".join(lines)


def write_report(report: CaptureReport, path: Path | None = None) -> Path:
    out = path or (PROJECT_ROOT / "docs" / "eval_report_capture.md")
    out.write_text(render_markdown(report), encoding="utf-8")
    return out


__all__ = ["SENDERS", "run_capture_evaluation", "write_report"]
