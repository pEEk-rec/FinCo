# PLAN.md: Phase 0 Architecture Foundation

Project: Personal Finance & Budgeting Copilot
Scope of this file: **Phase 0 only.** Phases 1 to 7 are NOT part of this task.
Owner / only contributor: the user (the repo owner).

---

## 0. READ THIS FIRST (rules for the implementing agent)

You are building the foundation of a governed financial copilot. The foundation must be boring, small, correct and tested. Do not be clever.

### 0.1 How to work
1. Work on **ONE step at a time**, in the order given in section 6. Never start a step early.
2. Before starting a step: re-read that step, restate its goal in 2 to 3 lines, and list the files you will create or change. Then start.
3. Keep each step small. If a step feels too big, split it and tell the user. Do not silently expand it.
4. After finishing a step, run the full test suite and the linter. Both must pass.
5. After each step, stop and report using the format in section 0.4. **Wait for the user to say "go" before starting the next step.**
6. If something is unclear, contradictory, or needs a decision not covered here: **stop and ask.** Do not guess. Do not invent requirements.
7. Do not touch files outside the current step's file list unless it is a necessary fix, and if so say so in the report.
8. Do not add dependencies beyond section 3 without asking first.
9. Write simple code. Short functions, clear names, type hints everywhere, a short docstring on every public function. No metaprogramming, no clever abstractions, no frameworks beyond the listed stack.

### 0.2 Scope discipline
- If it is not in the current step, do not build it.
- Section 5 lists things that are explicitly **NOT to be built** in Phase 0. If you feel tempted to build one of them "because it will be needed later", don't. Leave a note in `docs/decisions.md` under "Deferred" instead.
- Do not build any UI, dashboard, web server, messaging integration or LangGraph workflow. Those belong to later phases.

### 0.3 Git rules (STRICT, no exceptions)
Every git action needs the user's explicit approval **first, every single time**, even if the user approved a similar action earlier. Earlier approval does not carry over.

Git actions that require asking first include: `git init`, creating or switching branches, `git add`, `git commit`, `git push`, `git tag`, `git merge`, `git rebase`, `git stash`, adding a remote, and any change to git config.

How to ask:
1. Show `git status` (short) and a one-line summary of what changed.
2. Show the exact commit message you propose.
3. Ask: "Commit this? (yes / change message / not yet)". Wait for the answer.
4. Only after a clear "yes" run the command. Pushing is a separate question, ask again before the push and say which branch and remote.

Identity and attribution:
- Commits must be authored **only** by the user's own git identity (whatever is already in their git config). Do not change `user.name` or `user.email`. If no identity is configured, stop and ask the user. Do not make one up.
- **Do NOT add yourself or any AI tool as a contributor or author.** No `Co-authored-by:` trailers. No "Generated with ..." or "Created by ..." lines in commit messages, code, README or docs. No AI attribution anywhere in the repo history.

Commit message style:
- Short, natural, plain English, the way a student developer would write it. Imperative mood.
- One line, under about 70 characters. Add a short body only if really needed.
- Good: `Add money helpers using integer paise`, `Create audit events table`, `Block unregistered tools in executor`
- Bad: `feat(core): implement comprehensive robust audit subsystem`, anything with emojis, buzzwords or long lists.
- One logical change per commit. Do not bundle unrelated work.

Safety:
- Never force push. Never rewrite history. Never delete branches or tags without asking.
- Never commit secrets, `.env` files, API keys, the SQLite database files or generated data. Make sure `.gitignore` covers them (Step 0).
- Suggested (not automatic) commit points are marked **[GIT CHECKPOINT]** at the end of steps. At each one, ask. The user may choose to skip, combine, or delay.

### 0.4 Report format after every step
Keep it short:
```
STEP N DONE: <name>
What I built: <2-4 bullets>
Files added/changed: <list>
Tests: <X passed, Y total> | Lint: <pass/fail>
Decisions I made: <anything not dictated by the plan, or "none">
Open questions: <or "none">
Git: <proposed commit message, awaiting your approval>
```
Do not claim something works unless you ran it. If a test fails, say so plainly. Do not hide failures or weaken tests to make them pass.

### 0.5 Explain-back rule
After each step, append a short entry to `docs/decisions.md` (3 to 6 lines): what was built, why it was designed this way, and what it is deliberately not doing. The user must be able to explain every module in an interview, so write for someone reading it to learn.

---

## 1. Phase 0 goal

Build the reusable substrate the later phases sit on:

- a typed financial data model and database
- exact money and time handling
- a tool system with contracts and metadata
- a **single governance choke point** that every tool call passes through
- an append-only audit log
- deterministic financial tools (math lives in code, not in the LLM)
- a mock bank data source with seeded synthetic data
- interfaces (not full implementations) for memory, planner and the LLM

**Definition of done for Phase 0:** section 7 checklist, all green.

### Design principles (do not violate)
1. **Deterministic code owns financial truth.** The LLM never does arithmetic on money.
2. **No money-moving tool exists.** Not disabled, not denied: *not registered, not written.* A test asserts this.
3. **Default deny.** A tool call is blocked unless governance explicitly allows it.
4. **Everything important is audited.** State changes and policy decisions produce audit events.
5. **Money is integer paise.** Never floats.
6. **Every table has `user_id`.**
7. **Interfaces before implementations** for anything Phase 0 does not exercise.

---

## 2. Two kinds of state (do not merge them)

| Kind | Where it lives | Contents |
|---|---|---|
| **Persistent financial state** | SQLite database | users, accounts, transactions, categories, budgets, audit events, memory entries (schema only), reserved tables |
| **Per-run state** | In-memory Pydantic model (`RunState`) | intent, plan, observations, tool results, pending actions, run id |

Rules:
- Do not create one giant "AgentState" object holding everything.
- `RunState` is versioned (`schema_version` field) and serialisable to JSON.
- Anything given to an LLM must be a small **projection** of the state (only the fields needed), never the whole thing.

---

## 3. Tech stack (fixed, don't change without asking)

- Python 3.11+
- Pydantic v2 (models, validation)
- SQLite via the standard `sqlite3` module (no ORM)
- `pytest` for tests
- `ruff` for lint and format
- `zoneinfo` (stdlib) for timezones
- `uuid`, `json`, `decimal`, `datetime` from stdlib
- **No** LangGraph, FastAPI, Streamlit, vector DB or LLM SDK in Phase 0 (LLM layer uses an interface plus a fake client; a real provider adapter is added later)

Decisions already made:
- Currency: INR only. Amounts stored as **integer paise** (Rs 499.00 = `49900`).
- Timezone: `Asia/Kolkata` (IST). Timestamps stored as UTC ISO-8601 strings; month and day boundaries always computed in IST.
- "Month" = calendar month in IST, half-open range `[first day 00:00 IST, next month first day 00:00 IST)`.
- IDs: UUID4 strings (text).

---

## 4. Target folder layout

```
finance-copilot/
  PLAN.md
  README.md
  pyproject.toml
  .gitignore
  .env.example
  config/
    policy.yaml            # capability matrix (data, not code)
    settings.yaml          # thresholds, defaults
  docs/
    decisions.md           # running design log (explain-back entries)
  src/copilot/
    __init__.py
    core/
      money.py             # paise helpers
      timeutil.py          # IST + month boundaries
      errors.py            # standard error types/codes
      config.py            # loads yaml config
    db/
      connection.py
      schema.sql
      repo.py              # small data-access functions
    models/
      domain.py            # Transaction, Budget, Category, ...
      run_state.py         # RunState (per-run)
      memory.py            # MemoryEntry schema
    audit/
      events.py            # append-only audit log
    tools/
      contracts.py         # ToolSpec, ToolResult, ToolError
      registry.py
      executor.py          # THE choke point
      financial.py         # deterministic tools
    governance/
      policy.py            # loads matrix + decide()
    bank/
      mock_bank.py         # mock bank connector
      synth.py             # seeded synthetic data generator
    llm/
      client.py            # LLMClient interface + FakeLLMClient + structured call w/ retry
    planner/
      router.py            # Planner interface + trivial router
  tests/
    ... (mirrors src layout)
    golden/
      scenarios.json
      test_golden.py
```

---

## 5. Explicitly NOT in Phase 0 (do not build)

Do not build any of these, even partially:
- LangGraph / the fixed agent graph (Phase 1)
- Real categorization logic, rules engine, or LLM categorization (Phase 1)
- Monthly review, advice drafting, dispute flow UI (Phase 1)
- Real planner, hypothesis/evidence reasoning, anomaly investigation (Phase 2)
- What-if simulation, adaptive alerts (Phase 2)
- Goals logic, commitments, financial calendar, investment readiness (Phase 3)
- Memory retrieval, decay or confidence updates (Phase 3). Only the schema now.
- Virtual buckets logic (Section 3 of roadmap). Only reserve the table now.
- Gamification, experiments, social features, sharing (Phases 4, 5)
- Web dashboard, chat interface, WhatsApp/messaging, API server (Phase 6)
- Guidance levels (Lenient/Alerting/Strict) logic, mock approval flow, eval harness (Phase 7)
- Hash-chained or event-sourced audit log. A plain append-only table is enough.
- Authentication, multi-user login. (`user_id` column exists; one seeded user is enough.)
- Any real bank, UPI, payment or brokerage integration.

---

## 6. Build steps

Each step: **Goal, Build, Rules, Tests (must pass), Done when.** Do them in order.

---

### Step 0: Project skeleton

**Goal:** an empty but working project where `pytest` and `ruff` run.

**Build**
- Folder layout from section 4 (empty `__init__.py` files are fine).
- `pyproject.toml` with the listed dependencies and pytest/ruff config.
- `.gitignore` covering: `__pycache__/`, `.venv/`, `.env`, `*.db`, `*.sqlite*`, `.pytest_cache/`, `.ruff_cache/`, `data/`.
- `.env.example` (empty or placeholder keys only, no real secrets).
- `README.md`: 10 to 15 lines: what the project is, how to install, how to run tests.
- `docs/decisions.md` with the header and a "Deferred" section.
- One trivial passing test (e.g. package imports).

**Done when:** `pytest` passes, `ruff check` passes.

**[GIT CHECKPOINT]** Ask before `git init` (if no repo), before the first commit, and before any push. Suggested message: `Set up project skeleton`

---

### Step 1: Money and time primitives

**Goal:** exact money math and consistent IST time handling, before anything else depends on them.

**Build**
- `core/money.py`:
  - `rupees_to_paise(value: str | int | Decimal) -> int` (accepts strings like `"499.50"`; **reject floats** with a clear error)
  - `paise_to_rupees_str(paise: int) -> str` (e.g. `"₹499.50"` or `"499.50"`, pick one and document)
  - `add`, `subtract` are just ints; provide `safe_percent(paise, pct)` using integer/Decimal math with defined rounding (round half up)
- `core/timeutil.py`:
  - `IST = ZoneInfo("Asia/Kolkata")`
  - `to_utc_iso(dt)`, `from_utc_iso(s)`
  - `month_bounds(year, month) -> (start_utc, end_utc)` half-open, based on IST
  - `month_of(utc_iso) -> (year, month)` in IST
  - `now_utc()` should be injectable/overridable for tests (accept an optional clock argument; do not call `datetime.now()` inside business logic)

**Rules:** no floats touching money anywhere. No naive datetimes.

**Tests:**
- `"499.50"` becomes `49950`; passing `499.5` (float) raises.
- 23:30 IST on Jan 31 belongs to January; 00:30 IST on Feb 1 belongs to February (check against UTC conversion).
- Leap year February bounds are correct.
- Rounding cases for `safe_percent`.

**Done when:** all tests pass.

**[GIT CHECKPOINT]** Suggested: `Add money and IST time helpers`

---

### Step 2: Domain models and database schema

**Goal:** the persistent data model, with `user_id` on every table.

**Build**
- `models/domain.py` (Pydantic v2): `User`, `Account`, `Category`, `Transaction`, `Budget`.
  - `Transaction` fields: `id`, `user_id`, `account_id`, `occurred_at` (UTC ISO), `amount_paise` (int, positive = spend, negative = credit; document the sign convention in a comment), `direction` (`debit`/`credit`), `merchant_raw`, `description`, `category_id` (nullable), `category_confidence` (0.0 to 1.0, nullable), `category_source` (`rule` / `llm` / `user` / `none`), `created_at`.
  - `Budget`: `id`, `user_id`, `category_id`, `period` (`monthly`), `limit_paise`, `warn_threshold_pct`.
- `db/schema.sql` with tables: `users`, `accounts`, `categories`, `transactions`, `budgets`, `audit_events` (created in Step 3, leave a placeholder comment), `memory_entries` (schema only, see Step 8), and **reserved, unused** `goals` and `buckets` tables (minimal columns: `id`, `user_id`, `name`, `created_at`; add a comment "reserved for later phase, no logic yet").
  - Every table: `user_id TEXT NOT NULL` (except `users` itself). Add indexes on `(user_id, occurred_at)` for transactions.
  - Use `CHECK` constraints where simple (e.g. `limit_paise >= 0`).
- `db/connection.py`: `get_connection(path)` (enables `PRAGMA foreign_keys=ON`), `init_db(conn)` runs schema.
- `db/repo.py`: small functions only: `insert_transaction`, `get_transaction`, `list_transactions(user_id, start, end, category_id=None)`, `insert_budget`, `list_budgets(user_id)`, `update_transaction_category(...)`. Every function takes `user_id` and filters by it.

**Rules:** no ORM. No business logic in the repo layer. Never build SQL with string formatting of user values; use `?` parameters.

**Tests:** use an in-memory SQLite DB. Insert and read back; a query for user A never returns user B's rows; invalid data (negative limit) is rejected; foreign keys enforced.

**Done when:** tests pass and `init_db` works on a fresh DB.

**[GIT CHECKPOINT]** Suggested: `Add domain models and database schema`

---

### Step 3: Audit event log  *(user-led, see note)*

**Goal:** an append-only record of everything important.

> **Note for the agent:** the user may want to write the core of this module themselves, since it is a key part of the project. At the start of this step, **ask**: "Do you want to write `audit/events.py` yourself? I can give you the design and write the tests, or I can implement it." Follow the answer.

**Build**
- `audit_events` table: `id`, `user_id`, `run_id` (nullable), `occurred_at` (UTC), `actor` (`user` / `agent` / `system`), `event_type` (text), `entity_type`, `entity_id`, `before_json` (nullable), `after_json` (nullable), `reason` (text), `policy_decision` (nullable: `allow`/`deny`/`needs_approval`), `metadata_json`.
- `audit/events.py`:
  - `record_event(conn, ...) -> event_id`
  - `list_events(conn, user_id, run_id=None, entity_id=None, event_type=None)`
  - **No update or delete functions. Not now, not ever.**
- Add SQLite triggers that `RAISE(ABORT, ...)` on `UPDATE` and `DELETE` of `audit_events`, so append-only is enforced by the database, not just by convention.

**Tests:** record then list; updating a row fails; deleting a row fails; events are filtered by user and by run.

**Done when:** tests pass, including the two "cannot modify" tests.

**[GIT CHECKPOINT]** Suggested: `Add append-only audit log`

---

### Step 4: Tool contracts and registry

**Goal:** a standard way to define tools, with metadata governance can read.

**Build**
- `core/errors.py`: `ErrorCode` enum (`INVALID_INPUT`, `NOT_FOUND`, `DENIED_BY_POLICY`, `APPROVAL_REQUIRED`, `TOOL_FAILURE`, `STALE_DATA`, `INTERNAL`), and `ToolError` with `code`, `message`, `retryable: bool`.
- `tools/contracts.py`:
  - `SideEffect` enum: `READ`, `WRITE_LOGICAL` (changes our own database, reversible), `EXTERNAL` (touches the outside world).
  - `ToolSpec`: `name`, `description`, `input_model` (Pydantic class), `output_model` (Pydantic class), `side_effect`, `handler` (callable).
  - `ToolResult`: `ok: bool`, `data` (or None), `error` (ToolError or None).
- `tools/registry.py`: `register(spec)`, `get(name)`, `list_specs()`. Registering a duplicate name is an error.
- Input and output are always validated through the Pydantic models.

**Rules:** there is **no** `SideEffect` value for money movement, and no tool for it will be registered. Do not add one.

**Tests:** register and fetch; duplicate name rejected; invalid input returns `INVALID_INPUT` (not an exception leaking out); unknown tool returns `NOT_FOUND`.

**Done when:** tests pass.

**[GIT CHECKPOINT]** Suggested: `Add tool contracts and registry`

---

### Step 5: Governance and the executor choke point  *(user-led, see note)*

**Goal:** every tool call passes through one function that checks policy and writes audit events. This is the most important safety piece.

> **Note for the agent:** same as Step 3. Ask the user whether they want to write `governance/policy.py` and `tools/executor.py` themselves. The design below is the spec either way.

**Build**
- `config/policy.yaml` (data, not code). Example shape:
  ```yaml
  default: deny
  side_effects:
    read:          {decision: allow}
    write_logical: {decision: needs_approval}
    external:      {decision: deny}
  tools:
    get_transactions:          {decision: allow}
    recategorize_transaction:  {decision: needs_approval}
  ```
  Tool-specific entries override side-effect defaults. A tool with no matching rule is **denied**.
- `governance/policy.py`: `load_policy(path)`, `decide(policy, tool_spec) -> Decision` where `Decision` has `outcome` (`allow`/`deny`/`needs_approval`) and `reason` (readable sentence).
- `tools/executor.py`: `execute_tool(ctx, tool_name, raw_input, approved: bool = False) -> ToolResult`:
  1. Look up the tool (not found gives `NOT_FOUND`).
  2. Ask governance for a decision.
  3. `deny`: return `DENIED_BY_POLICY`, audit it, do not run the handler.
  4. `needs_approval` and `approved` is False: return `APPROVAL_REQUIRED`, audit it, do not run the handler.
  5. Validate input, run handler, validate output, catch exceptions into `TOOL_FAILURE`.
  6. Audit every call (allowed or not) with `actor`, `run_id`, tool name, decision, reason.
- `ctx` is a small object holding `conn`, `user_id`, `run_id`, `policy`, `clock`.
- **The handler must not be callable by any other path in the agent code.** Document this rule in the module docstring; the agent only ever calls `execute_tool`.

**Tests (all required):**
- Read tool is allowed and audited.
- `write_logical` tool without `approved=True` is blocked and the handler is **not called** (use a counter or mock to prove it).
- Tool with no policy rule is denied (default deny).
- **`test_no_money_movement_tools_registered`:** scan the registry and assert that no tool name contains words like `transfer`, `pay`, `send_money`, `trade`, `withdraw`, `deposit`; also assert no `SideEffect.EXTERNAL` tool is registered in Phase 0.
- Handler exception becomes a `TOOL_FAILURE` result, and the failure is audited.

**Done when:** tests pass.

**[GIT CHECKPOINT]** Suggested: `Add governance policy and tool executor`

---

### Step 6: Deterministic financial tools

**Goal:** the real financial math, tested with no LLM involved.

**Build** in `tools/financial.py`, each registered with a `ToolSpec` and policy entry:
1. `get_transactions` (READ): filters by date range, category, optional limit.
2. `get_balance` (READ): current balance derived from transactions plus account opening balance.
3. `aggregate_spend_by_category` (READ): totals per category for a month; uncategorised shown as its own bucket.
4. `check_budgets` (READ): per category budget status: `spent_paise`, `limit_paise`, `pct_used`, status `ok` / `warning` / `exceeded` using the budget's `warn_threshold_pct`.
5. `forecast_category_spend` (READ): simple deterministic run-rate forecast: `spent_so_far / days_elapsed * days_in_month` (IST). Put it behind a clear function signature so a better forecaster can replace it later. Document the method and its limits in the docstring.
6. `recategorize_transaction` (WRITE_LOGICAL): changes the category, sets `category_source = user` (or as given), and **writes an audit event with before and after**. Must be reversible: store enough in the audit event to undo. Needs approval per policy.

**Rules:** pure functions for the math (take data in, return data out) so they are trivially testable; the tool handler just fetches data and calls the pure function. Excluded credits/refunds must be handled explicitly (document your choice).

**Tests:**
- Hand-computed expected values for aggregation, budget status boundaries (exactly at the threshold, exactly at the limit, one paisa over), and forecast (day 1, mid month, last day, zero spend).
- Recategorize changes totals, writes an audit event with correct before/after, and is blocked without approval.
- Totals stay consistent: sum of category totals equals total spend.

**Done when:** tests pass. (This step may be split into 6a read tools and 6b the write tool. Do 6a first, report, then 6b.)

**[GIT CHECKPOINT]** Suggested: `Add read-only financial tools` (6a), `Add recategorize tool with audit trail` (6b)

---

### Step 7: Mock bank connector and synthetic data

**Goal:** realistic, **reproducible** test data with known ground truth.

**Build**
- `bank/synth.py`: `generate_transactions(seed, months, user_id, account_id)`:
  - Seeded `random.Random(seed)` only. Same seed gives identical output.
  - Realistic Indian student-style UPI merchants and amounts: mess/food, subscriptions, travel, stationery, etc. Raw merchant strings should be messy (e.g. `UPI-SWIGGY-...`), because Phase 1 categorization will use them.
  - Plant **known anomalies** (e.g. one unusually large transaction, one duplicate charge, one new merchant) and return them as a separate `ground_truth` list so tests can check them later.
- `bank/mock_bank.py`: `MockBankConnector` with `fetch_transactions(account_id, start, end)` returning raw dicts/models, simulating an external source. It should be able to simulate a failure (raise a `ToolError` with `TOOL_FAILURE`) when configured to, for failure-handling tests.
- A small loader that ingests connector output into the DB via the repo (no categorisation yet; `category_source = none`).

**Rules:** no network, no real bank formats, no real personal data. Do not commit generated data files.

**Tests:** same seed gives identical data; different seeds differ; anomalies are present in ground truth; loader inserts the expected number of rows; simulated connector failure is reported cleanly.

**Done when:** tests pass.

**[GIT CHECKPOINT]** Suggested: `Add mock bank and seeded test data`

---

### Step 8: RunState, memory schema, planner interface

**Goal:** define the shapes the later phases will use, without building the behavior.

**Build**
- `models/run_state.py`: `RunState` (Pydantic): `schema_version`, `run_id`, `user_id`, `intent` (nullable text), `plan` (list of planned step names), `observations` (list), `tool_results` (list of `ToolResult` summaries), `pending_actions` (list), `confidence` (nullable), `created_at`. Provide `to_llm_projection(state, fields=[...]) -> dict` that returns only the requested fields.
- `models/memory.py`: `MemoryEntry` (Pydantic) and the `memory_entries` table: `id`, `user_id`, `kind` (`preference` / `pattern` / `feedback`), `content`, `source` (`user_stated` / `observed` / `inferred`), `confidence` (0 to 1), `created_at`, `last_confirmed_at`, `provenance` (text: where it came from). **Schema plus insert/list functions only.** No decay, no retrieval ranking.
- `planner/router.py`: a `Planner` interface (Protocol) with `plan(state) -> list[str]`, and a `TrivialRouter` that maps a few fixed intent keywords to fixed tool lists. Mark it clearly in a docstring as a placeholder for Phase 2.
- Confidence convention in `docs/decisions.md`: where scores come from (rule match = high, LLM-only = capped at a documented maximum, user-corrected = 1.0). Treat confidence as a **threshold signal**, not a true probability.

**Tests:** RunState round-trips through JSON; projection excludes unrequested fields; memory entry requires provenance and source; router returns expected tool lists.

**Done when:** tests pass.

**[GIT CHECKPOINT]** Suggested: `Add run state, memory schema and planner interface`

---

### Step 9: LLM access layer

**Goal:** one place where the model is called, with validated structured output. No real provider yet.

**Build** in `llm/client.py`:
- `LLMClient` Protocol: `complete(prompt: str, **options) -> str`.
- `FakeLLMClient` that returns scripted responses (for tests).
- `structured_call(client, prompt, output_model, max_retries=2)`: asks for JSON, parses and validates it with the Pydantic model; on invalid output, retries with a short "your last output was invalid because ..." message; after the retries it raises a typed error (`TOOL_FAILURE`-style, not a crash).
- Keep prompts out of business logic: prompt strings live in a single `prompts.py` or constants block.

**Rules:** no provider SDK, no API keys, no network calls. The real adapter is a later task. Do not let LLM output flow into money math.

**Tests:** valid JSON passes; invalid then valid succeeds on retry; always-invalid raises the typed error after exactly `max_retries + 1` attempts.

**Done when:** tests pass.

**[GIT CHECKPOINT]** Suggested: `Add LLM client interface with validated output`

---

### Step 10: Config, golden tests, and Phase 0 exit review

**Goal:** lock in behavior so later phases cannot silently break it.

**Build**
- `core/config.py` + `config/settings.yaml`: default warn threshold, forecast method name, DB path, timezone. Loading validates via Pydantic. Make sure no thresholds are hardcoded elsewhere.
- `tests/golden/scenarios.json` with about **10 fixed scenarios** using a fixed seed, each with hand-verified expected outputs, for example:
  1. month totals per category
  2. budget exactly at the warning threshold
  3. budget exceeded by one paisa
  4. forecast at mid month
  5. recategorize changes totals and writes the audit event
  6. write tool blocked without approval
  7. unknown tool denied
  8. a simulated bank failure handled
  9. timezone edge: transaction at 23:59 IST on the last day of a month
  10. duplicate transaction is present in ground truth and visible to `get_transactions`
- `tests/golden/test_golden.py` runs them all.
- Walk through the section 7 checklist and report on each item honestly.
- Update `README.md` (how to run tests, folder overview) and finalize `docs/decisions.md`.

**Done when:** golden tests pass and the section 7 checklist is fully checked.

**[GIT CHECKPOINT]** Suggested: `Add golden tests and finish Phase 0 docs`. After this, **ask** whether to push and whether to tag the milestone (for example `phase-0-complete`). Do not do either without a yes.

---

## 7. Phase 0 exit checklist

- [ ] `pytest` passes fully; `ruff check` is clean
- [ ] All money stored as integer paise; no floats anywhere in money paths
- [ ] Month boundaries verified in IST, including edge cases
- [ ] Every table has `user_id` (except `users`); reserved `goals`/`buckets` tables exist with no logic
- [ ] Audit log is append-only and enforced by DB triggers
- [ ] Every tool call goes through `execute_tool` and is audited (allowed, denied, failed)
- [ ] Default-deny works; write tools blocked without approval; handler provably not called when blocked
- [ ] Test asserts no money-movement tool is registered
- [ ] Deterministic financial tools are covered by hand-computed tests
- [ ] Synthetic data is seeded and reproducible, with ground-truth anomalies
- [ ] `RunState` versioned and projection works; memory schema has provenance/source/confidence
- [ ] LLM layer validates structured output with retries; uses only the fake client
- [ ] About 10 golden scenarios pass
- [ ] `docs/decisions.md` has an entry for every step
- [ ] No AI attribution anywhere in code, docs, or git history
- [ ] Nothing from section 5 was built

---

## 8. If you are stuck or a step fails

- Do not skip the step or weaken the test. Report the failure with the exact error.
- Do not refactor earlier steps to "make this one easier" without asking.
- If two steps conflict, stop and ask which wins.
- If a step takes more than one sitting, propose a split and ask first.
- When in doubt: **smaller, simpler, tested, and ask.**
