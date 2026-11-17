# eval

Offline evaluation: does FinCo actually do what it claims, measured before anyone has to trust it?

Every suite is listed in **`registry.py`**:

| Suite | Measures |
| --- | --- |
| `ledger` | categorisation accuracy, transfer and recurring detection, anomalies, advice grounding |
| `agent` | reading intent, plan minimality, investigations, what-if properties, alerts |
| `memory` | commitments, calendar, buckets, readiness, memory, multi-agent answers, learning, runtime safety |
| `engagement` | experiments: false alarms and detection on held-out seeds, offers |
| `capture` | SMS parsing per bank, what must be dropped, reconciliation, double counts, guess hit rate |
| `categorise` | the cascade before and after, calibration, entity resolution, swapping the model |

Run one with `copilot eval --suite <name>`; `copilot eval --list` shows them. Each one is
deterministic: seeded data, recorded model replies where a model is involved. Each declares its
targets before measuring and writes a report under `docs/`. A missed target stays visible as a
FAIL with the reason. Nothing is tuned on held-out data.

The older module names (`harness.py`, `harness_phase2.py`, ...) still resolve to these suites.
