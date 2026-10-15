"""
Which categories are essential, and so can never be the target of a reduction.

A category counts as essential when its id, its display name, or any word in either matches the
configured list. Matching on ids alone is not enough: this product's rent category has the id
`housing`, utilities are `bills`, and users create categories of their own ("Flat rent").
Used by experiments, challenge offers, goal decomposition and LLM-proposed specs, so the safety
rule is decided in one place (PLAN_PHASE4 section 5.8, rule 1).
"""

import re
import sqlite3
from functools import lru_cache

from copilot.config.phase4 import load_phase4_safety_config

_WORDS = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


@lru_cache(maxsize=1)
def _rules() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(whole ids and names, exact words, word prefixes) from config/phase4_safety.yaml."""
    cfg = load_phase4_safety_config()
    whole = frozenset(" ".join(_tokens(c)) for c in cfg.essential_categories)
    exact: set[str] = set()
    prefixes: set[str] = set()
    for word in cfg.essential_keywords:
        word = word.strip().lower()
        if word.endswith("*"):
            prefixes.add(word[:-1])
        elif word:
            exact.add(word)
    return whole, frozenset(exact), frozenset(prefixes)


def is_essential(category_id: str, category_name: str | None = None) -> bool:
    """True when the id or the name marks the category as essential spending."""
    whole, exact, prefixes = _rules()
    for text in (category_id, category_name or ""):
        if not text:
            continue
        tokens = _tokens(text)
        if " ".join(tokens) in whole:
            return True
        for token in tokens:
            if token in exact or any(token.startswith(p) for p in prefixes):
                return True
    return False


def essential_category_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    """Ids of this user's categories that are essential, by id, name or keyword."""
    rows = conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,)).fetchall()
    return {r["id"] for r in rows if is_essential(r["id"], r["name"])}


def first_essential(conn: sqlite3.Connection, user_id: str, categories: list[str]) -> str | None:
    """The first of `categories` that is essential (an id or a name), or None."""
    names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    }
    for cat in categories:
        if is_essential(cat, names.get(cat)):
            return cat
    return None
