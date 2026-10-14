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
What was built: detect_transfers and detect_recurring core logic in core/patterns.py and tool handlers in 	ools/patterns.py. Config settings 	ransfer_window_hours and 
ecurring_tolerance_pct were added to settings.yaml. Tests added to verify the synthetic data ground-truth anomalies are correctly identified. 
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
- Enhanced 
ecategorize_transaction to support --remember flag, creating merchant overrides.
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

## Stage 1.9: LangGraph workflow
### 1. Architecture Isolation and Tool Execution Choke Point
- Workflow nodes NEVER import or execute tool handlers directly (`*_handler`).
- Every tool interaction passes strictly through `execute_tool(ctx, tool_name, params)` in `src/copilot/tools/executor.py`.
- An automated AST-based architecture test (`tests/workflow/test_architecture.py`) inspects all Python files outside `src/copilot/tools/` to enforce that no module imports any `*_handler` function, and asserts that workflow nodes execute tools solely via `execute_tool`.

### 2. State Management and In-Memory Checkpointing
- Defined `AgentState` in `src/copilot/workflow/state.py` as a JSON-serialisable TypedDict so that checkpointers can save and restore state across interruptions without encountering non-picklable database connections.
- Used `langgraph.checkpoint.memory.MemorySaver` for in-memory checkpointing and resumption within process. Runtime execution contexts (`ExecutionContext`, sqlite connection, policy) are passed via `config["configurable"]` dependency injection.
- Accumulates execution traces across nodes using `Annotated[list[TraceEntry], operator.add]`, capturing node name, ISO start/end timestamps, duration in ms, tool names invoked, summary counts, and status.
- Added `to_run_state` projection function to ensure full backwards compatibility with the Phase 0 `RunState` and `to_llm_projection` models.

### 3. Human-in-the-Loop Review Interruption
- The `review_node` uses LangGraph's native `interrupt({"drafts": ...})` mechanism when pending draft advice items exist and decisions have not been pre-supplied.
- To prevent swallowing the control flow exception, `review_node` explicitly catches and re-raises `GraphInterrupt`, allowing the LangGraph engine to checkpoint state and pause execution.
- Resuming the workflow with `Command(resume=[{"advice_id": ..., "decision": "approved" | "rejected"}])` extracts the user decisions and executes `decide_advice` tool with `actor="user"`, properly updating the database and writing audited lifecycle events.

### 4. Conditional Edge Routing and Dual Graph Modes
- Conditional edge after `ingest`: If 0 new transactions are inserted, skips `categorize` and routes to `analyze` (to produce fresh analysis on existing data) or `finalize` (configurable via `on_zero_txns`). If `inserted > 0`, routes to `categorize`.
- Error routing: Any unhandled node failure transitions to `error_node`, which records an audited `run_failed` event in `audit_events`, appends an error trace record, and terminates cleanly at `END`.
- Built `build_agent_graph` for primary end-to-end execution and `build_monthly_review_graph` for targeted monthly reviews (`analyze → advise → review → finalize`).

## Stage 1.10: Monthly Review Architecture and Safety Invariants

### 1. Document Schema and Immutable Snapshot Versioning
- Modeled the monthly review as a typed Pydantic document (`MonthlyReviewData`) in `src/copilot/review/models.py`, comprising:
  - Income, spend, net cashflow (all in integer paise)
  - Prior month period baseline and category change deltas (paise and percentage)
  - Category expenditures sorted descending by spend
  - Budget performance statuses (`ok`, `warning`, `exceeded`, `projected_exceed`)
  - Detected recurring payment series and cadence
  - Anomalies and month-end run-rate forecasts
  - Approved/draft financial advice items with stated assumptions
  - Data quality and completeness metrics (`review_queue_size`, `duplicates_flagged`, `days_recorded`, `missing_days`, `is_partial_month`)
- Versioning is strictly monotonic per `(user_id, year, month)`: re-generating a review (e.g., following a user category correction) increments the version counter (`v1 -> v2`). Both versions remain permanently accessible via `get_monthly_review(conn, user_id, year, month, version=N)` and `monthly_reviews` table.

### 2. Temporal Consistency for Partial Months
- When building a review for an ongoing month (`now_dt < end_of_month`), `effective_end_utc` is capped at `clock` (the current execution time), ensuring future transactions from the bank connector or synthetic mocks do not pollute partial month aggregates.
- `days_recorded` computes distinct IST calendar days having transaction activity up to the clock timestamp, and `missing_days` tracks elapsed days without transaction records.

### 3. Renderer Number Containment Invariant
- CRITICAL SAFETY INVARIANT: The Markdown and HTML renderers must NEVER invent, fabricate, or hardcode numerical figures not present in the structured `MonthlyReviewData` model.
- Enforced and validated via `extract_numbers_from_rendered_text` and `extract_all_review_numbers`:
  - Strips HTML tags, styles, and currency glyphs (`₹`, `Rs.`).
  - Normalizes token signs (ensuring absolute, positive, and negative Decimal representations match).
  - Safety test (`test_renderer_contains_no_unauthorized_numbers`) asserts `rendered_numbers.issubset(review_numbers)`. Negative tampering tests confirm that any injected unauthorized number immediately triggers a test failure.

## Stage 1.11: Unified Typer CLI and Demo Surface Architecture

### 1. Unified CLI Entrypoint and Architectural Choke Point Compliance
- Registered `copilot = "copilot.cli.main:app"` console script in `pyproject.toml` using Typer.
- Architectural safety invariant strictly maintained: CLI commands never import or invoke tool handlers directly. All business mutations, domain views, and updates execute solely through `execute_tool(ctx, tool_name, params)` or compiled LangGraph workflows (`build_agent_graph`, `build_monthly_review_graph`). AST tests (`tests/workflow/test_architecture.py`) verify 100% compliance.

### 2. Dual Presentation Layer: Rich Terminal UI vs Clean Machine JSON
- Every query and command supports default human-friendly presentation rendered with `rich.table.Table`, `rich.panel.Panel`, and styled badges.
- All read and operational commands support `--json`. When `--json` is supplied, raw unstyled JSON is emitted directly to `sys.stdout` without Rich ANSI escape codes, terminal line wraps, or soft hyphens, ensuring pipe-compatibility (`copilot txns --json | jq`).
- Expected domain errors (policy refusals, invalid parameters, missing consents) print clean human-readable error messages to `sys.stderr` via `print_error` and exit with non-zero status codes without emitting raw Python tracebacks.

### 3. Cross-Process Persistence and Connector Sync
- CLI invocations run in distinct processes. Synthetic transactions generated by `copilot seed` are persisted to `data/mock_bank_<user_id>.json` so that `copilot run` or `ingest_statements` can reconstruct the exact state via `MockAAConnector`.
- Execution traces are serialized with `default=str` to `data/trace_<run_id>.json` during workflow execution, enabling subsequent trace inspections via `copilot trace <run_id>`.
- `load_and_register_connector` synchronizes SQLite consent records with the in-memory mock bank connector across process boundaries, ensuring deterministic Account Aggregator session fetching.

## Stage 1.12: Evaluation Harness and Golden Scenarios

### 1. Honest Multi-Seed Benchmark Engine
- What was built: `src/copilot/eval/harness.py` and `scripts/run_eval.py` implementing a deterministic evaluation harness across multiple synthetic seeds (`[42, 123, 999]`), outputting `docs/eval_report.md`.
- Why it was designed this way: A defensible viva evaluation must provide concrete mathematical metrics on categorization accuracy, coverage, review queue rate, transfer detection F1, subscription detection F1, anomaly detection F1, advice grounding rate, and double ingestion idempotency rather than anecdotal claims.
- Rules enforced: Never tune categorization rules on evaluation seeds; maintain held-out seeds; report both mean and spread; state weak spots plainly.

### 2. Golden Scenarios Suite
- What was built: 12 comprehensive scenario tests in `tests/golden/test_golden_scenarios.py` validating critical Phase 1 safety and consistency invariants:
  1. Idempotent double ingestion produces zero duplicate rows.
  2. Internal transfers between owned accounts excluded from spend aggregations.
  3. Recurring subscriptions correctly identified and projected as fixed obligations.
  4. Budget warning transitions precisely at configured threshold.
  5. Run-rate spend acceleration triggers projected exceed warning.
  6. Insufficient historical data gracefully triggers safe fallback forecast.
  7. Low-confidence ambiguous transactions routed to human review queue.
  8. User corrections propagate to Monthly Review v2 while preserving immutable v1.
  9. Autonomous agent strictly blocked from overwriting user category choices.
  10. Batch undo safely reverts automated categorizations without affecting user edits.
  11. Advice validator rejects ungrounded/invented numbers and triggers deterministic template fallback.
  12. Expired or revoked Account Aggregator consent strictly blocks statement fetches.

## Stage 1.13: Minimal Streamlit UI Blueprint

### 1. Architectural Invariant: Zero Business Logic in UI
- What was built: `src/copilot/ui/app.py` providing a clean, modular Streamlit blueprint containing 5 core financial views:
  1. Financial Overview Dashboard (KPI cards, budget progress bars, recent transactions).
  2. Review Queue (HITL workflow with category selection, "Remember rule" checkbox, recategorization).
  3. Financial Advice Approvals (draft advice review with Approve/Reject actions).
  4. Monthly Review Viewer (versioned Markdown and HTML preview with on-demand rebuild).
  5. Audit Trail & Undo (append-only timeline, before/after diffs, one-click undo).
- Why: Serves as a working functional prototype and architectural blueprint for subsequent phases without duplicating any domain logic, database queries, or policy rules.
- Choke point enforcement: Streamlit callbacks NEVER import or execute tool handlers directly. Every action strictly invokes `execute_tool(ctx, tool_name, params)` with actor attribution and append-only audit logging.

## Stage 1.14: Hardening, Security Firewalls, and Phase 1 Sign-Off

### 1. Hardening and Error Degradation
- What was reviewed and verified:
  - Database integrity: Foreign key constraints, negative budget prevention, and integer paise arithmetic across all paths.
  - Logging privacy: Zero PII, bank account numbers, or transaction narrations emitted to logs or standard error.
  - LLM resilience: Automatic PII redaction firewall; quota exhaustion or provider errors gracefully fall back to deterministic template advice and review queues without application crashes.
  - Idempotency & Concurrency: Savepoint rollbacks ensure atomicity on tool failures; append-only SQLite triggers prevent mutation of audit events.

### 2. Phase 1 Sign-Off
- Full test suite: 397 passed / 397 total.
- Code quality: Clean linting with 0 ruff errors across src, tests, config, and scripts.
- Documentation: Complete architecture reference, CLI guide, Streamlit quickstart, and evaluation benchmark in `README.md`, `STATUS.md`, `docs/PLAN_PHASE1.md`, and `docs/eval_report.md`.

## Stage 2.0: Alignment, Failure-Path Audit, and Capability Matrix

### 1. What was built:
- Mapped Phase 2 requirements to existing code in `docs/phase2_alignment.md`.
- Enhanced `ToolFailure` with optional `audit_event_type` and `audit_metadata`, enabling refusal audit records (`undo_refused`, `plan_rejected`, `input_refused`) to survive handler savepoint rollback on the real `execute_tool` path.
- Aligned UI undo caller parameter from `event_id` to `audit_event_id`.
- Created Pydantic schemas and strict loaders in `src/copilot/config/phase2.py` for all 8 Phase 2 YAML configs.
- Created `scripts/generate_capability_matrix.py` and `docs/capability_matrix.md`.
- Established `docs/known_issues.md`.

### 2. Why this design:
- Preserving domain failure events (`undo_refused`, `plan_rejected`) in `audit_events` without weakening savepoint rollbacks ensures that when a handler fails or is refused, its partial writes are cleanly discarded while the exact governance refusal record is immutably logged for auditability and timeline generation.

### 3. What it deliberately does not do:
- It does not modify `execute_tool`'s signature or its default-deny policy lookup.
- It does not permit any write-class tool to be `planner_selectable`.

### 4. Examiner Viva Q&A:
- *Q: Why can't a tool handler simply insert its own refusal audit record before raising an exception?*
- *A: Because `execute_tool` encapsulates the tool handler in an atomic transaction savepoint. If a handler raises an exception, the savepoint rolls back ALL database writes made inside the handler block to guarantee state consistency. By carrying `audit_event_type` and `audit_metadata` on `ToolFailure`, the executor writes the refusal event in its own independent savepoint AFTER the rollback, guaranteeing the audit record survives while partial mutations are discarded.*
## Stage 2.1: Schema, Typed Models, and Repositories

### 1. What was built:
- SQLite migration `003_phase2_schema.sql` adding `agent_tasks`, `plan_steps`, `investigations`, `hypotheses`, `evidence_items`, `simulations`, `alerts`, `alert_preferences`, extending `advice_items` with Phase 2 origin/status/calculation columns, and upgrading `goals` from Phase 0 stub to full schema.
- All 16 typed Pydantic models in `src/copilot/models/agentic.py` (`AgentTask`, `PlanStep`, `Goal`, `Investigation`, `Hypothesis`, `EvidenceItem`, `Simulation`, `Alert`, `AlertPreference`, `Intent`, `Plan`, `Reflection`, `WhatIfScenario`, `SimulationResult`, `AlertRule`, `TaskGraph`).
- Repository functions in `src/copilot/db/repo.py` supporting parameterised queries, transactions, and mandatory `user_id` isolation.
- Comprehensive test suite in `tests/db/test_phase2_schema.py` verifying migrations, idempotency, foreign key enforcement, and JSON round-trips.

### 2. Why this design:
- Upgraded the stub `goals` table via a temporary table transfer pattern (`new_goals` -> copy -> drop old -> rename) to preserve database backward compatibility and maintain `STRICT` constraints and foreign keys without destructive drops.
- Pydantic models separate DB representation (e.g. `evidence_json` as string) from business reasoning objects (e.g. `evidence: list[EvidenceItem]`), while providing validation and ISO-8601 normalization.

### 3. What it deliberately does not do:
- Does not expose untyped or arbitrary JSON blobs without schema validation.
- Does not allow database queries to bypass `user_id` filtering.

### 4. Examiner Viva Q&A:
- *Q: Why was `goals` upgraded via a table copy pattern rather than ALTER TABLE?*
- *A: SQLite's `ALTER TABLE` has limitations regarding adding columns with complex NOT NULL constraints and foreign keys in STRICT mode. Using the table copy pattern (`CREATE TABLE new_goals ...; INSERT INTO new_goals ...; DROP TABLE goals; ALTER TABLE new_goals RENAME TO goals;`) guarantees table constraints (such as `CHECK (target_paise > 0)` and `FOREIGN KEY (user_id)`) are fully validated and consistent without losing existing records.*

## Stage 2.2: Goals and Goal-Aware Reasoning

### 1. What was built:
- Pure deterministic goal functions in `src/copilot/core/goals.py`: `months_remaining`, `required_monthly_paise`, `monthly_surplus_estimate`, `goal_status`, and `goal_impact`.
- Tool handlers and contracts in `src/copilot/tools/goals.py`: `create_goal` and `update_goal` (actor user: allow, actor agent: needs_approval; write_logical), `list_goals` (read, planner-selectable), `evaluate_goal_impact` (compute, planner-selectable).
- Actor-aware governance permissions in `config/policy.yaml` and tool definitions in `config/planner_capabilities.yaml`.
- Full test coverage in `tests/core/test_goals.py` and `tests/tools/test_goals_tools.py` verifying hand-computed boundaries, ceil rounding, IST month boundaries, user isolation, and through-executor execution.
- Mutation check per rule 0.6.3: temporarily weakened `create_goal` agent policy rule to `allow`; confirmed test `test_load_repo_policy` failed immediately; reverted and restored clean state.

### 2. Why this design:
- All financial calculations (surplus, pace, shortfall) are pure functions operating on integer paise. Deadlines are evaluated using IST calendar months so timezone boundaries do not cause shifts in required monthly savings.
- Goals modifications are strictly restricted: agents can evaluate impact autonomously, but creating or updating goals requires human-in-the-loop approval.

### 3. What it deliberately does not do:
- Does not move money or allocate funds into bank accounts or virtual partitions (virtual balance partitioning is deferred to Phase 3).
- Does not allow the LLM to invent numbers, compute savings rates, or decide goal feasibility.

### 4. Examiner Viva Q&A:
- *Q: Why does `required_monthly_paise` use ceiling rounding instead of standard rounding?*
- *A: If someone needs to save 100 paise over 3 months, standard rounding (or floor rounding) would yield 33 paise per month, totalling 99 paise and leaving a 1-paisa shortfall at the deadline. Ceiling rounding produces 34 paise per month (34 * 3 = 102 paise), guaranteeing that the target amount is achieved by the deadline.*

## Stage 2.3: What-If Simulation Engine

### 1. What was built:
- Core deterministic projection engine in `src/copilot/core/simulation.py`: `simulate()` and `compare_scenarios()`, along with `build_financial_snapshot()` which aggregates accounts, variable category spending over trailing months, recurring commitments, budgets, and active goals.
- Tool handlers in `src/copilot/tools/whatif.py`: `run_whatif` and `compare_options`, registered under `SideEffect.READ` with compute classification and full planner selectability.
- Invariant and property-based test suite in `tests/core/test_simulation.py` and tool invocation tests in `tests/tools/test_whatif_tools.py`:
  - Identity: 0 amount matches baseline spend and surplus exactly.
  - Monotonicity: adding spend never increases surplus or decreases spend; reducing spend never decreases surplus or increases spend across 50 pseudo-random property iterations.
  - Conservation of paise: all additions and reductions balance exactly without paise leakage.
  - Horizon bounds: simulation strictly clamps horizons to [1, 24] months.
  - Audit logging: executions record immutable simulation records to `simulations` table and `simulation_executed` audit events.
- Executed Rule 0.6.3 mutation check proving test failure when `month_surplus` calculation is altered, followed by clean reversion.

### 2. Why this design:
- Simulation projections must never mutate accounts, budgets, or transactions. By generating transient projections and recording explanation records to `simulations` with `SideEffect.READ`, agents can freely explore scenarios safely.
- Invariant tests guarantee that arithmetic properties hold across wide ranges of randomly sampled amounts and horizons without introducing external testing dependencies.

### 3. What it deliberately does not do:
- Does not modify any user transactions or persisted account balances.
- Does not perform complex Monte Carlo or stochastic market return modeling; projections are based on deterministic historical baseline snapshot extrapolation.

### 4. Examiner Viva Q&A:
- *Q: Why are `run_whatif` and `compare_options` categorized under `SideEffect.READ` when they write to the `simulations` and `audit_events` tables?*
- *A: From a financial and security perspective, they have read-only effects on user financial state: they do not mutate accounts, categories, transactions, or budgets. The writes to `simulations` and `audit_events` are append-only explanation and audit records for reproducibility and user history, not state mutations that change financial truth.*

## Stage 2.4: Investigation Engine and Hard Synthetic Data

### 1. What was built:
- Enhanced Synthetic Generator v3 in `src/copilot/bank/synth.py`:
  - `generate_transactions_v3` with hidden ground-truth causes (`InjectedCause`), distinct `DEV_SEEDS` vs `HELD_OUT_SEEDS`, and `hard` profile (obscure merchant aliases like `BUNDLTECH-BANGALORE`, POS/DEBIT noise, short baseline histories, and overlapping causes).
  - Deterministic fixed recurring commitments (e.g. rent and mess bills) held stable across baseline and target months to prevent artificial noise variance.
- Core Investigation Suite in `src/copilot/core/investigation.py`:
  - Mathematical spend decomposition invariant ($V + T + new + stopped + residual \equiv \Delta S$) with zero paise drift.
  - Closed catalogue of 8 hypotheses (`one_off_large`, `more_frequent`, `higher_ticket`, `new_merchant`, `recurring_change`, `miscategorization`, `duplicate_or_refund`, `seasonal_or_timing`).
  - Deterministic hypothesis scoring, evidence collection, and outcome synthesis (`explained`, `partially_explained`, `inconclusive`, `needs_clarification`).
  - Noise floor rule: monthly changes below 12% and ₹2,500 with no decisive structural cause return `inconclusive`.
- Tools in `src/copilot/tools/investigation.py`:
  - `investigate_anomaly`, `explain_change`, `dismiss_anomaly` registered in policy and capability matrix.
- Comprehensive test suites in `tests/bank/test_synth_v3.py`, `tests/tools/test_investigation_tools.py`, and `tests/core/test_investigation.py` (17 tests total, 450 total across codebase).
- Executed Rule 0.6.3 mutation check proving test failure when outcome classification threshold is altered.

### 2. Why this design:
- An investigation engine must exhibit honest uncertainty: when data is noisy, short, or ambiguous, it must return `inconclusive` or `needs_clarification` rather than hallucinating explanations.
- Ground truth causes must be tracked separately from transaction domain models so that the investigation engine is evaluated on truly blinded data.
- The mathematical decomposition invariant guarantees that volume, ticket, merchant additions/cessations, and residuals sum exactly to total spend change in integer paise across all periods.

### 3. What it deliberately does not do:
- Does not allow LLM free-text reasoning to invent candidate causes outside the closed catalogue of 8 hypotheses.
- Does not modify past transactions or auto-recategorize without passing through audited HITL tools.

### 4. Examiner Viva Q&A:
- *Q: Why does the decomposition theorem include a `residual_paise` term alongside Volume and Ticket effects?*
- *A: When transaction volumes and ticket averages change simultaneously across diverse merchants, cross-terms arise ($V \times T$ interaction effects). Setting $residual = \Delta S - (V + T + new + stopped)$ ensures the decomposition holds as an exact mathematical identity in integer paise with zero drift, regardless of basket composition.*
- *Q: How does the engine avoid false explanations on unstructured noise months?*
- *A: Under the noise floor rule (PLAN_PHASE2 Section 5.4), if total monthly change is below 12% of baseline spend and less than ₹2,500, the variation is statistically consistent with ordinary random living expenses. Unless a decisive structural cause (such as a subscription price hike, category misclassification, or double charge) is strongly supported, the engine honestly returns `inconclusive` (0% false explanations).*

## Stage 2.5: Adaptive Alerts

### 1. What was built:
- Core Adaptive Alerting in `src/copilot/core/alerts.py`:
  - Multi-signal scoring engine combining 5 deterministic signals normalized to [0.0, 1.0]:
    1. Threshold: budget status and consumption ratio (1.0 for exceeded, 0.5..1.0 for warning).
    2. Forecast: projected overflow and range exceedance based on run-rate daily velocity.
    3. History deviation: robust z-score of category spend-to-date against prior months median using Median Absolute Deviation (MAD).
    4. Anomaly: open anomaly scores for the category from Phase 1 detectors.
    5. Goal impact: detects active financial goals transitioning to `at_risk` or `off_track`.
  - Confidence damping function: scales score down (from 1.0 to 0.35) when historical baseline is sparse (<3 months or <5 transactions), ensuring the system does not produce high-severity alerts on low data sufficiency.
  - Severity mapping: basis point bands for `info` (2500), `notice` (5000), `warning` (7500), and `critical` (9000).
  - Grounded `why_text` template engine: strictly formats text using only verified component numbers.
- Tools in `src/copilot/tools/alerts.py`:
  - `evaluate_alerts`: Agent-executable logical write evaluating active categories against signals and user preferences. Supports deduplication by `dedup_key`, cooldown windows on dismissal, and in-place escalation for worsening conditions.
  - `decide_alert`: User-actor tool for `acknowledge`, `dismiss`, and `snooze(days)`.
  - `set_alert_preference`: User-actor tool configuring category/global muting, minimum severity, and maximum open alert quotas.
  - `list_alerts`: Filterable read tool for active and historical alerts.
  - Auditing: All suppressed alerts emit `alert_suppressed` audit events for timeline transparency.
- Governance & Registrations:
  - Policy entries in `config/policy.yaml`, capability assignments in `config/planner_capabilities.yaml`, registration in `src/copilot/workflow/nodes.py`, and capability matrix documentation updated.
- Comprehensive Testing:
  - 15 tests across `tests/core/test_alerts.py` and `tests/tools/test_alert_tools.py` verifying all signals, boundaries, damping, grounded why_text, user preferences, dedup/escalation, cooldown, snooze, and cross-user isolation.
  - Executed Rule 0.6.3 mutation check proving test failure when confidence damping is mutated to 0.0, followed by clean reversion.

### 2. Why this design:
- Alert fatigue is a primary reason users abandon personal finance applications. Adaptive alerts enforce a "quiet-by-default" design: healthy ordinary months produce zero alerts above `info`.
- Signals combine deterministic threshold breaches with predictive forecast run-rates, robust historical deviations, and goal impacts, rather than triggering on simple single-point threshold crossings.
- Damping factor strictly damps (never inflates) the score when data history is short, honoring honest uncertainty.
- In-place escalation prevents duplicate alert clutter by updating existing open alerts when metrics worsen.

### 3. What it deliberately does not do:
- Does not send push notifications, emails, or SMS; notification delivery channels belong to Phase 6. In Phase 2, alerts are persisted records accessible via tools and timeline.
- Does not permit the LLM to invent alert thresholds, confidence numbers, or why_text text outside the deterministic templates.
- Does not allow the agent to mutate user alert preferences or dismiss alerts on behalf of the user.

### 4. Examiner Viva Q&A:
- *Q: Why are alerts damped by data confidence rather than just using a simple threshold rule?*
- *A: A single transaction in a brand-new account could easily exceed an initial budget or look like a 10x deviation if only 2 days of history exist. Without confidence damping, new users would be inundated with high-severity false alarms. Damping scales the alert severity down (e.g., from critical/warning to info/notice) until sufficient history (>=3 months, >=5 transactions) confirms genuine behavioral shift.*
- *Q: Why are suppressed alerts logged to `audit_events` if they are not shown to the user?*
- *A: When a user asks "Why didn't you alert me about Dining spend?", the copilot timeline must explain: "An alert was evaluated with score 6500 bp, but suppressed because Dining was muted by user preference." Logging `alert_suppressed` ensures complete explainability and auditability without violating user preference silences.*

## Stage 2.6: Explainable Recommendations and Narration Validation

### 1. What was built:
- Extended Advice Validation (`src/copilot/core/advice.py`):
  - Upgraded Phase 1 validator without forking to support multi-source number grounding across findings, investigations (decomposition numbers and evidence metrics), simulations (scenario amount, months, monthly spend/surplus projections), goals (target, current, required monthly, months remaining), and intermediate calculations.
  - Causal-claim safety rule: Words asserting cause (`because`, `due to`, `caused by`, `driven by`) are strictly forbidden unless supported by an investigation with outcome `explained` and confidence >= `medium`.
  - Consequence safety rule: Recommendations of kind `spend_decision`, `reduce_spend`, or `contribution_change` strictly require a valid `simulation_id` linked to a registered simulation.
  - Prediction check: Predictive statements permitted only when grounded in forecast findings or an attached simulation scenario.
  - Unknown ID validation: Rejects drafts citing nonexistent finding IDs or simulation IDs.
  - Preserved Phase 1 rounding tolerances, boundary checks, and lakh formatting without regression.
- Recommendation Services (`src/copilot/core/recommendations.py`):
  - Memory extraction: `find_relevant_memories` queries past advice decisions and preference overrides with strict `user_id` filtering.
  - Recommendation builder: `build_recommendation` deterministically validates draft narration against all cited evidence sources. Upon validation failure or ungrounded claims, it seamlessly substitutes a safe, deterministic fallback template loaded from `config/explanation_templates.yaml`.
  - Explanation renderer: `format_recommendation_explanation` renders complete human-readable explanations for `copilot explain <id>` exposing all 8 required sections (ID/origin/status, Text, Evidence Cited, Calculations Performed, Assumptions, Tools Used, User Memories/Past Decisions Relied On, and Linked Simulation Scenario).
- Repository Integration (`src/copilot/db/repo.py`):
  - `insert_recommendation`, `_row_to_recommendation`, `get_recommendation`, `list_recommendations`, and `update_recommendation_status` mapped directly to migration 003's extended `advice_items` schema.
- Tool Invariant Fix (`src/copilot/tools/advice.py`):
  - Integrated `to_utc_iso` from `timeutil` ensuring second-precision ISO-8601 formatting complying with database `GLOB` check constraints across advice lifecycles.
- Comprehensive Testing (`tests/core/test_recommendations.py`):
  - 10 tests verifying number grounding, rejection of invented numbers and wrong percentages, causal-claim enforcement, consequence rule enforcement, forbidden content rejection (investment advice, money transfers, guarantees), fallback template application, full 8-section explanation formatting, strict cross-user memory isolation, unknown ID rejection, and verification that recommendation approval triggers no financial mutations or actions.
  - Executed Rule 0.6.3 mutation checks proving test failure when either the causal-claim rule or consequence rule is disabled, followed by clean reversion.

### 2. Why this design:
- In financial advice, ungrounded claims and unwarranted causal assertions ("you overspent because of weekend dining" when unexplained residual is large) destroy user trust and carry legal/regulatory liability.
- The causal-claim and consequence safety rules ensure the LLM cannot assert cause without mathematically proven investigation evidence, nor propose consequential budget changes without simulated projections.
- Deterministic fallback templates ensure the system fails gracefully into safe, grounded advice even if the LLM hallucinates ungrounded numbers or violates safety constraints.
- Full 8-section explanations empower users to inspect the exact evidence, formulas, assumptions, tools, and past decisions that produced every piece of advice.

### 3. What it deliberately does not do:
- Does not allow the LLM to invent numbers, percentages, or time horizons not present in cited findings, investigations, simulations, or goals.
- Does not permit recommendations to name specific investment assets, stocks, mutual funds, or provide payment transfer instructions.
- Does not execute financial actions or money movements upon recommendation approval. Approval merely records user acceptance in `advice_items`.

### 4. Examiner Viva Q&A:
- *Q: Why are causal words like "because" and "due to" treated as safety violations in recommendations?*
- *A: An LLM naturally generates convincing causal stories even when the underlying data is inconclusive. In personal finance, false causal attributions lead users to take wrong actions (e.g., cutting grocery spend when the real driver was an annual insurance premium). The causal-claim rule enforces that causal assertions can only be made when deterministic investigation has proved the cause with >= medium confidence.*
- *Q: Why do consequential recommendations mandate a simulation_id?*
- *A: Advising a user to make a large discretionary purchase or alter monthly savings contributions directly impacts future liquidity and goal completion dates. Mandating a simulation ensures that every consequential proposal is backed by month-by-month cashflow projections and verified goal impact waterfall calculations before reaching the user.*

## Stage 2.7: Input Gate and Intent Understanding

### 1. What was built:
- Input Gate and Refusal Framework (`src/copilot/core/intent.py`):
  - Deterministic evaluation of natural language queries against 5 refusal classes: `INVESTMENT_ADVICE`, `MONEY_MOVEMENT`, `MARKET_PREDICTION`, `SENSITIVE_DATA_SUBMISSION`, and `OUT_OF_SCOPE`.
  - Helpful refusal guidance: Template responses explaining what the copilot can do instead (analyze savings rate, simulate what-if scenarios, budget limits) loaded from `config/intent_patterns.yaml`.
  - Look-alike benign query preservation: Distinguishes between imperative commands to move money/provide stock picks and analytical historical questions (e.g., "How much did I transfer to savings last month?", "Did I pay my electricity bill in September?", "How much did I spend on gold jewelry?").
- Deterministic Parsers:
  - Amount parser: Converts natural amounts into integer paise with support for Western and Indian comma grouping (`1,25,000`), multipliers (`20k`, `2 lakh`, `1.5 cr`), prefixes/suffixes (`₹`, `Rs.`, `rupees`), and spending contexts (`buy laptop for 45000`, `cut dining by 3500`).
  - Period parser: Supports relative periods (`this month`, `last month`, `next month`), IST boundaries (evaluating midnight rollover in Asia/Kolkata), explicit formats (`2026-10`, `October 2026`), and multi-month horizons (`last 3 months`, `next 6 months`).
  - Entity resolver: Resolves categories, merchants, and goals strictly against active database records with zero-hallucination guarantee (unknown entities return `None`).
- Intent Classification & Task Creation:
  - 10 core intent types: `summarize_period`, `explain_change`, `investigate_anomaly`, `check_budget`, `forecast`, `whatif_add_spend`, `whatif_reduce_spend`, `goal_check`, `list_recurring`, `alerts_overview`.
  - Single-round clarification generator: Produces concrete, data-derived choices (up to 4 options from user's data) when a required slot is missing.
  - Safe `create_agent_task` entrypoint: Automatically redacts PII before prompts, enforces that raw text is never logged or exposed in audit payloads, and persists typed `AgentTask` rows.
- PII Redaction (`src/copilot/llm/redactor.py`):
  - Strict pattern replacement for phone numbers (`[PHONE]`), account/card numbers (`[ACCOUNT]`), UPI IDs (`[UPI]`), and credentials (`[REDACTED_SECRET]`).
- Safety Rule 4 Enforcement:
  - An LLM-proposed refusal is added; an LLM-proposed "allow" cannot remove a deterministic refusal.
  - Hallucinated entities returned by an LLM helper are strictly dropped.
  - Fully functional with LLM completely off.
- Comprehensive Testing (`tests/core/test_intent.py`):
  - 33 tests covering amount tables, period tables, IST boundaries, month rollover, entity resolution, 42 labelled queries achieving 100% deterministic accuracy, refusal vs look-alike benign queries, Safety Rule 4 enforcement, prompt redaction, and logging safety.
  - Executed Rule 0.6.3 mutation check proving test failure when the deterministic input gate is bypassed, followed by clean reversion.

### 2. Why this design:
- Natural language input from end-users is noisy, ambiguous, and potentially adversarial. The deterministic input gate acts as an inviolable perimeter: safety refusals trigger before any LLM is called, minimizing token cost and eliminating jailbreak risks.
- PII redaction and logging guards guarantee financial privacy: account numbers, phone numbers, and UPI handles never leak into LLM prompts or persistent audit traces.
- Deterministic mathematical and entity parsers guarantee exact integer paise arithmetic and prevent hallucinated categories or goals from entering agent planning.
- The single-round clarification limit avoids conversational rabbit-holes and enforces bounded execution.

### 3. What it deliberately does not do:
- Does not execute plans or invoke financial tools directly (planning and tool selection are owned by Stage 2.8).
- Does not allow the LLM to remove or weaken any deterministic input gate refusal.
- Does not persist raw user prompt text in audit events or system logs.

### 4. Examiner Viva Q&A:
- *Q: How does the input gate differentiate an illegal payment request like "Transfer ₹5,000 to Rahul" from a benign query like "How much did I transfer to savings last month?"*
- *A: The input gate employs structural syntax classification. Imperative command phrases instructing action ("Transfer ₹X to Y", "Send money", "Pay my bill") are distinguished from interrogative/analytical past inquiries ("How much did I transfer...", "Did I pay...", "Show transfers"). The latter are allowed through to analytical tools, while imperative transaction requests are immediately refused with a safe guidance message.*
- *Q: Why are LLM-returned entities re-validated against the database?*
- *A: An LLM may hallucinate non-existent categories (e.g. "Cryptocurrency") or foreign goals when parsing ambiguous natural text. Re-validating entities against the user's active database tables (`categories`, `goals`, `transactions`) guarantees that only verified, existing identifiers reach the planner. Anything unverified is safely dropped.*

## Stage 2.8: Planner, Dynamic Tool Selection, and Agent Graph

### 1. What was built:
- Capability Matrix & Tool Catalogue Projection (`src/copilot/planner/capabilities.py`):
  - Strict enforcement of Rule 1: only `read` and `compute` tools may be planner-selectable; write tools and money movement tools are strictly non-selectable.
  - Generates sanitized tool catalogue projections (name, description, args schema) for LLM prompts.
  - Safe capability matrix validation enforcing that every registered tool has an explicit policy and capability classification.
- Plan Validation & Execution Loop (`src/copilot/planner/validator.py`, `src/copilot/planner/execution.py`):
  - Deterministic `PlanValidator`: validates tool existence, planner selectability, Pydantic input schema conformity, user data isolation on all referenced IDs, required tool sets per intent, step budgets, and duplicate step prevention. Disallowed or adversarial plans emit audited `plan_rejected` events and fall back immediately to deterministic templates.
  - Execution loop helper: enforces execution strictly through `execute_tool(ctx, tool_name, args)` executor choke point, memoizes identical calls as `skipped_memoized`, detects loops on repeated identical or failing calls with `loop_detected`, and updates `plan_steps` state in SQLite.
- Planners (`src/copilot/planner/deterministic.py`, `src/copilot/planner/llm_planner.py`):
  - `DeterministicPlanner`: dynamically binds parsed intent entities to minimal canonical templates in `config/plan_templates.yaml`.
  - `LLMPlanner`: structured JSON proposal via Gemini SDK with automatic fallback to `DeterministicPlanner`.
- Planner-Driven Agent Graph (`src/copilot/workflow/agent_graph.py`, `src/copilot/workflow/agentic_nodes.py`, `src/copilot/workflow/agentic_state.py`):
  - LangGraph StateGraph topology: `understand` -> (conditional: `clarify`? / `refusal`?) -> `plan` -> `act` (loop) -> `reflect` (bounded replan) -> `synthesize` -> `review` (interrupt) -> `finalize` / `error`.
  - Thin nodes maintaining comprehensive audit trace entries, supporting human-in-the-loop interrupts (`interrupt` and `Command(resume=...)`), and persisting final task status (`done`, `stopped`, `refused`).
- Comprehensive Testing:
  - 18 tests across `tests/planner/` (`test_capabilities.py`, `test_validator.py`, `test_planner.py`).
  - 5 integration tests in `tests/workflow/test_agent_graph.py` covering end-to-end execution, refusal immediate termination, clarification interrupt & resumption, step budget bounds, and adversarial LLM plan rejection & fallback.
  - 3 updated tests in `tests/tools/test_no_money_movement.py`.
  - Executed Rule 0.6.3 mutation check proving test failure when `is_planner_selectable` check in `PlanValidator` is weakened, followed by clean reversion.

### 2. Why this design:
- Bounded autonomy and safety-by-construction: Rather than allowing the LLM unbounded execution or direct access to code/handlers, the agent graph enforces that every tool proposal is validated deterministically before execution.
- Default-deny capability isolation ensures the LLM planner cannot select write tools, edit user preferences, recategorize transactions, or initiate actions.
- The execution loop enforces memoization and repeat loop detection to prevent runaway LLM execution or wasted compute.
- Deterministic template fallbacks guarantee that even if an LLM is completely offline, quota-exhausted, or adversarial, the user still receives a correct, evidence-based financial answer.

### 3. What it deliberately does not do:
- Does not permit the planner or any workflow node to call tool handlers directly; all execution passes strictly through `execute_tool(ctx, tool_name, args)`.
- Does not allow write tools, user configuration tools, or money movement tools to be selected by the planner.
- Does not allow multi-turn conversational chat; clarification is strictly bounded to a single round before conclusive resolution or clean termination.

### 4. Examiner Viva Q&A:
- *Q: How does FinCo prevent an adversarial or hallucinating LLM from executing unauthorized database modifications?*
- *A: Through a three-layer defense: First, the prompt tool catalogue projection exposes only tools marked `planner_selectable: true` in `config/planner_capabilities.yaml` (write tools are excluded at the prompt level). Second, when the LLM returns a proposed plan, `PlanValidator.validate_plan` deterministically checks each step against `is_planner_selectable`; if any disallowed tool (such as `recategorize_transaction` or `create_goal`) is present, the plan is rejected, audited under `plan_rejected`, and completely replaced by the deterministic template plan. Third, even if a plan step were somehow scheduled, the execution choke point `execute_tool` enforces the actor role and policy permissions from `config/policy.yaml`.*
- *Q: How does the agent graph handle bounded re-planning without entering infinite loops?*
- *A: The `reflect_node` inspects the outcome of evidence gathering (e.g. from an anomaly investigation). If the outcome is `partially_explained` or `inconclusive`, and the current rounds count is strictly less than `max_rounds` (default 2), it appends exactly one further investigation step testing untested catalogue hypotheses. Once `rounds >= max_rounds` or `replan_triggered` is True, reflection terminates and execution advances to `synthesize_node`, ensuring strict termination bounds.*

---

## Stage 2.9: Activity Timeline and CLI Interface: DONE

### 1. What was built:
- Activity Timeline Read Model (`src/copilot/core/timeline.py`):
  - Pure derived read model merging `audit_events`, `agent_tasks`, `plan_steps`, run trace entries, `investigations`, `simulations`, `alerts`, and pending `advice_items` into chronologically ordered `TimelineEntry` objects.
  - Separates pending approvals into a dedicated section, guarantees stable ordering, sanitizes all raw query texts into structured intent representations, and outputs JSON compatible with frontend dashboards.
- CLI Commands Extension (`src/copilot/cli/main.py`, `src/copilot/cli/formatters.py`):
  - `copilot ask "<text>"`: Full agent graph execution for natural language queries with status indicators, governance refusal banners, and clarification prompts.
  - `copilot investigate`: Direct anomaly or category spend investigation with detailed mathematical breakdown.
  - `copilot whatif`: `add-spend`, `reduce-spend`, and `compare` commands with rich tabular projection and diff formatting.
  - `copilot goals`: Complete user lifecycle commands (`add`, `list`, `update`, `done`).
  - `copilot alerts`: Multi-signal evaluation, list, acknowledgment, dismissal, snooze, and preference updates.
  - `copilot timeline`: Chronological visual table and `--json` machine-readable output.
  - `copilot explain` & `copilot decide`: Recommendation explainability inspection and approval/rejection.
- Documentation & Demo Script:
  - Created `docs/demo_script_phase2.md` outlining the 6-minute offline demo path.
  - `tests/cli/test_phase2_cli.py`: 12 comprehensive integration tests covering all CLI commands, JSON streaming, error handling (unknown IDs, invalid arguments, constraints), and full offline demo path execution (`test_demo_script_phase2_offline`).

### 2. Why this design:
- Derived over stored: The timeline requires no separate storage tables, eliminating data duplication and synchronization issues.
- Consistent governance: All CLI commands route through `execute_tool` or service layers, ensuring identical audit logging, policy checks, and error formatting regardless of entry point.
- Machine readability: Every command supports `--json` for direct ingestion by tests, automation, and web/UI frontends.

### 3. What it deliberately does not do:
- Does not expose financial write tools or money movement to autonomous execution.
- Does not permit multi-turn conversation in `copilot ask`; queries are single-round with bounded single-question clarification.
- Does not store unredacted user query text in the timeline or audit logs.

### 4. Examiner Viva Q&A:
- *Q: Why is the agent timeline implemented as a derived read model rather than a dedicated database table?*
- *A: A derived read model guarantees that the timeline is always an immutable, synchronized, single source of truth computed directly from the append-only `audit_events`, `agent_tasks`, `investigations`, `simulations`, and `advice_items` tables. If it were a separate table, it would risk falling out of sync on rollbacks or errors, violating audit integrity.*
- *Q: How does the CLI ensure that expected errors (like unknown IDs or invalid syntax) do not expose raw Python exceptions?*
- *A: All CLI commands catch domain errors (such as `ToolFailure`, validation exceptions, or missing entities) and route them through `print_error` from `src/copilot/cli/formatters.py`, exiting with code 1 and clean, actionable terminal messages without tracebacks.*











### Web UI track: user corrections resolve the review flag
What changed: `recategorize_transaction` now clears `needs_review` and records it in the audit before/after, and `undo` restores it. Golden scenario 05's expected audit payload gained `needs_review: false` for the same reason.
Why: found by the browser end-to-end test: after a user corrected an item in the review queue it stayed in the queue, because only the category fields changed. A user's choice settles the question.
Not doing: the divergence check in undo still compares only the category fields.

---

## Stage 2.10: Evaluation Harness and Golden Scenarios: DONE

### 1. What was built:
- Multi-Seed Phase 2 Evaluation Harness (`src/copilot/eval/harness_phase2.py`, `scripts/run_eval_phase2.py`, `copilot eval --phase 2`):
  - Benchmarks the autonomous agentic pipeline across held-out synthetic seeds (`[777, 888, 999]`) that were never used during development or tuning.
  - Automatically measures and writes `docs/eval_report_phase2.md` covering:
    - Intent Type Accuracy: 100.0% (16/16 test queries correctly classified).
    - Refusal Precision & Recall: 100.0% / 100.0% (all investment advice, market prediction, and money movement requests blocked).
    - Planner Canonical Match: 100.0% exact-set tool selection, with 0.0 extra tools per task.
    - Adversarial Plan Rejection: 100.0% rejection of unauthorized write and configuration tools.
    - Spend Decomposition Mathematical Invariant: 100.0% exact conservation of paise ($\Delta \text{Total} = \Delta \text{Fixed} + \Delta \text{Variable} + \text{Unexplained}$).
    - No-Cause False Explanation Rate: 0.0% (all no-cause months correctly yield inconclusive or hedged outcomes).
    - Simulation Invariants: Identity, monotonicity, and paise conservation all PASS.
    - Adaptive Alerts: Ordinary month silence rate 100.0%, noise reduction vs threshold baseline 66.7%, muted category suppression 100.0%.
    - Recommendation Grounding & Safety: 100.0% narration number grounding, 0 causal claim violations, 0 missing simulation violations.
    - Mean Query Latency: ~23ms offline execution.
- 16 Phase 2 Golden Scenarios (`tests/golden/phase2/test_golden_phase2.py`):
  - Comprehensive invariant suite verifying all 16 critical Phase 2 requirements (investigations, hedged sentences, plan validation, runaway plan step budgets, what-if goal flipping, zero-amount what-if baseline equality, alert silence and muting, causal claim defense, consequence simulation gate, governance refusals, clarification bounds, activity timeline pending approvals, Phase 1 monthly review compatibility, and user category preservation).

### 2. Why this design:
- Empirical mathematical rigor: Prevents subjective or anecdotal claims by enforcing hard mathematical assertions on held-out seeds.
- Zero data leakage: Evaluation seeds were strictly sequestered; rules and thresholds were tuned solely on development seeds (`[42, 101, 202]`).
- Both CLI and script runnable: Exposes both rich terminal table formatting and raw pipeable `--json` output.

### 3. What it deliberately does not do:
- Does not tune thresholds on evaluation seeds (honesty rule 6).
- Does not test live internet APIs; evaluation is completely offline, deterministic, and reproducible.
- Does not hide inconclusive rates or hard profile recall drops; all weak spots are explicitly documented in `docs/eval_report_phase2.md`.

### 4. Examiner Viva Q&A:
- *Q: Why does the evaluation harness test on held-out seeds, and what does the inconclusive rate represent?*
- *A: Testing on held-out seeds (`[777, 888, 999]`) proves that the agent's intent classification, spend decomposition, and hypothesis ranking generalize to unseen transaction patterns without data leakage. The ~40% inconclusive rate is an intended safety feature: when transaction data contains no clear causal jump (no-cause or multi-factor noise), the system refuses to assert hallucinated correlations and honestly reports inconclusive with a hedged explanation.*
- *Q: How does FinCo ensure that recommendations never make unsupported causal claims?*
- *A: Safety Rule 5 (Causal-Claim Defense) scans generated recommendation texts for causal connectives (`because`, `due to`, `caused by`). If present, the validator checks the referenced investigation. Unless the investigation achieved outcome `explained` with confidence >= `medium`, the causal claim is blocked, audited, and replaced with deterministic template fallback.*

---

## Stage 2.11: Hardening and Documentation Sign-Off: DONE

### 1. What was built:
- Architecture Documentation & README (`README.md`):
  - Full ASCII Agentic Architecture Diagram detailing Intent Router, Dynamic Planner, PlanValidator, unified `execute_tool` choke point, core engines (Investigation, Simulation, Alerts), Explanation Grounding Firewall, Timeline Read Model, and SQLite core.
  - Phase 1 vs Phase 2 Capability Matrix.
  - Complete Phase 2 CLI command reference (`ask`, `investigate`, `whatif`, `goals`, `alerts`, `timeline`, `explain`, `decide`, `eval --phase 2`).
  - Project directory map and test suite execution guide.
- Exit Checklist Verification (`docs/PLAN_PHASE2.md` Section 8):
  - Verified and marked all 17 Phase 2 exit checklist criteria as `[x]`.
- Suite Integrity & Linting:
  - Full regression test suite passing: 564/564 tests passing in ~20s.
  - Zero skips, zero xfails, zero weakened assertions.
  - Ruff linting and formatting check passing cleanly across all source, test, config, and script directories.
- Git Checkpoint B Preparation (`STATUS.md`):
  - Prepared `[GIT CHECKPOINT B]` proposed commit (`Add planner, intent understanding and agent timeline`) with exact modified/added file list, adhering strictly to the zero-unauthorized-git-commands rule.

### 2. Why this design:
- Rock-solid foundation for UI: The completion of all Phase 2 agentic engines, deterministic safety firewalls, CLI tools, and timeline read models provides a complete, stable, and tested backend for the user to develop the frontend and UI layer.
- Single source of truth: Documentation, checklists, and benchmark reports accurately reflect the actual executed codebase and verified test outputs.

### 3. What it deliberately does not do:
- Does not execute any git commands (`git status`, `git commit`, `git push`, etc.) without the user's explicit command.
- Does not introduce any new external package dependencies.
- Does not modify Phase 1 contracts or break backwards compatibility.

### 4. Examiner Viva Q&A:
- *Q: What are the primary safety firewalls separating autonomous agent decisions from financial state corruption?*
- *A: Five independent layers: 1) Intent input gate blocking money movement and investment advice; 2) Dynamic planner validator rejecting write tools from read plans and enforcing a 5-step budget; 3) Unified `execute_tool` choke point enforcing caller roles, user isolation, and append-only audit logging; 4) Explanation grounding firewall preventing unverified causal claims and ungrounded numbers; 5) Deterministic integer-paise arithmetic across all database tables, schemas, and simulation projections.*
