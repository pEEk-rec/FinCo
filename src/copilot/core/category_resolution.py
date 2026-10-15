"""
Match challenge-template hints to this user's own categories and merchants.

A template says "dining_out"; the user's category might be `food` shown as "Dining", or one the
user created. Nothing about a particular user is assumed in code: the synonyms live in
config/category_hints.yaml, the categories and merchants come from the user's data, and
essential categories are never returned (PLAN_PHASE4 section 0.8.4 and 5.8).
"""

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import yaml

from copilot.core.essentials import is_essential

_PATH = Path(__file__).resolve().parents[3] / "config" / "category_hints.yaml"
_WORDS = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=1)
def _hints() -> dict:
    return yaml.safe_load(_PATH.read_text(encoding="utf-8"))


def _words(text: str) -> set[str]:
    return set(_WORDS.findall(text.lower()))


def resolve_categories(conn: sqlite3.Connection, user_id: str, hints: list[str]) -> list[str]:
    """
    The user's non-essential category ids that match any hint, in a stable order.

    A category matches when its id equals a hint, or when a word of its id or name equals a word
    of the hint or one of the hint's synonyms.
    """
    synonyms = _hints().get("category_synonyms", {})
    wanted_ids = {h.lower() for h in hints}
    wanted_words: set[str] = set()
    for hint in hints:
        wanted_words |= _words(hint)
        wanted_words |= {w.lower() for w in synonyms.get(hint, [])}
    out: list[str] = []
    rows = conn.execute(
        "SELECT id, name FROM categories WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    for r in rows:
        if is_essential(r["id"], r["name"]):
            continue
        if r["id"].lower() in wanted_ids or (_words(r["id"]) | _words(r["name"])) & wanted_words:
            out.append(r["id"])
    return out


def resolve_merchants(conn: sqlite3.Connection, user_id: str, group: str | None) -> list[str]:
    """Merchant words from the user's own debits that belong to a configured merchant group."""
    if not group:
        return []
    keywords = {k.lower() for k in _hints().get("merchant_groups", {}).get(group, [])}
    if not keywords:
        return []
    rows = conn.execute(
        "SELECT DISTINCT COALESCE(merchant_normalized, merchant_raw, '') AS m FROM transactions "
        "WHERE user_id = ? AND direction = 'debit'",
        (user_id,),
    ).fetchall()
    seen = {k for r in rows for k in keywords if k in (r["m"] or "").lower()}
    return sorted(seen)
