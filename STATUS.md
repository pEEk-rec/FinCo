## Current state
Last completed stage: 1.8 | Blockers: none

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
1. Add migrations and Phase 1 config: docs/phase1_alignment.md, src/copilot/db/connection.py, src/copilot/db/migrations/001_initial.sql, src/copilot/core/config.py, config/settings.yaml, .env.example, docs/decisions.md, tests/db/test_schema.py, tests/core/test_config.py, src/copilot/db/schema.sql (deleted)
2. Add Phase 1 schema and models: src/copilot/db/migrations/002_phase1_schema.sql, src/copilot/models/domain.py, src/copilot/db/repo.py, tests/models/test_phase1_models.py, tests/db/test_phase1_repo.py, docs/decisions.md
5. Add idempotent ingestion tools and handlers: src/copilot/bank/ingest.py, src/copilot/tools/financial.py, config/policy.yaml, tests/bank/test_bank.py
6. Add deterministic categorization, pipeline, LLM clients, and batch tools: src/copilot/core/categorisation.py, src/copilot/core/pipeline.py, src/copilot/llm/gemini.py, src/copilot/llm/redactor.py, src/copilot/tools/categorisation.py, src/copilot/tools/financial.py, config/policy.yaml, src/copilot/core/config.py, config/categorization_rules.yaml, config/merchant_aliases.yaml, config/advice_templates.yaml, src/copilot/governance/policy.py, src/copilot/tools/executor.py, tests/core/test_categorisation.py, tests/core/test_pipeline.py, tests/tools/test_categorisation_tools.py, tests/llm/test_redactor.py, tests/governance/test_policy.py

- [x] Stage 1.5: Add transfer and recurring payment detection
- [x] Stage 1.6: Analysis tools and derived state
- [x] Stage 1.7: Dispute, correction and undo
- [x] Stage 1.8: Findings, advice drafting and validator
