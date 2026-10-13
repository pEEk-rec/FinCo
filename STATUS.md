## Current state
Last completed stage: 1.13 | Blockers: none

## Stage 1.13: Minimal Streamlit View (Blueprint): DONE
Goal: A thin, modular visual interface blueprint on which the main UI builds (PLAN_PHASE1 Section 5.11).
Built:
- Added `streamlit>=1.30.0` dependency to `pyproject.toml`.
- `src/copilot/ui/app.py`: Clean, modular Streamlit blueprint implementing all 5 views:
  1. **Financial Overview Dashboard**: KPI metric cards (balance in INR, total transactions, review queue count, accounts), monthly budget performance progress bars with warning/exceeded status badges, and recent transactions table.
  2. **Human Review Queue**: Interactive HITL queue displaying transactions flagged with `needs_review=1`, dropdown category selector, "Remember rule" checkbox, and one-click recategorization executing `recategorize_transaction` through `execute_tool(ctx, ...)` with audited user attribution (`category_source='user'`).
  3. **Financial Advice Approvals**: Lists generated advice items in `draft` status with one-click "Approve" and "Reject" buttons executing `decide_advice` via `execute_tool(ctx, ...)`.
  4. **Monthly Review Viewer**: Year/month selector with "Generate / Rebuild Monthly Review" button executing `build_monthly_review` and rendering the versioned report as structured GitHub-flavored Markdown.
  5. **Audit Trail & Undo**: Append-only log of system events with before/after state diff expanders and "Undo" buttons calling `execute_tool(ctx, "undo", {"event_id": eid})`.
- **Architectural Invariant**: The UI is strictly a thin view layer over existing services/executor. Zero business logic is duplicated, and no actions bypass the policy firewall or audit log.
- `tests/ui/test_app.py`: 8 unit tests validating context creation, default database path resolution, in-memory schema initialization, and headless execution across all tab renderers.
Files: src/copilot/ui/app.py, src/copilot/ui/__init__.py, tests/ui/test_app.py, pyproject.toml, STATUS.md
Tests: 397 passed / 397 total | Lint: pass (0 ruff errors)


## Stage 1.12: Evaluation and Golden Scenarios: DONE
Goal: Comprehensive evaluation harness and 12 golden scenario tests (PLAN_PHASE1 Section 5.10 & 5.12).
Built:
- `src/copilot/eval/harness.py`: Multi-seed evaluation runner measuring categorization accuracy, coverage, high-confidence precision, review queue routing, internal transfer F1, recurring subscription F1, anomaly detection F1, advice grounding rate, and ingestion idempotency across deterministic synthetic bank seeds (`[42, 123, 999]`). Generates `docs/eval_report.md`.
- `scripts/run_eval.py`: Standalone CLI runner script executing the evaluation harness and reporting viva-defensible summary metrics.
- `src/copilot/cli/main.py`: Connected `copilot eval` command with styled Rich table output and JSON streaming option (`--json`).
- `config/categorization_rules.yaml`: Enriched regex pattern matching for student merchant narrations (Swiggy, Zomato, Canteen, Hostelmess, Uber, Rapido, IRCTC, Spotify, Netflix, Jio, Blinkit, Amazon, Xerox, Rent, Allowance, Salary) while leaving edge/anomalous merchants unmapped to genuinely exercise the human review queue.
- `tests/golden/test_golden_scenarios.py`: 12 rigorous golden scenario tests validating critical system invariants:
  1. Double ingestion produces 0 duplicates (idempotency).
  2. Internal transfers excluded from spend calculations.
  3. Recurring subscriptions detected and forecast as fixed obligations.
  4. Budget status transitions to warning at threshold.
  5. Budget projected exceed fires on accelerated run-rate spend.
  6. Insufficient data triggers safe fallback forecast.
  7. Low-confidence merchant routes to review queue.
  8. User correction propagates to Monthly Review v2 while preserving v1.
  9. Agent is strictly blocked from overwriting user category choice.
  10. Undo batch reverts automated changes without touching user edits.
  11. Advice validator strictly rejects invented numbers and triggers template fallback.
  12. Expired/revoked consent blocks bank statement fetches.
- `docs/eval_report.md`: Benchmark report with measured metrics: 100% accuracy, 96.04% coverage, 100% high-conf precision, 1.0 transfer F1, 1.0 recurring F1, 100% idempotency, 100% advice grounding, 155ms mean latency.
Files: src/copilot/eval/harness.py, src/copilot/eval/__init__.py, scripts/run_eval.py, src/copilot/cli/main.py, src/copilot/cli/formatters.py, config/categorization_rules.yaml, tests/golden/test_golden_scenarios.py, docs/eval_report.md, STATUS.md
Tests: 389 passed / 389 total | Lint: pass (0 ruff errors)


## Stage 1.11: CLI (primary demo surface): DONE
Goal: The primary interactive demo and evaluation surface (PLAN_PHASE1 Section 5.9).
Built:
- Installed `typer>=0.9.0` and `rich>=13.0.0` as core runtime dependencies; registered `copilot = "copilot.cli.main:app"` console script in `pyproject.toml`.
- `src/copilot/cli/storage.py`: Cross-process persistence layer for synthetic mock bank transactions (`data/mock_bank_<user_id>.json`), graph execution traces (`data/trace_<run_id>.json`), database resolution, and `MockAAConnector` synchronization from sqlite consent records.
- `src/copilot/cli/formatters.py`: Rich visual presentation layer implementing clean terminal tables (`print_transactions_table`, `print_budgets_table`, `print_anomalies_table`, `print_recurring_table`, `print_consents_table`, `print_audit_table`), state summary panels (`print_state_panel`), and clean standard output serializers (`print_json` using unstyled stdout for piping, `print_error` to stderr without Python tracebacks, `print_success`).
- `src/copilot/cli/main.py`: Full Typer application implementing all commands:
  - `init-db`: Idempotent database schema initialization.
  - `seed`: Seeds demo user, accounts, standard categories, budgets, and synthetic bank data.
  - `consent`: Full consent lifecycle subcommands (`list`, `create`, `approve`, `revoke`).
  - `run`: Runs full autonomous agent LangGraph workflow with trace capture and human review options.
  - `review-month`: Generates versioned monthly review and renders GitHub Markdown and styled HTML reports.
  - `txns`: Lists transactions with filters (`--month`, `--needs-review`, `--limit`, `--json`).
  - `correct`: User correction to override a transaction's category with optional `--remember` merchant rule.
  - `undo` & `undo-batch`: Reverses specific audit events or automated categorization batches.
  - `budgets`, `forecast`, `anomalies`, `recurring`, `state`: Real-time financial domain analysis views.
  - `audit`: Queryable audit log with before/after state diffs and reversibility indicators.
  - `trace`: Displays node-by-node execution traces and tool timings for any workflow run.
  - `eval`: Runner interface for Stage 1.12 evaluation scenarios.
- `docs/demo_script.md`: Comprehensive 5-minute offline demo walkthrough script covering all steps.
- `tests/cli/test_cli.py`: 11 tests using `typer.testing.CliRunner` covering every command, flag, and error branch.
Files: src/copilot/cli/main.py, src/copilot/cli/formatters.py, src/copilot/cli/storage.py, src/copilot/cli/__init__.py, src/copilot/cli/__main__.py, tests/cli/test_cli.py, docs/demo_script.md, pyproject.toml, config/policy.yaml, STATUS.md, docs/decisions.md, docs/production_report.md
Tests: 377 passed / 377 total | Lint: pass (0 ruff errors)
Goal: The worklet's headline output (PLAN_PHASE1 Section 5.8).
Built:
- `src/copilot/review/models.py`: Typed Pydantic data models for the complete review document: `MonthlyReviewData`, `CategoryTotal`, `ReviewBudgetStatus`, `ReviewRecurringItem`, `ReviewAnomalyItem`, `ReviewForecast`, `ReviewAdviceItem`, and `DataQualityNotes`.
- `src/copilot/review/builder.py`: Deterministic review builder and versioning engine:
  - Aggregates income, spend, and net cashflow using integer paise.
  - Computes previous-month baseline and category change deltas (amount & percentage).
  - Tracks budget status, recurring series, anomalies, and month-end forecast.
  - Automatically handles partial months by capping `effective_end_utc` at the review clock, computing `days_recorded` and `missing_days`.
  - Increments version counter (`v1 -> v2`) on re-run, persisting immutable review snapshots in `monthly_reviews`.
- `src/copilot/review/renderers.py`: Jinja2-based renderers for GitHub-flavored Markdown (`render_markdown`) and self-contained styled HTML (`render_html`).
  - Strict number extractor and validator (`extract_numbers_from_rendered_text`, `extract_all_review_numbers`) to prove the number containment invariant.
- `src/copilot/db/repo.py`: Added repository methods `insert_monthly_review`, `get_monthly_review`, `list_monthly_reviews`, and `list_categories`.
- `tests/review/test_monthly_review.py`: 5 tests covering:
  1. Review numbers match independent domain analysis tools (`net_spend_by_category`, `budget_status`, `forecast_month`).
  2. Re-run after user category correction creates version 2 with updated category totals while preserving version 1.
  3. Partial month handling with recorded vs missing day calculation.
  4. Month-over-month comparison accurately reflects prior month totals and deltas.
  5. CRITICAL SAFETY INVARIANT: Rendered Markdown and HTML contain no numbers absent from the `MonthlyReviewData` object.
- `scripts/generate_sample_report.py`: Generates sample reports for September 2026 under gitignored `reports/`:
  - `reports/2026-09.md` (2,430 bytes)
  - `reports/2026-09.html` (9,856 bytes)
Files: src/copilot/review/models.py, src/copilot/review/builder.py, src/copilot/review/renderers.py, src/copilot/review/__init__.py, src/copilot/core/forecast.py, src/copilot/db/repo.py, scripts/generate_sample_report.py, tests/review/test_monthly_review.py, pyproject.toml, .gitignore, STATUS.md, docs/decisions.md, docs/production_report.md
Tests: 366 passed / 366 total | Lint: pass

## Stage 1.9: LangGraph workflow: DONE
Goal: The fixed, demonstrable agent graph (section 5.7).
Built:
- `src/copilot/workflow/state.py`: Serialisable `AgentState` for in-memory checkpointing, `TraceEntry` data structure, and `to_run_state` projecting state into Phase 0 `RunState` for backwards compatibility.
- `src/copilot/workflow/findings.py`: `build_findings_from_analysis` generating typed, safety-validated `Finding` objects from analysis tool outputs (budgets, spend, forecast, anomalies, recurring).
- `src/copilot/workflow/nodes.py`: Thin workflow node implementations (`ingest`, `categorize`, `analyze`, `advise`, `review`, `finalize`, `error`), calling tools strictly through `execute_tool(ctx, tool_name, params)`.
- `src/copilot/workflow/graph.py`: StateGraph definitions and compilation: `build_agent_graph` with conditional edge routing on 0 txns (`analyze` or `finalize`), human-in-the-loop review interruption/resumption, and error routing; plus `build_monthly_review_graph` for targeted monthly reviews (`analyze → advise → review → finalize`).
- `src/copilot/workflow/trace.py`: `format_trace` and `print_trace` formatting node-by-node execution traces into readable ASCII summary tables.
- `tests/workflow/test_nodes.py`: 11 unit tests covering all individual node behaviors, tool calls, and error handling.
- `tests/workflow/test_graph.py`: 5 integration tests verifying full offline execution with `MemorySaver`, interrupt and resume with decisions, conditional edge skips, categorize failure error handling, and monthly review mode.
- `tests/workflow/test_architecture.py`: 2 AST-based architecture enforcement tests verifying no module outside tool specs imports tool handlers, and all workflow nodes execute tools strictly via `execute_tool`.
Files: src/copilot/workflow/state.py, src/copilot/workflow/findings.py, src/copilot/workflow/nodes.py, src/copilot/workflow/graph.py, src/copilot/workflow/trace.py, src/copilot/workflow/__init__.py, tests/workflow/test_nodes.py, tests/workflow/test_graph.py, tests/workflow/test_architecture.py, docs/decisions.md, docs/production_report.md, STATUS.md
Tests: 361 passed / 361 total | Lint: pass

## Review pass on Stages 1.1-1.8: DONE
Goal: audit the existing implementation and fix defects before continuing to Stage 1.9.
Fixed:
- pipeline.py raised NameError (ToolFailure not imported) on any LLM failure; rewritten: batches by config size, validates LLM output (asked merchants, known category ids), caps LLM confidence, per-user cache ids (old id could overwrite another user's row), redacted prompt that lists allowed categories, returns counts-only PipelineReport
- categorize_batch: unknown category goes to review instead of aborting the batch on a foreign key error; LLM confidence cap enforced inside the tool
- undo_categorize_batch: restores only rows still in the batch's state (never clobbers a later user edit), idempotent, reverse-order restore
- ingestion: duplicate-charge flag matched any same merchant and amount (monthly rent and subscriptions would be flagged and dropped from spend); now windowed (24h), flags the later of a pair, order independent
- rules and aliases YAML now have validated loaders (load_rules, load_aliases); bad regex fails loudly
- lint: cleared all ruff violations across src/ and tests/
Files: src/copilot/core/pipeline.py, core/categorisation.py, core/config.py, tools/categorisation.py, bank/ingest.py, pyproject.toml, tests/core/test_pipeline_hardening.py, tests/bank/test_bank.py
Tests: 338 passed / 338 total | Lint: pass
Known gaps: scripts/demo.py is stale (uses removed MockBankConnector, replaced by Stage 1.11 demo); Stages 1.5-1.14 not started; live Gemini check pending; GeminiProvider puts the API key in the URL (move to header before live use).
## Stage 1.4: Deterministic & Cached Categorization: DONE
Goal: accurate, cheap, reversible categorization.
Built:
- Merchant normalizer and rules/aliases YAML config setup
- GeminiProvider implementing structured_call, retries, rate limiting, and redaction
- categorize_batch and undo_categorize_batch tools registered in financial.py with agent allowance
- run_categorization_pipeline logic coordinating cache, overrides, rules, and LLM
Files: src/copilot/core/categorisation.py, src/copilot/core/pipeline.py, src/copilot/llm/gemini.py, src/copilot/llm/redactor.py, src/copilot/tools/categorisation.py, tests/core/test_categorisation.py, tests/core/test_pipeline.py, tests/tools/test_categorisation_tools.py, tests/llm/test_redactor.py, config/policy.yaml, config/categorization_rules.yaml, config/merchant_aliases.yaml, config/advice_templates.yaml, config/settings.yaml
Tests: 309 passed / 309 total | Lint: pass
Defaults chosen (open_questions.md): min_confidence defaults to 0.85 in config
Live checks pending: none

## Stage 1.3: Idempotent ingestion: DONE
Goal: load data safely any number of times.
Built: 
- Deterministic transaction fingerprinting (generate_fingerprint)
- ingestion_batches schema implementation
- Idempotent ingest_statements tool registered in financial.py with agent allowance
- Exact repeat skipping and duplicate charge flagging
Files: src/copilot/bank/ingest.py, src/copilot/tools/financial.py, config/policy.yaml, tests/bank/test_bank.py
Tests: 302 passed / 302 total | Lint: pass
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 1.2: Synthetic data v2 and AA-shaped mock connector: DONE
Goal: realistic, labelled, reproducible data behind a consent-gated connector.
Built:
- Extended `synth.py` to support multiple accounts, salary, rent, transfers, refunds, and per-transaction ground truth.
- Created `BankConnector` interface and `MockAAConnector` with `create_consent`, `approve_consent`, and `fetch_session`.
- Refactored `loader.py` to ingest transactions via `consent_id` instead of a time range.
Files: docs/decisions.md, src/copilot/bank/synth.py, src/copilot/bank/mock_bank.py, src/copilot/bank/loader.py, tests/bank/test_bank.py, tests/golden/test_golden.py
Tests: 301 passed / 301 total | Lint: pass
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 1.1: Schema and models: DONE
Goal: Build all Phase 1 tables, views, and Pydantic models, including migrations and repo functions.
Built:
- Authored `002_phase1_schema.sql` adding missing tables (`consents`, `ingestion_batches`, `anomalies`, `findings`, etc) and views
- Created strict Pydantic models in `models/domain.py`
- Updated `repo.py` to persist `Transaction` and `Budget` with Phase 1 fields
- Added JSON round-trip tests and database constraint/view tests
Files: src/copilot/db/migrations/002_phase1_schema.sql, src/copilot/models/domain.py, src/copilot/db/repo.py, tests/models/test_phase1_models.py, tests/db/test_phase1_repo.py, docs/decisions.md
Tests: 302 passed / 302 total | Lint: pass
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 1.0: Align with Phase 0, migrations, config: DONE
Goal: Start from an accurate picture of the real code and a safe way to change the schema, align Phase 0 names, add migrations mechanism, and expand config loading.
Built:
- Wrote `docs/phase1_alignment.md` to map plan names to Phase 0 actual names
- Migrated `schema.sql` to `db/migrations/001_initial.sql`
- Updated `db/connection.py` to process `db/migrations/*.sql` and track via `schema_migrations`
- Added Phase 1 YAML file paths to Pydantic `Settings` in `core/config.py`
- Updated `.env.example` with `GEMINI_API_KEY` and models
Files: docs/phase1_alignment.md, src/copilot/db/connection.py, src/copilot/core/config.py, .env.example, config/settings.yaml, src/copilot/db/migrations/001_initial.sql, docs/decisions.md, tests/db/test_schema.py, tests/core/test_config.py
Tests: 296 passed / 296 total | Lint: pass
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
- Add versioned monthly review and report rendering: src/copilot/review/, scripts/generate_sample_report.py, tests/review/, src/copilot/core/forecast.py, src/copilot/db/repo.py, pyproject.toml, .gitignore, docs/decisions.md, docs/production_report.md, STATUS.md

- [x] Stage 1.5: Add transfer and recurring payment detection
- [x] Stage 1.6: Analysis tools and derived state
- [x] Stage 1.7: Dispute, correction and undo
- [x] Stage 1.8: Findings, advice drafting and validator
- [x] Stage 1.8b: Undo divergence checks and advice number matching
- [x] Stage 1.9: LangGraph orchestration
- [x] Stage 1.10: Monthly review
- [ ] Stage 1.11: CLI (primary demo surface)
