"""
Memory retrieval ranking engine (PLAN_PHASE3 Section 5.14).

Ranking formula:
  score = subject_match_weight (exact 3, parent category 2, global 1)
          * confidence (conf_bp / 10000.0)
          * recency_weight (half-life decay)

Constraints:
1. ONLY active memories of the SAME user are retrieved.
2. Ties broken deterministically by item id ascending.
3. No embeddings (keyword and structured subject matching).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from copilot.config.phase3 import load_context_config
from copilot.core.memory import (
    compute_memory_confidence,
    determine_memory_status,
    load_memory_config,
)
from copilot.core.timeutil import from_utc_iso, now_utc
from copilot.db.repo_phase3 import list_memory_evidence
from copilot.models.phase3 import MemoryItem

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@dataclass(frozen=True)
class ScoredMemory:
    item: MemoryItem
    score: float
    subject_match_weight: int
    confidence: float
    recency_weight: float


def retrieve_relevant_memories(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    subject: str | None = None,
    parent_category: str | None = None,
    purpose: str | None = None,
    top_k: int | None = None,
    clock: datetime | None = None,
) -> list[MemoryItem]:
    """
    Retrieve and rank active behavioural memories for the given user.

    Enforces strict multi-tenant isolation, dynamic active status evaluation,
    subject match prioritization (exact=3, parent category=2, global=1),
    confidence weighting, recency decay, and deterministic tie breaking.
    """
    mem_cfg = load_memory_config()
    ctx_cfg_path = CONFIG_DIR / "context.yaml"
    ctx_cfg = load_context_config(ctx_cfg_path) if ctx_cfg_path.exists() else None

    effective_top_k = (
        top_k if top_k is not None else (ctx_cfg.top_k_memories if ctx_cfg else 5)
    )
    now_dt = now_utc(clock) if clock is not None else datetime.now(UTC)

    # Multi-tenant query: only memories of user_id, excluding forgotten
    rows = conn.execute(
        """
        SELECT * FROM memory_items
        WHERE user_id = ? AND status != 'forgotten'
        ORDER BY id ASC
        """,
        (user_id,),
    ).fetchall()

    scored_list: list[ScoredMemory] = []

    clean_subj = subject.strip().lower() if subject else None
    clean_parent = parent_category.strip().lower() if parent_category else None

    for row in rows:
        d = dict(row)
        if isinstance(d.get("statement_json"), str):
            d["statement_json"] = json.loads(d["statement_json"])
        item = MemoryItem.model_validate(d)

        # Invariant: Verify tenant isolation in Python as second defense line
        if item.user_id != user_id:
            continue

        ev_list = list_memory_evidence(conn, user_id, item.id)
        conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, now_dt, mem_cfg)
        contras = sum(1 for e in ev_list if e.polarity == "contradicts")
        cur_status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, contras, mem_cfg)

        # Invariant: ONLY active memories are retrievable
        if cur_status != "active":
            continue

        item_subj_key = item.subject_key.strip().lower()
        stmt = item.statement_json or {}
        stmt_cat = str(stmt.get("category", "")).strip().lower()
        stmt_merchant = str(stmt.get("merchant", "")).strip().lower()

        # 1. Subject match weight: exact 3, parent category 2, global 1
        subject_match_weight = 0

        if clean_subj:
            # Check exact match
            is_exact = (
                clean_subj == item_subj_key
                or f"category:{clean_subj}" == item_subj_key
                or f"merchant:{clean_subj}" == item_subj_key
                or (stmt_cat and clean_subj == stmt_cat)
                or (stmt_merchant and clean_subj == stmt_merchant)
            )
            if is_exact:
                subject_match_weight = 3

        if subject_match_weight == 0 and clean_parent:
            # Check parent category match
            is_parent = (
                f"category:{clean_parent}" in item_subj_key
                or (stmt_cat and clean_parent == stmt_cat)
            )
            if is_parent:
                subject_match_weight = 2

        if subject_match_weight == 0:
            # Check global match
            is_global = (
                item_subj_key == "global"
                or str(stmt.get("subject", "")).strip().lower() == "global"
                or item.kind == "preference"
            )
            if is_global:
                subject_match_weight = 1
            elif not clean_subj and not clean_parent:
                # If neither subject nor parent category specified, match as global baseline
                subject_match_weight = 1

        if subject_match_weight == 0:
            # Not relevant to this query subject
            continue

        # 2. Confidence component (0.0 to 1.0)
        confidence = conf_bp / 10000.0

        # 3. Recency weight component
        anchors: list[str] = []
        if item.last_evidence_at:
            anchors.append(item.last_evidence_at)
        if item.last_confirmed_at:
            anchors.append(item.last_confirmed_at)
        if item.created_at:
            anchors.append(item.created_at)

        anchor_iso = max(anchors) if anchors else None
        try:
            anchor_dt = from_utc_iso(anchor_iso) if anchor_iso else now_dt
            age_days = max(0.0, (now_dt - anchor_dt).total_seconds() / 86400.0)
        except Exception:
            age_days = 0.0

        half_life_days = mem_cfg.get("half_lives_days", {}).get(item.kind, 90)
        if half_life_days <= 0 or item.kind == "preference":
            recency_weight = 1.0
        else:
            recency_weight = math.pow(0.5, age_days / float(half_life_days))

        # Overall composite score
        score = float(subject_match_weight) * confidence * recency_weight

        scored_list.append(
            ScoredMemory(
                item=item,
                score=score,
                subject_match_weight=subject_match_weight,
                confidence=confidence,
                recency_weight=recency_weight,
            )
        )

    # Sort strictly: higher score first, ties broken by item id ascending
    scored_list.sort(key=lambda sm: (-sm.score, sm.item.id))

    return [sm.item for sm in scored_list[:effective_top_k]]
