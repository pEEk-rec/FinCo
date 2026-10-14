# PLAN_PHASE2.md: Phase 2, Agentic Intelligence Layer

Project: Personal Finance & Budgeting Copilot (Agentic AI course project)
Scope of this file: **Phase 2 only.** Phases 3 to 7 are not part of this task, but Phase 2 must leave clean extension points for them (section 10).
Owner and only contributor: the user (repo owner).

Read this whole file before writing any code. Then read `PLAN.md` (Phase 0), `docs/PLAN_PHASE1.md`, `docs/decisions.md`, `STATUS.md`, `docs/open_questions.md` and the current code. Phase 2 builds **on** Phases 0 and 1; it does not replace them. The Phase 1 fixed graph (`copilot run`, `copilot review-month`) must keep working unchanged.

---

## 0. Rules for the implementing agent

### 0.1 Work mode: autonomous, inside gates
Work through the stages in section 6 **in order**, without waiting for "go" between stages, but only inside these gates.

For every stage:
1. Write the stage goal (2 to 3 lines) and the files you will create or change at the top of that stage's entry in `STATUS.md`.
2. Build in small steps. Run tests and lint often.
3. A stage is done only when its **Done when** is met and the **full** test suite and lint pass.
4. Append the explain-back entry to `docs/decisions.md` (0.5) and the report to `STATUS.md` (0.4).
5. Continue to the next stage.

**Hard gates: stop and wait for the user**
- Any git action (0.3).
- Adding any dependency. Phase 2 needs **no new dependencies**. If you think one is needed, record it in `docs/open_questions.md`, work around it with the standard library, and continue.
- Anything that costs money, signs up for a service, or deploys.
- Deleting or overwriting anything outside this repository.
- A failing test or lint error you cannot fix after an honest attempt. Never weaken, skip, `xfail` or delete a test. Record the blocker; continue only with later stages that are fully independent of it, and say so.
- A change that would break a Phase 0 or Phase 1 contract: the governance choke point (`execute_tool`), append-only audit triggers, integer-paise money, `user_id` on every table, no money-movement tools, advice-validator behaviour, user > override > rule > cache > LLM precedence.

**Soft gates: decide, record, continue**
- A product decision this plan does not cover: take the most conservative reasonable default (quieter, safer, simpler), record it in `docs/open_questions.md` with the alternative.
- No Gemini key or quota exhausted: use the fake LLM provider, mark live checks pending in `STATUS.md`.
- A name in this plan differs from the real code: **the real code wins.** Record the mapping in `docs/phase2_alignment.md` (Stage 2.0).
- A small unrelated issue you notice (naming, a long line, a doc typo): add one line to `docs/known_issues.md` (file, line, what) and keep going. The owner will do a cleanup sweep after Phase 2. Do not fix unrelated things mid-stage. Do not let a known issue be a failing test or a lint error.

**Context hygiene:** if your tool supports it, start a fresh session every two stages. A fresh session must re-read this file, `STATUS.md` and `docs/decisions.md` before continuing.

### 0.2 Code rules
- Simple, readable Python. Short functions, clear names, type hints everywhere, a docstring on every public function. The owner must be able to explain every module in a viva.
- **Deterministic code owns financial truth.** The LLM never computes, compares or invents a number, an evidence result or a confidence. See section 2.
- **Every tool call goes through the executor** (`execute_tool` or its real name). No graph node, CLI command, planner or service calls a tool handler directly. A test enforces this, and in Phase 2 the test also covers every new module.
- **Money is integer paise.** No floats in any money path. Use `Decimal` for intermediate maths and round half up to paise (or ceil where this plan says so). Scores, weights and confidences are not money, but use `Decimal` for them too wherever it costs nothing, so results are reproducible.
- **Every new table has `user_id`.** Every query filters by it.
- **All thresholds, weights, limits and templates live in YAML config**, validated with Pydantic at load. No magic numbers in code.
- **No money movement exists.** No tool, CLI command, graph node, planner step or API that pays, transfers, trades, withdraws or deposits. The existing no-money-movement test must be extended to every new tool and must still pass.
- **No investment advice.** The system never names, rates or recommends a stock, fund, scheme, broker or platform, and never predicts market outcomes (roadmap: "no stock-picking").
- **Windows-safe.** The owner develops on Windows with Python 3.11 and a `.venv`. Use `pathlib`, no shell-specific assumptions, UTF-8 for every file read and write (the ₹ sign must round-trip).
- Never claim something works unless you ran it.

### 0.3 Git rules (strict, with a new commit cadence)
- Every git action needs the owner's explicit approval **first, every single time**: `init`, `add`, `commit`, `push`, `branch`, `checkout -b`, `merge`, `rebase`, `stash`, `tag`, remotes, `mv`, config changes. Earlier approval never carries over.
- **Phase 1 was committed stage by stage and with approval that was not confirmed. That must not repeat.**
- **New cadence: two commits for the whole of Phase 2**, not one per stage and never one per fix:
  - `[GIT CHECKPOINT A]` after Stage 2.6
  - `[GIT CHECKPOINT B]` after Stage 2.11
- Between checkpoints: **no git commands at all**, not even `git status` or `git diff`, unless the owner is present and asks. Work continues across stages with an uncommitted tree; that is expected.
- At each checkpoint, do not commit. Write the proposed commit message and exact file list into "Proposed commits (awaiting approval)" in `STATUS.md`, make sure the full suite and lint pass, then continue to the next stage if the owner is away, or stop and ask if the owner is present. The owner then approves, changes or declines. A push is a separate question; name the branch and remote and ask again. Push to **one** branch only, the one the owner names.
- Commits are authored only by the owner's existing git identity. Never change `user.name` or `user.email`.
- **No AI attribution anywhere:** no `Co-Authored-By` trailers, no "Generated with ..." lines, no session links, in commits, PR text, code comments or docs.
- Commit messages: short, plain English, imperative, under about 70 characters, one logical change. Suggested: A = `Add goals, simulation, investigation and alerts`, B = `Add planner, intent understanding and agent timeline`.
- Never force push, rewrite history, or commit `.env`, keys, the database file, `reports/` or generated data.

### 0.4 STATUS.md report (newest stage first)
```
## Current state
Last completed stage: <N> | Blockers: <list or "none">

## Stage N: <name>: DONE / BLOCKED / IN PROGRESS
Goal: <2 to 3 lines>
Built: <2 to 5 bullets>
Files: <list>
Tests: <passed / total> | Lint: <pass/fail>
Evidence: <the last line of the real pytest output and the real ruff output, pasted, not summarised>
Defaults chosen (open_questions.md): <list or "none">
Live checks pending: <list or "none">

## Proposed commits (awaiting approval)
1. <message>: <files>
```

### 0.5 Explain-back
After each stage, append 4 to 8 lines to `docs/decisions.md`: what was built, why this design, what it deliberately does not do, and one question an examiner might ask with its answer.

### 0.6 Honesty and quality rules (learned from the Phase 1 review)
These exist because Phase 1 reports claimed more than the code did. Follow them literally.
1. **Test the real path.** Every tool must have at least one test that goes through `execute_tool` with an `ExecutionContext`, including its failure path, and assertions about audit rows must be made on that path. A handler-only test does not prove governance or audit behaviour (Phase 1's `undo_refused` row existed when the handler was called directly but was rolled back when called through the executor).
2. **Boundary tests, both sides.** For every threshold, tolerance, weight cut-off or limit, write tests exactly at, just inside and just outside. A rule with one-sided tests is untested.
3. **Prove tests can fail.** For each safety rule listed in section 7 (validators, capability allowlist, step budget), do a one-time mutation check: weaken the rule temporarily, confirm a test fails, revert, confirm a clean state. Record the result in `docs/decisions.md`.
4. **Docs state only what tests prove.** No marketing language ("firewall", "quantum", "bulletproof", "military-grade", "production-grade" as a claim). Plain, factual sentences. Stage numbers in docs must match this file.
5. **Reports quote real output.** In `STATUS.md` paste the real final lines of `pytest` and `ruff check`. Never write a number you did not read from output. If a command was not run, say "not run".
6. **Do not tune on evaluation seeds.** Develop on dev seeds; report on held-out seeds that no code or config was tuned on. Perfect scores (100%, F1 1.0) on synthetic data are a warning that the data is too easy, not a result to celebrate; the evaluation must include a hard profile (section 6, Stage 2.4) and state weak spots plainly.
7. **Same names everywhere.** If a tool takes `audit_event_id`, every caller (CLI, UI, graph, tests) uses `audit_event_id`. After adding or renaming any tool input, grep all callers (including `src/copilot/ui/`) and add a test that calls the tool the way the UI/CLI does.

---

## 1. Phase 2 goal

Roadmap definition: *"Move from a fixed workflow to genuine investigate-and-plan behavior."*

> A user can ask in natural language ("why did my food spend jump this month?", "what if I buy a ₹30,000 laptop?", "am I on track for my trip goal?"). The agent turns the request into a typed task, **chooses only the tools it needs**, forms hypotheses, gathers deterministic evidence, estimates confidence, simulates the consequences of options, and produces a recommendation that exposes its evidence, calculations, assumptions, tools used and relevant memories. Alerts become adaptive instead of threshold-only. Every step is visible in an activity timeline. The agent still never moves money and never acts without approval.

### 1.1 The nine roadmap items and where they land
| Roadmap item | Stage | Implemented as |
|---|---|---|
| Intent Understanding | 2.7 | Input gate + typed `Intent` (deterministic first, LLM fallback, one clarifying question) |
| Dynamic Tool Selection | 2.8 | Planner over a capability-filtered tool catalogue, validated plans, step budget |
| Hypothesis, Evidence, Decision | 2.4 | Closed hypothesis catalogue, pure evidence functions, deterministic confidence |
| Agentic Anomaly Investigation | 2.4 | `investigate` over Phase 1 anomalies and "why did X change" questions |
| Goal-Aware Reasoning | 2.2 | Minimal goal model + deterministic goal-impact calculation |
| What-If Simulation | 2.3 | Pure simulation engine, scenario comparison, never writes financial state |
| Adaptive Alerts | 2.5 | Explainable multi-signal alert score with preferences, dedup and cooldown |
| Explainable Recommendations | 2.6 | `advice_items` extended with calculations, assumptions, tools, memories, simulation link |
| Agent Activity Timeline | 2.9 | Derived read model over audit events + run traces + pending approvals |

### 1.2 Decisions already made (do not re-open)
| Decision | Choice |
|---|---|
| LLM | Gemini only, behind the existing provider interface; fake provider for all tests |
| Surface | CLI (`copilot ...`); Streamlit is not extended in Phase 2 (frontend is designed separately) |
| Orchestration | LangGraph, with a **new** planner-driven graph beside the Phase 1 fixed graph |
| Languages | English intents only in Phase 2; record multilingual intent parsing in `open_questions.md` |
| Quality bar | Production-level: complete, tested, documented |

### 1.3 Roadmap tensions and how this plan resolves them (conservative defaults)
1. **Goals are a Phase 3 feature, but goal-aware reasoning is Phase 2.** Phase 2 adds only a *minimal* `goals` table (name, target, current amount maintained by the user, deadline, priority). Progress tracking, required-savings-rate dashboards, projected completion and goal-linked buckets stay in Phase 3.
2. **Virtual balance partitioning (roadmap section 3) belongs to no numbered phase.** Default: **not in Phase 2**; it lands with goal-linked buckets in Phase 3. Phase 2 must not use or alter the reserved bucket schema.
3. **"Relevant memories" must be shown in explanations, but behavioural memory is Phase 3.** Phase 2 surfaces only records that already exist: merchant overrides, past user corrections, and past approved/rejected advice. No new learning, no decay.
4. **"LLM reasoning is used for planning and investigation" vs "deterministic systems own financial truth".** The LLM may choose *which* allowed steps to run and *which* catalogue hypotheses to test, and may phrase validated findings. It never produces evidence, numbers, confidence or conclusions (section 2).
5. **Conversational interface is Phase 6.** Phase 2 offers one-shot `copilot ask` with at most one clarifying question. No multi-turn chat memory.

---

## 2. Design principles for Phase 2

1. **Agentic where it is safe, deterministic where it matters.** The LLM sits in four places only: (a) fallback entity extraction for an intent, (b) proposing a plan or next step from the allowed tools, (c) choosing hypotheses from a closed catalogue, (d) narrating already-validated findings. Everything else (evidence, calculations, confidence, alert scores, simulations, goal impact, numbers) is deterministic code.
2. **Every LLM output is a proposal that deterministic code validates.** Invalid, disallowed or out-of-schema proposals are rejected, audited, and replaced by the deterministic fallback. The system must produce a correct (if less flexible) answer with the LLM completely off.
3. **The planner can only reach tools it is allowed to reach.** A capability matrix in config decides which tools the planner may select. Write tools are never planner-selectable. Default-deny, tested.
4. **Bounded autonomy.** Max steps per task, max LLM calls per task, max investigation rounds, loop detection, and memoization of identical tool calls. Hitting a bound ends the task cleanly with a typed reason, never an exception.
5. **Honest uncertainty.** Outcomes include `inconclusive` and `needs_clarification`. A cause is asserted only when deterministic evidence meets the configured bar. Unexplained residual is always reported.
6. **Simulation before action.** Any recommendation with a financial consequence carries a simulation of that consequence. A recommendation without one is rejected by the validator.
7. **Derived over stored.** The activity timeline, goal impact and alert context are computed from existing tables wherever possible. Store only what must be preserved as an explanation record (investigations, simulations, alerts).
8. **Quiet by default.** An ordinary month produces zero alerts. Adaptive alerting must reduce noise compared with thresholds alone without losing meaningful events (measured in Stage 2.10).
9. **Nodes stay thin.** Graph nodes call tools through the executor and update state. Logic lives in pure functions and services, testable without LangGraph.
10. **Privacy.** The LLM receives only: the structured intent text with account numbers, UPI IDs, phone numbers and names redacted, normalized merchant names, categories, aggregate paise values, and finding JSON. Never raw narrations. Redaction runs before every call (asserted on the fake provider's captured prompts). Logs contain counts and codes only, never user query text or merchant text.

---

## 3. Stack

Keep everything from Phases 0 and 1. **No new dependencies.** Before writing new Gemini structured-output code, check the current official documentation for the installed SDK version (APIs change). Model names come from config, never hard-coded. Record the model and prompt version in every audit event and trace entry that involves an LLM call.

---

## 4. Data model additions

Add numbered migrations after the last Phase 1 migration (`db/migrations/NNN_name.sql`), each idempotent and in a transaction. All tables have `user_id`, foreign keys on, `CHECK` constraints where simple. If `audit_events.event_type` is constrained by a `CHECK`, extend it in a migration; never relax the append-only triggers.

| Table | Purpose and key columns |
|---|---|
| `agent_tasks` | One row per user request: `id`, `run_id`, `raw_text` (local only, never logged), `intent_json`, `status` (`understood`/`needs_clarification`/`refused`/`planned`/`running`/`awaiting_approval`/`done`/`failed`/`stopped`), `stop_reason` (nullable: `completed`/`step_budget`/`llm_budget`/`loop_detected`/`tool_failure`/`inconclusive`), `planner_mode`, `model`, `prompt_version`, `created_at`, `finished_at` |
| `plan_steps` | `task_id`, `seq`, `tool_name`, `args_json`, `rationale`, `proposed_by` (`deterministic`/`llm`), `status` (`proposed`/`rejected`/`running`/`done`/`failed`/`skipped_memoized`), `reject_reason`, `started_at`, `finished_at` |
| `goals` | Minimal: `name`, `kind` (`savings`/`purchase`/`emergency_fund`/`other`), `target_paise`, `current_paise` (user-maintained), `deadline` (date, nullable), `priority` (1 to 3), `status` (`active`/`paused`/`done`), `created_at`, `updated_at` |
| `investigations` | `task_id`, `run_id`, `subject_kind` (`anomaly`/`category_change`/`merchant_change`/`period_change`), `subject_ref_json`, `outcome` (`explained`/`partially_explained`/`inconclusive`/`needs_clarification`), `confidence_label` (`high`/`medium`/`low`), `explained_share_bp` (basis points, integer), `unexplained_paise`, `rounds`, `created_at` |
| `hypotheses` | `investigation_id`, `code` (from catalogue), `status` (`supported`/`contradicted`/`untested`/`neutral`), `score_bp`, `contribution_paise` |
| `evidence_items` | `investigation_id`, `hypothesis_code`, `test_code`, `result` (`supports`/`contradicts`/`neutral`), `strength_bp`, `numbers_json`, `txn_ids_json` |
| `simulations` | `task_id`, `scenario_json`, `baseline_json`, `result_json`, `assumptions_json`, `created_at` (append-only by convention; never edited) |
| `alerts` | `kind`, `subject_key`, `period`, `score_bp`, `severity` (`info`/`notice`/`warning`/`critical`), `components_json`, `why_text`, `status` (`open`/`acknowledged`/`dismissed`/`snoozed`), `snoozed_until`, `dedup_key`, `run_id`, `created_at`, `decided_at`, `dismiss_reason` |
| `alert_preferences` | `category_id` (nullable), `kind` (nullable), `min_severity`, `muted` (bool), `max_open_alerts` (nullable) |
| `advice_items` (extend) | add `origin` (`monthly_review`/`investigation`/`whatif`/`alert`/`goal`), `calculations_json`, `tools_used_json`, `memories_json`, `confidence_label`, `simulation_id` (nullable), `task_id` (nullable) |

Notes:
- Scores stored as **basis points** (integers 0 to 10000) to avoid floats in storage. Convert to `Decimal` in code.
- `raw_text` of a task is user data on the user's device. It may be shown back to the user but is never written to logs and always redacted before an LLM call.
- No view is needed for the timeline (section 5.9); it is built from existing tables.

---

## 5. Key designs

### 5.1 Capability matrix and tool catalogue
`config/planner_capabilities.yaml` lists every registered tool with: `planner_selectable` (bool), `class` (`read`/`compute`/`write_logical`/`approval_required`/`prohibited`), `cost` (`cheap`/`medium`/`expensive`), `short_description` (used in planner prompts), and `intents` it is relevant to.

Rules (enforced in code and tested):
- Only `read` and `compute` tools may have `planner_selectable: true`. Tools that write financial or user state (`categorize_batch`, `recategorize_transaction`, `undo`, `decide_advice`, `create_goal`, `update_goal`, and similar) are **never** planner-selectable. Writing to explanation records (`investigations`, `simulations`, `alerts`, `plan_steps`, `agent_tasks`) is done by dedicated, narrow tools that are `compute`-class from the planner's point of view and `WRITE_LOGICAL`, allowed for actor `agent` in `policy.yaml`.
- A test enumerates **every registered tool** and fails if it lacks both a policy entry and a capability-matrix entry (default-deny stays default-deny).
- `docs/capability_matrix.md` is generated from the YAML (a script, not hand-written) and lists: autonomous analysis, approval-required, permanently prohibited. Mark it `DRAFT: awaiting user review`.

### 5.2 Input gate and intent understanding
Pipeline for `copilot ask "<text>"`:
1. **Input gate** (deterministic patterns first; an LLM classifier may add a refusal, never remove one). Refusal classes: `INVESTMENT_ADVICE` (what to buy/sell/hold, which fund/stock/broker), `MONEY_MOVEMENT` (pay, transfer, send, withdraw, invest this), `MARKET_PREDICTION`, `SENSITIVE_DATA_SUBMISSION` (OTP, PIN, password, card or account numbers pasted in), `OUT_OF_SCOPE`. A refusal is a typed template response, audited, and never reaches the planner. Refusals state what the agent can do instead.
2. **Deterministic parsers** (pure, heavily tested, config-driven patterns in `config/intent_patterns.yaml`):
   - *Period:* "this month", "last month", month names, "last N months", "this week", date ranges. Asia/Kolkata boundaries. Ambiguity returns `None`, not a guess.
   - *Amount:* ₹/Rs/rupees, commas, lakh/crore, `k`. Output integer paise. Reuse and invert the Phase 1 advice-number logic where possible, and keep one shared module for number formats.
   - *Entities:* category, merchant, goal, resolved against the user's real rows with normalized, case-insensitive match; unknown entity is not guessed.
3. **Intent classifier:** keyword/pattern classification into `IntentType`: `summarize_period`, `explain_change`, `investigate_anomaly`, `check_budget`, `forecast`, `whatif_add_spend`, `whatif_reduce_spend`, `goal_check`, `list_recurring`, `alerts_overview`, `unknown`.
4. **LLM helper (optional, off by default if no key):** only when the deterministic pass leaves entities missing or the type `unknown`. Returns a structured `Intent` candidate (strict schema). Every field is then re-validated against the database; anything that does not resolve is dropped. The LLM can never create an intent type outside the enum.
5. **Clarification:** if a required entity is missing or ambiguous, produce **one** clarifying question (a typed template naming the missing slot, with up to 4 concrete options from the user's own data). `needs_clarification` status; the CLI asks interactively once; a second failure ends the task cleanly.
6. `Intent` object: `type`, `period`, `category_id`, `merchant_normalized`, `goal_id`, `amount_paise`, `horizon_months`, `confidence_label`, `source` (`deterministic`/`llm`), `clarification` (nullable).

### 5.3 Planner and dynamic tool selection
**Plan** = ordered list of `PlanStep(tool_name, args, rationale)`.

Two planners behind one interface (`Planner.propose(intent, state_projection, tool_catalogue) -> Plan`):
- `DeterministicPlanner`: table `config/plan_templates.yaml` maps each `IntentType` to the minimal ordered tool list and argument bindings from the intent. This is the baseline, always available, and what the LLM-off mode uses.
- `LLMPlanner`: receives the intent, a compact projection of what is already known (never the whole state), and the **planner-selectable** tool catalogue (name, short description, input schema). Returns structured JSON: list of steps with rationale. Temperature 0.

**Plan validator (deterministic, the key safety piece of Phase 2):**
- every `tool_name` exists **and** is planner-selectable; args validate against the tool's input schema; referenced ids exist and belong to the user
- step count within `max_steps`; no duplicate (tool, args) pairs; no step after a terminal step
- plan must include every tool the template marks `required` for that intent (so the LLM cannot skip the evidence)
- on any failure: audit `plan_rejected` with the reasons (using the failure-path audit from Stage 2.0), discard the LLM plan, use the deterministic plan. Never partially accept an invalid plan.

**Execution loop:** each step runs through `execute_tool`. Results are summarised into a compact **observation** (structured, not prose) appended to task state. Memoization: identical (tool, args) returns the earlier result and is recorded as `skipped_memoized`. Loop detection: the same tool failing or repeating beyond `max_repeat` ends the task with `loop_detected`.

**Re-planning (the agentic part, bounded):** after the evidence step of an investigation, if `outcome` is `partially_explained` or `inconclusive` and `rounds < max_rounds` (config, default 2), the planner may add one further round of hypotheses/tests from the catalogue not yet tried. Deterministic rule decides whether another round is allowed; the LLM may only choose among untested catalogue entries.

**Minimality:** for every canonical intent the set of tools called must equal the expected minimal set (tested and measured in Stage 2.10). Calling extra tools "just in case" is a defect.

### 5.4 Investigation engine: hypothesis, evidence, decision
All pure functions over transaction data (excluding transfers and duplicates as the Phase 1 spend views do), returning Decimal-based results. Config in `config/investigation.yaml`.

**Subjects:** an anomaly row from Phase 1; or a change question ("why did category X rise in month M vs M-1 (or vs its trailing average)").

**Hypothesis catalogue (closed list; adding one is code plus tests, not config):**
| Code | Meaning | Deterministic evidence tests |
|---|---|---|
| `one_off_large` | A few large transactions explain the change | share of change from top-k transactions; whether merchant/category history has comparable amounts |
| `more_frequent` | Same typical ticket, more transactions | change in count vs change in mean ticket (volume/price effect) |
| `higher_ticket` | Same count, larger average amount | same decomposition |
| `new_merchant` | A merchant not seen in lookback accounts for the change | spend from merchants absent in lookback window |
| `recurring_change` | A known recurring series changed amount, appeared or stopped | compare `recurring_series` expected vs actual |
| `miscategorization` | Spend moved because a merchant's category differs from its history | merchants whose category differs from its dominant historical category; shows effect on both categories |
| `duplicate_or_refund` | A duplicate charge or a matching refund distorts the total | `is_duplicate_of`, matching reversal within window |
| `seasonal_or_timing` | The month has different shape (weekend count, payday timing, partial month) | compare with same-length windows; flag partial months |

**Decomposition invariant:** for a change question, the volume effect + ticket effect + new-merchant effect + stopped-merchant effect (+ residual) must sum **exactly** to the total change in paise. A property test enforces this on random data. The residual is reported as `unexplained_paise`.

**Scoring (deterministic, documented in `docs/decisions.md`):**
- each hypothesis gets `contribution_paise` (the part of the change it explains, disjoint or clearly overlapping-flagged) and `score_bp`
- `explained_share_bp = min(10000, sum of non-overlapping supported contributions / total change)`
- `confidence_label` from config thresholds on explained share, data sufficiency (history months, transaction counts) and margin between the top hypothesis and the next
- `outcome`: `explained` (share ≥ threshold and confidence ≥ medium), `partially_explained`, `inconclusive` (nothing supported above the bar, or insufficient history), `needs_clarification` (a decisive fact is only the user's to give, for example whether a large payment was planned; ask one question)
- **No-cause cases must return `inconclusive`.** A random noisy increase with no structure must not be "explained".

LLM role here: choose which catalogue hypotheses to test first (optional, order only), and narrate the validated result. It cannot add evidence or change scores.

Tools: `investigate_anomaly(anomaly_id)`, `explain_change(category_id|merchant, period, baseline)`; both `compute`-class from the planner's view, writing `investigations/hypotheses/evidence_items` as `WRITE_LOGICAL` for actor agent. Results include the `finding` objects (kind `investigation_result`) used for narration.

Dismissing an anomaly as expected: `dismiss_anomaly(anomaly_id, reason)` is a user-actor tool; not planner-selectable.

### 5.5 Goal-aware reasoning (minimal)
Config `config/goals.yaml`: horizon limits, how many complete months to use for the surplus estimate, minimum months required.

Pure functions:
- `months_remaining(goal, today)` using IST calendar months; no deadline means `None`
- `required_monthly_paise(goal, today)` = ceil((target - current) / months_remaining), never negative, `None` if no deadline
- `monthly_surplus_estimate(user, today)` over the last N complete months: median of (income - spend, transfers excluded) with a low/high range from the spread; fewer than the configured minimum months returns `insufficient_data`
- `goal_status(goal, surplus_range)`: `on_track` (low ≥ required), `at_risk` (expected ≥ required but low < required), `off_track` (expected < required), `unknown` (insufficient data or no deadline)
- `goal_impact(decision_paise, goals, surplus_range)`: for each active goal by priority, status before vs after subtracting the decision from this period's surplus, and the shortfall in paise

Tools: `create_goal`, `update_goal` (actor user: allow; actor agent: approval required; not planner-selectable), `list_goals`, `evaluate_goal_impact` (read/compute, planner-selectable). Goal changes are audited.

### 5.6 What-if simulation
`config/whatif.yaml`: max horizon months (default 6), max scenarios per comparison (3), caps on amounts.

`Scenario`: `kind` (`add_spend`, `reduce_spend`, `change_contribution`), `category_id` (optional), `amount_paise`, `start` (month), `recurring` (bool), `months`, `goal_id` (for contribution). `change_contribution` adjusts a goal's planned monthly saving and does not move money.

`simulate(snapshot, forecast, recurring, goals, scenario) -> Projection`, a **pure function**:
- baseline = the Phase 1 forecast v2 range (fixed recurring part + variable run-rate) per month over the horizon
- scenario deltas applied to the right bucket (variable or fixed)
- output per month: category spend (low/expected/high), budget status per category, surplus range, goal status/shortfall per active goal
- assumptions recorded explicitly (for example "variable spend continues at the last 3-month rate", "income unchanged")
- insufficient data in the baseline propagates as `insufficient_data`, never a made-up number

`compare_scenarios(snapshot, scenarios[<=3])` returns a side-by-side table with the baseline.

Invariants (property tests): simulation never writes financial tables; zero-amount scenario equals baseline exactly; adding spend never improves any metric; reducing spend never worsens any metric; results sum correctly in paise; same inputs give identical outputs.

Tools: `run_whatif(scenario)`, `compare_options(scenarios)` (compute-class, planner-selectable). Each run writes one `simulations` row (the explanation record) and one audit event.

### 5.7 Adaptive alerts
`config/alerts.yaml`: signal weights, tier cut-offs, cooldown days, default `max_open_alerts`, dedup rules.

Signals (each normalised to 0..1, deterministic):
1. **Threshold:** budget status (`warning` low weight, `exceeded` high)
2. **Forecast:** `projected_exceed` and how far the forecast range's low/expected/high exceed the limit
3. **History deviation:** robust z-score of the category's spend-to-date vs same point in prior months
4. **Anomaly:** open Phase 1 anomaly score for the category/merchant
5. **Goal impact:** any active goal moving to `at_risk`/`off_track` because of current spend
6. **Data confidence:** low data sufficiency damps the score (never raises it)

`score = clamp(sum(weight_i * signal_i) * confidence_damping)`, then map to `info`/`notice`/`warning`/`critical`. Alert stores the component breakdown and a template-built `why_text` (e.g. "Dining is 91% of budget with 11 days left; the forecast range exceeds the limit; usual spend by this day is ₹X"), numbers from components only.

User preferences (`alert_preferences`): per-category or per-kind `muted`, `min_severity`, `max_open_alerts`. A muted kind never alerts, but the suppressed alert is still recorded in the audit as `alert_suppressed` (counts only) so the timeline can explain "why no alert".

Lifecycle: `open` → `acknowledged`/`dismissed` (with optional reason)/`snoozed(until)`. Dedup by `dedup_key` per period; cooldown after dismissal; an alert escalates in place (higher severity) rather than duplicating.

Tools: `evaluate_alerts(period)` (WRITE_LOGICAL on `alerts`, allowed for actor agent), `decide_alert(alert_id, action, reason)` (actor user), `set_alert_preference` (actor user). No message sending exists in Phase 2; delivery channels are Phase 6.

Quiet-by-default test: an ordinary seeded month produces zero alerts above `info`.

### 5.8 Explainable recommendations
Extend `advice_items` (section 4). A recommendation is an advice item with extra explanation fields:
- `evidence`: finding ids and numbers (from Phase 1 design) plus investigation/evidence ids
- `calculations_json`: list of steps `{label, formula_id, inputs, result}`, produced by deterministic code (for example "required monthly saving = ceil((₹60,000 - ₹18,000) / 6) = ₹7,000")
- `assumptions_json`
- `tools_used_json`: from the task's plan steps (tool, args summary, status)
- `memories_json`: existing records the recommendation relied on (merchant overrides, past corrections, past approved/rejected advice of the same kind); may be empty; each entry says what it is and when it was created
- `confidence_label`
- `simulation_id`: **required** when the recommendation has a financial consequence

**Narration validator (extend the Phase 1 advice validator, do not fork it):**
- numbers: same rules and tolerance as Phase 1, checked against findings, investigation results, simulation results and goal calculations
- every `finding_id` / `simulation_id` / `investigation_id` cited must exist and belong to the task
- **causal-claim rule:** words that assert a cause ("because", "due to", "caused by", "driven by") are allowed only when the cited investigation's outcome is `explained` with confidence at least `medium`. Otherwise the text is replaced by the hedged template ("could not determine a cause; unexplained: ₹X")
- forbidden content as in Phase 1 (named investments, instructions to move money, guarantees, predictions beyond the simulation's own range)
- **consequence rule:** a recommendation of kind `spend_decision`, `reduce_spend` or `contribution_change` without `simulation_id` is rejected
- on failure: deterministic template from `config/explanation_templates.yaml` for that finding kind; the item is marked `fallback_used`
- recommendations are `draft` until the user approves or rejects with `decide_advice` (existing tool); approval triggers nothing

`explain <recommendation_id>` prints the full explanation: evidence, calculation steps, assumptions, tools used, memories, simulation, confidence.

### 5.9 Agent activity timeline
Derived read model (no new storage): `build_timeline(user, run_id|task_id|since)` merges `audit_events`, `agent_tasks`, `plan_steps`, run-trace entries, investigations, simulations, alerts and pending advice into one chronologically ordered list of `TimelineEntry(ts, kind, title, detail, status, ref)`. Kinds: `observation`, `plan`, `tool_call`, `investigation`, `simulation`, `alert`, `decision`, `approval_pending`, `refusal`, `error`.

Requirements: stable ordering (ts, then seq), pending approvals pinned in a separate "needs your decision" section, no raw user text in entries (intent type and entities only), JSON output identical to what the Phase 6 dashboard will consume. Redaction rules from Phase 1 apply.

### 5.10 Planner-driven graph
New compiled graph `agent_graph` (LangGraph), separate from the Phase 1 fixed graph:
`understand → (clarify?) → plan → act (loop) → investigate/simulate/etc. via act → reflect → synthesize → review (interrupt) → finalize`, plus the `error` node.
- `understand`: input gate + intent
- `clarify`: interrupt for the one question
- `plan`: planner + plan validator
- `act`: executes the next planned step via `execute_tool`, updates observations
- `reflect`: deterministic check (bounded re-planning rule from 5.3)
- `synthesize`: builds findings and narration (validator + template fallback), creates draft recommendations
- `review`: interrupt for approve/reject of recommendations (reuse Phase 1 mechanism)
- `finalize`: closes task with `stop_reason`
Same thin-node rules as Phase 1. Every node appends a trace entry. Budget exhaustion and loop detection route to `finalize` with the typed reason, never to a crash.

### 5.11 CLI additions (all through services and the executor, all with `--json`)
| Command | Does |
|---|---|
| `copilot ask "<text>"` | full agent graph for a natural-language request; prints answer, evidence summary, drafts needing approval |
| `copilot investigate --anomaly <id>` / `--category <c> --month <YYYY-MM>` | direct investigation without NL parsing |
| `copilot whatif add-spend --amount ... [--category ...] [--months N] [--recurring]` / `reduce-spend ...` / `compare ...` | simulation |
| `copilot goals add/list/update/done` | goal management (user actor) |
| `copilot alerts [list/evaluate/ack/dismiss/snooze/prefs]` | adaptive alerts |
| `copilot timeline [--task ID] [--run ID]` | activity timeline |
| `copilot explain <advice_id>` | full explanation of a recommendation |
| `copilot decide <advice_id> approve\|reject` | approve/reject (wraps `decide_advice`) |
| `copilot eval --phase 2` | Phase 2 evaluation harness |

---

## 6. Stages

Each stage: **Goal, Build, Tests, Done when.** Remember rules 0.6.1 and 0.6.2 for every stage.

### Stage 2.0: Align, carry-overs, capability matrix
**Goal:** start from an accurate picture of the real Phase 1 code, fix the one infrastructure gap Phase 2 depends on, and set up config skeletons.
**Build:**
1. Read the whole codebase. Write `docs/phase2_alignment.md` mapping every name in this plan to the real module/function and listing gaps. Record the baseline test count and lint state (paste real output).
2. **Failure-path audit.** In Phase 1, a row written inside a tool handler is rolled back when the handler raises (savepoint), and the executor then writes a generic `tool_call` failure event. Phase 2 needs domain-specific audit of refusals and rejected plans (`plan_rejected`, `undo_refused`, `input_refused`) to survive. Design: let `ToolFailure` carry an optional `audit_event_type` and `audit_metadata`; the executor writes its failure audit event using them, after the rollback and in its own savepoint. Do not change `execute_tool`'s signature or its default-deny behaviour. Keep all existing executor tests unchanged and green. If this requires changing a Phase 0 contract beyond that, it is a hard gate: record the design and stop that part.
3. Add the config skeletons and Pydantic validation for the new YAML files (section 3 list), failing loudly on bad config.
4. Add `docs/known_issues.md` (empty list) and `docs/capability_matrix.md` generator script.
5. Check one Phase 1 caller risk: grep every caller of the `undo` tool (CLI, Streamlit, graph, tests) and confirm they pass the input name the tool actually declares; add a test that calls it the way the Streamlit view does. If it mismatches, fix the caller and record it in `known_issues.md`/`decisions.md`.
**Tests:** failure-path audit through `execute_tool` (row survives, correct event type, metadata present); config validation failures; baseline suite unchanged.
**Done when:** baseline plus new tests pass; alignment doc complete.

### Stage 2.1: Schema and models
**Goal:** all Phase 2 tables and typed models.
**Build:** migrations for section 4; Pydantic models (`Intent`, `Plan`, `PlanStep`, `Observation`, `AgentTask`, `Goal`, `Hypothesis`, `EvidenceItem`, `Investigation`, `Scenario`, `Projection`, `Alert`, `AlertPreference`, `Recommendation`, `TimelineEntry`, `CalcStep`); small parameterised repo functions filtered by `user_id`.
**Tests:** constraints, foreign keys, user isolation, JSON round-trips, migration idempotency on a fresh and on a Phase 1 database (data preserved), `advice_items` extension keeps existing Phase 1 rows valid.
**Done when:** tests pass.

### Stage 2.2: Goals and goal-aware reasoning
**Goal:** the minimal goal model and its deterministic maths (section 5.5).
**Build:** pure functions, tools (`create_goal`, `update_goal`, `list_goals`, `evaluate_goal_impact`), policy entries (actor-aware), CLI-ready services.
**Tests:** hand-computed cases on both sides of every boundary: exactly on-track, one paisa short, deadline this month, deadline passed, no deadline, target already met, zero history, fewer than the minimum months; ceil rounding; IST month boundaries; agent cannot create or update goals without approval; through-executor tests.
**Done when:** tests pass.

### Stage 2.3: What-if simulation engine
**Goal:** pure, trustworthy simulation (section 5.6).
**Build:** `Scenario`, `simulate`, `compare_scenarios`, tools writing `simulations` rows, assumptions list.
**Tests:** the invariants in 5.6 as property tests (Hypothesis); hand-computed month-by-month projections; scenario that crosses a budget exactly at the limit and one paisa over; recurring vs one-off; horizon limit; insufficient baseline data propagates; no financial table is modified by any simulation (assert by snapshotting table contents before/after); through-executor tests.
**Done when:** tests pass.

### Stage 2.4: Investigation engine and hard synthetic data
**Goal:** hypothesis, evidence, decision with honest uncertainty (section 5.4), measured against hidden truth.
**Build:**
- Synthetic generator v3 with **injected causes recorded in hidden ground truth**: a one-off large purchase, a subscription price hike, a new habit (higher frequency), a new merchant, a miscategorised merchant, a duplicate charge plus a refund, a partial-month effect, and **no-cause noise months** where spend moves without structure. Add a **hard profile**: noisier narrations, merchant aliases not in the alias file, overlapping causes, small histories. Dev seeds and held-out seeds listed in config; never tuned on held-out.
- Hypothesis catalogue, evidence functions, decomposition, scoring, outcome rules, `investigate_anomaly` and `explain_change` tools, `dismiss_anomaly` (user actor).
**Tests:** decomposition sums exactly (property test); each hypothesis detected on its injected cause; every threshold tested at, inside and outside; noise months return `inconclusive` (false-explanation rate reported); overlapping causes are not double counted; partial history gives low confidence; `needs_clarification` raised only when the decisive fact is user-only; through-executor tests; investigation rows written with correct user isolation.
**Done when:** tests pass; ground-truth recall on dev seeds reported in `STATUS.md` with the hard profile reported separately.

### Stage 2.5: Adaptive alerts
**Goal:** explainable, quiet-by-default alerting (section 5.7).
**Build:** signal functions, scoring, tiers, dedup/cooldown, preferences, tools, suppression audit.
**Tests:** every signal and every tier cut-off at the boundary; an ordinary month yields no alert above `info`; the same breach alerts higher when forecast and history agree and lower when data confidence is low; muted kind never alerts but is audited as suppressed; dedup and in-place escalation; cooldown after dismissal; alert `why_text` numbers all come from components (validator test); through-executor tests.
**Done when:** tests pass.

### Stage 2.6: Explainable recommendations and narration validation
**Goal:** every recommendation exposes evidence, calculations, assumptions, tools and memories, and cannot assert more than the data supports (section 5.8).
**Build:** migration use of the extended `advice_items`; `build_recommendation` services for each origin; extend the Phase 1 validator (do not fork); causal-claim rule; consequence rule; `config/explanation_templates.yaml`; `explain` rendering; existing-memory lookup (overrides, past decisions).
**Tests:** validator accepts correct narration and rejects: invented number, wrong percentage, unknown id, cause asserted for an `inconclusive` investigation, missing simulation on a consequential recommendation, named fund/stock, "transfer ₹X"; fallback template used on each failure; rounding tolerance behaves exactly as in Phase 1 (re-run those tests unchanged); `memories_json` never contains records of another user; approval triggers no action; mutation check per 0.6.3 on the causal-claim rule and the consequence rule.
**Done when:** tests pass.
**[GIT CHECKPOINT A]**: full suite and lint green. Record in `STATUS.md`: commit message `Add goals, simulation, investigation and alerts`, with the exact file list. **Do not run git.** Continue.

### Stage 2.7: Input gate and intent understanding
**Goal:** safe, typed task creation from natural language (section 5.2).
**Build:** input gate with refusal classes and templates; period, amount and entity parsers (shared number module); classifier; LLM entity-extraction helper with strict schema and re-validation; clarification flow; `agent_tasks` persistence; audit events.
**Tests:** parser tables with many phrasings and ambiguous/edge inputs (month rollover, IST boundaries, "last 3 months", "20k", "2 lakh", "Rs. 1,25,000"); at least 40 labelled queries across intent types (deterministic accuracy reported); every refusal class triggers on its examples and never on look-alike benign queries; an LLM-proposed refusal is added but an LLM-proposed "allow" cannot remove a deterministic refusal; hallucinated entity is dropped; exactly one clarification, then clean stop; redaction asserted on captured prompts (account numbers, UPI IDs, phone numbers); raw text never appears in logs (captured log test); works with the LLM completely off.
**Done when:** tests pass.

### Stage 2.8: Planner, dynamic tool selection and agent graph
**Goal:** the genuinely agentic loop with hard bounds (sections 5.1, 5.3, 5.10).
**Build:** capability matrix loader and enforcement; tool catalogue projection for prompts; `DeterministicPlanner` with `plan_templates.yaml`; `LLMPlanner` (Gemini structured output, fake provider for tests); plan validator; execution loop with memoization, loop detection, step and LLM budgets; reflect node with bounded re-planning; synthesize node using Stage 2.6; `agent_graph` wired with LangGraph (clarify and review interrupts); run trace entries; `error` path.
**Tests:**
- *Selection and minimality:* for each canonical intent, tools called equal the expected minimal set; LLM-on and LLM-off give the same facts.
- *Adversarial plans (fake LLM returns):* a write tool, a prohibited tool, a nonexistent tool, invalid args, another user's id, too many steps, a plan missing a required step, duplicate steps, malformed JSON. Every one is rejected, audited as `plan_rejected`, and the deterministic plan runs. Mutation check: temporarily remove the allowlist check and confirm tests fail.
- *Bounds:* step budget, LLM-call budget, max rounds, repeat/loop detection each end the task cleanly with the right `stop_reason`.
- *Architecture:* no module outside the executor imports a tool handler (extend the existing test to all new modules, including planner and graph); no planner-selectable tool has side effect beyond explanation records; no-money-movement test covers all new tools.
- *Graph:* end-to-end offline runs for each intent type; resume after the clarify interrupt and after the review interrupt; failure in a step ends with an audited error; Phase 1 graph tests unchanged and green.
**Done when:** tests pass; a full offline `ask` run prints a correct trace.

### Stage 2.9: Activity timeline and CLI
**Goal:** visible agent behaviour and the complete command set (sections 5.9, 5.11).
**Build:** timeline read model; all CLI commands in 5.11 with `--json`; clear errors (no stack traces for expected failures); `docs/demo_script_phase2.md`: an exact 6-minute path: seed → goals → anomaly appears → `ask "why did my food spend jump?"` → investigation result with evidence and confidence → `whatif` laptop purchase vs goal → compare two options → adaptive alert with its why → `explain` a recommendation → approve → `timeline`.
**Tests:** timeline ordering and stability; pending approvals section; no raw query text in entries; JSON schema stable (snapshot test); CLI tests via Typer's test runner for every command, including error paths (unknown id, unknown category, expired budget, malformed amount); the demo script runs start to finish offline with the fake LLM.
**Done when:** tests pass; demo script runs.

### Stage 2.10: Evaluation harness and golden scenarios
**Goal:** honest numbers for the viva (`docs/eval_report_phase2.md`).
**Build:** `copilot eval --phase 2` and `eval/run_eval_phase2.py` reporting, on **held-out seeds**, mean and spread, standard and hard profiles separately:
- *Intent:* type accuracy, entity accuracy, clarification rate, refusal precision/recall
- *Tool selection:* exact-set match and minimality (extra tools per task), LLM-off vs LLM-on
- *Investigation:* top-hypothesis accuracy on injected causes, confidence calibration (accuracy per confidence label), **false-explanation rate on no-cause months**, mean explained share, inconclusive rate
- *Simulation:* property-test pass counts, determinism check
- *Alerts:* precision/recall against hidden "meaningful event" labels, alerts per month versus a threshold-only baseline, silence rate on ordinary months
- *Recommendations:* grounding rate (all numbers traceable), fallback rate, causal-claim violations (must be 0), missing-simulation violations (must be 0)
- *Safety:* adversarial plan suite (all rejected), refusal suite, budget-bound suite
- *Cost and latency:* LLM calls per task, latency per node
Golden scenarios in `tests/golden/phase2/` (at least 16), for example: ask returns an explained investigation with correct share; no-cause month returns inconclusive and a hedged sentence; planner rejects an LLM plan that selects `recategorize_transaction`; step budget stops a runaway plan; what-if purchase flips a goal to `at_risk`; zero-amount what-if equals baseline; ordinary month raises no alert; muted category is suppressed and audited; causal claim blocked when confidence is low; recommendation without simulation rejected; refusal of "which mutual fund should I buy"; refusal of "transfer ₹5,000 to Rahul"; clarification asked once; timeline shows pending approval; Phase 1 graph still produces the same monthly review; user-set category untouched by any Phase 2 tool.
**Rules:** never tune on held-out seeds; write weak spots plainly in the report; do not round or smooth numbers.
**Done when:** report generated; golden scenarios pass.

### Stage 2.11: Hardening and documentation
**Goal:** finish.
**Build:** failure-handling pass (LLM down or invalid JSON, quota exhausted mid-task, missing bank data, empty or one-month history, deleted category or goal referenced by an old task, stale consent, budget unset, user with no goals); logging review (no query text, merchant text or PII in logs); README additions (Phase 2 architecture diagram of the agent loop, capability matrix summary, privacy, limitations); update `docs/capability_matrix.md`; run the mutation checks from 0.6.3 and record them; final `docs/decisions.md` and `STATUS.md`; clear `docs/known_issues.md` of anything that is now a real defect, or leave remaining items listed for the owner's sweep.
**Done when:** section 8 checklist all green.
**[GIT CHECKPOINT B]**: full suite and lint green. Record in `STATUS.md`: commit message `Add planner, intent understanding and agent timeline` with exact file list. **Do not run git.** Push and any tag are separate questions for the owner.

---

## 7. Safety rules that must each have a failing-when-removed test

1. Planner cannot select a non-planner-selectable tool.
2. Invalid, partial or over-long LLM plans are rejected and replaced.
3. Every registered tool has both a policy entry and a capability-matrix entry.
4. The input gate refusal cannot be removed by the LLM.
5. Causal claims require an `explained` outcome with at least medium confidence.
6. Consequential recommendations require a simulation.
7. Numbers in narration must come from findings, investigations, simulations or goal calculations.
8. No tool handler is reachable except through the executor.
9. No money-movement tool exists.
10. Simulations never modify financial state.
11. User-set categories and merchant overrides are never touched by any Phase 2 tool.
12. Redaction runs before every LLM call.

---

## 8. Phase 2 exit checklist

- [x] Full suite and lint pass; Phase 0 and Phase 1 tests unchanged and green; the Phase 1 graph and CLI behave as before
- [x] Migrations apply on a fresh database and on a Phase 1 database, idempotently
- [x] Failure-path audit survives rollback; verified through `execute_tool`
- [x] Natural-language request becomes a typed intent; refusals work; at most one clarification
- [x] Planner selects only allowed tools; adversarial plans all rejected and audited; step, LLM and round budgets enforced
- [x] Tool selection is minimal for each canonical intent; LLM-off gives the same facts
- [x] Investigations produce hypotheses, evidence, decomposition that sums exactly, and honest outcomes (`inconclusive` on no-cause noise)
- [x] Goal-aware reasoning and what-if simulation are deterministic, property-tested and never write financial state
- [x] Adaptive alerts are explainable, quiet on ordinary months, and measured against a threshold-only baseline
- [x] Every consequential recommendation links a simulation and exposes evidence, calculations, assumptions, tools and memories
- [x] Narration validator blocks invented numbers, unsupported causal claims and prohibited content
- [x] Activity timeline shows the full trace and pending approvals; JSON schema stable
- [x] CLI demo script runs offline end to end
- [x] Evaluation report generated on held-out seeds, with weak spots stated
- [x] No tool handler reachable except through the executor; no money-movement tool (tested)
- [x] Docs contain no marketing language; stage numbers match this file; reports quote real command output
- [x] Exactly two proposed commits recorded; no git command was run; no AI attribution anywhere

---

## 9. Explicitly NOT in Phase 2

- Goal progress tracking over time, commitments, financial calendar, investment readiness, contribution planning, trade-off analysis (Phase 3)
- Behavioural memory logic, learning from accepted/rejected advice, memory decay (Phase 3). Phase 2 only *reads* existing records
- Virtual buckets or envelopes of any kind (Phase 3 with goal-linked buckets)
- Experiments, challenges, gamification (Phase 4); social and shared finance (Phase 5)
- Web dashboard, multi-turn conversation, messaging channels, proactive delivery of alerts (Phase 6)
- Guidance levels, risk-aware intervention modes, multi-step confirmation flows (Phase 7)
- Multilingual intent parsing, voice, a second LLM backend (the provider interface must still allow them)
- Any real bank, UPI, Account Aggregator or broker integration; any money movement; any investment advice

---

## 10. Extension points Phase 2 must leave

| Built now | Used later by |
|---|---|
| Capability matrix + planner validator | Phase 7 action capability matrix, guidance levels |
| `agent_tasks`, `plan_steps`, timeline read model | Phase 6 dashboard and conversational interface, cross-channel state |
| Minimal `goals` table + goal-impact functions | Phase 3 goal tracking, commitments, contribution planning, goal-linked buckets |
| `simulate` / `compare_scenarios` | Phase 3 trade-off analysis, investment readiness, Phase 7 mock confirmation flow |
| `memories_json` + existing override/decision records | Phase 3 behavioural memory and confidence decay |
| Alert score components + preferences | Phase 6 proactive messaging, Phase 7 risk-aware intervention |
| Investigation outcomes and dismiss reasons | Phase 3 contextual exceptions, Phase 4 experiment learning loop |
| Explanation fields on `advice_items` | Phase 7 policy explainability |
| Deterministic planner templates | Fallback for every future planner upgrade |
