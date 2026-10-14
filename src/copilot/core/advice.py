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
from typing import Any, Literal

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


_CAUSAL_CLAIM = re.compile(r"\b(because|due to|caused by|driven by)\b", re.IGNORECASE)
_CONSEQUENTIAL_KINDS = {"spend_decision", "reduce_spend", "contribution_change"}


def _allowed_values(
    findings: list[Finding],
    investigations: list[Any] | None = None,
    simulations: list[Any] | None = None,
    goals: list[Any] | None = None,
    calculations: list[Any] | None = None,
) -> dict[str, list[Decimal]]:
    """Comparable values by mention kind; paise are converted to rupees."""
    amounts: list[Decimal] = []
    percents: list[Decimal] = []
    others: list[Decimal] = []

    # 1. Findings
    for f in findings:
        for n in f.numbers:
            if n.unit == "paise":
                amounts.append(Decimal(n.value) / 100)
            elif n.unit == "percent":
                percents.append(Decimal(n.value))
            else:
                others.append(Decimal(n.value))

    # 2. Investigations
    if investigations:
        for inv in investigations:
            decomp = getattr(inv, "decomposition", None)
            if decomp:
                keys = [
                    "volume_paise",
                    "ticket_paise",
                    "new_merchant_paise",
                    "stopped_merchant_paise",
                    "residual_paise",
                    "delta_spend_paise",
                    "unexplained_paise",
                ]
                for k in keys:
                    v = getattr(decomp, k, None) if not isinstance(decomp, dict) else decomp.get(k)
                    if v is not None and isinstance(v, (int, float, Decimal)):
                        amounts.append(Decimal(abs(int(v))) / 100)

            evidence_items = getattr(inv, "evidence", [])
            for ev in evidence_items:
                val = (
                    getattr(ev, "metric_value", None)
                    if not isinstance(ev, dict)
                    else ev.get("metric_value")
                )
                if isinstance(val, (int, float, Decimal)):
                    if abs(val) >= 100:
                        amounts.append(Decimal(abs(int(val))) / 100)
                    others.append(Decimal(val))

    # 3. Simulations
    if simulations:
        for sim in simulations:
            scen = getattr(sim, "scenario", None)
            if scen:
                amt = (
                    getattr(scen, "amount_paise", None)
                    if not isinstance(scen, dict)
                    else scen.get("amount_paise")
                )
                if amt is not None and isinstance(amt, (int, float, Decimal)):
                    amounts.append(Decimal(abs(int(amt))) / 100)
                m_cnt = (
                    getattr(scen, "months", None)
                    if not isinstance(scen, dict)
                    else scen.get("months")
                )
                if m_cnt is not None and isinstance(m_cnt, (int, float, Decimal)):
                    others.append(Decimal(m_cnt))

            proj = getattr(sim, "projection", None)
            if proj:
                m_projs = (
                    getattr(proj, "monthly_projections", [])
                    if not isinstance(proj, dict)
                    else proj.get("monthly_projections", [])
                )
                for mp in m_projs:
                    for field_name in ["spend_expected_paise", "surplus_expected_paise"]:
                        v = (
                            getattr(mp, field_name, None)
                            if not isinstance(mp, dict)
                            else mp.get(field_name)
                        )
                        if v is not None and isinstance(v, (int, float, Decimal)):
                            amounts.append(Decimal(abs(int(v))) / 100)

    # 4. Goals
    if goals:
        for g in goals:
            for field_name in ["target_paise", "current_paise", "required_monthly_paise"]:
                v = getattr(g, field_name, None) if not isinstance(g, dict) else g.get(field_name)
                if v is not None and isinstance(v, (int, float, Decimal)):
                    amounts.append(Decimal(abs(int(v))) / 100)
            m_rem = (
                getattr(g, "months_remaining", None)
                if not isinstance(g, dict)
                else g.get("months_remaining")
            )
            if m_rem is not None and isinstance(m_rem, (int, float, Decimal)):
                others.append(Decimal(m_rem))

    # 5. Calculations
    if calculations:
        for c in calculations:
            inputs = getattr(c, "inputs", {}) if not isinstance(c, dict) else c.get("inputs", {})
            if isinstance(inputs, dict):
                for val in inputs.values():
                    if isinstance(val, (int, float, Decimal)):
                        if abs(val) >= 100:
                            amounts.append(Decimal(abs(int(val))) / 100)
                        others.append(Decimal(val))
            res = getattr(c, "result", None) if not isinstance(c, dict) else c.get("result")
            if isinstance(res, (int, float, Decimal)):
                if abs(res) >= 100:
                    amounts.append(Decimal(abs(int(res))) / 100)
                others.append(Decimal(res))

    return {
        "amount": amounts,
        "percent": percents,
        "plain": amounts + percents + others,
    }


def _context_numbers(
    findings: list[Finding],
    investigations: list[Any] | None = None,
    simulations: list[Any] | None = None,
    goals: list[Any] | None = None,
) -> set[Decimal]:
    """Years, months, horizon counts, day numbers and subject digits allowed as plain numbers."""
    allowed: set[Decimal] = {Decimal(100), Decimal(0)}
    # Allow calendar days
    for d in range(1, 32):
        allowed.add(Decimal(d))

    for f in findings:
        if f.period and "-" in f.period:
            year, month = f.period.split("-")
            allowed |= {Decimal(year), Decimal(int(month))}
        for digits in re.findall(r"\d+", f.subject or ""):
            allowed.add(Decimal(digits))

    if investigations:
        for inv in investigations:
            for attr in ["target_month", "baseline_month"]:
                val = getattr(inv, attr, None) if not isinstance(inv, dict) else inv.get(attr)
                if val and "-" in val:
                    y, m = val.split("-")
                    allowed |= {Decimal(y), Decimal(int(m))}

    if simulations:
        for sim in simulations:
            scen = getattr(sim, "scenario", None)
            if scen:
                m_cnt = (
                    getattr(scen, "months", None)
                    if not isinstance(scen, dict)
                    else scen.get("months")
                )
                if m_cnt is not None:
                    allowed.add(Decimal(m_cnt))

    if goals:
        for g in goals:
            m_rem = (
                getattr(g, "months_remaining", None)
                if not isinstance(g, dict)
                else g.get("months_remaining")
            )
            if m_rem is not None:
                allowed.add(Decimal(m_rem))

    return allowed


def validate_advice(
    draft: AdviceDraft | Any,
    findings_by_id: dict[str, Finding],
    *,
    investigations_by_id: dict[str, Any] | None = None,
    simulations_by_id: dict[str, Any] | None = None,
    goals_by_id: dict[str, Any] | None = None,
    calculations: list[Any] | None = None,
    recommendation_kind: str | None = None,
    simulation_id: str | None = None,
    investigation_id: str | None = None,
) -> AdviceValidation:
    """
    Check one draft / recommendation against findings and evidence sources
    (PLAN_PHASE2 Section 5.8).
    Never raises on bad text; returns AdviceValidation(ok=bool, violations=list[str]).
    """
    violations = []
    text = getattr(draft, "text", str(draft))

    # 1. Finding IDs validation
    finding_ids = getattr(draft, "finding_ids", [])
    unknown = [fid for fid in finding_ids if fid not in findings_by_id]
    if unknown:
        violations.append(f"unknown finding id(s): {', '.join(unknown)}")
    cited = [findings_by_id[fid] for fid in finding_ids if fid in findings_by_id]

    # 2. Forbidden phrases check
    for reason, pattern in _FORBIDDEN:
        hit = pattern.search(text)
        if hit:
            violations.append(f"{reason}: '{hit.group(0)}'")

    # 3. Causal-claim rule (PLAN_PHASE2 Section 5.8)
    # Words asserting cause ('because', 'due to', 'caused by', 'driven by') are permitted
    # ONLY when the cited investigation's outcome is 'explained' with confidence >= 'medium'.
    hit_causal = _CAUSAL_CLAIM.search(text)
    if hit_causal:
        inv = None
        target_inv_id = investigation_id or getattr(draft, "investigation_id", None)
        if target_inv_id and investigations_by_id:
            inv = investigations_by_id.get(target_inv_id)
        elif investigations_by_id:
            evidence_list = getattr(draft, "evidence", [])
            for cand_id, cand_inv in investigations_by_id.items():
                if cand_id in finding_ids or cand_id in evidence_list:
                    inv = cand_inv
                    break
        if not inv:
            violations.append(
                f"causal claim '{hit_causal.group(0)}' "
                "requires a cited investigation with explained outcome"
            )
        else:
            outcome = getattr(inv, "outcome", None)
            confidence = getattr(inv, "confidence", None)
            if outcome != "explained" or confidence not in ("medium", "high"):
                violations.append(
                    f"causal claim '{hit_causal.group(0)}' not supported: "
                    f"investigation outcome must be 'explained' with >= medium confidence "
                    f"(got outcome='{outcome}', confidence='{confidence}')"
                )

    # 4. Consequence rule (PLAN_PHASE2 Section 5.8)
    # A recommendation of kind spend_decision, reduce_spend or contribution_change
    # requires a simulation_id.
    rec_kind = recommendation_kind or getattr(draft, "kind", None) or getattr(draft, "origin", None)
    if rec_kind in _CONSEQUENTIAL_KINDS:
        effective_sim_id = simulation_id or getattr(draft, "simulation_id", None)
        if not effective_sim_id:
            violations.append(
                f"consequential recommendation of kind '{rec_kind}' requires a simulation_id"
            )
        elif simulations_by_id is not None and effective_sim_id not in simulations_by_id:
            violations.append(
                f"unknown simulation id: '{effective_sim_id}'"
            )

    # 5. Prediction check
    has_simulation = bool(simulation_id or getattr(draft, "simulation_id", None))
    if not any(f.kind in _PREDICTION_KINDS for f in cited) and not has_simulation:
        hit = _PREDICTION.search(text)
        if hit:
            violations.append(f"predicts beyond the given findings: '{hit.group(0)}'")

    # 6. Multi-source number grounding
    inv_list = list(investigations_by_id.values()) if investigations_by_id else None
    sim_list = list(simulations_by_id.values()) if simulations_by_id else None
    goal_list = list(goals_by_id.values()) if goals_by_id else None
    calc_list = calculations or getattr(draft, "calculations", None)

    allowed = _allowed_values(
        cited,
        investigations=inv_list,
        simulations=sim_list,
        goals=goal_list,
        calculations=calc_list,
    )
    context = _context_numbers(
        cited,
        investigations=inv_list,
        simulations=sim_list,
        goals=goal_list,
    )

    for mention in extract_numbers(text):
        if mention.kind == "plain" and mention.value in context:
            continue
        if not any(matches(mention.value, v, mention.quantum) for v in allowed[mention.kind]):
            violations.append(
                f"{mention.kind} '{mention.raw}' is not in the cited findings or evidence"
            )

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
