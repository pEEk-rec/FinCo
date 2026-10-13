# PLAN_PHASE1.md: Phase 1, Foundational MVP (complete backend)

Project: Personal Finance & Budgeting Copilot (Agentic AI course project)
Scope of this file: **Phase 1 only.** Phases 2 to 7 are not part of this task, but Phase 1 must leave clean extension points for them (section 9).
Owner and only contributor: the user (repo owner).

Read this whole file before writing any code. Then read `PLAN.md` (Phase 0), `docs/decisions.md` and the current code. Phase 1 builds **on** Phase 0; it does not replace it.

---

## 0. Rules for the implementing agent

### 0.1 Work mode: autonomous, inside gates
Work through the stages in section 6 **in order**, without waiting for "go" between stages, but only inside these gates.

For every stage:
1. Write the stage goal (2–3 lines) and the files you will create or change at the top of that stage's entry in `STATUS.md`.
2. Build in small steps. Run tests and lint often.
3. A stage is done only when its **Done when** is met and the **full** test suite and lint pass.
4. Append the explain-back entry to `docs/decisions.md` (section 0.5) and the report to `STATUS.md` (section 0.4).
5. Continue to the next stage.

**Hard gates: stop and wait for the user**
- Any git action (section 0.3).
- Adding a dependency not listed in section 3.
- Anything that costs money, signs up for a service, or deploys.
- Deleting or overwriting anything outside this repository.
- A failing test or lint error you cannot fix after an honest attempt. Never weaken, skip, `xfail` or delete a test. Record the blocker; continue only with later stages that are fully independent of it, and say so.
- A change that would break a Phase 0 contract (governance choke point, audit append-only triggers, integer-paise money, `user_id` on every table, no money-movement tools).

**Soft gates: decide, record, continue**
- A product decision this plan does not cover: take the most conservative reasonable default, record it in `docs/open_questions.md` with the alternative.
- No Gemini key or quota exhausted: use the fake LLM provider, mark live checks pending in `STATUS.md`.
- A name in this plan differs from the real Phase 0 code: **the real code wins.** Record the mapping in `docs/phase1_alignment.md` (Stage 1.0).

**Context hygiene:** if your tool supports it, start a fresh session every two stages. A fresh session must re-read this file, `STATUS.md` and `docs/decisions.md` before continuing.

### 0.2 Code rules
- Simple, readable Python. Short functions, clear names, type hints everywhere, a docstring on every public function. The owner must be able to explain every module in a viva.
- **Deterministic code owns financial truth.** The LLM never computes, compares or invents a number. Every rupee figure the user sees comes from a deterministic function.
- **Every tool call goes through the Phase 0 executor** (`execute_tool` or its actual name). No graph node, CLI command or service calls a tool handler directly. A test enforces this.
- **Money is integer paise.** No floats in any money path, including forecasts (use `Decimal` for intermediate maths, round half up to paise).
- **Every new table has `user_id`.** Every query filters by it.
- **All thresholds, limits and rules live in YAML config,** never as magic numbers in code.
- **No money movement exists.** No tool, CLI command, graph node or API that pays, transfers, trades, withdraws or deposits. Phase 0's test for this must still pass and must be extended to the new tools.
- Never claim something works unless you ran it.

### 0.3 Git rules (strict, unchanged from Phase 0)
- Every git action needs the owner's explicit approval **first, every single time**: `init`, `add`, `commit`, `push`, `branch`, `checkout -b`, `merge`, `rebase`, `stash`, `tag`, remotes, `mv`, config changes. Earlier approval never carries over.
- While the owner is away, run **no** git commands. At each `[GIT CHECKPOINT]`, add the proposed commit message and exact file list to the "Proposed commits" section of `STATUS.md`.
- Commits are authored only by the owner's existing git identity. Never change `user.name` or `user.email`.
- **No AI attribution anywhere:** no `Co-Authored-By` trailers, no "Generated with …" lines, no session links, in commits, PR text, code comments or docs.
- Commit messages: short, plain English, imperative, under about 70 characters, one logical change each. Example: `Add idempotent statement ingestion`.
- Never force push, rewrite history, or commit `.env`, keys, the database file or generated data.

### 0.4 STATUS.md report (newest stage first)
```
## Current state
Last completed stage: <N> | Blockers: <list or "none">

## Stage N: <name>: DONE / BLOCKED / IN PROGRESS
Goal: <2–3 lines>
Built: <2–5 bullets>
Files: <list>
Tests: <passed / total> | Lint: <pass/fail>
Defaults chosen (open_questions.md): <list or "none">
Live checks pending: <list or "none">

## Proposed commits (awaiting approval)
1. <message>: <files>
```

### 0.5 Explain-back
After each stage, append 4–8 lines to `docs/decisions.md`: what was built, why this design, what it deliberately does not do, and one question an examiner might ask with its answer.

---

## 1. Phase 1 goal

Deliver the college worklet end to end on top of the Phase 0 foundation:

> Load realistic synthetic bank data through a consent-gated mock connector, categorize it accurately and reversibly, analyze budgets, forecasts, recurring payments, transfers and anomalies, draft explainable advice that a human approves, let the user correct anything with full audit and undo, and produce a monthly review. Run it as a **LangGraph** workflow driven from a **CLI**, measured by an **evaluation harness**.

**Decisions already made by the owner**
| Decision | Choice |
|---|---|
| Demo surface | CLI first (primary). Minimal Streamlit only as the optional last stage, as a thin view over the same services |
| Orchestration | LangGraph, fixed graph in Phase 1 |
| LLM | Gemini only in Phase 1, behind the Phase 0 LLM interface (fake provider for tests) |
| Agent categorization | Agent may categorize in batch without per-row approval, under the `categorize_batch` policy (section 5.3) |
| Quality bar | Production-level: complete, tested, documented. No time cuts |

---

## 2. Design principles for Phase 1

1. **Rules first, LLM for the long tail.** Merchant normalization, user overrides and rules handle most transactions. The LLM only sees merchants nothing else could categorize, and its answers are cached so the same merchant is never asked twice.
2. **Derived state, not cached state.** Balances, category totals and budget status are computed from transactions on demand (SQL views or pure functions). Corrections therefore propagate automatically. Cache only with a measured reason, and invalidate on every write.
3. **Idempotent everything.** Re-running ingestion, categorization or a monthly review with the same inputs changes nothing and creates no duplicates.
4. **Never silently lose or change data.** Duplicates are flagged, not dropped. Every agent change is audited with before and after, and can be undone.
5. **User beats rule beats LLM.** A user-set category is never overwritten by the agent. A user correction becomes a merchant override that wins next time.
6. **Findings first, words second.** Deterministic analysis produces structured findings; the LLM only narrates them; a validator rejects any narration whose numbers or claims are not in the findings.
7. **Uncertainty is visible.** Low-confidence categorizations go to a review queue instead of being forced. Forecasts say "insufficient data" instead of guessing.
8. **Nodes are thin.** Each LangGraph node only calls tools through the executor and updates run state. All logic lives in services and pure functions, testable without LangGraph. Phase 2 will replace the fixed edges with a planner without rewriting nodes.
9. **Privacy.** The LLM receives only what it needs: normalized merchant text, direction and an amount band. Never account numbers, names, UPI IDs or full narrations. Redact before every call.

---

## 3. Stack

Keep everything from Phase 0. Pre-approved additions:

| Package | Use |
|---|---|
| `langgraph` | Fixed agent graph, state, human-in-the-loop interrupt |
| `google-genai` | Official Gemini SDK, structured JSON output |
| `typer` | CLI |
| `rich` | CLI tables and formatting |
| `jinja2` | Markdown/HTML rendering of the monthly review |
| `hypothesis` | Property tests (if not already present) |
| `streamlit` | **Only** in the optional Stage 1.13 |

Before writing LangGraph or Gemini code, **check the current official documentation** for the installed versions (APIs change). Pin exact versions in `pyproject.toml`. Model names come from config (`.env` / settings), never hard-coded; record the model used in every audit event and run trace.

---

## 4. Data model additions

Add a **migration mechanism** first (Stage 1.0): a `schema_migrations` table and numbered SQL files `db/migrations/NNN_name.sql`, applied in order, each in a transaction, idempotent. Phase 0's `schema.sql` becomes migration `001` (or is wrapped by it; record which in the alignment doc).

New or extended tables (all with `user_id`, foreign keys on, `CHECK` constraints where simple):

| Table | Purpose and key columns |
|---|---|
| `consents` | Mock Account-Aggregator-style consent: `purpose`, `fi_types`, `account_ids`, `date_range_from/to`, `status` (`pending`/`active`/`revoked`/`expired`), `expires_at`, `created_at` |
| `ingestion_batches` | `consent_id`, `account_id`, `range_from/to`, `fetched_count`, `inserted_count`, `duplicate_count`, `status`, `error_code`, `started_at`, `finished_at` |
| `transactions` (extend) | `fingerprint` (unique per user), `batch_id`, `merchant_normalized`, `mode` (`upi`/`card`/`atm`/`neft`/`imps`/`other`), `is_duplicate_of` (nullable), `needs_review` (bool), `category_confidence`, `category_source` (`user`/`override`/`rule`/`cache`/`llm`/`none`), `excluded_from_spend` (bool, for own-account transfers) |
| `merchant_overrides` | `merchant_normalized` → `category_id`, `created_by` (`user`), `created_at`. Wins over everything except a per-transaction user choice |
| `merchant_rules` | Loaded from `config/categorization_rules.yaml` into memory, not a table (rules are config, versioned with the code) |
| `llm_category_cache` | `merchant_normalized`, `category_id`, `confidence`, `model`, `prompt_version`, `created_at` |
| `recurring_series` | `merchant_normalized`, `typical_amount_paise`, `cadence_days`, `last_seen`, `next_expected`, `confidence`, `kind` (`subscription`/`bill`/`income`/`other`) |
| `transfer_links` | `debit_txn_id`, `credit_txn_id`, `confidence` (own-account transfers) |
| `anomalies` | `txn_id` (nullable), `kind`, `score`, `details_json`, `run_id`, `status` (`open`/`dismissed`) |
| `findings` | Structured analysis facts per run: `run_id`, `kind`, `data_json`, `created_at` |
| `advice_items` | `run_id`, `finding_ids_json`, `text`, `evidence_json`, `assumptions_json`, `status` (`draft`/`approved`/`rejected`/`superseded`), `decided_at`, `decided_by` |
| `monthly_reviews` | `year`, `month`, `version`, `run_id`, `review_json`, `created_at`; unique (`user_id`,`year`,`month`,`version`) |
| `budgets` (extend if needed) | `warn_threshold_pct`, optional `forecast_warn` flag |

**Views (derived state):** `v_category_totals_month`, `v_budget_status_month`, `v_balance`. Spend excludes `excluded_from_spend` and duplicates. Write tests that a correction immediately changes these views.

---

## 5. Key designs

### 5.1 Mock bank connector, Account-Aggregator shaped
Real Indian bank data arrives through RBI's Account Aggregator framework: consent request, user approval, then an encrypted, time-bound data fetch. The mock follows the same shape so a real adapter can replace it later without touching the rest:
1. `create_consent(user, accounts, range, purpose)` → `pending`
2. `approve_consent(consent_id)` (simulated user approval) → `active`, with expiry
3. `fetch_session(consent_id)` → raw transaction JSON (no categories), only within the consented accounts and range
4. Fetching with a revoked, expired or out-of-scope consent fails with a typed error and is audited.

The connector is a `BankConnector` interface; `MockAAConnector` implements it; it can simulate failures (timeout, partial data, malformed rows) by config for tests.

### 5.2 Categorization pipeline
For each uncategorized transaction, in order, stopping at the first hit:
1. **User's own per-transaction choice** (never touched).
2. **Merchant override** (from past user corrections) → confidence 1.0.
3. **Rules** from `config/categorization_rules.yaml` (exact and regex on normalized merchant, mode, direction, amount ranges) → configured confidence.
4. **LLM cache** hit → cached confidence.
5. **LLM (Gemini)**, only for remaining *distinct* merchants, batched (several merchants per call), structured JSON output, temperature 0, confidence capped at a configured maximum (for example 0.85). Results cached.
6. Nothing confident enough → `category_id = null`, `needs_review = true`, `category_source = none`.

Thresholds (config): `auto_accept_min_confidence`, `llm_confidence_cap`, `review_queue_below`.

**Merchant normalization** is a pure function with heavy tests: strips UPI/IMPS prefixes, reference numbers, handles, dates and noise; lowercases; maps known aliases (`config/merchant_aliases.yaml`).

**Gemini robustness:** client-side rate limiter (requests per minute from config), retries with exponential backoff and jitter on 429/5xx, timeout, schema validation of every response (invalid → retry once with the validation error → give up for that merchant, mark for review). Quota exhaustion degrades to "needs review", never crashes a run. Log only counts and codes, never merchant text, in plain logs.

### 5.3 The `categorize_batch` policy
- New tool `categorize_batch` (side effect `WRITE_LOGICAL`), policy **allow for actor `agent`**, with built-in constraints enforced inside the tool **and** tested:
  - only writes to transactions where `category_source` is `none`, `rule`, `cache` or `llm`; never `user` or `override`
  - only applies categories at or above `auto_accept_min_confidence`; lower ones go to the review queue
  - every change writes one audit event with before/after, confidence, source, model and prompt version, all sharing the batch's `run_id`
  - the whole batch is undoable in one call (`undo_categorize_batch(run_id)`, also audited)
- `recategorize_transaction` keeps Phase 0 behaviour: **needs approval when the actor is the agent**; **allowed when the actor is the user** (the user's own command is the approval). Make the policy actor-aware in config, not in code branches scattered around.
- Extend the "no money movement" test to all new tools.

### 5.4 Transfers and recurring payments
- **Own-account transfers:** a debit in one of the user's accounts matched to a credit in another within a configured time window and exact amount → `transfer_links` row, both marked `excluded_from_spend`. Without this, income and spend are both overstated.
- **Recurring detection:** same normalized merchant, amounts within a tolerance, regular cadence (weekly / monthly / yearly within tolerance), at least N occurrences (config) → `recurring_series`. Used to split forecasts into fixed vs variable and to show upcoming expected payments.

### 5.5 Analysis
- **Budgets:** per category: spent, limit, percent used, status `ok` / `warning` / `exceeded`, plus `projected_exceed` (forecast says it will exceed by month end) as a separate flag.
- **Forecast v2** (replaces or wraps Phase 0's run-rate behind the same interface): month-end projection = known upcoming recurring amounts + variable run-rate. Returns a **range** (low / expected / high from historical daily-spend variation) and a confidence label. Below a minimum number of elapsed days or history, returns `insufficient_data` instead of a number. Configurable horizon for category-level forecasts.
- **Anomalies (detection only, no investigation in Phase 1):** large amount vs the category's own history (robust z-score or IQR, minimum history required), new merchant above an amount, possible duplicate charge, unusual frequency. Each with a score and a plain reason. Ground-truth anomalies from the synthetic generator must be found.

### 5.6 Findings, advice and the validator
1. Analysis produces typed `Finding` objects (kind, numbers, ids, period). Stored in `findings`.
2. The LLM receives only the findings (JSON) and returns structured advice items: `{finding_ids: [...], text: "..."}`.
3. **Advice validator** (deterministic, the most important safety piece of Phase 1):
   - every `finding_id` exists
   - every number in `text` (₹ amounts in any common format, percentages, counts) matches a number in the referenced findings after normalization
   - no forbidden content: no investment products, stocks or funds named or recommended, no instruction to transfer or pay money, no guarantees, no predictions beyond the given forecast
   - on failure: discard the LLM text and use a deterministic template for that finding (`config/advice_templates.yaml`)
4. Advice items are always `draft` until the user approves or rejects them in review. Approve/reject is audited. Approval never triggers any action; it only records the decision.
5. Each item stores `evidence` (finding ids and numbers) and `assumptions`, ready for Phase 2 explainability.

### 5.7 LangGraph workflow
- **Graph state:** the Phase 0 `RunState` (or a thin LangGraph-compatible wrapper around it); the LLM always receives a projection, never the whole state.
- **Graph:** `ingest → categorize → analyze → advise → review → finalize`, plus:
  - conditional edge after `ingest`: no new transactions → skip to `analyze` (still produce a fresh analysis) or `finalize` (config)
  - after `categorize`: review-queue items are recorded as pending clarifications, not blocking
  - `review` uses LangGraph's human-in-the-loop **interrupt** to wait for approve / reject decisions on advice; the CLI resumes the graph with the decisions
  - any node error → `error` node that records a typed failure, audits it, and ends the run cleanly
- **Run trace:** each node appends a trace entry (node, start, end, tools called, counts, status). Stored with the run and printable from the CLI.
- **Checkpointing:** use an in-memory checkpointer for the interrupt/resume within one CLI process; document the choice. If the installed LangGraph offers a SQLite checkpointer without new dependencies, use it so a review can resume in a later CLI call.
- A **second compiled graph or mode** runs the monthly review (`analyze → advise → review → finalize` for a given month).

### 5.8 Monthly review
A typed `MonthlyReview` object: period, income, spend, net, category totals with change vs previous month, budget status, recurring payments, anomalies, forecast for next month, approved/draft advice, data-quality notes (review queue size, duplicates found, missing days). Rendered separately to Markdown and HTML (Jinja2). Re-running after a correction creates a **new version** linked to its `run_id`; old versions are kept. The Phase 6 dashboard will consume the same JSON.

### 5.9 CLI (primary demo surface)
`copilot` command (Typer + Rich), every command going through services and the executor:

| Command | Does |
|---|---|
| `copilot init-db` | apply migrations |
| `copilot seed --seed 42 --months 3` | create demo user, accounts, budgets, synthetic data in the mock bank |
| `copilot consent create/approve/revoke/list` | consent lifecycle |
| `copilot run` | full graph: ingest → … → review (interactive approve/reject) |
| `copilot review-month 2026-09` | monthly review graph; writes `reports/<month>.md` and `.html` |
| `copilot txns [--month] [--category] [--needs-review]` | list transactions |
| `copilot correct <txn_id> <category> [--remember]` | user correction; `--remember` creates a merchant override |
| `copilot undo-batch <run_id>` / `copilot undo <audit_event_id>` | undo |
| `copilot budgets`, `copilot forecast`, `copilot anomalies`, `copilot recurring` | analysis views |
| `copilot audit [--txn] [--run]` | audit trail with before/after, reason, timestamp, status, reversibility |
| `copilot trace <run_id>` | node-by-node run trace |
| `copilot eval` | evaluation harness (Stage 1.12) |

Output is readable tables; `--json` flag on every read command for machine output.

---

## 6. Stages

Each stage: **Goal, Build, Tests, Done when.**

### Stage 1.0: Align with Phase 0, migrations, config
**Goal:** start from an accurate picture of the real code and a safe way to change the schema.
**Build:** read the whole Phase 0 codebase; write `docs/phase1_alignment.md` mapping every name this plan uses to the real module/function (and noting gaps); run the full test suite and record the baseline; add the migration mechanism (section 4); extend config loading for the new YAML files with Pydantic validation; add `.env.example` entries (`GEMINI_API_KEY`, `GEMINI_MODEL`, rate limits).
**Tests:** migrations apply on a fresh DB, are idempotent, and run in order; bad config fails loudly with a clear message.
**Done when:** baseline suite passes unchanged; alignment doc complete.
**[GIT CHECKPOINT]** `Add migrations and Phase 1 config`

### Stage 1.1: Schema and models
**Goal:** all Phase 1 tables, views and Pydantic models.
**Build:** migrations for section 4; models for every new entity; repo functions (small, parameterized SQL, `user_id` filtered).
**Tests:** constraints, foreign keys, user isolation, view correctness on hand-made data, JSON round-trips.
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add Phase 1 schema, views and models`

### Stage 1.2: Synthetic data v2 and AA-shaped mock connector
**Goal:** realistic, labelled, reproducible data behind a consent-gated connector.
**Build:** extend the Phase 0 generator: several accounts, messy Indian narrations (UPI/IMPS/NEFT/card/ATM), salary or allowance credits, rent, subscriptions on cadence, food and travel, own-account transfers, refunds, a duplicate charge, a large outlier, a new merchant, a quiet period; **hidden ground truth** per transaction (`true_category`, `is_transfer`, `is_recurring`, `is_anomaly`) stored separately from the visible data and never read by the pipeline. `BankConnector` interface + `MockAAConnector` (section 5.1) with failure simulation.
**Tests:** same seed → identical data; consent scope and expiry enforced; failures produce typed errors and audit events.
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add labelled synthetic data and mock AA connector`

### Stage 1.3: Idempotent ingestion
**Goal:** load data safely any number of times.
**Build:** fingerprint (account, timestamp, amount, normalized narration, reference); `ingest_statements` tool (WRITE_LOGICAL, allowed for agent) creating an `ingestion_batches` row; exact repeats skipped and counted; likely duplicate charges flagged via `is_duplicate_of`, not dropped; whole batch in one DB transaction; audit summary event.
**Tests:** ingesting twice inserts nothing new; partial failure rolls back; duplicate charge flagged; property test: ingestion order does not change the final set.
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add idempotent statement ingestion`

### Stage 1.4: Categorization pipeline and Gemini provider
**Goal:** accurate, cheap, reversible categorization (sections 5.2, 5.3).
**Build:** merchant normalizer; rules and aliases YAML; overrides; cache; `GeminiProvider` implementing the Phase 0 LLM interface with structured output, rate limiter, retries and redaction; `categorize_batch` tool with its constraints; review queue; `undo_categorize_batch`; actor-aware policy entries.
**Tests:** normalizer cases (many real-looking narrations); precedence order; never overwrites user/override; low confidence → review queue; batching sends each distinct merchant at most once; cache hit avoids LLM; 429 then success; quota exhaustion → needs review, run completes; redaction (no account numbers, UPI IDs or names in any LLM prompt, asserted on the fake provider's captured prompts); undo restores exactly. Live Gemini test marked separately, never required.
**Done when:** offline suite passes; live check run or marked pending.
**[GIT CHECKPOINT]** `Add categorization pipeline and Gemini provider`

### Stage 1.5: Transfers and recurring detection
**Goal:** correct spend totals and known future payments (section 5.4).
**Build:** `detect_transfers` and `detect_recurring` tools (pure core + thin tool), config thresholds.
**Tests:** generator ground truth found; no false link between unrelated equal amounts outside the window; property test: excluded transfers never count as spend.
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add transfer and recurring payment detection`

### Stage 1.6: Analysis tools and derived state
**Goal:** budgets, forecast v2, anomalies, and one `FinancialStateSnapshot` read model (section 5.5).
**Build:** `check_budgets` (with `projected_exceed`), `forecast_month` (range, insufficient data, fixed vs variable), `detect_anomalies`, `get_financial_state` (balance, category totals, recent batch, budget status, review-queue size) all from views and pure functions.
**Tests:** hand-computed values at every boundary (exactly at warning, at limit, one paisa over; day 1, mid month, last day; zero history); anomaly ground truth recall; no float in any money value (type check test).
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add budget, forecast and anomaly analysis`

### Stage 1.7: Dispute, correction and undo
**Goal:** the user can fix anything and see it propagate.
**Build:** user correction through `recategorize_transaction` (actor user); `--remember` creates a merchant override and re-applies it to past agent-set transactions of that merchant (audited, undoable); generic `undo(audit_event_id)` for reversible events; re-analysis after correction.
**Tests:** correction changes totals and budget status immediately; override wins next ingestion; undo restores before-state exactly; audit shows before/after, reason, timestamp, status, reversibility; agent cannot recategorize a user-set transaction (blocked and audited).
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add corrections, merchant overrides and undo`

### Stage 1.8: Findings, advice drafting and validator
**Goal:** explainable, approval-only advice that cannot invent numbers (section 5.6).
**Build:** `Finding` types and builder; `draft_advice` tool (LLM via provider, structured output); advice validator; template fallback; advice lifecycle and `decide_advice` tool (approve/reject, actor user, audited).
**Tests:** validator rejects an invented amount, a wrong percentage, an unknown finding id, a named fund or stock, "transfer ₹X to…"; accepts the same number written in common formats (₹1,234 / Rs 1234 / 1,234 rupees); rounded forms such as "₹1.2k" are accepted only within a documented rounding tolerance (decide the rule, document it, test both sides of it); fallback used on failure; approval triggers no action.
**Done when:** tests pass.
**[GIT CHECKPOINT]** `Add findings, advice drafting and validator`

### Stage 1.9: LangGraph workflow
**Goal:** the fixed, demonstrable agent graph (section 5.7).
**Build:** graph module; one thin node per step; conditional edges; interrupt-based review; error node; run trace; monthly-review graph or mode.
**Tests:** each node unit-tested with fakes; full graph runs end to end offline; resume after interrupt applies decisions; failure in categorize ends cleanly with an audited error; **architecture test:** no module outside the executor imports a tool handler.
**Done when:** tests pass; a full offline run prints a correct trace.
**[GIT CHECKPOINT]** `Add LangGraph workflow with human review`

### Stage 1.10: Monthly review
**Goal:** the worklet's headline output (section 5.8).
**Build:** `MonthlyReview` model and builder; Markdown and HTML renderers; versioning; previous-month comparison.
**Tests:** review numbers equal the analysis tools' numbers; re-run after correction creates version 2 with updated numbers; partial month handled; renderer output contains no number absent from the review object.
**Done when:** tests pass; a sample report is generated under `reports/` (gitignored) and described in `STATUS.md`.
**[GIT CHECKPOINT]** `Add versioned monthly review and report rendering`

### Stage 1.11: CLI
**Goal:** a complete, pleasant demo from the terminal (section 5.9).
**Build:** all commands; `--json` output; clear errors (no stack traces for expected errors); `docs/demo_script.md` with an exact 5-minute demo path: seed → consent → run → review queue → correction with `--remember` → undo → monthly review → audit and trace.
**Tests:** CLI tests with Typer's test runner for every command, including error paths.
**Done when:** the demo script runs start to finish offline with the fake LLM, and with Gemini if a key exists.
**[GIT CHECKPOINT]** `Add copilot CLI and demo script`

### Stage 1.12: Evaluation harness and golden scenarios
**Goal:** honest numbers for the viva.
**Build:** `copilot eval` and `eval/run_eval.py` producing `docs/eval_report.md`:
- categorization accuracy, coverage (share auto-categorized), precision of the high-confidence bucket, review-queue rate; by source (override/rule/cache/LLM); LLM-off vs LLM-on
- transfer and recurring detection precision/recall
- anomaly precision/recall vs ground truth
- idempotency check, validator pass rate, fallback rate
- latency per node; LLM calls per run
- several seeds; report mean and spread
Golden scenarios in `tests/golden/` (at least 12), for example: double ingestion; transfer excluded from spend; subscription detected and forecast as fixed; budget exactly at warning; projected exceed; insufficient data forecast; low-confidence merchant to review queue; correction propagates to monthly review v2; agent blocked from overwriting a user category; undo batch; validator rejects invented number and falls back; consent expired blocks fetch.
**Rules:** never tune rules on the evaluation seed; keep a held-out seed set; write weak spots plainly.
**Done when:** report generated; golden scenarios pass.
**[GIT CHECKPOINT]** `Add evaluation harness and golden scenarios`

### Stage 1.13 (optional): Minimal Streamlit view
Only after every earlier stage is done. A thin page over the same services (no business logic in Streamlit): financial state, budgets, review queue with correct buttons, draft advice with approve/reject, monthly review view, audit trail. Every action goes through the same service and executor. If anything here would duplicate logic, stop and record why in `open_questions.md` instead.
**[GIT CHECKPOINT]** `Add minimal Streamlit view`

### Stage 1.14: Hardening and documentation
**Goal:** production-quality finish.
**Build:** failure-handling pass (missing data, malformed rows, LLM down, quota, stale consent, empty months); logging review (no transaction text or PII in logs); README (setup, CLI, architecture diagram, data flow, privacy, limitations); update `docs/decisions.md`; final `STATUS.md` checklist.
**Done when:** section 7 checklist all green.
**[GIT CHECKPOINT]** `Harden Phase 1 and update docs`. Ask separately about push and a `phase-1-complete` tag.

---

## 7. Phase 1 exit checklist

- [ ] Full suite and lint pass; Phase 0 tests unchanged and green
- [ ] Migrations apply cleanly on a fresh database and are idempotent
- [ ] Ingestion idempotent; duplicates flagged, never dropped
- [ ] Consent required, scoped and expiring for every fetch
- [ ] Categorization: user > override > rule > cache > LLM > review queue; agent never overwrites user choices
- [ ] Every LLM prompt redacted (tested); LLM failures degrade to review, never crash
- [ ] Transfers excluded from spend; recurring payments drive fixed-part forecasts
- [ ] Forecast returns ranges or "insufficient data"; no floats in money paths
- [ ] Advice is draft-only, validated against findings, template fallback works
- [ ] Corrections propagate to totals, budgets and monthly review; full undo
- [ ] Audit trail shows before/after, reason, timestamp, status, reversibility for every change
- [ ] LangGraph graph runs end to end with interrupt-based review and a printable trace
- [ ] No tool handler reachable except through the executor (tested); no money-movement tool (tested)
- [ ] CLI demo script runs offline end to end
- [ ] Evaluation report generated with honest numbers and held-out seeds
- [ ] No AI attribution anywhere

---

## 8. Explicitly NOT in Phase 1

- Dynamic planner, intent understanding, hypothesis-evidence investigation, what-if simulation, adaptive alerts (Phase 2). Phase 1 *detects* anomalies; it does not investigate them.
- Goals, commitments, calendar, investment readiness, behavioural memory logic (Phase 3)
- Virtual buckets logic (schema reserved in Phase 0 stays unused)
- Gamification, social, messaging channels, web dashboard (Phases 4–6)
- Guidance levels, real approval flows for simulated actions (Phase 7)
- Ollama or any second LLM backend (the provider interface must still allow it later)
- Any real bank, UPI, Account Aggregator or broker integration

---

## 9. Extension points Phase 1 must leave

| Built now | Used later by |
|---|---|
| Thin nodes + tools behind the executor | Phase 2 planner replaces fixed edges |
| `Finding` + advice `evidence`/`assumptions` | Phase 2 explainability, Phase 7 policy explanations |
| `merchant_overrides` + audit of user decisions | Phase 3 behavioural memory |
| `recurring_series` | Phase 3 commitments and calendar |
| `MonthlyReview` JSON | Phase 6 dashboard |
| `BankConnector` interface + consents | Real AA adapter, Phase 6 channels |
| Actor-aware policy in config | Phase 7 guidance levels |
| Run trace | Phase 2 agent activity timeline |
