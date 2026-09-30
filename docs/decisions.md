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

## Step 6: Deterministic financial tools
What was built: Tool handlers for reading transactions, getting balances, aggregating spend, checking budgets, forecasting, and recategorizing.
Why it was designed this way: All mathematical and business logic is handled in deterministic Python code so the LLM is only responsible for intent routing, preventing hallucinations in numbers.
What it is deliberately not doing: No LLM calls are made inside the tools. Tools don't decide their own governance—they rely entirely on the executor.

## Removed: chat loop and CLI (built out of plan order)
What happened: `cli.py`, `agent/loop.py` and an end-to-end test were built in place of PLAN Steps 7 and 8, and this log briefly claimed "Phase 0 is complete".
Why it was removed: PLAN section 5 forbids a chat interface in Phase 0. The loop also routed "recategorize transaction ..." to `get_transactions`, formatted money with float division, and its CLI approval re-ran whatever the previous message was. `test_no_orms_present` could never pass (`pytest.raises` around `pass`).
What replaces it: the keyword-routing idea becomes Step 8's `TrivialRouter`; end-to-end coverage becomes Step 10's golden scenarios. Steps 7 to 10 are still to be built as specified.

## Review fixes (Steps 0-3 hardening)

### Money and time helpers
What changed: money helpers reject `bool` (a subclass of `int`), floats for the paise argument of `safe_percent`, NaN/Infinity, exponent and underscore strings; all bad input now raises a clear `TypeError`/`ValueError`. `from_utc_iso` rejects strings with no offset, and `normalize_utc_iso` produces the one canonical storage form (`YYYY-MM-DDTHH:MM:SSZ`).
Why: `rupees_to_paise(True)` returned 100 and `safe_percent(100.7, 10)` accepted a float amount. A naive timestamp silently read as UTC would shift IST month boundaries by 5.5 hours.
Rounding: `ROUND_HALF_UP` in `decimal` is half away from zero, so refunds round symmetrically (-12.5 -> -13).

### Caller-owned transactions
What changed: repo and audit functions no longer call `commit()`. `db.connection.savepoint(conn)` marks a unit of work: at top level it commits on exit, inside a caller's transaction it nests, and on any exception it undoes everything since entry. `execute_tool` runs the handler, output validation and the success audit event inside one savepoint. `update_transaction_category` returns False when no row matched.
Why: each function committed on its own, so a category change could be saved while its audit event failed, leaving a change with no audit trail. It also meant a failed handler left half-written state behind.
Not doing: no connection pool or retry on `database is locked`; Phase 0 is single-process.

### Audit log hardening
What changed: a `BEFORE INSERT` trigger rejects re-inserting an existing audit id; `record_event` validates actor, decision, non-empty type/reason and JSON-serialisability before writing, and takes an optional `clock`; `list_events` returns typed `AuditEvent` models (JSON decoded) ordered by `occurred_at` then `rowid`.
Why: `INSERT OR REPLACE` overwrote an audit row because SQLite does not fire DELETE triggers for REPLACE. Timestamps are second-precision, so same-second events needed a deterministic tie-breaker.
Known limit: a process with raw write access can still `DROP TRIGGER`. Triggers protect against bugs in our code, not against a hostile database owner; hash-chaining is deferred (section 5).

### Governance and executor hardening
What changed: the policy file is validated strictly (`extra=forbid`, `decision` must be allow/deny/needs_approval, side-effect keys must be real `SideEffect` values, `default` can only be `deny`). `decide()` denies EXTERNAL tools in code before reading any rule. `ToolSpec` is a frozen, validated dataclass whose input model must subclass `ToolInput` (unknown fields rejected). `execute_tool` never raises, audits every outcome including NOT_FOUND and invalid input, stores raw input safely even when it is not JSON, and maps `ToolFailure` exceptions to their own error code. If writing the success audit event fails, the handler's writes are rolled back and the result is INTERNAL.
Why: a typo like `decision: "deny "` used to fall through to the more permissive side-effect rule; an unknown-tool probe such as `transfer_money` left no audit trace; non-JSON input made `execute_tool` raise.
Not doing: approval is still a boolean flag passed by the caller; binding approval to a specific pending action is Phase 7.

### Financial tools rewrite
What changed: the math lives in pure functions (`net_spend_by_category`, `budget_status`, `days_elapsed_in_month`, `run_rate_forecast`, `compute_balance`) that use integer paise only; handlers just fetch rows and call them. Inputs are validated (canonical timestamps, `start < end`, month 1..12, `limit` 1..1000) and missing transactions, accounts or categories return NOT_FOUND via `ToolFailure`.
Bugs fixed: `get_balance` subtracted income (credits are negative, so adding them lowered the balance) and ignored opening balances; `check_budgets` used float division, so 29/100 became 28% and missed a 29% warning.
Refund policy: credits net against spend in their own category, floored at 0; uncategorised credits (salary) are not spend. A refunded order therefore no longer counts toward a budget.
Budget rules: `exceeded` only when spent > limit; `warning` when spent > 0 and spent*100 >= warn%*limit; `pct_used` is floored and None for a zero limit.
Balance: opening balance minus the sum of amounts, counting only transactions up to "now" (the context clock).
Not doing: forecasting beyond a straight run rate; `run_rate_forecast` is the single place to swap in a better method.

## Step 7: Mock bank connector and synthetic data
What was built: `bank/synth.py` generates months of hostel-student UPI activity (mess, food delivery, canteen, travel, recharge, printouts, monthly pocket money) from one `random.Random(seed)`, with ids drawn from the same generator and a fixed start month, so the same seed gives identical output. Three anomalies are planted in the last month and returned as `ground_truth`: a large electronics purchase, a duplicate charge 2 minutes apart, and a first purchase at a new merchant. `bank/mock_bank.py` serves these as raw records in an invented external format (rupee strings, DR/CR, narration) and can simulate an outage. `bank/loader.py` parses records with `rupees_to_paise` and stores them with `category_source = none`.
Why: messy narrations are the input Phase 1 categorisation must handle, and known anomalies give later anomaly detection a ground truth to be scored against. Parsing a separate record format exercises the boundary where a real connector's data enters the system.
Loader rules: one savepoint per sync (the batch and its audit event are all-or-nothing), a malformed record fails the whole batch with INVALID_INPUT, and records already stored (same id) are skipped so a re-sync never duplicates. The planted duplicate charge has its own id, so it is loaded, as a real double charge would be.
Not doing: no categorisation, no anomaly detection, no network, and generated data is never written to the repo.

## Step 8: RunState, memory schema, planner interface
What was built: `RunState` (per-run, in memory, `schema_version` pinned to 1 so an unknown version fails to load), `summarize_tool_result` to store JSON-safe tool summaries, and `to_llm_projection(state, fields)` which returns only the requested fields and rejects unknown names. `MemoryEntry` requires kind, source, confidence and non-blank provenance (also CHECKed in SQL), with `insert_memory_entry` / `list_memory_entries` only. `planner/router.py` defines the `Planner` protocol and `TrivialRouter`, a Phase 2 placeholder that matches whole words and only plans READ tools.
Why: per-run state and persistent financial state stay separate (PLAN section 2), and projections keep LLM context small and deliberate.
Not doing: memory retrieval, ranking, decay or confidence updates (Phase 3); real planning (Phase 2); the router never plans write tools.

### Confidence convention
Confidence is a threshold signal for "act / ask / ignore", not a calibrated probability.
- User-stated or user-corrected: 1.0.
- Deterministic rule match (e.g. a merchant rule in Phase 1): 0.9.
- LLM-only judgement: capped at 0.7, whatever the model claims, so it can never reach the "act without asking" band on its own.
- Observed pattern (memory): starts at 0.5 and is only raised by user confirmation (Phase 3).
- No signal: null, never 0.0 (0.0 would mean "confidently wrong").

## Step 9: LLM access layer
What was built: `llm/client.py` with the `LLMClient` protocol, a scripted `FakeLLMClient`, and `structured_call(client, prompt, output_model, max_retries=2)`. It asks for JSON matching the model's schema, accepts a single ```json fenced block, validates with Pydantic, and on invalid output retries with the original task plus a short "your last output was invalid because ..." note. After exactly `max_retries + 1` attempts it raises `StructuredOutputError`, a `ToolFailure` with TOOL_FAILURE. A failing client is wrapped as a retryable TOOL_FAILURE and not retried here. Prompt text lives only in `llm/prompts.py`.
Why: every model call goes through one validated path, so malformed output can never reach business logic as raw text.
Guard: `structured_call` refuses output models with any `*_paise` field (nested too), so the LLM is never asked to produce money (design principle 1).
Not doing: no provider SDK, API keys or network; the real adapter is a later task and only has to implement `complete()`.
