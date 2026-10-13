# Phase 1 Implementation & Test Verification Report

This document reports the technical status of Phase 1 (Foundational MVP backend) through Stage 1.8b. All assertions below are verified by the automated test suite and static analysis.

## 1. Stage Status Overview

### Completed Stages (Phase 1 Backend Foundation)
- **Stage 1.0 (Align with Phase 0, migrations, config):** Added SQLite migration runner tracking applied scripts in `schema_migrations`. Converted Phase 0 schema to `001_initial.sql`. Extended Pydantic settings in `core/config.py`.
- **Stage 1.1 (Schema and models):** Applied migration `002_phase1_schema.sql` adding `consents`, `ingestion_batches`, `anomalies`, `findings`, `advice_items`, `recurring_series`, `transfer_links`, and `merchant_overrides`. Built domain models in `models/domain.py` and `models/findings.py`.
- **Stage 1.2 (Synthetic data v2 and Mock AA connector):** Extended `synth.py` with multi-account transactions, salary, rent, internal transfers, refunds, and ground-truth labels. Implemented `MockAAConnector` supporting `create_consent`, `approve_consent`, and `fetch_session`.
- **Stage 1.3 (Idempotent ingestion):** Built `ingest_statements` tool and handler in `bank/ingest.py`. Transactions are fingerprinted; identical transactions are skipped; duplicate debits within a 24-hour window are flagged (`is_duplicate_of`).
- **Stage 1.4 (Deterministic and cached categorization):** Implemented merchant normalization, rule-based matching (`config/categorization_rules.yaml`), alias substitution (`config/merchant_aliases.yaml`), per-user database cache, and LLM fallback via `GeminiProvider` with PII redaction (`llm/redactor.py`).
- **Stage 1.5 (Transfer and recurring payment detection):** Implemented greedy bipartite matching for internal transfers within configurable window hours and recurring cadence detection in `core/patterns.py` and `tools/patterns.py`.
- **Stage 1.6 (Analysis tools and derived state):** Implemented `detect_anomalies`, `forecast_month` (fixed + run-rate projection), and `get_financial_state` in `tools/analysis.py`.
- **Stage 1.7 (Dispute, correction and undo):** Implemented `recategorize_transaction` with optional `--remember` override flag, and `undo` in `tools/undo.py`.
- **Stage 1.8 (Findings, advice drafting and validator):** Implemented `draft_advice` and `decide_advice`. Added deterministic validator (`validate_advice`) enforcing allowed finding numbers, forbidden phrase detection, and template fallback (`config/advice_templates.yaml`).
- **Stage 1.8b (Hardening: undo divergence and number tolerance):**
  - Refusal of undo when entity or batch state has diverged from `after_data` (interleaved edit preserved, refusal audited as `undo_refused`, all-or-nothing batch semantics).
  - Explicit advice matching tolerance rule: `tolerance = min(half of last displayed digit, 5% of stated value)`.

### Upcoming Stages (Orchestration, Workflows, UI, Hardening)
- **Stage 1.9:** LangGraph orchestration
- **Stage 1.10:** Monthly Review workflow
- **Stage 1.11:** CLI
- **Stage 1.12:** Evaluation
- **Stage 1.13:** Streamlit UI
- **Stage 1.14:** Hardening & packaging

---

## 2. Test Verification & Concrete Guarantees

The test suite contains **342 automated tests**, all passing in ~1.6s (`pytest`). Static typing and style checks pass cleanly with zero violations (`ruff check src tests`).

The test suite establishes the following properties:

### A. Number Representation & Integrity
- **Paise Precision:** All currency fields in SQLite are `INTEGER` columns (`amount_paise`, `limit_paise`). Pydantic domain models type money fields strictly as `int`.
- **No Money in LLM Output:** `structured_call` inspects Pydantic output schemas and rejects models containing fields ending with `_paise`.
- **Zero Floating-Point Division in Ledger:** Balances, category spend, and budget status calculations operate purely on integer arithmetic.

### B. Advice Number Matching Rule
The advice validator (`core/advice.py`) checks that any number mentioned in advice corresponds to a cited finding.
- **Tolerance Formula:** `tolerance = min(half of last displayed digit, 5% of stated value)`.
- **Tested Boundaries:**
  - `"₹1.2k"` (`value=1200, quantum=100`): tolerance = 50. Accepts `[1150, 1250]`, including 1234.50. Rejects 1149.99 and 1250.01.
  - `"1 lakh"` (`value=100000, quantum=100000`): tolerance = 5000. Accepts `[95000, 105000]`. Rejects 94999, 105001, 60000, and 150000.
  - `"1.5 lakh"` (`value=150000, quantum=10000`): tolerance = 5000. Accepts `[145000, 155000]`. Rejects 144999 and 155001.
  - `"2 crore"` (`value=20000000, quantum=10000000`): tolerance = 1000000. Accepts `[19000000, 21000000]`. Rejects 18999999 and 21000001.
  - Plain rupee `"₹500"` (`value=500, quantum=1`): tolerance = 0.5. Accepts `[499.5, 500.5]`. Rejects 499.49 and 500.51.
- **Forbidden Vocabulary:** Verified by tests to reject terms suggesting payments, transfers, investments, stocks, or guaranteed returns.

### C. Undo Divergence & Audit Log
- **Append-Only Ledger:** SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers prevent alteration or deletion of rows in `audit_events`.
- **State Divergence Verification:**
  - If a transaction's category is modified by an interleaved user action after an event, calling `undo` on the prior event raises `ToolFailure(ErrorCode.STALE_DATA)` and leaves the newer category unchanged.
  - The refusal is audited with `event_type="undo_refused"` and `metadata.refusal_reason="state_diverged"`.
- **All-or-Nothing Batch Undo:** In an override batch affecting multiple transactions, if even one transaction's state has diverged, none of the transactions are reverted, and the refusal is audited.

### D. Idempotent Ingestion & Deduplication
- **Fingerprint Protection:** Re-running statement ingestion with previously ingested transaction IDs results in zero inserted rows and increments `skipped_existing`.
- **Duplicate Charges:** Repeated transactions with identical merchant and amount within a 24-hour window flag the second transaction as `is_duplicate_of`, excluding it from spend aggregations. Transactions separated by more than 24 hours (such as monthly subscriptions) remain unflagged.

### E. PII Redaction
- Phone numbers, email addresses, 12-16 digit account numbers, and UPI virtual payment addresses (`user@bank`) are redacted to tokens (`[PHONE_REDACTED]`, `[EMAIL_REDACTED]`, `[ACCOUNT_REDACTED]`, `[UPI_REDACTED]`) before inclusion in LLM prompt contexts.

### F. Governance & Policy Choke Point
- Every tool is registered in `FINANCIAL_TOOLS` and dispatched through `execute_tool`.
- Tools missing in policy or denied by policy are blocked from handler execution.
- `test_no_money_movement_tools_registered` confirms no external payment or money movement tools are registered.
