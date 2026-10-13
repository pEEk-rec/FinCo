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

## Step 10: Config, golden tests, Phase 0 exit review
What was built: `config/settings.yaml` + `core/config.py` (strict Pydantic; relative paths resolve against the project root; `timezone`, `currency` and `forecast_method` only accept the values the code implements, and a test checks settings agree with the code). `tests/golden/scenarios.json` holds 10 scenarios whose data is written in rupees and IST wall-clock time so every expected value can be checked by hand; `test_golden.py` runs them through the real executor, repo policy, tools and audit log.
Why: golden scenarios freeze Phase 0 behaviour. Checked by mutation: making the warning check `>` instead of `>=`, ignoring refunds, or computing month bounds in UTC each fails at least one scenario.
Rule: never edit an expected value to make a test pass; a change there is a behaviour change and needs its own entry here.

### Phase 0 exit checklist (verified 2026-10-01)
- [x] `pytest` passes fully (296 tests); `ruff check` and `ruff format --check` are clean.
- [x] Money is integer paise everywhere: StrictInt in models, STRICT INTEGER columns, no float arithmetic in money paths (scanned).
- [x] Month boundaries are IST, half-open, with tests at 23:59 / 00:00 IST, leap and non-leap February, and year rollover.
- [x] Every table has `user_id` (tested by introspection); `goals` and `buckets` exist with no logic.
- [x] Audit log is append-only, enforced by triggers for UPDATE, DELETE and re-INSERT (REPLACE).
- [x] Every tool call goes through `execute_tool` and is audited: allowed, denied, needs-approval, not found, invalid input and failed.
- [x] Default deny works (and `default` cannot be set to anything else); write tools are blocked without approval; handler provably not called.
- [x] `test_no_money_movement_tools_registered` scans the real registry; no EXTERNAL tool exists, and EXTERNAL is denied in code.
- [x] Deterministic tools covered by hand-computed boundary tests (threshold, limit, one paisa over; forecast day 1, mid, last day, zero spend).
- [x] Synthetic data is seeded and reproducible, with ground-truth anomalies.
- [x] `RunState` is versioned and projection works; memory schema has provenance, source and confidence.
- [x] LLM layer validates structured output with retries and uses only the fake client.
- [x] 10 golden scenarios pass.
- [x] `docs/decisions.md` has an entry for every step, plus the review fixes.
- [x] No AI attribution in code, docs or git history (scanned).
- [x] Nothing from PLAN section 5 was built (the out-of-scope chat loop was removed).

Known history notes: commit `ad51480` also contains the schema/model hardening that was uncommitted when it was made, and `9dd0466` ("Final Phase 0 testing and lockdown") added the since-removed integration test. History was not rewritten (PLAN 0.3).

## Stage 1.0: Align with Phase 0, migrations, config
What was built: Phase 0 `schema.sql` was moved to `db/migrations/001_initial.sql` and the initialization logic was updated to use a `schema_migrations` table tracking applied SQL files. Pydantic `Settings` was updated to read paths for Phase 1 YAML config files, and `.env.example` was updated with Gemini LLM config properties. A Phase 1 alignment map was written.
Why it was designed this way: A formal migration mechanism allows safe incremental evolution of the database state. Keeping the Phase 0 PRAGMA logic alongside the migrations table guarantees Phase 0 golden tests remain intact without modifying their assumptions.
What it deliberately does not do: No actual Phase 1 tables or views are built yet.
Question: How does the new migration engine preserve the atomicity constraint?
Answer: Each migration is executed as a whole script inside an overarching explicitly declared `BEGIN; ... COMMIT;` string executed via `executescript`. This allows multiple statements while preserving single-transaction rollback on failure.

## Stage 1.1: Schema and models
What was built: Phase 1 database schema additions were authored in `002_phase1_schema.sql`, defining tables for consent, data ingestion batches, analytics (anomalies, findings, advice), merchant overrides, recurring series, transfer links, and extending existing core entities. Relevant views (`v_category_totals_month`, `v_budget_status_month`, `v_balance`) were added. Pydantic Domain models were created for each new entity, and data access functions in `repo.py` were adjusted for the new `Transaction` fields. Tests for view correctness and json round-trips were added.
Why it was designed this way: SQLite enforces `STRICT` table typing. Recreating `transactions` via `new_transactions` table was necessary to append new values to the `CHECK` constraint on `category_source`. Foreign key dependencies were disabled temporarily for the migration to allow renaming. 
What it deliberately does not do: No domain logic functions have been built for the new entities yet; they are currently just persisted structures.
Question: Why recreate `transactions` instead of just altering it?
Answer: SQLite limits `ALTER TABLE` operations; it doesn't support changing `CHECK` constraints (like `category_source IN (...)`). A full table recreate inside a disabled foreign-keys session safely overcomes this limit.

## Stage 1.2: Synthetic data v2 and AA-shaped mock connector
What was built: The Phase 0 `synth.py` transaction generator was extended to generate data across multiple accounts, including own-account transfers, refunds, recurring subscriptions, salary deposits, and a new ground-truth tracking map per transaction. `mock_bank.py` was rewritten to implement the `BankConnector` interface which mocks Account Aggregator consents (`create_consent`, `approve_consent`, `fetch_session`). The `loader.py` and test suite were updated to ingest based on an active consent instead of a date range.
Why it was designed this way: Micking the Indian Account Aggregator architecture isolates the copilot logic from the bank connector. If a real AA adapter is written in the future, it just needs to implement `BankConnector` and the rest of the application remains unchanged.
What it deliberately does not do: No parsing logic (like extracting merchant names from raw text) is done by the mock AA connector. It just provides the raw string to be parsed down the line. It also does not persist consents in a real database, just in memory for the mock.
Question: Why is ground truth tracked for every transaction separately from the returned `Transaction` models?
Answer: Keeping ground truth completely separate ensures that the categorisation pipeline cannot accidentally cheat by reading the true category. The evaluation harness will read the hidden truth map to grade the pipeline.

## Review pass on Stages 1.1-1.4: DONE
Goal: audit the existing implementation and fix defects before continuing to Stage 1.5.
Fixed:
- pipeline.py raised NameError (ToolFailure not imported) on any LLM failure; rewritten: batches by config size, validates LLM output (asked merchants, known category ids), caps LLM confidence, per-user cache ids (old id could overwrite another user's row), redacted prompt that lists allowed categories, returns counts-only PipelineReport
- categorize_batch: unknown category goes to review instead of aborting the batch on a foreign key error; LLM confidence cap enforced inside the tool
- undo_categorize_batch: restores only rows still in the batch's state (never clobbers a later user edit), idempotent, reverse-order restore
- ingestion: duplicate-charge flag matched any same merchant and amount (monthly rent and subscriptions would be flagged and dropped from spend); now windowed (24h), flags the later of a pair, order independent
- rules and aliases YAML now have validated loaders (load_rules, load_aliases); bad regex fails loudly
- lint: 99 errors cleared (E501 ignored in tests only)
- GeminiProvider: API key moved from URL to x-goog-api-key header.

## Stage 1.5: Transfers and recurring detection
What was built: detect_transfers and detect_recurring core logic in core/patterns.py and tool handlers in 	ools/patterns.py. Config settings 	ransfer_window_hours and ecurring_tolerance_pct were added to settings.yaml. Tests added to verify the synthetic data ground-truth anomalies are correctly identified. 
et_spend_by_category was updated to exclude excluded_from_spend transactions.
Why it was designed this way: Finding deterministic patterns locally reduces LLM workload and prevents false alarms on known monthly bills or salary deposits. The tool wrapper handles database mutation and audit logging while the core logic stays pure.

## Stage 1.6: Analysis tools and derived state (Started)
What was built: Examined existing tools in src/copilot/tools/financial.py. Next step is to implement detect_anomalies, update check_budgets for projected_exceed, and add get_financial_state.

## Stage 1.6: Analysis tools and derived state (Completed)
What was built:
- Added detect_anomalies which correctly recalls ground truth anomalies (large transactions, new merchants, duplicate charges).
- Created orecast_month which splits transactions into fixed (recurring series) and variable, and forecasts the rest of the month.
- Created get_financial_state to output FinancialStateSnapshot including the balance, budget statuses, and queue size.
- Updated udget_status to include projected_exceed.
All integrated into src/copilot/tools/analysis.py and registered.

## Stage 1.7: Dispute, correction and undo (Completed)
What was built:
- Enhanced ecategorize_transaction to support --remember flag, creating merchant overrides.
- Applied overrides automatically to past agent-set transactions of the same merchant.
- Added undo tool that restores efore_data from audit events to revert recategorizations or batch overrides.
- Configured policy to allow undo for both agent and user.

## Stage 1.8: Findings, advice drafting and validator (Completed)
What was built:
- Defined Finding model to encapsulate insights.
- Implemented draft_advice tool that formats findings and uses a deterministic validator to ensure no halluciations, forbidden content (transfer, fund, stock) and consistent numbers (supporting rounding up to 5% tolerance like 1.2k). Fallbacks used for invalid LLM output.
- Implemented decide_advice tool to approve/reject draft advice, properly audited.
- Included corresponding tests checking valid and invalid drafted advice based on real finding numbers.

## Stage 1.8b: Undo divergence checks and advice number matching rule
### 1. Undo divergence check
What was built:
- Removed unconditional force-restore in `src/copilot/tools/undo.py`.
- Before reverting any transaction or batch, the undo handler compares the entity's current state with `after_data` recorded in the audit event.
- If the current state has diverged (e.g. an interleaved user or agent edit occurred after the event), the undo is refused.
- On the direct handler path, a refusal audit event (`event_type="undo_refused"`) is recorded with `metadata.refusal_reason` ("state_diverged" or "batch_item_diverged") and a `ToolFailure(ErrorCode.STALE_DATA)` is raised.
- On the `execute_tool` path (production path for agents and CLI), the executor's savepoint cleanly rolls back the failed handler's internal writes, and `execute_tool._fail` audits the refusal in its own savepoint as `event_type="tool_call"` with `metadata.error_code="STALE_DATA"` and `reason="Undo refused: ..."`. In both paths, the entity is never modified.
- For batch undos (`override_applied`), divergence checks are executed across all transactions in the batch first; if any item has diverged, none are restored (all-or-nothing guarantee).

### 2. Advice number matching rule
What was built:
- Documented and implemented the exact number matching tolerance in `src/copilot/core/advice.py`:
  `tolerance = min(half of the last displayed digit, 5% of the stated value)`.
- A written figure `W` matches a true value `T` from a finding if and only if `abs(W - T) <= tolerance`.
- This replaced the previous quantum truncation rule, which was overly permissive (accepting 50,000 to 199,999 for "1 lakh").
- Examples of accepted and rejected ranges under this rule:
  - "1 lakh" (`W = 100,000`, `quantum = 100,000`): `half_last_digit = 50,000`, `5% = 5,000` -> `tolerance = 5,000`. Matches `[95,000, 105,000]`. Correctly rejects 60,000 and 150,000.
  - "₹1.2k" (`W = 1,200`, `quantum = 100`): `half_last_digit = 50`, `5% = 60` -> `tolerance = 50`. Matches `[1,150, 1,250]`. Correctly accepts 1,234.50 and rejects 1,149 / 1,251.
  - "1.5 lakh" (`W = 150,000`, `quantum = 10,000`): `half_last_digit = 5,000`, `5% = 7,500` -> `tolerance = 5,000`. Matches `[145,000, 155,000]`.
  - "2 crore" (`W = 20,000,000`, `quantum = 10,000,000`): `half_last_digit = 5,000,000`, `5% = 1,000,000` -> `tolerance = 1,000,000`. Matches `[19,000,000, 21,000,000]`.
  - Plain rupee "₹500" (`W = 500`, `quantum = 1`): `half_last_digit = 0.5`, `5% = 25` -> `tolerance = 0.5`. Matches `[499.5, 500.5]`.
