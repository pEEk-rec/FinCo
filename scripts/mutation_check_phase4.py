"""
Mutation checks for the Phase 4 safety rules (PLAN_PHASE4 section 8).

For each rule, a small deliberate break is made in the code or configuration, the tests that
guard the rule are run, and they must FAIL. The file is then restored and verified byte for byte.
A rule whose break goes unnoticed has no test that protects it.

    python scripts/mutation_check_phase4.py            # run all and write the report
    python scripts/mutation_check_phase4.py --rule 7   # one rule

Nothing is left modified: each file is restored in a `finally` block and compared by hash.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = "tests/golden/phase4/test_golden_phase4.py"


@dataclass(frozen=True)
class Mutation:
    rule: int
    name: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        1,
        "essential check always says 'not essential'",
        "src/copilot/core/essentials.py",
        '    whole, exact, prefixes = _rules()\n    for text in (category_id, category_name or ""):',  # noqa: E501
        '    return False\n    whole, exact, prefixes = _rules()\n    for text in (category_id, category_name or ""):',  # noqa: E501
        (
            "tests/core/test_phase4_corrections.py",
            f"{GOLDEN}::test_01_essential_categories_are_never_offered_designed_or_proposed",
        ),
    ),
    Mutation(
        1,
        "design_experiment skips the essential check",
        "src/copilot/core/experiments.py",
        "blocked = first_essential(conn, user_id, categories)",
        "blocked = None",
        ("tests/core/test_phase4_corrections.py", "tests/core/test_experiments_lifecycle.py"),
    ),
    Mutation(
        2,
        "explicit target below half of the usual value is accepted",
        "src/copilot/core/experiments.py",
        "            if target_val < min_target:",
        "            if False:",
        (
            f"{GOLDEN}::test_02_the_target_never_falls_below_half_of_the_usual_value",
            "tests/core/test_experiments_lifecycle.py",
        ),
    ),
    Mutation(
        3,
        "reward allowlist check does nothing",
        "src/copilot/core/rewards.py",
        "    c = cfg or load_rewards_config()\n    forbidden_terms =",
        "    return\n    c = cfg or load_rewards_config()\n    forbidden_terms =",
        ("tests/core/test_rewards.py",),
    ),
    Mutation(
        3,
        "XP can be awarded as a non-positive amount (never decreases)",
        "src/copilot/core/rewards.py",
        "    points_to_award = min(rule.points, remaining_cap)",
        "    points_to_award = -min(rule.points, remaining_cap)",
        ("tests/core/test_rewards.py", f"{GOLDEN}::test_09_xp_is_never_awarded_twice"),
    ),
    Mutation(
        4,
        "pressure phrases are not scanned",
        "src/copilot/core/rewards.py",
        "    for phrase in safety_cfg.pressure_phrases:",
        "    for phrase in []:",
        ("tests/core/test_rewards.py",),
    ),
    Mutation(
        4,
        "encouragement to skip essentials is not scanned",
        "src/copilot/core/rewards.py",
        "    for enc in safety_cfg.forbidden_encouragements:",
        "    for enc in []:",
        ("tests/core/test_rewards.py",),
    ),
    Mutation(
        5,
        "'beyond usual range' no longer needs the minimum effect",
        "src/copilot/core/baseline.py",
        "        if observed_value < low and (median - observed_value) >= min_effect:",
        "        if observed_value < low:",
        ("tests/core/test_baseline_and_metrics.py",),
    ),
    Mutation(
        5,
        "causal claims are not rejected",
        "src/copilot/core/learning_loop.py",
        "    lower = text.lower()\n    for term in FORBIDDEN_CAUSAL_TERMS:",
        "    lower = text.lower()\n    for term in []:",
        (
            "tests/core/test_learning_loop.py",
            f"{GOLDEN}::test_24_no_review_ever_says_the_challenge_caused_the_result",
        ),
    ),
    Mutation(
        6,
        "an optional target raise is applied automatically",
        "src/copilot/core/adaptive.py",
        '            kind="raise_target_optional",\n            reason_code="ahead_at_midpoint_wide_margin",',  # noqa: E501
        '            kind="raise_target_optional",\n            status="auto_applied_pause",\n            reason_code="ahead_at_midpoint_wide_margin",',  # noqa: E501
        ("tests/core/test_adaptive.py", f"{GOLDEN}::test_10_raising_a_target_is_never_automatic"),
    ),
    Mutation(
        7,
        "a flagged win earns target XP without confirmation",
        "src/copilot/core/rewards.py",
        '    if integ.get("confirmation_required") is True:',
        "    if False:",
        (
            "tests/core/test_rewards.py",
            f"{GOLDEN}::test_07_a_recategorisation_assisted_win_asks_for_confirmation_before_xp",
        ),
    ),
    Mutation(
        8,
        "weekly offers use a random seed",
        "src/copilot/core/challenges.py",
        "rng_seed = seed if seed is not None else _week_seed(user_id, today_str)",
        'rng_seed = seed if seed is not None else __import__("random").randint(1, 10**9)',
        (
            "tests/core/test_offer_policy_wiring.py",
            f"{GOLDEN}::test_12_offers_are_reproducible_by_seed_with_logged_propensities",
        ),
    ),
    Mutation(
        8,
        "offers store a constant instead of the policy's propensity",
        "src/copilot/core/challenges.py",
        "            propensity_bp=propensity_bp,",
        "            propensity_bp=5000,",
        ("tests/core/test_offer_policy_wiring.py",),
    ),
    Mutation(
        9,
        "social comparison is not rejected",
        "src/copilot/core/self_competition.py",
        "    lower = text.lower()\n    for term in FORBIDDEN_SOCIAL_COMPARISON_TERMS:",
        "    lower = text.lower()\n    for term in []:",
        ("tests/core/test_self_competition.py", "tests/core/test_rewards.py"),
    ),
    Mutation(
        10,
        "the agent may start an experiment",
        "config/policy.yaml",
        "  start_experiment:            {agent: deny, user: allow}",
        "  start_experiment:            {agent: allow, user: allow}",
        (
            f"{GOLDEN}::test_19_the_planner_cannot_reach_a_write_tool",
            "tests/workflow/test_agent_integration_phase4.py",
        ),
    ),
    Mutation(
        10,
        "MCP exposes a write tool",
        "config/mcp.yaml",
        "exposed_tools:\n",
        'exposed_tools:\n  - "start_experiment"\n',
        (
            f"{GOLDEN}::test_18_the_mcp_server_shows_no_write_tool",
            "tests/workflow/test_agent_integration_phase4.py",
        ),
    ),
    Mutation(
        11,
        "a tool named like a money transfer is registered",
        "src/copilot/tools/challenges.py",
        'name="dismiss_offer"',
        'name="send_money_offer"',
        ("tests/tools/test_no_money_movement.py",),
    ),
    Mutation(
        12,
        "learning may lower a hard-floor alert",
        "src/copilot/core/learning.py",
        "        effective_m = max(1.0, multiplier)",
        "        effective_m = multiplier",
        ("tests/learning/test_learning.py",),
    ),
)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _apply(text: str, old: str, new: str) -> str | None:
    crlf = "\r\n" in text
    old_n = old.replace("\n", "\r\n") if crlf else old
    new_n = new.replace("\n", "\r\n") if crlf else new
    return text.replace(old_n, new_n, 1) if text.count(old_n) == 1 else None


def run_one(m: Mutation) -> tuple[str, str]:
    """('caught' | 'MISSED' | 'not applied', detail)."""
    path = ROOT / m.file
    original = _read(path)
    digest = hashlib.sha256(original).hexdigest()
    mutated = _apply(original.decode("utf-8"), m.old, m.new)
    if mutated is None:
        return "not applied", f"anchor not found exactly once in {m.file}"
    try:
        path.write_bytes(mutated.encode("utf-8"))
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *m.tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        tail = (proc.stdout.strip().splitlines() or [""])[-1]
        return ("caught" if proc.returncode != 0 else "MISSED"), tail
    finally:
        path.write_bytes(original)
        if hashlib.sha256(_read(path)).hexdigest() != digest:  # pragma: no cover - safety net
            raise SystemExit(f"FATAL: {m.file} was not restored")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rule", type=int, default=None)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    rows = []
    for m in MUTATIONS:
        if args.rule is not None and m.rule != args.rule:
            continue
        verdict, detail = run_one(m)
        rows.append((m, verdict, detail))
        print(f"rule {m.rule:>2}  {verdict:<11} {m.name}")
    bad = [r for r in rows if r[1] != "caught"]
    if not args.no_report and args.rule is None:
        lines = [
            "# Phase 4 mutation checks",
            "",
            "Generated by `python scripts/mutation_check_phase4.py`. Each row breaks one safety rule "  # noqa: E501
            "on purpose and runs the tests that guard it; the tests must fail. The file is restored "  # noqa: E501
            "and verified by hash after every row.",
            "",
            "| Rule | Deliberate break | Result | Guarding tests (last line of output) |",
            "|--:|---|:-:|---|",
        ]
        for m, verdict, detail in rows:
            lines.append(f"| {m.rule} | {m.name} | {verdict} | {detail.replace('|', '/')} |")
        lines += [
            "",
            f"{len(rows) - len(bad)} of {len(rows)} breaks were caught "
            f"({time.monotonic() - started:.0f}s).",
            "",
        ]
        (ROOT / "docs" / "phase4_mutation_checks.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(rows) - len(bad)} of {len(rows)} breaks caught")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
