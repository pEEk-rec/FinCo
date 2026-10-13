"""
Advice validator and template fallback: pure, deterministic, no DB, no LLM, no clock.

This is the main safety piece of Phase 1 (PLAN_PHASE1 section 5.6). The LLM may only narrate
findings; `validate_advice` rejects any text that mentions an unknown finding, a number that
is not in the referenced findings, or forbidden content.

Number matching rule (decided 2026-10-13, see docs/decisions.md)
-----------------------------------------------------------------
Each number written in the text has a *quantum*: the place value of its last displayed digit
times its suffix multiplier ("1,234" -> 1, "1,234.5" -> 0.1, "1.2k" -> 100, "1 lakh" -> 100000).
A written number W matches a true value T when:
    abs(W - T) <= min(half of the last displayed digit, 5% of the stated value)
For example:
- "1 lakh" (W = 100,000, quantum = 100,000): tolerance = min(50,000, 5,000) = 5,000
  -> accepted range is [95,000, 105,000]
- "₹1.2k" (W = 1,200, quantum = 100): tolerance = min(50, 60) = 50 -> [1,150, 1,250]
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from string import Formatter
from typing import Literal

import yaml

from copilot.models.findings import AdviceDraft, Finding

MentionKind = Literal["amount", "percent", "plain"]

_MULTIPLIERS = {
    "k": Decimal(1_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "l": Decimal(100_000),
    "cr": Decimal(10_000_000),
    "crore": Decimal(10_000_000),
}

# Currency prefix, number (western or Indian grouping), optional suffix, optional % / rupees.
_NUMBER_RE = re.compile(
    r"(?P<cur>₹|\bRs\.?|\bINR)?\s*"
    r"(?<![\w.,])(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d,]*\d)"
    r"(?:\s?(?P<suf>k|lakhs?|L|cr|crore)\b)?"
    r"(?:\s?(?P<pct>%|percent\b))?"
    r"(?:\s?(?P<rup>rupees\b|rs\b))?",
    re.IGNORECASE,
)

_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "names or recommends an investment product",
        re.compile(
            r"\b(stocks?|equit(?:y|ies)|mutual funds?|index funds?|etfs?|bonds?|"
            r"crypto(?:currency|currencies)?|bitcoin|fixed deposits?|ulips?|sips?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "instructs moving or paying money",
        re.compile(r"\b(transfer|pay|send|invest|deposit|withdraw|move)\b", re.IGNORECASE),
    ),
    (
        "makes a guarantee",
        re.compile(
            r"\b(guarantee[sd]?|risk[- ]free|assured returns?|definitely|no risk)\b",
            re.IGNORECASE,
        ),
    ),
)
_PREDICTION = re.compile(
    r"\b(will|next month|going to|expected to|projected|forecast(?:ed)?)\b", re.IGNORECASE
)
_PREDICTION_KINDS = {"forecast"}


@dataclass(frozen=True)
class NumberMention:
    """A number found in advice text."""

    raw: str
    value: Decimal
    quantum: Decimal
    kind: MentionKind


@dataclass
class AdviceValidation:
    """Validator verdict; `violations` explains every rejection."""

    ok: bool
    violations: list[str] = field(default_factory=list)


def extract_numbers(text: str) -> list[NumberMention]:
    """Every number written in `text`, with its unit kind and rounding quantum."""
    mentions = []
    for m in _NUMBER_RE.finditer(text):
        digits = m.group("num").replace(",", "")
        value = Decimal(digits)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        multiplier = _MULTIPLIERS[m.group("suf").lower()] if m.group("suf") else Decimal(1)
        kind: MentionKind
        if m.group("pct"):
            kind = "percent"
        elif m.group("cur") or m.group("rup") or m.group("suf"):
            kind = "amount"
        else:
            kind = "plain"
        mentions.append(
            NumberMention(
                raw=m.group(0).strip(),
                value=value * multiplier,
                quantum=Decimal(1).scaleb(-decimals) * multiplier,
                kind=kind,
            )
        )
    return mentions


def matches(written: Decimal, true_value: Decimal, quantum: Decimal) -> bool:
    """True if `true_value` is within tolerance of `written`.

    Rule: tolerance = min(half of the last displayed digit, 5% of the stated value).
    """
    t = abs(true_value)
    w = abs(written)
    half_last_digit = quantum / Decimal(2)
    five_percent = w * Decimal("0.05")
    tolerance = min(half_last_digit, five_percent)
    return abs(w - t) <= tolerance


def _allowed_values(findings: list[Finding]) -> dict[str, list[Decimal]]:
    """Comparable values by mention kind; paise are converted to rupees."""
    amounts: list[Decimal] = []
    percents: list[Decimal] = []
    others: list[Decimal] = []
    for f in findings:
        for n in f.numbers:
            if n.unit == "paise":
                amounts.append(Decimal(n.value) / 100)
            elif n.unit == "percent":
                percents.append(Decimal(n.value))
            else:
                others.append(Decimal(n.value))
    return {
        "amount": amounts,
        "percent": percents,
        "plain": amounts + percents + others,
    }


def _context_numbers(findings: list[Finding]) -> set[Decimal]:
    """Years, months and subject digits that may appear as bare numbers."""
    allowed: set[Decimal] = set()
    for f in findings:
        year, month = f.period.split("-")
        allowed |= {Decimal(year), Decimal(int(month))}
        for digits in re.findall(r"\d+", f.subject or ""):
            allowed.add(Decimal(digits))
    return allowed


def validate_advice(draft: AdviceDraft, findings_by_id: dict[str, Finding]) -> AdviceValidation:
    """Check one draft against the findings it cites. Never raises on bad text."""
    violations = []
    unknown = [fid for fid in draft.finding_ids if fid not in findings_by_id]
    if unknown:
        violations.append(f"unknown finding id(s): {', '.join(unknown)}")
    cited = [findings_by_id[fid] for fid in draft.finding_ids if fid in findings_by_id]

    for reason, pattern in _FORBIDDEN:
        hit = pattern.search(draft.text)
        if hit:
            violations.append(f"{reason}: '{hit.group(0)}'")
    if not any(f.kind in _PREDICTION_KINDS for f in cited):
        hit = _PREDICTION.search(draft.text)
        if hit:
            violations.append(f"predicts beyond the given findings: '{hit.group(0)}'")

    allowed = _allowed_values(cited)
    context = _context_numbers(cited)
    for mention in extract_numbers(draft.text):
        if mention.kind == "plain" and mention.value in context:
            continue
        if not any(matches(mention.value, v, mention.quantum) for v in allowed[mention.kind]):
            violations.append(f"{mention.kind} '{mention.raw}' is not in the cited findings")

    return AdviceValidation(ok=not violations, violations=violations)


# ---------------------------------------------------------------------------------------------
# Formatting and templates
# ---------------------------------------------------------------------------------------------

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_inr(paise: int) -> str:
    """Indian-grouped rupees: 12345678 -> '₹1,23,456.78'; whole rupees drop '.00'."""
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("paise must be an int")
    sign = "-" if paise < 0 else ""
    rupees, paisa = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    fraction = f".{paisa:02d}" if paisa else ""
    return f"{sign}₹{digits}{fraction}"


def period_label(period: str) -> str:
    """'2024-10' -> 'October 2024'."""
    year, month = period.split("-")
    return f"{_MONTHS[int(month) - 1]} {year}"


@dataclass(frozen=True)
class AdviceTemplates:
    """Deterministic fallback text and assumptions per finding kind."""

    templates: dict[str, str]
    default: str
    assumptions: dict[str, list[str]]

    def assumptions_for(self, kind: str) -> list[str]:
        """Assumptions recorded with advice about this kind of finding."""
        return list(self.assumptions.get(kind, []))


def load_templates(path: str | Path) -> AdviceTemplates:
    """Load and sanity-check config/advice_templates.yaml."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    templates = data.get("templates") or {}
    default = data.get("default")
    if not isinstance(templates, dict) or not isinstance(default, str) or not default.strip():
        raise ValueError(f"{path}: needs a 'templates' mapping and a non-empty 'default'")
    for name, text in [*templates.items(), ("default", default)]:
        if not isinstance(text, str):
            raise ValueError(f"{path}: template '{name}' must be a string")
        list(Formatter().parse(text))  # raises ValueError on malformed braces
    assumptions = data.get("assumptions") or {}
    return AdviceTemplates(templates=dict(templates), default=default, assumptions=assumptions)


def _placeholders(finding: Finding) -> dict[str, str]:
    values = {
        "subject": finding.subject or finding.description,
        "description": finding.description,
        "period_label": period_label(finding.period),
    }
    for n in finding.numbers:
        values[n.label] = format_inr(n.value) if n.unit == "paise" else str(n.value)
    return values


def render_template(finding: Finding, templates: AdviceTemplates) -> str:
    """
    Deterministic advice text for one finding.

    Uses the kind's template, or the default when the kind has none or a placeholder is
    missing. The result is guaranteed to pass `validate_advice`; if it does not, the template
    itself is wrong and a ValueError is raised instead of emitting unvalidated text.
    """
    values = _placeholders(finding)
    text = None
    if finding.kind in templates.templates:
        try:
            text = templates.templates[finding.kind].format(**values)
        except (KeyError, IndexError):
            text = None
    if text is None:
        text = templates.default.format(**values)
    verdict = validate_advice(
        AdviceDraft(finding_ids=[finding.id], text=text), {finding.id: finding}
    )
    if not verdict.ok:
        raise ValueError(
            f"template for kind '{finding.kind}' produced invalid advice: {verdict.violations}"
        )
    return text
