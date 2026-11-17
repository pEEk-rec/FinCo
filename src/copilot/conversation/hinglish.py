"""
Hinglish questions (PLAN_AGENTIC_V2, A10): "is mahine khane pe kitna gaya?"

A small, config-driven translator that runs *before* the existing rule reader: it replaces the
Hinglish words and phrases it knows with their English meaning and leaves everything else alone,
so the same intents, entities and periods work. It is a layer, not a second reader: anything it
does not know passes through unchanged, and the model-first reader sees the original words.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

CONFIG = Path(__file__).resolve().parents[3] / "config" / "hinglish.yaml"


class HinglishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phrases: dict[str, str]  # longest first when applied
    words: dict[str, str]


@lru_cache(maxsize=1)
def load_hinglish(path: Path | None = None) -> HinglishConfig:
    return HinglishConfig.model_validate(yaml.safe_load((path or CONFIG).read_text("utf-8")))


@lru_cache(maxsize=1)
def _compiled() -> tuple[list[tuple[re.Pattern[str], str]], re.Pattern[str], dict[str, str]]:
    cfg = load_hinglish()
    phrases = [
        (re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
        for k, v in sorted(cfg.phrases.items(), key=lambda kv: -len(kv[0]))
    ]
    words = {k.lower(): v for k, v in cfg.words.items()}
    pattern = re.compile(
        r"\b(" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    return phrases, pattern, words


def looks_hinglish(text: str) -> bool:
    _phrases, pattern, _words = _compiled()
    return len(pattern.findall(text)) >= 2


def to_english(text: str) -> str:
    """The question with known Hinglish words and phrases in English (unchanged if none)."""
    if not looks_hinglish(text) and not any(p.search(text) for p, _ in _compiled()[0]):
        return text
    phrases, pattern, words = _compiled()
    out = text
    for p, repl in phrases:
        out = p.sub(repl, out)
    out = pattern.sub(lambda m: words[m.group(1).lower()], out)
    return " ".join(out.split())
