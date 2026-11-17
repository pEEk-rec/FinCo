# ruff: noqa: E501  (long SQL and prose lines)
"""
Asking well and learning from the answers (PLAN_AGENTIC_V2, A5 and A6).

`rank_questions` orders what is waiting by how much one answer is worth: how many payments it
settles over the next month, how large they are, and how unsure we are. A person is never batched
(what a payment to a friend was for varies); a shop is, so one tap settles all its spellings.

`answer_entity` is the user's answer. It labels the entity, settles every waiting payment of that
entity, teaches the calibration what each stage got right, and may *propose* a rule. A proposal is
only a proposal: nothing applies it except the user accepting it.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.understand.calibration import Calibrator
from copilot.understand.config import UnderstandConfig, load_understand_config
from copilot.understand.entities import EntityStore

_PROTECTED = ("user", "override")
_WINDOW_DAYS = 28


@dataclass
class Question:
    entity_id: str
    display_name: str
    kind: str
    tx_ids: list[str]
    score: int
    batch: bool
    best_guess: str | None
    reason: str
    audit: bool = False
    amounts_paise: list[int] = field(default_factory=list)


def rank_questions(
    conn: sqlite3.Connection,
    user_id: str,
    cfg: UnderstandConfig | None = None,
    clock: datetime | None = None,
) -> list[Question]:
    cfg = cfg or load_understand_config()
    since = to_utc_iso(now_utc(clock) - timedelta(days=_WINDOW_DAYS))
    rows = conn.execute(
        "SELECT d.entity_id, d.transaction_id, d.category_id, d.confidence_bp, d.evidence_json,"
        " e.display_name, e.kind, ABS(t.amount_paise) AS amount, t.occurred_at, t.category_source"
        " FROM category_decisions d JOIN merchant_entities e ON e.id = d.entity_id"
        " JOIN transactions t ON t.id = d.transaction_id AND t.user_id = d.user_id"
        " WHERE d.user_id = ? AND d.superseded_by IS NULL",
        (user_id,),
    ).fetchall()
    by_entity: dict[str, dict] = {}
    for r in rows:
        e = by_entity.setdefault(
            r["entity_id"],
            {
                "name": r["display_name"],
                "kind": r["kind"],
                "pending": [],
                "recent": 0,
                "amounts": [],
            },
        )
        if r["occurred_at"] >= since:
            e["recent"] += 1
        evidence = json.loads(r["evidence_json"])
        waiting = r["category_id"] is None and r["category_source"] not in _PROTECTED
        confirm = bool(evidence.get("audit")) and r["category_source"] not in _PROTECTED
        if waiting or confirm:
            cands = evidence.get("candidates", [])
            best = max(cands, key=lambda c: c.get("p_bp", 0), default=None)
            e["pending"].append((r["transaction_id"], r["amount"], best, confirm, evidence))
            e["amounts"].append(r["amount"])
    out: list[Question] = []
    for eid, e in by_entity.items():
        if not e["pending"]:
            continue
        person = e["kind"] == "person"
        n_pending = len(e["pending"])
        # A shop's answer covers what is waiting and what is likely to come in the next four weeks.
        future = n_pending if person else max(n_pending, e["recent"])
        avg = sum(e["amounts"]) // n_pending
        best = max(
            (p[2] for p in e["pending"] if p[2]), key=lambda c: c.get("p_bp", 0), default=None
        )
        uncertainty = 10000 - (best.get("p_bp", 0) if best else 0)
        score = future * avg * max(uncertainty, 500) // 10000
        out.append(
            Question(
                entity_id=eid,
                display_name=e["name"],
                kind=e["kind"],
                tx_ids=[p[0] for p in e["pending"]],
                score=score,
                batch=not person and n_pending > 1,
                best_guess=best["category"] if best else None,
                reason=e["pending"][0][4].get("reason", ""),
                audit=all(p[3] for p in e["pending"]),
                amounts_paise=e["amounts"],
            )
        )
    out.sort(key=lambda q: (-q.score, q.entity_id))
    return out


# ---- answering ---------------------------------------------------------------------------------
def _tx_state(r: sqlite3.Row) -> dict:
    return {
        "category_id": r["category_id"],
        "category_source": r["category_source"],
        "category_confidence": r["category_confidence"],
        "needs_review": r["needs_review"],
    }


def answer_entity(
    conn: sqlite3.Connection,
    user_id: str,
    entity_id: str,
    category_id: str,
    *,
    cfg: UnderstandConfig | None = None,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
    teach: bool = True,
) -> dict:
    """The user's answer for a shop. `teach=False` is for simulated data that must not teach."""
    cfg = cfg or load_understand_config()
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can say what a shop is.")
    if (
        conn.execute(
            "SELECT 1 FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id)
        ).fetchone()
        is None
    ):
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Unknown category {category_id!r}.")
    store = EntityStore(conn, user_id, cfg, clock)
    ent = store.entity(entity_id)
    if ent is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "Unknown shop.")
    entity_id = ent["id"]
    now = to_utc_iso(now_utc(clock))

    # what each stage would have said, scored against the answer (done before labelling)
    latest = conn.execute(
        "SELECT evidence_json FROM category_decisions WHERE user_id = ? AND entity_id = ?"
        " AND superseded_by IS NULL ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id, entity_id),
    ).fetchone()
    if teach and latest:
        cal = Calibrator(conn, user_id, cfg)
        for c in json.loads(latest[0]).get("candidates", []):
            if c["stage"] in ("S1", "S2", "S3", "S4"):
                cal.update(c["stage"], c["raw_bp"], c["category"] == category_id)

    label_change = store.label(entity_id, category_id, actor=actor, run_id=run_id)

    ids = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT d.transaction_id FROM category_decisions d"
            " WHERE d.user_id = ? AND d.entity_id = ? AND d.superseded_by IS NULL",
            (user_id, entity_id),
        )
    ]
    before_tx: dict[str, dict] = {}
    for tid in ids:
        row = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND id = ?", (user_id, tid)
        ).fetchone()
        if row is None or row["category_source"] in _PROTECTED:
            continue
        before_tx[tid] = _tx_state(row)
        conn.execute(
            "UPDATE transactions SET category_id = ?, category_source = 'user',"
            " category_confidence = 1.0, needs_review = 0 WHERE user_id = ? AND id = ?",
            (category_id, user_id, tid),
        )
        d_id = f"dec_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "UPDATE category_decisions SET superseded_by = ? WHERE user_id = ?"
            " AND transaction_id = ? AND superseded_by IS NULL",
            (d_id, user_id, tid),
        )
        conn.execute(
            "INSERT INTO category_decisions (id, user_id, transaction_id, entity_id, stage,"
            " category_id, raw_bp, confidence_bp, evidence_json, created_at)"
            " VALUES (?, ?, ?, ?, 'S0', ?, 10000, 10000, ?, ?)",
            (d_id, user_id, tid, entity_id, category_id,
             json.dumps({"candidates": [], "reason": "you told me", "audit": False}), now),
        )  # fmt: skip

    before_over: dict[str, str | None] = {}
    for a in store.aliases(entity_id):
        if a["alias_type"] != "name":
            continue
        merchant = a["alias_value"]
        prev = conn.execute(
            "SELECT category_id FROM merchant_overrides WHERE user_id = ? AND merchant_normalized = ?",
            (user_id, merchant),
        ).fetchone()
        before_over[merchant] = prev[0] if prev else None
        conn.execute(
            "INSERT INTO merchant_overrides (id, user_id, merchant_normalized, category_id,"
            " created_by, created_at) VALUES (?, ?, ?, ?, 'user', ?)"
            " ON CONFLICT(user_id, merchant_normalized) DO UPDATE SET"
            " category_id = excluded.category_id, created_at = excluded.created_at",
            (str(uuid.uuid4()), user_id, merchant, category_id, now),
        )

    proposal = (
        maybe_propose_rule(conn, user_id, entity_id, category_id, cfg, clock) if teach else None
    )
    audit_id = record_event(
        conn, user_id=user_id, actor=actor, event_type="entity_answered",
        reason=f"Shop answered {category_id}; {len(before_tx)} payment(s) settled", run_id=run_id,
        entity_type="entity_answer", entity_id=entity_id,
        before_data={"label": label_change["before"], "transactions": before_tx,
                     "overrides": before_over},
        after_data={"label": label_change["after"], "transactions": list(before_tx)},
        clock=clock,
    )  # fmt: skip
    return {
        "entity_id": entity_id,
        "settled": len(before_tx),
        "audit_event_id": audit_id,
        "rule_proposal": proposal,
    }


def undo_answer(
    conn: sqlite3.Connection, user_id: str, entity_id: str, before: dict, after: dict
) -> None:
    store = EntityStore(conn, user_id)
    current = store.get_label(entity_id)
    if current is None or current[0] != after["label"]["category_id"]:
        raise ToolFailure(ErrorCode.STALE_DATA, "Undo refused: the answer changed afterwards.")
    store.restore_label(entity_id, before["label"])
    for tid, st in before["transactions"].items():
        conn.execute(
            "UPDATE transactions SET category_id = ?, category_source = ?, category_confidence = ?,"
            " needs_review = ? WHERE user_id = ? AND id = ?",
            (st["category_id"], st["category_source"], st["category_confidence"],
             st["needs_review"], user_id, tid),
        )  # fmt: skip
    for merchant, prev in before.get("overrides", {}).items():
        if prev is None:
            conn.execute(
                "DELETE FROM merchant_overrides WHERE user_id = ? AND merchant_normalized = ?",
                (user_id, merchant),
            )
        else:
            conn.execute(
                "UPDATE merchant_overrides SET category_id = ? WHERE user_id = ?"
                " AND merchant_normalized = ?",
                (prev, user_id, merchant),
            )


# ---- rule proposals ----------------------------------------------------------------------------
def _first_word(name: str) -> str | None:
    word = name.split()[0] if name.split() else ""
    return word if len(word) >= 4 and word.isalpha() else None


def maybe_propose_rule(
    conn: sqlite3.Connection,
    user_id: str,
    entity_id: str,
    category_id: str,
    cfg: UnderstandConfig,
    clock: datetime | None = None,
) -> str | None:
    """Several distinct shops starting with the same word, all answered the same way."""
    row = conn.execute(
        "SELECT alias_value FROM entity_aliases WHERE user_id = ? AND entity_id = ?"
        " AND alias_type = 'name' ORDER BY created_at, id LIMIT 1",
        (user_id, entity_id),
    ).fetchone()
    word = _first_word(row[0]) if row else None
    if not word:
        return None
    same, other = 0, 0
    for _eid, cat, name in conn.execute(
        "SELECT l.entity_id, l.category_id, a.alias_value FROM entity_labels l"
        " JOIN entity_aliases a ON a.entity_id = l.entity_id AND a.alias_type = 'name'"
        " JOIN merchant_entities e ON e.id = l.entity_id"
        " WHERE l.user_id = ? AND e.kind != 'person' AND e.merged_into IS NULL",
        (user_id,),
    ):
        if _first_word(name) == word:
            same, other = (same + 1, other) if cat == category_id else (same, other + 1)
    if other or same < cfg.learning.rule_after:
        return None
    pattern = rf"^{re.escape(word)}\b"
    exists = conn.execute(
        "SELECT 1 FROM rule_proposals WHERE user_id = ? AND pattern = ? AND category_id = ?",
        (user_id, pattern, category_id),
    ).fetchone()
    if exists:
        return None
    pid = f"rul_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO rule_proposals (id, user_id, pattern, category_id, evidence_json, status,"
        " created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (pid, user_id, pattern, category_id, json.dumps({"first_word": word, "shops": same}),
         to_utc_iso(now_utc(clock))),
    )  # fmt: skip
    return pid


def decide_rule(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_id: str,
    accept: bool,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> dict:
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can accept a rule.")
    row = conn.execute(
        "SELECT * FROM rule_proposals WHERE user_id = ? AND id = ?", (user_id, proposal_id)
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "No such proposal.")
    if row["status"] != "pending":
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"That proposal was already {row['status']}.")
    status = "accepted" if accept else "dismissed"
    conn.execute(
        "UPDATE rule_proposals SET status = ?, decided_at = ? WHERE user_id = ? AND id = ?",
        (status, to_utc_iso(now_utc(clock)), user_id, proposal_id),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type=f"rule_{status}",
        reason=f"Rule proposal {status}", entity_type="rule_proposal", entity_id=proposal_id,
        metadata={"pattern": row["pattern"], "category_id": row["category_id"]}, clock=clock,
    )  # fmt: skip
    return {"id": proposal_id, "status": status, "pattern": row["pattern"]}


def answer_transaction(
    conn: sqlite3.Connection,
    user_id: str,
    tx_id: str,
    category_id: str,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> dict:
    """Answer for one payment only. This is how a person is handled: what a payment to a friend was
    for varies, so it never becomes a rule for the friend. A shop answered here is answered whole."""
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can say what a payment was.")
    d = conn.execute(
        "SELECT entity_id FROM category_decisions WHERE user_id = ? AND transaction_id = ?"
        " AND superseded_by IS NULL",
        (user_id, tx_id),
    ).fetchone()
    if d is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "That payment has not been looked at yet.")
    store = EntityStore(conn, user_id, clock=clock)
    ent = store.entity(d[0])
    if ent is not None and ent["kind"] != "person":
        return answer_entity(
            conn, user_id, ent["id"], category_id, actor=actor, run_id=run_id, clock=clock
        )
    if (
        conn.execute(
            "SELECT 1 FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id)
        ).fetchone()
        is None
    ):
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"Unknown category {category_id!r}.")
    row = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND id = ?", (user_id, tx_id)
    ).fetchone()
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, "No such payment.")
    before = _tx_state(row)
    conn.execute(
        "UPDATE transactions SET category_id = ?, category_source = 'user', category_confidence = 1.0,"
        " needs_review = 0 WHERE user_id = ? AND id = ?",
        (category_id, user_id, tx_id),
    )
    new_id = f"dec_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "UPDATE category_decisions SET superseded_by = ? WHERE user_id = ? AND transaction_id = ?"
        " AND superseded_by IS NULL",
        (new_id, user_id, tx_id),
    )
    conn.execute(
        "INSERT INTO category_decisions (id, user_id, transaction_id, entity_id, stage, category_id,"
        " raw_bp, confidence_bp, evidence_json, created_at) VALUES (?, ?, ?, ?, 'S0', ?, 10000, 10000, ?, ?)",
        (new_id, user_id, tx_id, d[0], category_id,
         json.dumps({"candidates": [], "reason": "you told me", "audit": False}),
         to_utc_iso(now_utc(clock))),
    )  # fmt: skip
    audit_id = record_event(
        conn, user_id=user_id, actor=actor, event_type="payment_answered",
        reason=f"Payment answered {category_id}", run_id=run_id, entity_type="transaction",
        entity_id=tx_id, before_data=before,
        after_data={"category_id": category_id, "category_source": "user", "category_confidence": 1.0},
        clock=clock,
    )  # fmt: skip
    return {"entity_id": d[0], "settled": 1, "audit_event_id": audit_id, "rule_proposal": None}
