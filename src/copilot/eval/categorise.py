# ruff: noqa: E501  (report prose and data tables)
"""
Evaluation of categorisation (PLAN_AGENTIC_V2, A0 and A7): `copilot eval --categorise`.

A seeded simulated user lives through four weeks. Payments arrive in the messy shapes Indian
banks produce (the same shop truncated by one bank, spelled in full by another, paid by VPA or by
card), plus friends paid for varying reasons. Each week the system decides what it can and asks about
the rest; the simulated user answers truthfully, except for a small share of "odd" answers.

Two engines see exactly the same weeks:

* **before**: a faithful re-enactment of the existing pipeline (override, rule, model cache, model,
  review queue), using the real normaliser and the real rules file;
* **after**: the entity cascade (S0 to S5) with calibrated thresholds.

The model is *simulated* (and says so in the report): it knows well-known brands, does well on
descriptive names and is close to random on odd ones, and it is overconfident. That is the situation
the calibration has to cope with. Real-model numbers need real keys; the structure is the same.

Targets were fixed before building (PLAN_AGENTIC_V2 A0) and are never changed after a result:
accuracy on applied labels >= 95%; coverage of shop payments in weeks 3 and 4 >= 85%;
model calls <= 5 per 100 payments in weeks 3 and 4; calibration error <= 5 points;
entity pairwise precision >= 0.99 and recall >= 0.90.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from copilot.common.settings import load_settings
from copilot.common.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_transaction, insert_user
from copilot.models.domain import Account, Category, Transaction, User
from copilot.understand import learn
from copilot.understand.cascade import Cascade, Item
from copilot.understand.config import load_dictionary, load_understand_config
from copilot.understand.descriptor import parse_descriptor
from copilot.understand.rules import evaluate_rules, load_aliases, load_rules, normalize_merchant

PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER = "u1"
T0 = "2026-01-01T00:00:00Z"
START = datetime(2026, 9, 1, 12, 0, tzinfo=IST)
WEEKS = 4
SEEDS = (11, 23, 37, 41, 59)
CATEGORIES = {
    "food": "Dining", "groceries": "Groceries", "travel": "Travel", "shopping": "Shopping",
    "bills": "Utilities", "subscriptions": "Subscriptions", "education": "Education",
    "entertainment": "Entertainment", "housing": "Rent",
}  # fmt: skip
ODD_ANSWER = 0.02  # the user sometimes files a shop somewhere unusual

TARGETS = {
    "accuracy": 0.95,
    "coverage": 0.85,
    "model_calls_per_100": 5.0,
    "calibration_error_pp": 5.0,
    "pair_precision": 0.99,
    "pair_recall": 0.90,
}


# ---- the world --------------------------------------------------------------------------------
@dataclass
class Shop:
    key: str  # ground-truth identity
    name: str
    category: str
    vpa: str | None
    brand: bool
    cues: bool  # the name itself gives the category away ("cafe", "stationers")
    card: bool = False
    popularity: int = 3


@dataclass
class Person:
    key: str
    name: str
    vpa: str
    reasons: list[str]


@dataclass
class Txn:
    id: str
    week: int
    raw: str
    amount_paise: int
    truth_entity: str
    truth_category: str
    is_person: bool
    when: datetime


LOCAL_SHOPS = [  # (name, category, has cues)
    ("Lantern Cafe Traders", "food", True), ("Campus Canteen Foods", "food", True),
    ("Campus Canteen Block B", "food", True), ("Sri Balaji Tiffins", "food", True),
    ("Green Leaf Juice Centre", "food", True), ("Gupta Kirana Store", "groceries", True),
    ("Metro Mart Stores", "groceries", True), ("Fresh Basket Supermarket", "groceries", True),
    ("Sharma Stationers", "shopping", True), ("BookNest Stationers", "education", True),
    ("City Cab Services", "travel", True), ("Anand Medicals", "shopping", True),
    ("Power Grid Utilities", "bills", True), ("Skyline Broadband", "bills", True),
    ("Pixel Arcade", "entertainment", False), ("Zenith Corner", "shopping", False),
    ("Orbit Hub", "food", False), ("Kuteer Works", "shopping", False),
    ("Maple Lane Studio", "entertainment", False), ("Vantage Point", "food", False),
]  # fmt: skip
PEOPLE = [
    ("Ramesh K", ["food", "food", "shopping", "travel"]),
    ("Priya Sharma", ["food", "entertainment"]),
    ("Arjun Nair", ["shopping", "food", "bills"]),
    ("Meera Iyer", ["food", "travel"]),
]
BANKS = ["HDFC", "SBI", "ICICI", "AXIS", "KOTAK"]
CITIES = ["BANGALORE", "MUMBAI", "DELHI", "PUNE"]


def build_world(rng: random.Random) -> tuple[list[Shop], list[Person]]:
    shops: list[Shop] = []
    brands = [b for b in load_dictionary().brands if b.category in CATEGORIES]
    rng.shuffle(brands)
    for b in brands[:16]:
        shops.append(
            Shop(f"brand:{b.name}", b.name, b.category, f"{b.handles[0]}@ybl" if b.handles else None,
                 True, True, card=rng.random() < 0.5, popularity=rng.choice([2, 3, 5]))
        )  # fmt: skip
    for i, (name, cat, cues) in enumerate(LOCAL_SHOPS):
        sq = re.sub(r"[^a-z]", "", name.lower())
        vpa = rng.choice(
            [
                f"{sq[:9]}{i}@okaxis",
                f"paytmqr{rng.randrange(10**9, 10**10)}@paytm",
                f"{sq[:8]}{i}@ybl",
            ]
        )
        shops.append(Shop(f"shop:{i}", name, cat, vpa, False, cues, card=rng.random() < 0.25,
                          popularity=rng.choice([1, 2, 4, 6])))  # fmt: skip
    people = [
        Person(f"person:{i}", n, f"{rng.randrange(7_000_000_000, 9_999_999_999)}@ybl", r)
        for i, (n, r) in enumerate(PEOPLE)
    ]
    return shops, people


def render(rng: random.Random, shop: Shop) -> str:
    ref = rng.randrange(10**11, 10**12)
    bank = rng.choice(BANKS)
    upper = shop.name.upper()
    squashed = re.sub(r"[^A-Z]", "", upper)
    styles = ["slash", "dash", "trunc", "pos"] if shop.card else ["slash", "dash", "trunc"]
    if shop.vpa is None:
        styles = ["pos", "ecom"]
    style = rng.choice(styles)
    if style == "slash":
        return f"UPI/{ref}/{upper}/{shop.vpa}/{bank}"
    if style == "dash":
        return f"UPI-{upper}-{shop.vpa}-{ref}"
    if style == "trunc":  # one bank cuts the name short and squashes it
        return f"UPI-{squashed[:14]}-{shop.vpa}-{ref}"
    if style == "ecom":
        return f"ECOM {upper}"
    return f"POS {rng.randrange(1000, 9999)} {upper} {rng.choice(CITIES)} IN"


def build_weeks(seed: int) -> tuple[list[Txn], list[Shop], list[Person]]:
    rng = random.Random(seed)
    shops, people = build_world(rng)
    order = list(shops)
    rng.shuffle(order)
    txns: list[Txn] = []
    for week in range(WEEKS):
        live = order[: 8 + week * (len(order) - 8) // WEEKS]  # new shops keep appearing
        weights = [s.popularity for s in live]
        for n in range(44):
            day = START + timedelta(days=week * 7 + rng.randrange(7), hours=rng.randrange(-4, 8))
            if rng.random() < 0.12:
                p = rng.choice(people)
                raw = f"UPI/{rng.randrange(10**11, 10**12)}/{p.name.upper()}/{p.vpa}/{rng.choice(BANKS)}"
                txns.append(Txn(f"t{seed}_{week}_{n}", week, raw, rng.randrange(80, 900) * 100,
                                p.key, rng.choice(p.reasons), True, day))  # fmt: skip
                continue
            s = rng.choices(live, weights=weights)[0]
            cat = s.category
            if rng.random() < ODD_ANSWER:
                cat = rng.choice([c for c in CATEGORIES if c != s.category])
            txns.append(Txn(f"t{seed}_{week}_{n}", week, render(rng, s),
                            rng.randrange(40, 2500) * 100, s.key, cat, False, day))  # fmt: skip
    return txns, shops, people


# ---- a simulated model --------------------------------------------------------------------------
class SimulatedModel:
    """Knows brands, reads obvious names, is close to guessing on odd ones, and is overconfident."""

    def __init__(self, shops: list[Shop], seed: int, skill: float = 1.0) -> None:
        self.skill = skill  # 1.0 as described above; 0.0 is a model that is always wrong
        self.rng = random.Random(seed + 7)
        self.truth = {re.sub(r"[^a-z]", "", s.name.lower()): s for s in shops}
        self.calls = 0

    def suggest_many(self, requests, categories: dict[str, str]) -> list[tuple[str | None, int]]:
        """One request per batch of 20 names, as the real advisor makes them."""
        self.calls += -(-len(requests) // 20) if requests else 0
        return [self._one(name, categories, ex) for name, ex in requests]

    def _one(self, name: str, categories: dict[str, str], examples) -> tuple[str | None, int]:
        key = re.sub(r"[^a-z]", "", name.lower())
        shop = next(
            (s for k, s in self.truth.items() if k.startswith(key[:10]) or key.startswith(k[:10])),
            None,
        )
        if shop is None:
            return None, 0
        p_right = (0.95 if shop.brand else 0.8 if shop.cues else 0.4) * self.skill
        # shown the user's similar shops the model does a little better on descriptive names
        if examples and any(c == shop.category for _n, c in examples):
            p_right = min(0.97, p_right + 0.1 * self.skill)
        cat = (
            shop.category
            if self.rng.random() < p_right
            else self.rng.choice([c for c in categories if c != shop.category])
        )
        return cat, round(
            self.rng.uniform(0.70, 0.95) * 10000
        )  # confidence says nothing about correctness


# ---- engines ------------------------------------------------------------------------------------
@dataclass
class Row:
    tx: Txn
    applied: bool
    correct: bool
    asked: bool
    entity: str | None = None
    p_bp: int = 0


@dataclass
class RunResult:
    rows: list[Row] = field(default_factory=list)
    questions: dict[int, int] = field(default_factory=dict)
    model_calls: dict[int, int] = field(default_factory=dict)
    guess_hits: int = 0
    guess_asks: int = 0
    pairs: tuple[int, int, int] = (0, 0, 0)  # true positives, resolved pairs, true pairs


def run_before(txns: list[Txn], shops: list[Shop], seed: int) -> RunResult:
    """The existing pipeline, week by week."""
    settings = load_settings()
    rules = load_rules(settings.categorization_rules_path)
    aliases = load_aliases(settings.merchant_aliases_path)
    cfg = settings.categorization
    model = SimulatedModel(shops, seed)
    overrides: dict[str, str] = {}
    cache: dict[str, tuple[str | None, int]] = {}
    res = RunResult()
    for week in range(WEEKS):
        batch = [t for t in txns if t.week == week]
        review: dict[str, list[Txn]] = {}
        calls_before = model.calls
        need: list[str] = []
        for t in batch:  # which names will the old pipeline have to ask the model about?
            norm = normalize_merchant(t.raw, aliases)
            hit = evaluate_rules(norm, t.amount_paise, "debit", rules)
            if norm not in overrides and not (hit and hit[0] in CATEGORIES) and norm not in cache:
                if norm not in need:
                    need.append(norm)
        cache.update(
            zip(need, model.suggest_many([(n, []) for n in need], CATEGORIES), strict=True)
        )
        for t in batch:
            norm = normalize_merchant(t.raw, aliases)
            if norm in overrides:
                res.rows.append(Row(t, True, overrides[norm] == t.truth_category, False))
                continue
            hit = evaluate_rules(norm, t.amount_paise, "debit", rules)
            if hit and hit[0] in CATEGORIES:
                res.rows.append(Row(t, True, hit[0] == t.truth_category, False))
                continue
            cat, raw = cache[norm]
            conf = min(raw / 10000, cfg.llm_confidence_cap)
            if cat and conf >= cfg.auto_accept_min_confidence:
                res.rows.append(Row(t, True, cat == t.truth_category, False))
            else:
                review.setdefault(norm, []).append(t)
                res.rows.append(Row(t, False, False, True))
        res.questions[week] = len(review)
        res.model_calls[week] = model.calls - calls_before
        for norm, items in review.items():  # the user answers; the answer becomes an override
            overrides[norm] = items[0].truth_category
    return res


def _db(txns: list[Txn]):
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at=T0))
    insert_account(
        conn, Account(id="acc1", user_id=USER, name="S", opening_balance_paise=0, created_at=T0)
    )
    for cid, name in CATEGORIES.items():
        insert_category(conn, Category(id=cid, user_id=USER, name=name, created_at=T0))
    for t in txns:
        insert_transaction(
            conn,
            Transaction(
                id=t.id, user_id=USER, account_id="acc1", occurred_at=to_utc_iso(t.when),
                amount_paise=t.amount_paise, direction="debit", merchant_raw=t.raw, description="",
                created_at=to_utc_iso(t.when),
            ),
        )  # fmt: skip
    return conn


def run_after(
    txns: list[Txn],
    shops: list[Shop],
    seed: int,
    level: str | None = None,
    model_skill: float = 1.0,
) -> tuple[RunResult, Cascade]:
    cfg = load_understand_config()
    if level:
        cfg = cfg.with_level(level)
    settings = load_settings()
    conn = _db(txns)
    model = SimulatedModel(shops, seed, model_skill)
    cas = Cascade(
        conn, USER, categories=dict(CATEGORIES), rules=load_rules(settings.categorization_rules_path),
        aliases=load_aliases(settings.merchant_aliases_path), advisor=model, cfg=cfg,
    )  # fmt: skip
    res = RunResult()
    truth_by_id = {t.id: t for t in txns}
    for week in range(WEEKS):
        batch = [t for t in txns if t.week == week]
        calls_before = cas.model_calls
        decisions = cas.run([Item(t.id, t.raw, t.amount_paise, "debit") for t in batch])
        asked_entities: set[str] = set()
        qs = 0
        for d in decisions:
            t = truth_by_id[d.tx_id]
            row = Row(t, d.applied, d.applied and d.category_id == t.truth_category, d.asks_user,
                      d.entity_id, d.p_bp)  # fmt: skip
            res.rows.append(row)
        res.model_calls[week] = cas.model_calls - calls_before
        # the user answers what was asked, most valuable question first
        for q in learn.rank_questions(conn, USER, cfg, clock=batch[-1].when + timedelta(days=1)):
            first = truth_by_id[q.tx_ids[0]]
            if q.kind == "person":
                for tid in q.tx_ids:
                    learn.answer_transaction(conn, USER, tid, truth_by_id[tid].truth_category)
                    qs += 1
                continue
            if q.best_guess and not q.audit:
                res.guess_asks += 1
                res.guess_hits += int(q.best_guess == first.truth_category)
            learn.answer_entity(conn, USER, q.entity_id, first.truth_category)
            asked_entities.add(q.entity_id)
            qs += 1
        res.questions[week] = qs
    res.pairs = pair_counts(res.rows)
    return res, cas


# ---- measures -----------------------------------------------------------------------------------
def pair_counts(rows: list[Row]) -> tuple[int, int, int]:
    """Pairs of shop payments that share a resolved entity, a true shop, or both."""
    shop_rows = [r for r in rows if not r.tx.is_person and r.entity]
    truth = Counter(r.tx.truth_entity for r in shop_rows)
    got = Counter(r.entity for r in shop_rows)
    both = Counter((r.tx.truth_entity, r.entity) for r in shop_rows)

    def pairs(c: Counter) -> int:
        return sum(n * (n - 1) // 2 for n in c.values())

    return pairs(both), pairs(got), pairs(truth)


def calibration_error_pp(rows: list[Row]) -> float:
    """Expected calibration error on applied labels: claimed probability against what happened."""
    bins: dict[int, list[Row]] = {}
    for r in rows:
        if r.applied:
            bins.setdefault(min(9, r.p_bp // 1000), []).append(r)
    total = sum(len(v) for v in bins.values())
    if not total:
        return 0.0
    gap = sum(abs(sum(x.p_bp for x in v) / len(v) / 10000 - sum(x.correct for x in v) / len(v)) * len(v)
              for v in bins.values())  # fmt: skip
    return 100 * gap / total


def summarise(res: RunResult, late_from: int = 2) -> dict:
    rows = res.rows
    applied = [r for r in rows if r.applied]
    late = [r for r in rows if r.tx.week >= late_from]
    late_shops = [r for r in late if not r.tx.is_person]
    n_late = len(late) or 1
    q_total = sum(res.questions.values())
    return {
        "payments": len(rows),
        "applied": len(applied),
        "accuracy": sum(r.correct for r in applied) / len(applied) if applied else 1.0,
        "coverage_all": len(applied) / len(rows),
        "coverage_late_shops": sum(r.applied for r in late_shops) / len(late_shops)
        if late_shops
        else 1.0,
        "questions_per_100": 100 * q_total / len(rows),
        "model_calls_per_100_late": 100
        * sum(res.model_calls.get(w, 0) for w in range(late_from, WEEKS))
        / n_late,
        "model_calls_per_100": 100 * sum(res.model_calls.values()) / len(rows),
        "person_payments": sum(r.tx.is_person for r in rows),
        "person_applied": sum(r.tx.is_person and r.applied for r in rows),
        "person_wrong": sum(r.tx.is_person and r.applied and not r.correct for r in rows),
        "guess_hit_rate": res.guess_hits / res.guess_asks if res.guess_asks else 0.0,
    }


def pool(runs: list[RunResult]) -> RunResult:
    out = RunResult()
    for r in runs:
        out.rows += r.rows
        out.guess_hits += r.guess_hits
        out.guess_asks += r.guess_asks
        out.pairs = tuple(a + b for a, b in zip(out.pairs, r.pairs, strict=True))  # type: ignore[assignment]
        for w, v in r.questions.items():
            out.questions[w] = out.questions.get(w, 0) + v
        for w, v in r.model_calls.items():
            out.model_calls[w] = out.model_calls.get(w, 0) + v
    return out


@dataclass
class Check:
    name: str
    measured: str
    target: str
    passed: bool
    note: str = ""


@dataclass
class CategoriseReport:
    before: dict
    after: dict
    curve: dict[str, dict]
    swap: dict[str, dict]
    pair_precision: float
    pair_recall: float
    calibration_error_pp: float
    checks: list[Check] = field(default_factory=list)
    switch_over: bool = False
    verdict: str = ""

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def run_categorise_evaluation(seeds: tuple[int, ...] = SEEDS) -> CategoriseReport:
    before_runs, after_runs = [], []
    curve_runs: dict[str, list[RunResult]] = {
        "more_questions": [],
        "balanced": [],
        "fewer_questions": [],
    }
    for seed in seeds:
        txns, shops, _p = build_weeks(seed)
        before_runs.append(run_before(txns, shops, seed))
        for level in curve_runs:
            res, _cas = run_after(txns, shops, seed, level)
            curve_runs[level].append(res)
            if level == "balanced":
                after_runs.append(res)
    before = summarise(pool(before_runs))
    after_pool = pool(after_runs)
    after = summarise(after_pool)
    curve = {lvl: summarise(pool(rs)) for lvl, rs in curve_runs.items()}
    swap: dict[str, dict] = {}
    for label, skill in (("strong model", 1.0), ("weak model", 0.5), ("always-wrong model", 0.0)):
        runs = [run_after(*build_weeks(seed)[:2], seed, None, skill)[0] for seed in seeds]
        swap[label] = summarise(pool(runs))
    tp, got_pairs, true_pairs = after_pool.pairs
    precision = tp / got_pairs if got_pairs else 1.0
    recall = tp / true_pairs if true_pairs else 1.0
    ece = calibration_error_pp(after_pool.rows)
    t = TARGETS
    checks = [
        Check(
            "Accuracy on applied labels",
            f"{after['accuracy']:.1%} (before {before['accuracy']:.1%})",
            f">= {t['accuracy']:.0%}",
            after["accuracy"] >= t["accuracy"],
        ),
        Check(
            "Coverage, shop payments in weeks 3 and 4",
            f"{after['coverage_late_shops']:.1%} (before {before['coverage_late_shops']:.1%})",
            f">= {t['coverage']:.0%}",
            after["coverage_late_shops"] >= t["coverage"],
        ),
        Check(
            "Model calls per 100 payments, weeks 3 and 4",
            f"{after['model_calls_per_100_late']:.1f} (before {before['model_calls_per_100_late']:.1f})",
            f"<= {t['model_calls_per_100']:.0f}",
            after["model_calls_per_100_late"] <= t["model_calls_per_100"],
        ),
        Check(
            "Calibration error on applied labels",
            f"{ece:.1f} points",
            f"<= {t['calibration_error_pp']:.0f} points",
            ece <= t["calibration_error_pp"],
        ),
        Check(
            "Entity resolution, pairwise precision",
            f"{precision:.3f}",
            f">= {t['pair_precision']}",
            precision >= t["pair_precision"],
        ),
        Check(
            "Entity resolution, pairwise recall",
            f"{recall:.3f}",
            f">= {t['pair_recall']}",
            recall >= t["pair_recall"],
        ),
        Check(
            "Accuracy with an always-wrong model (swap check)",
            f"{swap['always-wrong model']['accuracy']:.1%}",
            f">= {t['accuracy']:.0%}",
            swap["always-wrong model"]["accuracy"] >= t["accuracy"],
            "the model only suggests, so a bad one costs questions, not wrong labels",
        ),
        Check(
            "People labelled automatically (must be 0)",
            f"{after['person_applied']} of {after['person_payments']}",
            "0",
            after["person_applied"] == 0,
            f"before: {before['person_applied']} applied, {before['person_wrong']} wrong",
        ),
        Check(
            "Questions per 100 payments (informational)",
            f"{after['questions_per_100']:.1f} (before {before['questions_per_100']:.1f})",
            "reported",
            True,
        ),
        Check(
            "One-tap guess right when asked (informational)",
            f"{after['guess_hit_rate']:.0%}",
            "reported",
            True,
            "the model's best guess, shown as the first choice",
        ),
    ]
    better = (
        after["accuracy"] > before["accuracy"]
        and after["coverage_all"] >= before["coverage_all"] - 0.05
    )
    return CategoriseReport(
        before,
        after,
        curve,
        swap,
        precision,
        recall,
        ece,
        checks,
        better,
        "The cascade replaces the old pipeline as the default."
        if better
        else "The cascade did not clearly beat the old pipeline; it stays behind the switch and the owner decides.",
    )


def render_markdown(r: CategoriseReport) -> str:
    L = [
        "# Categorisation evaluation (before and after)",
        "",
        "Generated by `copilot eval --categorise`. Four simulated weeks, five seeded personas, the same payments for both engines. "
        "**The model here is simulated** (it knows brands, reads obvious names, guesses on odd ones, and is overconfident); real-model numbers need real keys.",
        "",
        "| Check | Measured | Target | Result |",
        "| --- | --- | --- | --- |",
    ]
    for c in r.checks:
        note = f" ({c.note})" if c.note else ""
        L.append(
            f"| {c.name} | {c.measured}{note} | {c.target} | {'PASS' if c.passed else 'FAIL'} |"
        )
    L += [
        "",
        "## Accuracy against coverage (after), by how many questions you accept",
        "",
        "| Setting | Accuracy on applied labels | Coverage of all payments | Questions per 100 |",
        "| --- | --- | --- | --- |",
    ]
    for lvl, s in r.curve.items():
        L.append(
            f"| {lvl.replace('_', ' ')} | {s['accuracy']:.1%} | {s['coverage_all']:.1%} | {s['questions_per_100']:.1f} |"
        )
    L += [
        "",
        "## Swapping the model",
        "",
        "| Model | Accuracy on applied labels | Coverage of all payments | Questions per 100 | One-tap guess right |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, sm in r.swap.items():
        L.append(
            f"| {name} | {sm['accuracy']:.1%} | {sm['coverage_all']:.1%} | {sm['questions_per_100']:.1f} | {sm['guess_hit_rate']:.0%} |"
        )
    b, a = r.before, r.after
    L += [
        "",
        "## Before and after",
        "",
        "| | Before (old pipeline) | After (cascade) |",
        "| --- | --- | --- |",
        f"| Accuracy on applied labels | {b['accuracy']:.1%} | {a['accuracy']:.1%} |",
        f"| Coverage of all payments | {b['coverage_all']:.1%} | {a['coverage_all']:.1%} |",
        f"| Questions per 100 payments | {b['questions_per_100']:.1f} | {a['questions_per_100']:.1f} |",
        f"| Model calls per 100 payments | {b['model_calls_per_100']:.1f} | {a['model_calls_per_100']:.1f} |",
        f"| Payments to people applied automatically | {b['person_applied']} ({b['person_wrong']} wrong) | {a['person_applied']} |",
        "",
        f"**Verdict:** {r.verdict}",
        "",
        "## Not measured here",
        "",
        "- A real model's behaviour (the simulation above is an assumption, stated, not a measurement).",
        "- The owner's own transactions: the gold-set loader is not built yet (open question O-1), so nothing here uses real data.",
        "",
    ]
    return "\n".join(L)


def write_report(report: CategoriseReport, path: Path | None = None) -> Path:
    out = path or (PROJECT_ROOT / "docs" / "eval_report_categorise.md")
    out.write_text(render_markdown(report), encoding="utf-8")
    return out


__all__ = ["parse_descriptor", "run_categorise_evaluation", "write_report"]
