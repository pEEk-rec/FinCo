"""
Every evaluation suite, in one list. Run one with `copilot eval --suite <name>`; list them with
`copilot eval --list`.

Each suite is offline and deterministic (seeded data, recorded model replies where a model is
involved), declares its targets before it measures, and writes a report under `docs/`. A target
that is missed stays visible as a FAIL with the reason; nothing is tuned on held-out data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Suite:
    name: str
    measures: str
    module: str
    report: str
    #: how the CLI runs it today (kept so older commands keep working)
    cli: dict


SUITES: tuple[Suite, ...] = (
    Suite("ledger", "categorisation accuracy, transfer and recurring detection, anomalies, advice grounding",
          "copilot.eval.ledger", "docs/eval_report.md", {"phase": 1}),
    Suite("agent", "intent reading, planner minimality, investigations, what-if properties, alerts",
          "copilot.eval.agent", "docs/eval_report_phase2.md", {"phase": 2}),
    Suite("memory", "commitments, calendar, buckets, readiness, memory, multi-agent, learning, runtime safety",
          "copilot.eval.memory_and_multiagent", "docs/eval_report_phase3.md", {"phase": 3}),
    Suite("engagement", "experiments: false alarms and detection on held-out seeds, intent reading, offers",
          "copilot.eval.engagement", "docs/eval_report_phase4.md", {"phase": 4}),
    Suite("capture", "SMS parsing per bank, what must be dropped, reconciliation, double counts, guess hit rate",
          "copilot.eval.capture", "docs/eval_report_capture.md", {"capture": True}),
    Suite("categorise", "the categorisation cascade before and after, calibration, entity resolution, model swap",
          "copilot.eval.categorise", "docs/eval_report_categorise.md", {"categorise": True}),
)  # fmt: skip


def get(name: str) -> Suite | None:
    return next((s for s in SUITES if s.name == name), None)
