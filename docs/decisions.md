# Architecture Decisions Log

## Deferred
- LangGraph and fixed agent workflows
- Actual categorization logic / LLM categorization
- Monthly review, advice drafting, dispute flow UI
- Real planner, hypothesis/evidence reasoning
- What-if simulation, adaptive alerts
- Real bank and payment integrations
- Authentication and multi-user access

## Step 0: Project skeleton
What was built: The foundational project structure, `pyproject.toml`, and configuration for testing and linting.
Why it was designed this way: A standard modern Python structure with Pydantic for models and pytest/ruff for QA ensures strictness from day one.
What it is deliberately not doing: No application code or logic is written yet.

## Step 1: Money and time primitives
What was built: Core utilities for handling money as integer paise and time as UTC ISO strings with IST bounds.
Why it was designed this way: Prevents floating-point errors by using exact integers/Decimals for money, and enforces a standard timezone (Asia/Kolkata) to avoid naive datetime bugs.
What it is deliberately not doing: No general-purpose timezone conversion or currency conversion is implemented; it strictly handles INR and IST.

## Step 2: Domain models and database schema
What was built: Pydantic models for core entities (User, Account, Category, Transaction, Budget) and a raw SQLite schema with strict `CHECK` constraints.
Why it was designed this way: A raw SQLite schema avoids the overhead of an ORM while providing strong guarantees (e.g., negative budget limit prevention, foreign keys). `user_id` is mandatory on all tables to enforce data boundaries natively.
What it is deliberately not doing: No goals or virtual buckets logic is implemented; the tables are just reserved. No ORM is used.

## Step 3: Audit event log
What was built: An append-only audit log in SQLite with functions to record and query events.
Why it was designed this way: A reliable audit trail is critical for safety. SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers enforce the append-only constraint at the database level so bugs cannot mutate history.
What it is deliberately not doing: No hash-chaining or event-sourced architecture is implemented; a simple table with triggers is sufficient for Phase 0.

## Step 4: Tool contracts and registry
What was built: Pydantic-based definitions for tools (`ToolSpec`) and error types (`ErrorCode`, `ToolError`), plus a basic in-memory registry.
Why it was designed this way: A declarative tool specification ensures inputs and outputs are automatically validated by Pydantic, while side effects are rigidly categorized to allow granular governance checks later.
What it is deliberately not doing: The registry does not execute tools itself or handle any governance—that logic is deferred to the executor choke point. No money-moving side effect type is defined.

## Step 5: Governance and the executor choke point
What was built: A central `execute_tool` function that enforces policy rules (loaded from `policy.yaml`) before running any tool handler, recording every decision and execution outcome to the audit log.
Why it was designed this way: A single choke point guarantees that no tool can bypass governance or auditing. Pydantic validation on inputs and outputs prevents malformed data from causing silent corruption.
What it is deliberately not doing: No dynamic rule evaluation or complex permissions matrix; policy is a simple default-deny YAML lookup based on side-effects or specific tool overrides.

## Review fixes (Steps 0-3 hardening)

### Money and time helpers
What changed: money helpers reject `bool` (a subclass of `int`), floats for the paise argument of `safe_percent`, NaN/Infinity, exponent and underscore strings; all bad input now raises a clear `TypeError`/`ValueError`. `from_utc_iso` rejects strings with no offset, and `normalize_utc_iso` produces the one canonical storage form (`YYYY-MM-DDTHH:MM:SSZ`).
Why: `rupees_to_paise(True)` returned 100 and `safe_percent(100.7, 10)` accepted a float amount. A naive timestamp silently read as UTC would shift IST month boundaries by 5.5 hours.
Rounding: `ROUND_HALF_UP` in `decimal` is half away from zero, so refunds round symmetrically (-12.5 -> -13).
