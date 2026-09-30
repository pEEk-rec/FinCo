# Finance Copilot

A personal finance and budgeting copilot for a student in India. Phase 0 is the foundation:
typed data in SQLite, exact money (integer paise) and IST month handling, deterministic
financial tools behind a single governed executor, an append-only audit log, a seeded mock
bank, and interfaces for memory, planning and the LLM. There is no UI, server or real LLM yet.

## Install

Requires Python 3.11+ and SQLite 3.37+ (bundled with current Python builds).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

## Test and lint

```bash
pytest                    # unit tests + tests/golden (10 hand-verified scenarios)
ruff check . && ruff format --check .
```

## Layout

| Path | What it holds |
|---|---|
| `config/policy.yaml` | Governance matrix: which tools are allowed, denied or need approval |
| `config/settings.yaml` | Timezone, DB path, default warn threshold, forecast method, LLM retries |
| `src/copilot/core/` | `money` (paise), `timeutil` (UTC storage, IST months), `errors`, `config` |
| `src/copilot/db/` | `schema.sql` (STRICT tables, tenant-safe keys, audit triggers), `connection` (`savepoint`), `repo` |
| `src/copilot/models/` | Domain models, per-run `RunState`, `MemoryEntry` |
| `src/copilot/audit/` | Append-only audit log |
| `src/copilot/tools/` | Tool contracts, registry, **the executor choke point**, financial tools |
| `src/copilot/governance/` | Policy loading and `decide()` |
| `src/copilot/bank/` | Seeded synthetic data, mock bank connector, loader |
| `src/copilot/llm/` | `LLMClient` interface, fake client, validated `structured_call`, prompts |
| `src/copilot/planner/` | `Planner` interface and placeholder `TrivialRouter` |
| `tests/` | Mirrors `src/`; `tests/golden/` holds end-to-end scenarios |
| `docs/PLAN.md`, `docs/decisions.md` | The Phase 0 plan and the design log (why each piece is the way it is) |

## Core rules

- Money is integer paise; floats are rejected. Debit amounts are positive, credits negative.
- Timestamps are stored as `YYYY-MM-DDTHH:MM:SSZ`; months are calendar months in IST.
- Every tool call goes through `tools.executor.execute_tool`, which applies default-deny
  policy and audits every outcome. No money-moving tool exists, and a test enforces it.
