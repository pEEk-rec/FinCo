# ruff: noqa: E501  (long SQL and prose lines)
"""
The categorisation cascade (PLAN_AGENTIC_V2, A3 and A4).

For one transaction: parse the narration, find its entity, then walk the stages in order and stop
at the first whose *calibrated* probability reaches the user's threshold:

  S0  the user's own answer for this entity            (never second-guessed)
  S1  rules: config rules, accepted user rules, card category codes
  S2  the user's nearest labelled shops (character trigrams)
  S3  the brand dictionary
  S4  the model, shown the user's most similar labelled shops
  S5  ask

A person is never labelled automatically here (the capture lane has its own person policy) and a
model is never asked about one. Every decision keeps its stage, its raw and calibrated scores and
the candidates it considered, so "why was this tagged Food?" always has an answer.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.understand.advisor import Advisor, NoAdvisor
from copilot.understand.calibration import Calibrator
from copilot.understand.config import UnderstandConfig, load_understand_config
from copilot.understand.descriptor import Descriptor, parse_descriptor
from copilot.understand.entities import EntityStore
from copilot.understand.rules import CategorizationRule, evaluate_rules, normalize_merchant

AUTO_STAGES = ("S2", "S3", "S4")


@dataclass(frozen=True)
class Item:
    tx_id: str
    raw: str
    amount_paise: int
    direction: str


@dataclass
class Decision:
    tx_id: str
    entity_id: str
    kind: str
    stage: str  # the stage that decided; S5 means nobody was sure enough
    category_id: str | None
    raw_bp: int
    p_bp: int
    applied: bool
    audit: bool = False  # applied, but the user is asked to confirm it (a spot check)
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""

    @property
    def asks_user(self) -> bool:
        return not self.applied or self.audit


def _trigrams(name: str) -> Counter[str]:
    s = f" {name.strip()} "
    return Counter(s[i : i + 3] for i in range(max(0, len(s) - 2)))


def similarity_bp(a: Counter[str], b: Counter[str]) -> int:
    if not a or not b:
        return 0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return round(10000 * dot / (na * nb)) if na and nb else 0


class Cascade:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        *,
        categories: dict[str, str],
        rules: list[CategorizationRule],
        aliases: dict[str, str] | None = None,
        advisor: Advisor | None = None,
        cfg: UnderstandConfig | None = None,
        clock: datetime | None = None,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.cfg = cfg or load_understand_config()
        self.categories = categories
        self.rules = rules
        self.aliases = aliases or {}
        self.advisor: Advisor = advisor or NoAdvisor()
        self.clock = clock
        self.store = EntityStore(conn, user_id, self.cfg, clock)
        self.calibrator = Calibrator(conn, user_id, self.cfg)
        self._calls0 = getattr(self.advisor, "calls", 0)
        self._wanted: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        self._neigh: list[tuple[str, str, str, Counter[str]]] | None = None
        self._auto_count = conn.execute(
            "SELECT COUNT(*) FROM category_decisions WHERE user_id = ? AND stage IN ('S2','S3','S4')"
            " AND superseded_by IS NULL",
            (user_id,),
        ).fetchone()[0]

    # ---- neighbours --------------------------------------------------------------------------
    def invalidate(self) -> None:
        self._neigh = None

    def _neighbours(self) -> list[tuple[str, str, str, Counter[str]]]:
        """(entity id, display name, category, trigrams) for every steadily labelled shop."""
        if self._neigh is None:
            out = []
            rows = self.conn.execute(
                "SELECT l.entity_id, l.category_id, l.recent_json, e.display_name"
                " FROM entity_labels l JOIN merchant_entities e ON e.id = l.entity_id"
                " WHERE l.user_id = ? AND e.kind != 'person' AND e.merged_into IS NULL",
                (self.user_id,),
            ).fetchall()
            for eid, cat, recent, display in rows:
                last = json.loads(recent)
                if len(last) >= 2 and last[-1] != last[-2]:
                    continue  # an unsteady answer is not evidence
                vec: Counter[str] = Counter()
                for a in self.store.aliases(eid):
                    if a["alias_type"] == "name":
                        vec += _trigrams(a["alias_value"])
                if vec:
                    out.append((eid, display, cat, vec))
            self._neigh = out
        return self._neigh

    def _similar(self, desc: Descriptor, limit: int) -> list[tuple[int, str, str, str]]:
        mine = _trigrams(desc.name)
        scored = [
            (similarity_bp(mine, vec), eid, name, cat) for eid, name, cat, vec in self._neighbours()
        ]
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [t for t in scored if t[0] >= self.cfg.neighbours.min_similarity_bp][:limit]

    # ---- stages ------------------------------------------------------------------------------
    def _s1(self, desc: Descriptor, item: Item) -> tuple[str, int, str] | None:
        normalized = normalize_merchant(item.raw, self.aliases)
        hit = evaluate_rules(normalized, item.amount_paise, item.direction, self.rules)
        if hit and hit[0] in self.categories:
            return hit[0], round(hit[1] * 10000), "a rule"
        for pattern, cat in self.conn.execute(
            "SELECT pattern, category_id FROM rule_proposals WHERE user_id = ? AND status = 'accepted'",
            (self.user_id,),
        ):
            if cat in self.categories and re.search(pattern, desc.name, re.IGNORECASE):
                return cat, 9500, "a rule you accepted"
        if desc.mcc and self.cfg.learning.mcc_map.get(desc.mcc) in self.categories:
            return self.cfg.learning.mcc_map[desc.mcc], 8500, "the card's merchant category code"
        return None

    def _s2(self, desc: Descriptor) -> tuple[str, int, list[dict]] | None:
        top = self._similar(desc, self.cfg.neighbours.k)
        if not top:
            return None
        votes: dict[str, int] = {}
        for sim, _eid, _name, cat in top:
            votes[cat] = votes.get(cat, 0) + sim
        total = sum(votes.values())
        cat = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        best_sim = max(sim for sim, _e, _n, c in top if c == cat)
        raw = round(votes[cat] / total * best_sim)
        return cat, raw, [{"shop": n, "category": c, "similarity_bp": s} for s, _e, n, c in top]

    def _s3(self, desc: Descriptor) -> tuple[str, int, str] | None:
        brand = self.store.brand_for(desc)
        if brand and brand[1] in self.categories:
            return brand[1], 9200, brand[0]
        return None

    def _s4(self, desc: Descriptor, entity_id: str) -> tuple[str, int] | None:
        row = self.conn.execute(
            "SELECT category_id, raw_bp FROM entity_enrichment WHERE user_id = ? AND entity_id = ?",
            (self.user_id, entity_id),
        ).fetchone()
        if row:
            return (row[0], row[1]) if row[0] else None
        if desc.name:  # ask later, once, for every new name together
            examples = [
                (n, c) for _s, _e, n, c in self._similar(desc, self.cfg.neighbours.examples)
            ]
            self._wanted.setdefault(entity_id, (desc.name, examples))
        return None

    @property
    def model_calls(self) -> int:
        """Requests made to the model so far (a batch of names is one request)."""
        return getattr(self.advisor, "calls", 0) - self._calls0

    def _ask_model(self) -> None:
        wanted = list(self._wanted.items())[: self.cfg.model.max_calls_per_run * 20]
        answers = self.advisor.suggest_many([(n, ex) for _eid, (n, ex) in wanted], self.categories)
        now = to_utc_iso(now_utc(self.clock))
        for (eid, _req), (cat, raw) in zip(wanted, answers, strict=True):
            self.conn.execute(
                "INSERT OR REPLACE INTO entity_enrichment (id, user_id, entity_id, category_id,"
                " raw_bp, model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"enr_{uuid.uuid4().hex[:12]}", self.user_id, eid, cat,
                 min(raw, self.cfg.model.confidence_cap_bp), type(self.advisor).__name__, now),
            )  # fmt: skip
            if cat:  # the review screen shows the model's answer as a suggestion from this table
                name = self._wanted[eid][0]
                self.conn.execute(
                    "INSERT OR REPLACE INTO llm_category_cache (id, user_id, merchant_normalized,"
                    " category_id, confidence, model, prompt_version, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'v2-cascade', ?)",
                    (f"lcc_{uuid.uuid4().hex[:12]}", self.user_id, name, cat,
                     min(raw, self.cfg.model.confidence_cap_bp) / 10000,
                     type(self.advisor).__name__, now),
                )  # fmt: skip

    # ---- deciding ----------------------------------------------------------------------------
    def decide(self, item: Item) -> Decision:
        desc = parse_descriptor(item.raw)
        res = self.store.resolve(desc)
        thr = self.cfg.threshold_bp
        cands: list[dict] = []

        def done(stage: str, cat: str | None, raw: int, p: int, why: str) -> Decision:
            applied = cat is not None and p >= thr
            audit = False
            if applied and stage in AUTO_STAGES and self.cfg.audit.every:
                self._auto_count += 1
                audit = self._auto_count % self.cfg.audit.every == 0
            return Decision(
                item.tx_id, res.entity_id, res.kind, stage if applied else "S5",
                cat if applied else None, raw, p, applied, audit, cands, why,
            )  # fmt: skip

        if res.kind == "person":
            return done("S5", None, 0, 0, "a person: always ask")

        label = self.store.get_label(res.entity_id)
        if label:
            cat, conf = label
            cands.append({"stage": "S0", "category": cat, "raw_bp": conf})
            if conf >= 10000 and cat in self.categories:
                return done("S0", cat, conf, conf, "you told me")
            return done("S5", None, 0, 0, "your last two answers disagree")

        def consider(stage: str, cat: str | None, raw: int, why: str) -> Decision | None:
            if cat is None:
                return None
            p = self.calibrator.apply(stage, raw)
            cands.append({"stage": stage, "category": cat, "raw_bp": raw, "p_bp": p, "why": why})
            return done(stage, cat, raw, p, why) if p >= thr else None

        s1 = self._s1(desc, item)
        if s1 and (d := consider("S1", s1[0], s1[1], s1[2])):
            return d
        s2 = self._s2(desc)
        if s2 and (
            d := consider("S2", s2[0], s2[1], "like " + ", ".join(n["shop"] for n in s2[2]))
        ):
            return d
        s3 = self._s3(desc)
        if s3 and (d := consider("S3", s3[0], s3[1], f"the brand {s3[2]}")):
            return d
        s4 = self._s4(desc, res.entity_id)
        if s4 and (d := consider("S4", s4[0], s4[1], "the model, shown your similar shops")):
            return d
        best = max(cands, key=lambda c: c.get("p_bp", 0), default=None)
        return done("S5", None, best["raw_bp"] if best else 0, best.get("p_bp", 0) if best else 0,
                    "not sure enough")  # fmt: skip

    def run(self, items: list[Item]) -> list[Decision]:
        self.invalidate()
        self._wanted = {}
        for i in items:  # other screens group and look up payments by this cleaned name
            self.conn.execute(
                "UPDATE transactions SET merchant_normalized = ? WHERE id = ? AND user_id = ?",
                (normalize_merchant(i.raw, self.aliases), i.tx_id, self.user_id),
            )
        out = [self.decide(i) for i in items]
        if self._wanted:  # one request for every new name, then decide those payments again
            wanted = set(self._wanted)
            self._ask_model()
            self._wanted = {}
            out = [self.decide(i) if d.entity_id in wanted and not d.applied else d
                   for i, d in zip(items, out, strict=True)]  # fmt: skip
        self.persist(out)
        return out

    def persist(self, decisions: list[Decision]) -> None:
        now = to_utc_iso(now_utc(self.clock))
        for d in decisions:
            new_id = f"dec_{uuid.uuid4().hex[:12]}"
            self.conn.execute(
                "UPDATE category_decisions SET superseded_by = ? WHERE user_id = ?"
                " AND transaction_id = ? AND superseded_by IS NULL",
                (new_id, self.user_id, d.tx_id),
            )
            self.conn.execute(
                "INSERT INTO category_decisions (id, user_id, transaction_id, entity_id, stage,"
                " category_id, raw_bp, confidence_bp, evidence_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id,
                    self.user_id,
                    d.tx_id,
                    d.entity_id,
                    d.stage,
                    d.category_id,
                    d.raw_bp,
                    d.p_bp,
                    json.dumps(
                        {
                            "candidates": d.candidates,
                            "reason": d.reason,
                            "audit": d.audit,
                            "kind": d.kind,
                        }  # fmt: skip
                    ),
                    now,
                ),
            )
