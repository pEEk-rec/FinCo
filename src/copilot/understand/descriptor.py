"""
Descriptor parsing (PLAN_AGENTIC_V2, A1): a bank narration becomes structured parts.

`UPI/628912345678/SWIGGY8/swiggy8@ybl/HDFC` becomes rail upi, name "swiggy", handle ybl, brand
"swiggy", reference. The parser never invents a VPA: a field is empty unless the text had it.
Two things matter downstream: the *squashed* name (so a bank that truncates "LANTERN CAFE TRADERS"
to "LANTERNCAFETRA" still lines up with the longer form) and whether this looks like a person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from copilot.understand.config import NarrationConfig, load_narration_config
from copilot.understand.rules import normalize_merchant


@dataclass(frozen=True)
class Descriptor:
    raw_rail: str  # upi, card, imps, neft, mandate, atm, bank, other
    name: str  # cleaned, lowercase, spaces kept
    squash: str  # cleaned with every space removed
    vpa: str | None
    handle: str | None  # the part after @
    brand: str | None  # the VPA's local part without trailing digits
    ref: str | None
    city: str | None
    card4: str | None
    person_hint: bool  # looks like a person-to-person payment
    mcc: str | None  # a card merchant category code, when the narration carries one
    format: str  # which layout matched, or "plain"

    @property
    def key_name(self) -> str:
        return self.name


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, str, re.Pattern[str]]]:
    cfg = load_narration_config()
    return [(f.name, f.rail, re.compile(f.pattern, re.IGNORECASE)) for f in cfg.formats]


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_DIGITS = re.compile(r"\d+$")
_TRAILING_JUNK = re.compile(r"\b(?:upi|pay|payment|bank|ltd|pvt|limited)\b$", re.IGNORECASE)


_MCC = re.compile(r"\bMCC[:\s-]*(\d{4})\b", re.IGNORECASE)


def _mcc(text: str) -> str | None:
    m = _MCC.search(text)
    return m.group(1) if m else None


def _brand(vpa: str | None) -> str | None:
    if not vpa or "@" not in vpa:
        return None
    local = vpa.split("@", 1)[0].lower()
    if local.isdigit():
        return None  # a phone number is not a brand
    local = _DIGITS.sub("", local)
    local = re.sub(r"[^a-z]", "", local)
    return local if len(local) >= 3 else None


def _looks_like_person(
    name: str, vpa: str | None, rail: str, business: set[str], person_rails: set[str]
) -> bool:
    if vpa and vpa.split("@", 1)[0].isdigit():
        return True  # a phone number VPA
    if rail not in person_rails:
        return False
    tokens = name.split()
    if not tokens or len(tokens) > 3:
        return False
    if any(t in business for t in tokens):
        return False
    return rail in ("imps", "neft") or not _brand(vpa)


def parse_descriptor(raw: str, cfg: NarrationConfig | None = None) -> Descriptor:
    cfg = cfg or load_narration_config()
    business = set(cfg.business_words)
    person_rails = set(cfg.person_rails)
    text = " ".join(str(raw).split())
    mcc = _mcc(text)
    text = _MCC.sub("", text).strip()
    for fmt_name, rail, pattern in _compiled():
        m = pattern.search(text)
        if not m:
            continue
        g = m.groupdict()
        name_raw = (g.get("name") or "").strip()
        vpa = (g.get("vpa") or "").lower() or None
        if rail == "atm":
            name_raw = name_raw or "atm cash"
        name = normalize_merchant(name_raw) if name_raw else ""
        brand = _brand(vpa)
        if not name and brand:
            name = brand  # UPI to a VPA only: the VPA's brand is the best name there is
        name = _TRAILING_JUNK.sub("", name).strip()
        if brand and squash(name) != brand and squash(name).rstrip("0123456789") == brand:
            name = brand  # swiggy8 is swiggy
        return Descriptor(
            raw_rail=rail,
            name=name,
            squash=squash(name),
            vpa=vpa,
            handle=vpa.split("@", 1)[1] if vpa else None,
            brand=brand,
            ref=g.get("ref"),
            city=(g.get("city") or "").lower() or None,
            card4=g.get("card"),
            person_hint=_looks_like_person(name, vpa, rail, business, person_rails),
            mcc=mcc,
            format=fmt_name,
        )
    name = normalize_merchant(text)
    return Descriptor(
        raw_rail="other", name=name, squash=squash(name), vpa=None, handle=None, brand=None,
        ref=None, city=None, card4=None, person_hint=False, mcc=mcc, format="plain",
    )  # fmt: skip
