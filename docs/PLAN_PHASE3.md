# PLAN_PHASE3.md: Phase 3, Advanced Financial Copilot

Project: Personal Finance & Budgeting Copilot (FinCo, Agentic AI course project)
Scope of this file: **Phase 3 only**, plus the roadmap's section 3 *Virtual Balance Partitioning* (deferred from Phase 2 to here), plus the **agentic architecture upgrades** in section 1.4 (multi-agent planning, reusable skills, context engineering, self-correction, bounded feedback learning, agent runtime and observability, MCP server).
Owner and only contributor: the user (repo owner).

Read this whole file before writing code. Then read, in this order: `STATUS.md`, `docs/decisions.md`, `docs/open_questions.md`, `docs/known_issues.md`, `docs/PLAN_PHASE2.md`, `docs/phase2_alignment.md`, and the current code. Phase 3 builds **on whatever Phases 0 to 2 actually produced**. This plan is written to adapt: Stage 3.0 discovers the real system and section 0.7 tells you exactly what to do for each difference, so you should not need to ask the owner anything.

---

## 0. Rules for the implementing agent

### 0.1 Work mode: fully autonomous
Work through section 7 in order without waiting between stages. For every stage: write its goal and file list at the top of its `STATUS.md` entry; build in small steps; run tests and lint often; the stage is done only when its **Done when** is met and the full suite and lint pass; append the explain-back (0.5); continue.

**The owner wants no approval requests.** Every product decision you might need is pre-decided in section 1.3 or resolved by the adaptation rules in 0.7. If something is still not covered, apply the default rule in 0.2 (soft gate) and keep going.

**Hard gates (the only reasons to stop)**
1. A git command of any kind (0.3). You never run git; you only record proposals.
2. Adding a dependency. Phase 3 needs exactly **one**: the official Model Context Protocol Python SDK (`mcp`), for Stage 3.15 only. The owner pre-approves it by handing over this file. Pin the exact version and check its current documentation before use. Anything else: use the standard library.
3. Anything that costs money, signs up for a service, deploys, or touches files outside the repository.
4. A change that would break an earlier contract: `execute_tool` as the single choke point; append-only audit triggers; integer-paise money; `user_id` on every table; no money-movement tools; user > override > rule > cache > LLM precedence; the advice/narration validators; the planner capability allowlist.
5. A failing test or lint error you cannot fix after an honest attempt. Never weaken, skip, `xfail` or delete a test. Record the blocker, skip only work that depends on it, continue with independent stages, and say so.

When a hard gate is hit, do not wait idle: record it in `STATUS.md` under Blockers and continue with every stage that does not depend on it.

### 0.2 Soft gates: decide, record, continue
- **Uncovered product decision:** choose the most conservative option (quieter, safer, simpler, fewer automatic actions, more visible uncertainty), record it in `docs/open_questions.md` as "Decided: X. Alternative: Y. Why." and continue.
- **Name or structure differs from this plan:** the real code wins; follow 0.7; record the mapping in `docs/phase3_alignment.md`.
- **No Gemini key or quota exhausted:** use the fake provider; mark live checks pending.
- **Small unrelated issue:** one line in `docs/known_issues.md`; do not fix it mid-stage.

### 0.3 Git (two proposed commits, no git commands)
- Do **not** run any git command (not even `status`, `diff` or `log`).
- Two checkpoints: `[GIT CHECKPOINT A]` after Stage 3.9 (all planning features) and `[GIT CHECKPOINT B]` after Stage 3.18 (agentic upgrades and finish). At each: make sure everything passes, write the proposed message and the exact file list under "Proposed commits (awaiting approval)" in `STATUS.md`, and **continue working**. The owner commits when back.
- Messages: A = `Add goals, commitments, buckets, readiness and memory`; B = `Add multi-agent planning, skills, runtime and MCP server`.
- No AI attribution anywhere (commits, docs, code comments): no `Co-Authored-By`, no "Generated with", no session links.
- Never propose committing `.env`, keys, the database, `reports/`, generated data or screenshots.

### 0.4 STATUS.md report (newest stage first)
```
## Current state
Last completed stage: <N> | Blockers: <list or "none">

## Stage N: <name>: DONE / BLOCKED / IN PROGRESS
Goal: <2 to 3 lines>
Built: <2 to 5 bullets>
Files: <list>
Adaptations applied (0.7): <list or "none">
Tests: <passed / total> | Lint: <pass/fail>
Evidence: <real last lines of pytest and ruff, pasted>
Defaults chosen (open_questions.md): <list or "none">
Live checks pending: <list or "none">

## Proposed commits (awaiting approval)
1. <message>: <files>
```

### 0.5 Explain-back
After each stage append 4 to 8 lines to `docs/decisions.md`: what was built, why this design, what it deliberately does not do, and one examiner question with its answer.

### 0.6 Code, honesty and quality rules (all inherited; restated because they are tested)
1. Simple, readable Python; short functions; type hints; docstrings on every public function.
2. **Deterministic code owns financial truth.** The LLM never computes, compares, projects or invents a number, a status, a confidence or a memory.
3. **Every tool call goes through `execute_tool`.** The architecture test that no module imports a tool handler is extended to every Phase 3 module.
4. **Money is integer paise.** `Decimal` for intermediate maths; round half up to paise unless this plan says ceil/floor. Scores and confidences are stored as integer basis points (0 to 10000).
5. **Every new table has `user_id`; every query filters by it.**
6. **All thresholds, weights, horizons and templates live in YAML config**, validated by Pydantic at load.
7. **No money movement.** Buckets, allocations, contributions and plans are logical records only. The no-money-movement test is extended to every new tool.
8. **No investment advice.** Never name, rate, compare or recommend a fund, stock, scheme, platform or broker; never assume or display returns, growth rates, interest or inflation; never predict markets. Investment contributions are modelled only as planned outflows.
9. **Time:** all dates and month boundaries in Asia/Kolkata. Inject the clock (`ExecutionContext.clock` or the real equivalent); no `datetime.now()` in logic.
10. **Test the real path:** every tool has at least one test through `execute_tool`, including its failure path, and audit assertions are made on that path.
11. **Boundary tests on both sides** of every threshold, and a **one-time mutation check** on each safety rule in section 8 (weaken, confirm a test fails, revert; record in `decisions.md`).
12. **Reports quote real output.** Docs state only what tests prove. No marketing language.
13. Windows-safe (`pathlib`, UTF-8 for every file; the ₹ sign must round-trip).
14. Never claim something works unless you ran it.

### 0.7 Adaptation rules (use these instead of asking)
Stage 3.0 fills a table in `docs/phase3_alignment.md` with one row per item below: *expected*, *found*, *action taken*.

| If you find... | Do this |
|---|---|
| Phase 2 `goals` table exists | Extend it by migration (new columns with safe defaults); never recreate it; existing rows stay valid |
| No `goals` table (Phase 2 deviated) | Create it as in section 4 including the Phase 2 minimal columns |
| Phase 2 goal maths (`required_monthly_paise`, `monthly_surplus_estimate`, `goal_status`) exist | Reuse them; do not duplicate. If a needed behaviour differs, add a new function and leave the old one unchanged with its tests |
| Phase 2 simulation engine with a scenario model | Add new scenario kinds through an extension point (a registry or a dispatch table). Existing kinds and their tests must behave identically |
| Simulation engine missing or not extensible | Build the Phase 3 projection on the calendar engine (5.4) and record the gap |
| Phase 0 memory models (`tests/models/test_memory.py` suggests they exist) | Reuse and extend those models for behavioural memory. Do not create a parallel memory system |
| Phase 1 `recurring_series` | Use it as the source of commitment suggestions |
| Phase 1 views `v_balance`, `v_category_totals_month`, budget status | Use them; do not recompute balances another way |
| Phase 2 planner, capability matrix, intents, plan templates, narration validator | Extend them (new intent types, new plan templates, new capability rows, new templates). Never fork them |
| Phase 2 is incomplete (a stage marked BLOCKED or missing) | Build Phase 3 parts that do not depend on it; for dependent parts, implement the deterministic service and tool, skip only the agent wiring, record it in `STATUS.md` |
| An HTTP API layer exists (`src/copilot/api/`, from PLAN_UI) | Add Phase 3 read and write endpoints there, regenerate the OpenAPI schema and TS types, add route tests |
| No API layer | Build services, tools and CLI only; list the needed endpoints in `docs/phase3_api_contract.md` for the UI track |
| Capture-lane tables (ADR-0001: `payment_events`, `capture_labels`) exist | Feed their user labels into behavioural memory as evidence. If absent, do nothing and leave the hook (a function that accepts label evidence) |
| A Phase 3 table name already exists with a different meaning | Prefix the new one with `p3_`, record it |
| A config file named in this plan exists | Merge new keys; never drop existing keys |

### 0.8 LLM-first, deterministic-guarded (overrides any earlier wording in this file)
FinCo must respond dynamically to any user and any phrasing. Hardcoded behaviour is a **fallback**, never the main path. Where this file says "deterministic patterns first", "templates", "closed list" or "plan templates", read it with these rules:

1. **Use the owner's existing LLM router.** Stage 3.0 records its module, providers (Gemini, Groq or others), key pool, rate limiter, retry and budget settings in the alignment doc. Every LLM call goes ContextBuilder (or the existing prompt builder) → router. Never call a provider SDK directly, never add, print, log or commit keys, never bypass the router's limiter.
2. **The LLM is the primary path for understanding and composing:** interpreting the user's request (intent and entities in one structured call), decomposing it into sub-questions and choosing tools or skills, choosing hypotheses to test, composing personalised proposals (scenario options, experiments, challenges) within typed schemas, critiquing drafts, and writing every user-facing sentence.
3. **Deterministic code is the guard and the fallback.** It always owns numbers, statuses, confidences, baselines, eligibility and safety filters, XP, policy and the validation of every LLM output (schema, enums, ids exist and belong to the user, every number traced to findings, forbidden content, capability allowlist). The deterministic path (patterns, plan templates, narration templates) is used only when the router reports no capacity or budget, the LLM output fails validation twice, or in offline and test mode. Every response records `path: llm | fallback` and the reason; `copilot ops` reports the fallback rate.
4. **What "no hardcoding" means here:** no hardcoded answers, user-specific values, merchant or category assumptions, or response text in code. Everything user-specific comes from the user's data and memory. Catalogues (tools, skills, metrics, hypotheses, scenario kinds, challenge families) are **capability registries**: config plus code that computes numbers. The LLM composes them freely per user; it cannot invent a capability that computes numbers, because numbers must come from tested code.
5. **Efficient use of the keys:** one structured call per purpose where possible (intent and entities together; one planning call; one narration call per response, batching all findings); a response cache keyed by purpose, prompt version and a hash of the redacted input (TTL in config); explicit CLI commands with exact arguments skip the LLM entirely (they are already structured); per-task LLM call budget stays enforced; on a 429 or quota error, let the router rotate or back off, and if it reports exhaustion, fall back for the rest of the task instead of retrying.
6. **Testing must not burn the keys:**
   - All unit, integration, golden, property and safety tests use the fake provider (scripted outputs, including adversarial ones). **Zero network calls** by default; a test fails if the real router is reached without the live flag.
   - Live tests are marked `@pytest.mark.live`, skipped unless run with `--live`, and capped by `LIVE_MAX_CALLS` (default 20 per run) through a counter at the router boundary. On the first quota or rate-limit error the live run stops and marks the rest pending; no retry storms.
   - **Record and replay:** live responses are stored as redacted cassettes under `tests/cassettes/` and replayed afterwards, so the same live check never costs twice.
   - Evaluation's LLM-on run uses a fixed small question set (default 25, configurable), each answered once per prompt version and then served from cassettes; never loop live calls across seeds.
7. **Measure both paths:** the evaluation report gives LLM-path quality on the cassette set and fallback quality on the full set. Both must pass every safety check; the fallback may be less flexible but must never be wrong.
8. **If the earlier phases were built deterministic-first,** add a config flag `llm.primary: true` (default true) that switches the order to LLM-first, keep the deterministic path and its tests as the fallback, and record it in the alignment doc.

---

## 1. Phase 3 goal

Roadmap: *"Expand the system from budgeting into broader personal financial planning."*

> FinCo tracks the user's goals and known future obligations, looks ahead on a calendar to show whether current behaviour supports them, lets the user logically split one real balance into purposeful buckets, assesses whether they are ready to start or keep investing (without ever naming a product), plans contributions against competing goals, compares trade-offs side by side, and remembers the user's patterns, exceptions and feedback with confidence that decays as life changes.

### 1.1 Roadmap items and where they land
| Roadmap item | Stage |
|---|---|
| Financial Goals (targets, deadlines, progress, required savings rate, projected completion) | 3.3 |
| Financial Commitments (fees, bills, travel, rent, allowances, recurring contributions) | 3.2 |
| Financial Calendar (look-ahead, does behaviour support commitments) | 3.5 |
| Investment Readiness | 3.6 |
| Contribution Planning (SIP-style contributions vs surplus and goals; no stock-picking) | 3.7 |
| Goal Trade-Off Analysis | 3.7 |
| Behavioural Memory (patterns, contextual exceptions, accepted/rejected advice, preferences) | 3.8 |
| Memory Confidence / Decay | 3.9 |
| Virtual Balance Partitioning (roadmap §3, all seven points) | 3.4 |
| Reusable skills library (agent upgrade) | 3.10 |
| Multi-agent planning: supervisor, parallel specialists, merge, reviewer, Reflexion-style revision (agent upgrade) | 3.11 |
| Context engineering, retrieval and prompt-injection hardening (agent upgrade) | 3.12 |
| Agent runtime (scheduled jobs) and observability (agent upgrade) | 3.13 |
| Bounded feedback learning (agent upgrade) | 3.14 |
| MCP server (agent upgrade) | 3.15 |

### 1.4 Agentic upgrades: what is in, why, and what is deliberately out
Each upgrade is included only because it makes FinCo more reliable, cheaper, safer or more useful for real users. Each also makes a core agent-engineering concept concrete and measurable.

| Upgrade | Real-user value | Concept it makes concrete |
|---|---|---|
| **Skills library** (5.12) | Common multi-step jobs ("can I afford X", "monthly close", "plan a trip") run as tested, versioned procedures instead of improvised tool chains, so answers are consistent | Reusable skills; goal decomposition; planning strategies |
| **Multi-agent planning** (5.13) | Cross-domain questions ("can I take the trip and keep my monthly contribution?") are split into sub-questions answered in parallel by specialists with small, focused context; a reviewer catches gaps before the user sees them; one failed specialist does not sink the answer | Role-based specialisation; supervisor graph; parallel fan-out with merge; fault tolerance; hybrid structured + dynamic orchestration; plan-act-observe-revise |
| **Reflexion-style revision** (5.13) | A wrong or incomplete answer gets one bounded self-correction round; every critique is logged and becomes a regression test candidate | Self-correcting agents; agentic SDLC (failures → evals) |
| **Context engineering and retrieval** (5.14) | Each LLM call gets only the relevant, redacted, budgeted context, with a manifest of what was included and why: lower cost, better answers, provable privacy | Context handling and optimisation; dynamic retrieval; long-term memory retrieval |
| **Prompt-injection hardening** (5.14) | Bank narrations, merchant names, goal names and questions are untrusted text; a merchant called "ignore previous instructions" must not change behaviour | Safety for tool-using agents |
| **Agent runtime** (5.15) | Daily upkeep (rollover, memory refresh, alert evaluation, coverage scan, commitment suggestions) runs on its own, idempotently, with retries and a dead-letter list, so the product works without the user running commands | Long-running agent runtime patterns; failure handling |
| **Observability** (5.15) | Every run is traceable: latency, LLM calls, tokens, failures by type, budget stops; regressions are visible before users feel them | Logging and observability for real-world deployment |
| **Bounded feedback learning** (5.16) | Alerts and advice adapt to what this user finds useful, within hard safety floors, explainably and resettably | Learning agents; reinforcement-learning concepts (bandits, reward from feedback) |
| **MCP server** (5.17) | Users can query their own FinCo safely from MCP-capable assistants, through the same governance and audit | Model Context Protocol; connectors; tool exposure |
| **Orchestration comparison** (Stage 3.16) | Evidence for which orchestration pattern is worth its cost, measured on the same evaluation set | Comparison of orchestration paradigms |

**Deliberately out (record in `docs/learning_agents.md` and `docs/orchestration_paradigms.md`, do not build):**
- **RLHF, RLAIF, DPO:** these train model weights. FinCo does not train models, has no consented preference data at the needed scale, and must not ship user financial data into training. The docs explain how FinCo's approve/reject records *could* form preference pairs in a consented future, and why it does not do so now.
- **AutoGen-style free conversation between agents:** unbounded agent-to-agent chat cannot guarantee that numbers come from deterministic tools, and costs many LLM calls. Explain it in the comparison doc; FinCo uses structured LangGraph orchestration with typed reports.
- **Swarms of many identical agents, vector databases, cloud deployment:** no measured need now; listed as future options.
- **Adding the LangChain library itself:** LangGraph (already used) is the orchestration layer; the extra library adds nothing FinCo needs.

### 1.2 What "approval" means in Phase 3
Two different things, do not confuse them:
- **Owner approval** (the developer): only for git and the hard gates in 0.1.
- **User approval inside the product**: the agent may *draft* commitments, reallocations, memory candidates and recommendations; the *end user* accepts or rejects them through user-actor tools. This is product behaviour you build and test. It never requires stopping work.

### 1.3 Product decisions already made (do not re-open; put the values in config)
| Topic | Decision |
|---|---|
| Goal progress source | Exactly one per goal: `manual` (user-entered current amount), `bucket` (sum of its linked bucket), or `account` (balance of one linked account). Default `manual` |
| Projected goal completion | From the median monthly net contribution over the last `goals.projection_months` (default 3) complete months; needs at least 2 months, else `insufficient_data`; range low/expected/high from min/median/max of those months |
| Emergency fund target | `readiness.emergency_months_target` × essential monthly spend; default 3 months (range allowed 1 to 12) |
| Essential categories | Config list with user override; defaults: rent/housing, groceries, utilities, education fees, transport, health, insurance premiums, loan EMIs if present |
| Calendar horizon | Default 60 days, maximum 180 |
| Calendar buffer | `calendar.min_buffer_paise`, default ₹1,000 (100000 paise) |
| Bucket rollover | Spending buckets reset monthly (unspent returns to unallocated); goal buckets accumulate; commitment buckets accumulate until the commitment is paid, then the paid amount is released |
| Over-allocation | Allowed (balances move without our control) but always flagged as "over-allocated by ₹X"; never blocks |
| Category to bucket | At most one spending bucket per category |
| Contribution waterfall order (default, user can reorder) | 1 firm commitments → 2 essential spend → 3 emergency fund up to `readiness.emergency_min_months` (default 1 month) → 4 goals by user priority → 5 planned investment contributions → 6 discretionary |
| Returns, interest, inflation | Never modelled. Contributions are outflows; balances never grow by assumption |
| Advice suppression | After the user rejects an advice kind for a subject, do not draft the same kind for that subject for `memory.advice_cooldown_days` (default 30) |
| Memory thresholds (basis points) | use ≥ 6000; stale < 4000; retire < 2000 |
| Memory half-lives (days) | recurring_pattern 90; contextual_exception 365; advice_feedback 120; merchant_habit 180; user-stated preference: no time decay |
| Readiness thresholds | In section 5.6; all in config |
| Commitment suggestions | The agent drafts commitments from recurring series; they become active only when the user accepts them |

---

## 2. Design principles for Phase 3

1. **Logical, never physical.** Buckets, allocations, contributions and plans are numbers in our database. Nothing is moved, locked or reserved at a bank.
2. **Derived over stored.** Bucket spend, goal progress from buckets/accounts, calendar projections, readiness and memory confidence are computed from source records on demand. Store only user decisions and evidence: allocations, commitments, goals, memory evidence.
3. **One projection engine.** The calendar's daily projection is the single forward-looking engine for Phase 3. Trade-offs, contribution plans and commitment coverage all run through it (or through the extended Phase 2 simulator, per 0.7), so every number agrees everywhere.
4. **Explain every verdict.** Each status (on track, at risk, covered, ready) comes with the criteria, the numbers and "what would change it", built by deterministic templates.
5. **Planning, not advice on products.** FinCo talks about amounts, dates, buffers and the user's own priorities. Never about instruments.
6. **Memory is the user's.** Every memory is visible, explainable (with evidence), editable and forgettable. Observed memories start as candidates and must earn confidence. The LLM never writes memory.
7. **Uncertainty stays visible.** `insufficient_data`, `unknown`, `estimated` and ranges are first-class outputs everywhere.
8. **Agent drafts, user decides.** Every agent-originated change to plans (commitments, reallocations, memories used in advice) is a draft until the user accepts it.

---

## 3. Stack
One new dependency: the official MCP Python SDK (`mcp`), pre-approved, Stage 3.15 only. Reuse LangGraph (including its parallel branch / fan-out support and subgraphs; check the installed version's docs), the owner's existing LLM router (fake provider in tests; see 0.8), Typer, Rich, Jinja2, Hypothesis and the existing config loader. No tokenizer, vector database, AutoGen or LangChain packages.

---

## 4. Data model additions

Numbered migrations after the last existing one; idempotent; each in a transaction; `user_id`, foreign keys and simple `CHECK` constraints on everything. Extend `audit_events.event_type` constraints if they exist; never relax append-only triggers.

| Table | Key columns |
|---|---|
| `goals` (extend or create, see 0.7) | add: `progress_source` (`manual`/`bucket`/`account`), `linked_account_id` (nullable), `start_date`, `target_date` (if Phase 2 named it `deadline`, keep that name), `essential` (bool, for emergency fund), `notes` |
| `goal_contributions` | `goal_id`, `amount_paise` (signed: negative = withdrawal), `occurred_on`, `source` (`manual`/`bucket_allocation`/`account_delta`), `ref_id`, `created_at`. Logical records; for `manual` goals only. Bucket and account goals derive contributions |
| `commitments` | `name`, `direction` (`outflow`/`inflow`), `kind` (`fee`/`bill`/`rent`/`travel`/`allowance`/`income`/`subscription`/`emi`/`investment_contribution`/`goal_contribution`/`other`), `category_id`, `amount_paise` (nullable if ranged), `amount_min_paise`, `amount_max_paise`, `certainty` (`firm`/`estimated`), `schedule_kind` (`once`/`weekly`/`monthly`/`yearly`/`every_n_days`), `schedule_json` (for example `{"day": 5}`, `{"date": "2026-11-20"}`, `{"n": 14, "anchor": "..."}`), `start_date`, `end_date` (nullable), `recurring_series_id` (nullable), `goal_id` (nullable), `bucket_id` (nullable), `source` (`user`/`suggested`), `status` (`draft`/`active`/`paused`/`ended`/`rejected`), `created_at`, `updated_at` |
| `commitment_matches` | `commitment_id`, `due_date`, `txn_id`, `match_method` (`series`/`amount_date`/`manual`), `confidence_bp`. Links occurrences to real transactions |
| `buckets` | `name`, `kind` (`spending`/`goal`/`commitment`/`flexible`), `period_policy` (`reset_monthly`/`accumulate`), `goal_id` (nullable), `commitment_id` (nullable), `status` (`active`/`archived`), `sort_order`, `created_at` |
| `bucket_categories` | `bucket_id`, `category_id`; unique (`user_id`, `category_id`) so a category maps to at most one spending bucket |
| `bucket_allocations` | append-only ledger: `bucket_id`, `amount_paise` (signed), `kind` (`allocate`/`release`/`reassign_in`/`reassign_out`/`rollover`/`adjust`), `period` (`YYYY-MM`), `pair_id` (links the two halves of a reassignment), `source` (`user`/`approved_draft`/`system_rollover`), `draft_id` (nullable), `created_at` |
| `reallocation_drafts` | `from_bucket_id`, `to_bucket_id`, `amount_paise`, `reason_json`, `simulation_id` (nullable), `status` (`draft`/`approved`/`rejected`/`applied`/`expired`), `created_at`, `decided_at`, `applied_at` |
| `readiness_assessments` | `run_id`, `assessed_on`, `level`, `criteria_json`, `numbers_json`, `config_version`. An explanation record, append-only by convention |
| `contribution_plans` | `run_id`, `period_from`, `horizon_months`, `waterfall_json`, `result_json`, `assumptions_json`, `created_at` |
| `tradeoff_analyses` | `run_id`, `alternatives_json`, `results_json`, `assumptions_json`, `created_at` |
| `memory_items` (extend Phase 0 memory if present) | `kind` (`recurring_pattern`/`contextual_exception`/`advice_feedback`/`preference`/`merchant_habit`), `subject_key` (for example `category:dining`, `merchant:<normalized>`, `advice_kind:reduce_spend|category:dining`, `global`), `statement_json` (structured, never free prose), `source` (`observed`/`user_stated`/`feedback`/`capture_label`), `status` (`candidate`/`active`/`stale`/`retired`/`rejected`/`forgotten`), `prior_bp`, `created_at`, `last_evidence_at`, `last_confirmed_at`, `user_confirmed` (bool) |
| `memory_evidence` | `memory_id`, `polarity` (`supports`/`contradicts`), `ref_kind` (`txn`/`advice`/`audit_event`/`anomaly`/`investigation`/`capture_label`), `ref_id`, `observed_at`, `weight_bp` |
| `user_preferences` (if not present) | `key`, `value_json`, `updated_at`; holds waterfall order, essential-category overrides, emergency months target, calendar buffer |
| `skill_runs` | `task_id`, `skill_name`, `skill_version`, `inputs_json`, `status`, `outputs_json`, `started_at`, `finished_at` |
| `specialist_reports` | `task_id`, `agent_role`, `sub_question_json`, `status` (`ok`/`partial`/`failed`/`timeout`), `findings_json`, `gaps_json`, `error_code`, `duration_ms` |
| `reflections` | `task_id`, `round`, `critique_codes_json` (closed set), `source` (`deterministic`/`llm_critic`), `revised` (bool), `outcome` (`fixed`/`unchanged`/`gave_up`), `created_at` |
| `context_manifests` | `call_id`, `task_id`, `purpose`, `budget_tokens`, `estimated_tokens`, `included_json` (source, id, reason, estimated tokens), `excluded_json` (source, id, reason), `redactions_count`, `prompt_version`, `created_at` (never the prompt text itself) |
| `trace_spans` | `trace_id` (= run or task id), `span_id`, `parent_span_id`, `kind` (`node`/`tool`/`llm`/`job`/`skill`/`specialist`/`mcp`), `name`, `started_at`, `duration_ms`, `status`, `error_code`, `attrs_json` (counts, model, prompt version, tokens in/out estimates; never user text) |
| `scheduled_jobs` | `job_kind`, `schedule` (`daily@HH:MM` IST or `every_N_minutes`), `next_run_at`, `lease_owner`, `lease_until`, `last_status`, `consecutive_failures`, `enabled` |
| `job_runs` | `job_id`, `started_at`, `finished_at`, `status` (`ok`/`failed`/`skipped`/`dead_letter`), `attempt`, `error_code`, `summary_json` |
| `feedback_stats` | `subject_kind` (`alert_kind`/`advice_kind`), `subject_key`, `alpha_milli`, `beta_milli` (integers, thousandths), `updated_at`; the learned state, resettable |

Notes:
- **Forgetting:** `forget_memory` clears `statement_json` and evidence rows' details, sets `status = forgotten`, and writes an audit event without the content. Audit stays append-only; no content of a forgotten memory remains queryable.
- No table stores bucket spend, goal progress from buckets/accounts, calendar results or memory confidence; these are derived (2.2). `readiness_assessments`, `contribution_plans` and `tradeoff_analyses` are explanation snapshots, never inputs to other calculations.

---

## 5. Key designs

### 5.1 Commitments and the occurrence engine
**Pure functions:**
- `expand_occurrences(commitment, window_from, window_to) -> list[Occurrence]`: every due date in the window (IST). Rules: `monthly` with day 29 to 31 falls on the last day of shorter months; `yearly` on 29 February falls on 28 February in non-leap years; `every_n_days` anchored at `schedule_json.anchor`; respects `start_date`/`end_date`; `paused` produces none. `Occurrence` has `due_date`, `amount_low/expected/high` (firm: all equal; estimated: min/mid/max, with mid rounded half up), `direction`.
- `match_occurrences(occurrences, transactions)`: links a past occurrence to a transaction by (1) its `recurring_series_id`, else (2) same direction, amount within `commitments.amount_tolerance_bp` of expected, date within `commitments.date_tolerance_days`, category match preferred. One transaction matches at most one occurrence. Status per occurrence: `paid`, `partially_paid` (amount below low bound), `overdue` (past due + tolerance, no match), `upcoming`.

**Suggestions:** `suggest_commitments()` turns each active `recurring_series` (Phase 1) without a linked commitment into a `draft` commitment (`source = suggested`, `certainty` firm if amount variance within tolerance else estimated with min/max from history). Incoming recurring series (salary, allowance) become `inflow` drafts. Drafts never affect projections until `accept_commitment` (user actor) activates them.

**Tools:** `create_commitment`, `update_commitment`, `pause_commitment`, `end_commitment`, `accept_commitment`, `reject_commitment` (user actor: allow; agent: approval required; never planner-selectable); `list_commitments`, `get_commitment_status` (read; planner-selectable); `suggest_commitments` (agent allowed; writes drafts only).

### 5.2 Goals (full)
Extend the Phase 2 minimal goal model:
- `goal_progress(goal, today) -> GoalProgress` with `current_paise` from its single `progress_source`: `manual` = `current_paise` field + sum of `goal_contributions`; `bucket` = derived bucket balance (5.3); `account` = derived balance of `linked_account_id`.
- `remaining_paise = max(0, target - current)`; `percent_bp = min(10000, current * 10000 // target)` (target > 0 enforced by `CHECK`).
- `required_monthly_paise`: reuse Phase 2 (ceil).
- `monthly_contribution_history(goal, months)`: per complete IST month, net contribution (manual: sum of contributions; bucket: net allocations to the bucket; account: month-end balance delta, transfers in/out included).
- `projected_completion(goal)`: if remaining is 0 → `completed`; else with history of at least 2 months: for each of low/median/high monthly contribution `c > 0`, months_needed = ceil(remaining / c), completion = add months to the current month end; `c ≤ 0` → `never_at_current_pace`; fewer than 2 months → `insufficient_data`.
- `goal_feasibility`: compare `required_monthly_paise` with the contribution range and with the calendar's projected surplus (5.4): `on_track` / `at_risk` / `off_track` / `unknown`, using the same rule as Phase 2 so statuses never disagree.
- Tools: `record_goal_contribution` (user), `get_goal_progress`, `list_goals` (read, planner-selectable). Existing `create_goal`/`update_goal` gain the new fields.

### 5.3 Virtual buckets (roadmap §3)
**Balances (derived, per period `YYYY-MM`):**
- `allocated(bucket, period)` = sum of `bucket_allocations.amount_paise` for that bucket up to and including the period, respecting the period policy: `reset_monthly` buckets only count the period's own allocations plus nothing carried; `accumulate` buckets count all periods.
- `spent(bucket, period)` = sum of debit amounts of transactions in the period whose category maps to the bucket via `bucket_categories`, excluding transfers and duplicates, minus matching refunds. **Derived from transactions**, so a recategorisation automatically moves spend between buckets (roadmap: "allow manual reassignment when categorisation is disputed"). Commitment buckets count transactions matched to their commitment.
- For `accumulate` buckets, `spent` is likewise cumulative over all periods since the bucket was created; for `reset_monthly` buckets it is the period's spend only.
- `balance = allocated - spent`. Negative means **depleted** (roadmap: overspend detection).
- `reserved_total = sum(max(0, balance))` across active buckets; `liquid_balance` from the Phase 1 balance view over deposit accounts; `available_unallocated = liquid_balance - reserved_total` (may be negative → `over_allocated_by = -available_unallocated`).
- **Month rollover** (`rollover_buckets(period)`, idempotent, run lazily when a new period is first read): for `reset_monthly` buckets, the closing period's unspent balance is released by a `release` row dated in the **closing** period (`source = system_rollover`), so the closed month ends at zero and the new month starts from its own allocations only; a depleted (negative) bucket is not "released" and its overspend stays visible in the closed month; for `accumulate` buckets nothing changes. Running it twice for the same period writes nothing new (tested).

**Overspend detection:**
- `bucket_status`: `ok` / `low` (balance below `buckets.low_threshold_bp` of allocated) / `depleted`.
- `would_exceed(bucket, amount_paise)` pure check, used by alerts and later by the capture lane (ADR-0001).
- A depleted bucket becomes a new **signal** for Phase 2 adaptive alerts (add it through the alert signal extension; weights in config).

**Reallocation drafts (agent may recommend, user approves):**
- `draft_reallocation(from, to, amount)` (agent allowed) writes a `reallocation_drafts` row with a reason and, when it changes a goal or commitment outcome, a linked simulation (Phase 2 consequence rule).
- The user decides with `decide_reallocation(draft_id, approve|reject)` and applies with `apply_reallocation(draft_id)` (both user actor). Keep the Phase 1 rule that approving a recommendation performs no action: **apply is a separate explicit user action**, which writes the paired `reassign_out`/`reassign_in` rows. The UI may later show "Approve and apply" as one button that calls both, with that label.
- Drafts expire after `buckets.draft_ttl_days`.

**Tools:** `create_bucket`, `update_bucket`, `archive_bucket`, `map_category_to_bucket`, `allocate_to_bucket`, `release_from_bucket`, `reassign_between_buckets` (all user actor; agent requires approval; never planner-selectable); `list_buckets`, `get_bucket_status`, `get_allocation_summary` (read; planner-selectable); `draft_reallocation` (agent allowed, drafts only).

**Invariant tests:** allocations never change any transaction or balance table; recategorising a transaction moves its spend from one bucket to the other with totals conserved; reassignment rows always come in matched pairs summing to zero; `available_unallocated + reserved_total == liquid_balance` exactly.

### 5.4 Financial calendar (the projection engine)
`build_calendar(today, horizon_days) -> Calendar`:
1. **Start:** `liquid_balance` today (deposit accounts).
2. **Known flows:** all active commitment occurrences in the window (outflows negative, inflows positive), with low/expected/high amounts. Goal contributions planned via `goal_contribution` commitments are included; others are not assumed.
3. **Variable spend:** daily variable spend from Phase 1 forecast v2's variable run-rate (expected), with low/high from its range, **excluding** categories already covered by commitments in that window (prevents double counting rent, fees, subscriptions). If the forecast is `insufficient_data`, the calendar still shows known flows and marks the variable part `unknown`.
4. **Daily projection:** for each day, three running balances: *expected* (expected flows), *low* (high outflows, low inflows), *high* (low outflows, high inflows). Integer paise throughout.
5. **Coverage per outflow occurrence:** `covered` if the low balance on the due date (after the payment) ≥ `min_buffer_paise`; `at_risk` if only the expected balance is; `not_covered` if neither; `unknown` if the variable part is unknown and the expected balance after known flows alone is below the buffer.
6. **Shortfall days:** days where the low balance < buffer, grouped into ranges with the lowest point and the commitments due in them.
7. **Reconciliation invariant (tested):** for the current month, expected variable spend summed over the remaining days equals Phase 1 forecast v2's expected variable figure within one rupee of rounding; known commitments equal their occurrences' totals.

**Tools:** `get_calendar(horizon_days)`, `check_commitment_coverage(commitment_id|date)` (read; planner-selectable).

### 5.5 Scenario extension (for contributions and trade-offs)
Per 0.7, add new scenario kinds to the Phase 2 simulator through an extension point, or implement them on the calendar engine if the simulator cannot be extended:
- `change_contribution(commitment_id, new_amount)` (including pausing as amount 0 for N months)
- `add_commitment(spec)` / `remove_commitment(id)`
- `shift_goal_date(goal_id, new_date)`
- `allocate_to_bucket(bucket_id, amount_per_month)`
Invariants (property tests, as in Phase 2): zero-change scenario equals the baseline exactly; more outflow never improves any metric; scenarios never write financial tables.

### 5.6 Investment readiness (assessment only)
`assess_readiness(today) -> Readiness` with criteria, each `pass` / `fail` / `unknown` with numbers and a "what would change it" line:
| Criterion | Rule (config values in `readiness.yaml`) |
|---|---|
| Enough history | at least `min_history_months` (default 3) complete months of data, else every other criterion is `unknown` |
| Positive cash flow | net surplus (income − spend, transfers excluded) positive in at least `positive_months_required` (default 2) of the last 3 months |
| Stable cash flow | coefficient of variation of monthly net surplus ≤ `max_cv_bp` (default 5000 = 0.5), computed with `Decimal`; `unknown` if mean ≤ 0 |
| Emergency reserve | emergency fund (goal with `essential = true`, or the emergency bucket, or `user_preferences` declared reserve) ≥ `emergency_months_target` × essential monthly spend (median of last 3 months over essential categories) |
| Obligations covered | every firm outflow commitment in the next `obligation_window_days` (default 90) is `covered` in the calendar |
| Priority goals on track | every goal with priority 1 is `on_track` or `completed` |
| Declared high-cost debt | `user_preferences.high_cost_debt` is not `true`; `unknown` if never declared (the system never infers debt) |

Level: `not_ready` (any of positive cash flow, emergency reserve or obligations `fail`), `building` (those pass but stability or priority goals fail), `ready_with_conditions` (all pass except unknowns), `ready` (all pass). `insufficient_data` when history is short.

**Language:** templated only; no product, asset class, return or market statement. Validator test: every readiness template passes the forbidden-content check. Input-gate refusals for "which fund/stock should I buy", "will the market go up" are re-tested here.

**Tools:** `assess_investment_readiness` (compute; planner-selectable; writes an explanation snapshot).

### 5.7 Contribution planning and trade-off analysis
**Contribution plan** (`plan_contributions(horizon_months)`), per month in the horizon:
1. Expected and low **inflows** (calendar).
2. Waterfall in the user's order (default from 1.3): each step takes `min(remaining, need)`, where needs are firm commitments, essential spend (median, range), emergency top-up until the minimum months, goals by priority (`required_monthly_paise`), planned investment contributions (`investment_contribution` commitments), discretionary (rest).
3. Output per step: needed, funded (expected and low cases), shortfall. Verdict for each planned contribution: `fits` (funded in the low case), `fits_expected_only`, `does_not_fit`.
4. **Options when something does not fit** (at most 3; proposed by the LLM as typed scenario specs from the registered scenario kinds, validated and then evaluated deterministically; the deterministic generator below is the fallback and the minimum set): reduce that contribution to the fundable amount; pause it for N months until the emergency minimum is reached; move a lower-priority goal's date. Each option is evaluated as a scenario (5.5) and attached to a draft recommendation with its simulation. **No option is ever "invest in X"**; amounts and dates only.

**Trade-off analysis** (`compare_tradeoffs(alternatives[<=3])`): each alternative is a set of scenario changes over a horizon (default 12 months, max 24). Metrics per alternative, all from the projection engine: completion date per goal (or `never_at_current_pace`), emergency coverage in months at horizon end, number of `not_covered` commitments, lowest projected low balance and its date, shortfall days, total planned contributions made (a plain sum; **no growth**). The result names which alternatives satisfy all the user's hard constraints (no `not_covered` firm commitment, emergency minimum kept); it does not pick a "best" one unless exactly one satisfies all constraints, and then it says so in those words.

**Tools:** `plan_contributions`, `compare_tradeoffs` (compute; planner-selectable; write explanation snapshots).

### 5.8 Behavioural memory
**What can become a memory** (deterministic observers; each produces candidates with evidence):
| Kind | Observer rule (config) | Example statement_json |
|---|---|---|
| `recurring_pattern` | category or merchant spend shows a stable shape over ≥ `min_weeks` weeks (weekend vs weekday ratio ≥ x, month-start concentration ≥ y, payday spike) | `{"category":"dining","pattern":"weekend_heavy","ratio_bp":21000}` |
| `contextual_exception` | user dismisses an anomaly or alert with a reason, or marks a transaction "one-off" | `{"category":"gifts","period":"2026-11","reason":"festival"}` |
| `advice_feedback` | user approves or rejects an advice kind for a subject | `{"advice_kind":"reduce_spend","subject":"category:dining","decision":"rejected"}` |
| `preference` | user-stated settings (waterfall order, quiet categories, emergency target) | `{"key":"waterfall_order","value":[...]}` |
| `merchant_habit` | user corrections or capture labels for a merchant (Phase 1 overrides, ADR-0001 labels if present) | `{"merchant":"<normalized>","category":"groceries"}` |

**Rules:**
- Observed memories start as `candidate`; they become `active` when confidence ≥ the use threshold, or immediately when the user confirms one.
- **Only structured statements.** Never store free text from the user beyond a short reason label chosen from a list (`festival`, `travel`, `one_off_purchase`, `medical`, `family_event`, `other`); never store inferred personal attributes; never infer health, religion or similar from spending. (`medical` is a user-chosen reason label only, used for exceptions, never generalised.)
- **Where memory is used** (only `active` items, and every use is recorded in the consumer's `memories_json`):
  - Phase 2 **alerts**: an active contextual exception for the same category and period damps the alert score (weight in config), and the alert's why-text says so.
  - Phase 2 **investigations**: add catalogue hypothesis `known_exception` (code + tests): supported when an active exception covers the subject.
  - **Advice drafting**: rejected advice kinds for a subject are suppressed during the cooldown; approved kinds are not boosted (no reinforcement loops).
  - **Guess ranking and categorisation**: merchant habits feed the existing override/rule precedence only through existing mechanisms; memory never overrides a user choice.
- **Tools:** `list_memories`, `explain_memory(id)` (read; planner-selectable, returns structured statements and evidence counts, never other users' data); `confirm_memory`, `reject_memory`, `edit_memory_statement` (bounded fields only), `forget_memory` (user actor; never planner-selectable); `refresh_memories` (agent allowed; runs observers and recomputes statuses; idempotent for the same clock).

### 5.9 Memory confidence and decay (deterministic, documented)
For memory `m` at time `now`:
```
support      = sum of weight_bp of supporting evidence     (capped at support_cap_bp)
contradict   = sum of weight_bp of contradicting evidence
evidence_bp  = clamp(prior_bp + k_s * support - k_c * contradict, 0, 10000)
age_days     = days between last_evidence_at (or last_confirmed_at, whichever is later) and now
decay        = 0.5 ** (age_days / half_life_days[kind])        (computed with Decimal; user-stated preferences: decay = 1)
confidence   = floor(evidence_bp * decay)
```
Status rules: `active` if confidence ≥ use threshold (or user-confirmed and not contradicted); `stale` if below the use threshold but ≥ retire threshold; `retired` if below the retire threshold, or if `contradict ≥ support` with at least `min_contradictions` items. A user-confirmed memory that becomes contradicted is **not** auto-retired; it becomes `stale` and is surfaced as "Still true?" for the user. Conflicting active memories on the same subject and key: the higher confidence wins for use; both stay visible; the conflict is listed.

Tests: exact values at chosen ages (0 days, one half-life, two half-lives); boundary at each threshold; drift scenario (habit changes mid-history → old pattern becomes stale within the expected number of days, new one becomes active); same clock → same result; Hypothesis property: confidence never increases with age alone, never exceeds 10000, never negative.

### 5.10 Agent integration (extend Phase 2, never fork)
- **New intent types:** `goal_progress`, `commitment_check` ("can I pay the fees on the 5th?"), `calendar_lookahead`, `bucket_status`, `investment_readiness`, `contribution_check`, `tradeoff_compare`, `affordability` ("can I afford a ₹30,000 laptop next month?"), `trip_planning`, `memory_query` ("what do you know about my spending?"). Patterns in the intent config; at least 8 labelled examples per new type.
- **Plan templates** for each new type with the minimal tool or skill set (5.12); minimality tests as in Phase 2. Multi-domain types route to the multi-agent subgraph (5.13).
- **Capability matrix rows** for every new tool. Planner-selectable: only `read`/`compute` tools named as planner-selectable in section 5. Every write tool: not selectable.
- **Narration templates** for every new finding kind (`goal_progress`, `commitment_coverage`, `calendar_shortfall`, `bucket_status`, `readiness`, `contribution_plan`, `tradeoff_result`, `memory_used`), all passing the Phase 2 validator; numbers must come from these findings.
- **Refusals** extended: "which SIP/fund/stock", "how much will my SIP grow", "move money to my savings" → typed refusal with what FinCo can do instead.
- **Timeline**: new entries for commitments, allocations, reallocation drafts, readiness, plans, trade-offs, memory creation/confirmation/retirement/forgetting (forgotten items appear without content).

### 5.11 CLI (and API if present, per 0.7)
All through services and `execute_tool`, all read commands with `--json`:
| Command | Does |
|---|---|
| `copilot goals add/list/show/update/contribute/progress` | goals with progress, required monthly, projected completion |
| `copilot commitments add/list/show/pause/end/suggest/accept/reject` | commitments and drafts |
| `copilot calendar [--days 60]` | look-ahead with coverage and shortfall ranges |
| `copilot buckets list/create/map/allocate/release/reassign/status` | virtual buckets and the reserved vs available summary |
| `copilot reallocations list/decide/apply` | agent drafts |
| `copilot readiness` | investment readiness with criteria |
| `copilot contributions plan [--months 6]` | waterfall and fit verdicts with options |
| `copilot tradeoff --alt "<spec>" --alt "<spec>"` | side-by-side comparison |
| `copilot memory list/explain/confirm/reject/forget/refresh` | behavioural memory |
| `copilot prefs show/set` | waterfall order, essential categories, emergency target, buffer |
| `copilot skills list/show/run <name>` | skills library |
| `copilot jobs list/run-due/run <kind>/dead-letter/retry <id>` | agent runtime; `agentd` loop |
| `copilot agentd [--interval 60]` | foreground runtime loop (Ctrl+C to stop); Windows-friendly, no cron needed |
| `copilot ops [--since 7d]` | observability report |
| `copilot trace <task_or_run_id>` | extended: spans, specialists, reflections, context manifests |
| `copilot learning show/reset [--subject ...]` | learned feedback state |
| `copilot mcp-serve` | MCP server over stdio |

### 5.12 Skills library
A **skill** is a named, versioned, tested procedure that composes tools, with a manifest in `config/skills/<name>.yaml`:
```
name: affordability_check
version: 1
description: Can the user afford a one-off or recurring spend without breaking commitments or priority goals?
inputs: {amount_paise: required, category_id: optional, date: optional, recurring_months: optional}
preconditions: [has_transactions]          # checked deterministically; failing → typed "cannot run" with reason
steps:                                       # each step = a planner-selectable tool via execute_tool
  - get_calendar: {horizon_days: 60}
  - run_whatif: {kind: add_spend, amount_paise: $amount_paise, ...}
  - check_commitment_coverage: {window: 60}
  - evaluate_goal_impact: {amount_paise: $amount_paise}
outputs: [finding kinds produced]
narration_template: affordability_v1
eval_cases: tests/skills/affordability_check/
```
Required skills (at least): `affordability_check`, `monthly_close` (rollover, refresh memories, alerts, monthly review), `trip_planning` (goal + bucket + calendar + trade-off), `contribution_review`, `explain_month_change` (wraps the Phase 2 investigation).
Rules: steps may only reference planner-selectable tools; a skill never writes anything except explanation records and drafts; the skill runner is a thin executor of steps (no logic hidden in YAML: conditions are limited to a small documented set such as `if_status`, `if_missing`); each skill has at least 3 eval cases and a golden test; skills appear in the capability matrix as `compute`. The Phase 2 planner gains the option to select **a skill** as a single plan step (validated like a tool). Plan templates for intents that map cleanly to a skill must use the skill.

### 5.13 Multi-agent planning (supervisor, specialists, merge, reviewer, revision)
Used **only** for multi-domain intents (`affordability`, `tradeoff_compare`, `contribution_check`, `trip_planning`, and any intent whose decomposition yields at least two domains). Single-domain intents keep the Phase 2 single loop. A test asserts the routing rule.

**Graph** (LangGraph, as a subgraph called from the Phase 2 agent graph):
```
supervisor/decompose ─► fan-out (parallel) ─► CashflowAgent   ─┐
                                          ├► GoalsAgent       ─┤
                                          ├► ReadinessAgent   ─┼─► merge ─► reviewer ─► (revise ≤1) ─► synthesize ─► review interrupt
                                          └► BehaviourAgent   ─┘
```
- **Supervisor / decompose:** turns the intent into typed `SubQuestion`s (domain, question kind, parameters) primarily by an LLM call (0.8) that proposes sub-questions from the registered question kinds (each kind maps to a specialist), with parameters drawn from the request and the user's data. The proposal is validated like a plan (Phase 2 validator rules: known kinds, valid parameters, ids belong to the user, required coverage of the intent). The decomposition templates in `config/decomposition.yaml` are the fallback and the coverage reference. Maximum sub-questions per task in config (default 4).
- **Specialists** (roles, each a subgraph with its own allowed tool subset from the capability matrix and its own small state slice):
  | Role | Tools allowed |
  |---|---|
  | CashflowAgent | calendar, commitments, forecast, coverage, what-if |
  | GoalsAgent | goals, buckets, allocation summary, trade-offs |
  | ReadinessAgent | readiness, contribution plan |
  | BehaviourAgent | memory (read), anomalies, investigations |
  Each returns a typed `SpecialistReport` (findings with ids, evidence, confidence label, gaps, status). Specialists never talk to each other and never see each other's state: coordination happens only through the supervisor and the merge step.
- **Parallel execution and fault tolerance:** specialists run in parallel branches; each has a timeout and step budget (config). A failure or timeout yields a report with `status = failed/timeout` and an error code; the merge **continues with partial results** and the final answer states plainly what could not be checked. Retries: one retry for transient tool errors only.
- **Merge:** deterministic. Combines findings; detects contradictions (two specialists reporting different values for the same quantity, which must never happen because they share engines) and records any as an audited `merge_conflict` error with both values, then excludes the conflicting finding from narration.
- **Reviewer (critic):** deterministic checks first: every sub-question answered or explicitly marked as a gap; narration validator passes; causal-claim and consequence rules pass; confidence labels present. Then an optional LLM critic that may only return codes from a closed set (`missed_subquestion`, `unclear_answer`, `unsupported_claim`, `missing_caveat`, `ok`); it can never introduce or change numbers.
- **Revision (Reflexion-style):** if any critique code other than `ok` is present and `round < max_revision_rounds` (default 1), the supervisor re-runs only the affected sub-questions or re-synthesises with the critique as structured input. Every critique and its outcome is stored in `reflections`.
- **Learning from failures (agentic SDLC, not self-modification):** `copilot ops failures --export` writes tasks with `gave_up`, `merge_conflict`, budget stops or validator fallbacks into `eval/candidates/` as draft golden cases (inputs and expected-behaviour placeholders). The agent never rewrites its own prompts, templates or rules at runtime; promoting a candidate to a test is a development task.

### 5.14 Context engineering, retrieval and injection hardening
- **ContextBuilder:** the only way to build an LLM prompt. Inputs: purpose (intent extraction, planning, narration, critique), a token budget per purpose (config), and typed sources (intent, findings, sub-question, relevant memories, category list, tool or skill catalogue slice). It ranks sources by a fixed priority per purpose, includes items until the budget is reached, and records a `ContextManifest` (included and excluded items with reasons and estimated tokens). Token estimate: the SDK's token-count function if available, otherwise a documented character-based estimate. Redaction runs inside the builder.
- **Memory retrieval:** score = subject match (exact 3, parent category 2, global 1) × confidence × recency weight; top-k per purpose (config); only `active` memories; ties broken by id for determinism. No embeddings in Phase 3 (record the decision; keyword and subject matching is enough for structured memory).
- **Injection hardening:** all text that came from banks, merchants or the user (narrations, merchant names, goal and bucket names, notes, the ask text) is passed only inside a clearly delimited JSON data field, never concatenated into instructions; prompts state that data fields are untrusted and never instructions. Defence relies on validation, not on the model obeying: every LLM output is schema-validated, enum-constrained and policy-checked, so an "obeyed" injection can only produce a rejected output. **Adversarial corpus** (`tests/security/injection/`): narrations, merchant names, goal names and ask texts containing instructions, fake tool calls, JSON breakouts and "you are now an admin"; with the fake LLM scripted to *comply* with the injection, assert that categories stay within the enum, plans with write tools are rejected, no extra data appears in outputs, and audit records the rejection.

### 5.15 Agent runtime and observability
- **Runtime:** `scheduled_jobs` with job kinds `rollover_buckets`, `refresh_memories`, `evaluate_alerts`, `coverage_scan`, `suggest_commitments`, `expire_drafts`, `monthly_close` (via the skill). `copilot jobs run-due` runs everything due once (usable from Windows Task Scheduler); `copilot agentd` loops in the foreground. Each job: lease-based locking (no double run), idempotent for the same period, retries with exponential backoff up to `max_attempts`, then `dead_letter` with the error code; heartbeat timestamp; every run audited and traced. All jobs use `actor = agent` and go through `execute_tool`; none can perform user-actor writes.
- **Tracing:** a small span API (`with span(kind, name, attrs):`) used by nodes, tools, skills, specialists, LLM calls, jobs and MCP calls; spans stored in `trace_spans` and exportable as JSON Lines. Attributes are counts, ids, codes, model and prompt version, durations and token estimates. **Never** user text, merchant names or amounts beyond aggregates.
- **`copilot ops`:** p50/p95 latency per node and per skill; LLM calls and estimated tokens per task (and estimated cost if the owner fills `ops.price_per_1k_tokens`, otherwise "not configured"); failure counts by error code; budget stops; validator fallback rate; critic catch rate and revision success rate; job success and dead-letter counts; parallel speed-up (sum of specialist durations ÷ wall time).

### 5.16 Bounded feedback learning
A small, explainable learner, not a model trainer:
- **Signal:** for each alert kind × category and each advice kind × subject: *useful* = acknowledged, acted on (for example a reallocation applied after the alert) or approved; *not useful* = dismissed without reason or muted. Dismissals with a contextual reason (`festival`, `travel` ...) go to memory as exceptions instead, not to learning.
- **State:** a Beta posterior per subject in `feedback_stats` (prior from config, for example α = β = 2), stored as integers in thousandths.
- **Use:** posterior mean `p` → sensitivity multiplier `m = clamp(1 + η × (2p − 1), m_min, m_max)` (defaults η = 0.5, range 0.5 to 1.5) applied to the alert score; advice drafts are ordered by `p` within a response.
- **Hard floors (tested):** alerts for `exceeded` budgets, `not_covered` firm commitments and goal moves to `off_track` are never reduced below their base severity; learning can never suppress them.
- **No exploration:** the learner uses the posterior mean only (no Thompson sampling or random exploration), because randomly hiding or showing financial warnings is not acceptable. `docs/learning_agents.md` explains this choice, the bandit framing (context = alert kind and category, action = surface or damp, reward = usefulness), and why RLHF, RLAIF and DPO are out of scope (1.4).
- **Transparency:** each learned multiplier is visible (`copilot learning show`), explained in alert why-text when it changed the severity ("shown at lower priority because you usually dismiss these"), and resettable per subject or entirely.

### 5.17 MCP server
- `copilot mcp-serve` exposes FinCo over **stdio** (local only) using the official SDK.
- **Tools exposed:** exactly the planner-selectable read/compute tools and skills from the capability matrix, plus `ask` (runs the agent graph; can create drafts, never user-actor writes). Nothing else. Each MCP call goes through `execute_tool` with `actor = agent` (or a dedicated `external_agent` actor if the policy model supports adding one without changing its default-deny contract) and is audited and traced with kind `mcp`.
- **Resources:** latest monthly review JSON, current calendar summary, bucket summary.
- **Data minimisation:** by default return aggregates and findings only; transaction-level detail requires `mcp.allow_transaction_detail: true` in config (default `false`). Same redaction rules as LLM context.
- **Untrusted input:** all MCP arguments schema-validated; injection corpus (5.14) re-run against MCP tool arguments.
- **Tests:** with the SDK's in-process client: list tools equals the capability matrix's selectable set; write tools absent; a call to a non-exposed tool fails; detail flag respected; audit and trace rows present.

---

## 6. Synthetic data v4 (needed for tests and evaluation)
Extend the generator (keep v1 to v3 behaviour unchanged for existing tests):
- Allowance or salary inflows with realistic variance; one profile with volatile income.
- Semester fees (yearly or twice-yearly), rent on a fixed day, bills with variable amounts, travel bookings ahead of a trip.
- A monthly investment-contribution debit (generic NACH/auto-debit narration; no real product names).
- A festival month with elevated gifts and shopping, plus an anomaly the user dismisses with reason `festival`.
- A habit change mid-history (for example dining shifts from weekday to weekend) to test decay.
- Ground truth (hidden, never read by the pipeline): true commitments, expected coverage outcomes on known dates, true patterns per period, readiness level per persona.
- **Personas** (fixed seeds): stable student, volatile freelancer, no-buffer spender, ready saver. Dev seeds and held-out seeds listed in config; never tune on held-out.

---

## 7. Stages

### Stage 3.0: Discover, align, adapt
**Goal:** an exact picture of the real system and a recorded adaptation for every difference.
**Build:** read the codebase and docs; fill `docs/phase3_alignment.md` with the 0.7 table (expected / found / action); list Phase 2 stages and their status; run the full suite and record the baseline (paste real output); add config skeletons with Pydantic validation: `commitments.yaml`, `goals.yaml` (merge), `buckets.yaml`, `calendar.yaml`, `readiness.yaml`, `contributions.yaml`, `memory.yaml`, `skills/`, `decomposition.yaml`, `context.yaml` (token budgets, top-k), `runtime.yaml` (jobs, retries, leases), `learning.yaml` (priors, η, bounds, floors), `ops.yaml`, `mcp.yaml`, plus defaults from 1.3. Also record which LangGraph features the installed version offers for parallel branches and subgraphs (from its docs) in the alignment doc.
**Tests:** config validation (bad values fail loudly; boundaries such as horizon 180 accepted and 181 rejected).
**Done when:** alignment doc complete; baseline green.

### Stage 3.1: Schema and models
**Build:** migrations for section 4 (extend vs create per 0.7); Pydantic models (`Commitment`, `Occurrence`, `CommitmentMatch`, `GoalProgress`, `Bucket`, `BucketAllocation`, `BucketBalance`, `AllocationSummary`, `ReallocationDraft`, `Calendar`, `CalendarDay`, `Coverage`, `Readiness`, `ReadinessCriterion`, `ContributionPlan`, `TradeoffResult`, `MemoryItem`, `MemoryEvidence`, `UserPreference`, `SkillManifest`, `SkillRun`, `SubQuestion`, `SpecialistReport`, `Reflection`, `ContextManifest`, `Span`, `ScheduledJob`, `JobRun`, `FeedbackStat`); repo functions filtered by `user_id`.
**Tests:** constraints, foreign keys, user isolation, JSON round trips; migration on a fresh database and on a Phase 2 database with data preserved; uniqueness of category-to-bucket mapping.
**Done when:** green.

### Stage 3.2: Commitments
**Build:** 5.1 in full (occurrence engine, matching, statuses, suggestions from recurring series, tools, policy and capability rows).
**Tests:** occurrence expansion for every schedule kind including 31st in February, leap years, `every_n_days` across month and year boundaries, start/end limits, paused; matching tolerances on both sides; one transaction never matches two occurrences; suggestions only from active series and only as drafts; drafts excluded from projections until accepted; agent cannot create or accept commitments; through-executor tests.
**Done when:** green.

### Stage 3.3: Goals (full)
**Build:** 5.2 (progress sources, contributions, history, projected completion, feasibility, tools).
**Tests:** each progress source; exactly one source enforced; percent boundaries (0, exactly target, above target); projection with 1, 2 and 3 months of history; zero or negative contribution → `never_at_current_pace`; ceil rounding; statuses agree with Phase 2 for the same inputs (regression test); through-executor tests.
**Done when:** green.

### Stage 3.4: Virtual buckets
**Build:** 5.3 in full (derived balances, reserved vs available, rollover, overspend status, `would_exceed`, alert signal, reallocation drafts with separate decide and apply).
**Tests:** the four invariants in 5.3; rollover idempotency; recategorisation moves spend between buckets; refunds reduce spend; depleted and low thresholds at the boundary; over-allocation flagged, never blocked; apply requires an approved draft; approval alone writes no allocation rows; expired drafts cannot be applied; agent cannot allocate directly; no transaction or balance table changes (snapshot test); through-executor tests.
**Done when:** green.

### Stage 3.5: Financial calendar
**Build:** 5.4 (projection engine, coverage, shortfall ranges, tools); the scenario extension point from 5.5.
**Tests:** hand-computed calendars over 10 to 15 days with known flows; low/expected/high ordering always holds (property test); commitment categories excluded from variable spend (no double counting); coverage at buffer exactly, one paisa below, one paisa above; `insufficient_data` forecast path; reconciliation invariant with forecast v2; horizon limits; zero-change scenario equals baseline.
**Done when:** green.

### Stage 3.6: Investment readiness
**Build:** 5.6 (criteria, levels, snapshot record, templates, refusals).
**Tests:** each criterion `pass`/`fail`/`unknown` at its boundary; level mapping for every combination class; the four personas produce their ground-truth level on dev seeds; every template passes the forbidden-content validator; no product names, returns or market words in any output (scan test); through-executor tests.
**Done when:** green.

### Stage 3.7: Contribution planning and trade-offs
**Build:** 5.7 (waterfall, verdicts, option generator with simulations, trade-off metrics, constraint satisfaction wording, snapshots).
**Tests:** waterfall sums exactly (funded + shortfall = need for every step; total funded ≤ inflow); user-reordered waterfall changes results as expected; verdict boundaries; options never increase any outflow beyond the original plan; trade-off metrics hand-computed for two small alternatives; "best" stated only when exactly one alternative satisfies all constraints; no growth applied anywhere (test that totals are plain sums); every option-bearing recommendation links a simulation (Phase 2 consequence rule).
**Done when:** green.

### Stage 3.8: Behavioural memory store and observers
**Build:** 5.8 (memory items and evidence, five observers, candidate/active lifecycle, user tools, forgetting, capture-label hook per 0.7).
**Tests:** each observer finds its injected pattern on dev seeds and stays silent on noise; reasons limited to the allowed list; forgetting removes content from every query path while the audit keeps a content-free event; user isolation; observers idempotent for the same clock; the LLM provider is never called by any memory function (assert on the fake provider's call log).
**Done when:** green.

### Stage 3.9: Confidence, decay and memory use
**Build:** 5.9 formulas and status rules; integrate active memories into alerts (damping), investigations (`known_exception`), advice suppression, and `memories_json` population.
**Tests:** values at 0, one and two half-lives; each threshold boundary; drift scenario; user-confirmed contradicted memory becomes `stale` with a "Still true?" flag; alerts damped only by an active exception for the same category and period; `known_exception` hypothesis supported only then; suppression cooldown boundary (day 29, 30, 31); `memories_json` lists exactly the memories used; property tests from 5.9.
**Done when:** green.
**[GIT CHECKPOINT A]** record `Add goals, commitments, buckets, readiness and memory` with exact files in `STATUS.md`. Do not run git. Continue.

### Stage 3.10: Skills library and agent integration
**Build:** 5.12 (manifest schema, runner, the five required skills, capability rows, planner support for skill steps) and 5.10 (intents, plan templates, capability rows, narration templates, refusals, timeline entries).
**Tests:** manifest validation (unknown tool, write tool, bad placeholder → load error); preconditions; each skill's eval cases and golden test; skill runs through `execute_tool` per step with spans; intent accuracy on the new labelled examples; tool/skill minimality per new intent; LLM-off and LLM-on give the same facts; adversarial plans selecting any Phase 3 write tool are rejected and audited; narration validator rejects invented numbers and unsupported causal claims in the new templates; refusals for product, return and money-movement questions; timeline shows forgotten memories without content.
**Done when:** green.

### Stage 3.11: Multi-agent planning
**Build:** 5.13 (decomposition, four specialists as subgraphs with restricted tool subsets, parallel fan-out, timeouts, partial-result merge, contradiction detection, deterministic reviewer, closed-set LLM critic, one revision round, `reflections`, failure export).
**Tests:** LLM decomposition (scripted fake) accepted when valid, rejected and replaced by the template fallback when it uses an unknown question kind, misses required coverage or references another user's ids; routing (single-domain → single loop; multi-domain → multi-agent); each specialist can call only its tool subset (an attempt outside it is rejected and audited); parallel branches run concurrently (wall time below the sum of injected delays); one specialist failing or timing out yields a partial answer that names the missing part; injected contradiction is detected, audited and excluded; reviewer catches a missed sub-question and the revision fixes it; revision bound respected; the LLM critic cannot change numbers (scripted critic output containing numbers is rejected); failure export writes candidate files; same facts with critic on and off.
**Done when:** green.

### Stage 3.12: Context engineering and injection hardening
**Build:** 5.14 (ContextBuilder for every LLM call path, manifests, memory retrieval, data-field delimiting, adversarial corpus).
**Tests:** every LLM call in the codebase goes through the builder (architecture test: no other module calls the provider); budget respected with exclusions recorded; deterministic ordering; manifests never contain raw text; retrieval returns only active memories of the same user, ranked as specified; injection corpus passes with a complying fake LLM; redaction asserted on captured prompts.
**Done when:** green.

### Stage 3.13: Agent runtime and observability
**Build:** 5.15 (jobs, leases, retries, dead letter, `jobs run-due`, `agentd`, spans everywhere, JSONL export, `copilot ops`).
**Tests:** due-job selection with an injected clock; lease prevents double runs (two runners, one executes); idempotent re-run for the same period writes nothing; backoff schedule and dead-letter after max attempts; retry from dead letter; jobs cannot perform user-actor writes; spans form a correct tree for a full multi-agent task; no span attribute contains user text (scan test); `ops` numbers equal hand-counted values on a fixture trace.
**Done when:** green.

### Stage 3.14: Bounded feedback learning
**Build:** 5.16 (signals, Beta state, multiplier, floors, ordering of advice, transparency, reset, `docs/learning_agents.md`).
**Tests:** posterior updates exact; multiplier bounds at both ends; hard floors never reduced (property test over random feedback histories); contextual-reason dismissals go to memory, not learning; reset restores priors; why-text mentions learning only when it changed the severity; identical inputs give identical outputs.
**Done when:** green.

### Stage 3.15: MCP server
**Build:** 5.17 (stdio server with the official SDK, tool and resource exposure from the capability matrix, data-minimisation flag, audit and spans).
**Tests:** as listed in 5.17, plus the injection corpus against MCP arguments and a test that adding a write tool to the registry does not expose it over MCP.
**Done when:** green.

### Stage 3.16: Orchestration comparison
**Build:** run the same Phase 3 evaluation questions through (a) the Phase 2 single planner loop and (b) the multi-agent subgraph, with the LLM off and on (fake provider and, if a key exists, live). Write `docs/orchestration_paradigms.md`: fixed graph (Phase 1), single plan-act-observe-revise loop (Phase 2), supervisor with parallel specialists (Phase 3), conversational multi-agent (AutoGen-style, described, not built), with **measured** accuracy, sub-question coverage, latency, LLM calls, failure rate and partial-answer rate for the ones built, and a plain conclusion about when each is worth it.
**Done when:** document written from real measurements.

### Stage 3.17: CLI, API, demo script and evaluation
**Build:** 5.11 commands; API endpoints if the API layer exists, otherwise `docs/phase3_api_contract.md`; `docs/demo_script_phase3.md` with an exact path: seed persona → accept suggested commitments (rent, fees, allowance) → create a trip goal linked to a bucket → map categories and allocate → calendar shows a shortfall before fees → ask "can I take the trip and keep my monthly contribution?" (multi-agent: show parallel specialists, reviewer, revision in the trace) → readiness → contribution plan with options → trade-off comparison → reallocation draft approved and applied → festival exception damps an alert → `jobs run-due` performs the daily upkeep → `ops` report → the same question asked through the MCP server → forget one memory → timeline.
`copilot eval --phase 3` and `eval/run_eval_phase3.py` writing `docs/eval_report_phase3.md` on **held-out seeds**, mean and spread:
- commitment suggestion precision/recall; occurrence-match accuracy
- calendar coverage accuracy vs ground-truth outcomes on known dates
- goal projected-completion error (months)
- readiness level accuracy per persona
- memory: pattern detection precision/recall, false-memory rate on noise, time-to-stale after the habit change
- agent: intent accuracy; tool/skill minimality; **trajectory accuracy** (expected tool/skill sequence per labelled question); sub-question coverage; reviewer catch rate and revision success rate; partial-answer rate under injected specialist failures; parallel speed-up; LLM calls and estimated tokens per task
- learning: alert volume and useful-alert share on simulated feedback histories vs the unlearned baseline, floors never violated
- safety: forbidden-content scan (must be 0), refusal suite, adversarial plan suite, injection corpus, MCP exposure test
Golden scenarios in `tests/golden/phase3/` (at least 22), for example: 31st-of-month rent in February; fees `not_covered` when the trip bucket is funded first and `covered` after reordering; recategorisation moves spend between buckets; rollover idempotent; over-allocation flagged; approve without apply changes nothing; readiness `not_ready` with no emergency reserve; `ready` persona; contribution `does_not_fit` with three options each simulated; trade-off names the only constraint-satisfying alternative; no growth in any total; festival exception damps an alert and supports `known_exception`; rejected advice suppressed for 30 days, back on day 31; old habit becomes stale after the change; forgotten memory unrecoverable from any read path; refusal of "which SIP should I buy"; multi-agent answer with one specialist failing states the gap; reviewer-triggered revision fixes a missed sub-question; merchant-name injection has no effect; job lease prevents double rollover; learning never lowers an `exceeded` alert; MCP lists no write tool.
**Rules:** never tune on held-out seeds; report weak spots plainly.
**Done when:** demo runs offline end to end; report generated; golden scenarios green.

### Stage 3.18: Hardening and documentation
**Build:** failure-handling pass (no commitments, no goals, no buckets, a deleted category mapped to a bucket, a goal whose linked account is removed, empty history, a horizon crossing a year boundary, conflicting memories, clock at month end, all specialists failing, LLM down mid multi-agent task, job crash mid-run, MCP client disconnect); logging review (no memory statements, reasons, merchant text or user text in logs or spans); README Phase 3 section with diagrams (planning: commitments → calendar → waterfall → trade-offs; buckets; memory lifecycle; multi-agent graph; runtime and observability); `docs/architecture_agentic.md` mapping each component to the agent concept it implements (plan-act-observe-revise, skills, short-term vs long-term memory, retrieval, context engineering, MCP, supervisor and specialists, merge and fault tolerance, Reflexion-style revision, human-in-the-loop, approval gates, audit, evaluation, observability, learning) with file paths; capability matrix regenerated; mutation checks for section 8 recorded; final `decisions.md`, `STATUS.md`, `known_issues.md`.
**Done when:** section 9 all green.
**[GIT CHECKPOINT B]** record `Add multi-agent planning, skills, runtime and MCP server` with exact files in `STATUS.md`. Do not run git.

---

## 8. Safety rules that must each have a failing-when-removed test
1. No Phase 3 tool moves, locks or reserves real money; no transaction or balance row is modified by buckets, goals, commitments, plans or trade-offs.
2. Approving a reallocation writes nothing; only `apply_reallocation` by the user writes allocation rows, and only for an approved, unexpired draft.
3. Agent-drafted commitments and memories never affect projections or advice until accepted or active.
4. No output contains a product, fund, stock, platform or broker name, a return, growth, interest or inflation figure, or a market prediction.
5. Totals and contributions are plain sums; no growth is ever applied.
6. Calendar low ≤ expected ≤ high on every day.
7. `available_unallocated + reserved_total == liquid_balance` exactly.
8. Commitment categories are not double counted in variable spend.
9. Forgotten memories are unreadable through every tool and API path.
10. The LLM never writes or scores memory.
11. Planner cannot select any Phase 3 write tool.
12. User-set categories and merchant overrides are never touched by any Phase 3 tool.
13. A specialist cannot call a tool outside its subset.
14. The LLM critic cannot introduce or change a number; revision rounds are bounded.
15. Every LLM call goes through the ContextBuilder with redaction; an injected instruction in any data field cannot produce an accepted write, an out-of-enum category or extra data in the output.
16. Learning never lowers the severity of `exceeded`, `not_covered` or `off_track` alerts.
17. The MCP server exposes only planner-selectable read/compute tools and skills; transaction detail only with the config flag.
18. Jobs never perform user-actor writes and never run twice for the same lease and period.
19. No span, manifest or log contains user text, merchant names or memory statements.

---

## 9. Phase 3 exit checklist
- [ ] Full suite and lint green; Phase 0 to 2 tests unchanged and green
- [ ] `docs/phase3_alignment.md` lists every adaptation applied
- [ ] Migrations apply on a fresh and on a Phase 2 database, idempotently, with data preserved
- [ ] Commitments: all schedule kinds, matching, statuses, suggestions as drafts
- [ ] Goals: three progress sources, projected completion with ranges, statuses consistent with Phase 2
- [ ] Buckets: derived balances, reserved vs available, rollover, overspend, drafts with separate apply; invariants tested
- [ ] Calendar: daily low/expected/high projection, coverage and shortfalls, reconciled with forecast v2
- [ ] Readiness: criteria, levels, templates clean of product and return language
- [ ] Contribution planning and trade-offs: exact waterfall, options with simulations, no growth anywhere
- [ ] Behavioural memory: observers, lifecycle, user control, forgetting, decay formula with property tests, used in alerts, investigations and advice suppression
- [ ] Agent: new intents, minimal tool selection, validator-clean narration, refusals, timeline
- [ ] Skills library: five skills with manifests, eval cases and golden tests; planner can select skills
- [ ] Multi-agent: routing rule, parallel specialists with restricted tools, partial-result merge, contradiction detection, reviewer, bounded revision, reflections logged, failure export
- [ ] Context engineering: all LLM calls via ContextBuilder with manifests; retrieval deterministic; injection corpus green
- [ ] Runtime: jobs with leases, retries, dead letter; `run-due` and `agentd` work on Windows
- [ ] Observability: spans everywhere, `ops` report verified on a fixture trace
- [ ] Learning: bounded, floored, explainable, resettable; `docs/learning_agents.md` written
- [ ] MCP server: exposure equals the capability matrix's selectable set; data-minimisation flag
- [ ] `docs/orchestration_paradigms.md` from real measurements; `docs/architecture_agentic.md` maps every concept to code
- [ ] CLI (and API if present) complete; demo script runs offline
- [ ] Evaluation report on held-out seeds with weak spots stated; golden scenarios green
- [ ] Mutation checks for section 8 recorded
- [ ] Exactly two proposed commits recorded; no git command run; no AI attribution anywhere

---

## 10. Explicitly NOT in Phase 3
- Product or instrument recommendations, returns or growth modelling, tax calculations, market data
- Real money movement, real reserves or locks at a bank, payment initiation
- Experiments, challenges, gamification (Phase 4); social and shared finance (Phase 5)
- Messaging channels and proactive delivery (Phase 6); guidance levels and risk-aware intervention modes (Phase 7)
- The capture lane and real Account Aggregator connector (ADR-0001, ADR-0002), except the memory hook in 0.7
- Debt and loan modelling beyond the user's single declared `high_cost_debt` flag
- Training or fine-tuning any model (RLHF, RLAIF, DPO); exploration-based learning on financial warnings
- AutoGen-style free agent conversation, swarms, vector databases, the LangChain library, cloud deployment
- MCP over network transports (stdio only); MCP client connectors to third-party services

## 11. Extension points Phase 3 must leave
| Built now | Used later by |
|---|---|
| Commitments + occurrence engine | Phase 6 proactive reminders; capture lane matching |
| Calendar projection engine | Phase 4 experiments (measuring behaviour change), Phase 7 risk-aware intervention |
| Buckets + `would_exceed` | Capture-lane prompt ("this would exceed Dining by ₹X"), Phase 5 cooperative goals |
| Readiness criteria | Phase 7 guidance levels |
| Memory store, evidence and decay | Phase 4 experiment learning loop, Phase 6 cross-channel state |
| Waterfall order in user preferences | Phase 4 personalised challenges |
| Scenario extension point | Every future what-if |
| Skills library | Phase 4 experiments as skills; Phase 6 conversational shortcuts |
| Multi-agent subgraph and specialist roles | New specialists (Phase 4 ExperimentAgent, Phase 5 GroupAgent) without changing the supervisor |
| Runtime jobs | Phase 6 proactive messaging, AA periodic fetch (ADR-0002) |
| Spans and `ops` | Phase 7 production hardening and dashboards |
| Feedback learner | Phase 4 adaptive challenges; capture-lane guess ranking (ADR-0001) |
| MCP server | Phase 6 multi-channel access through MCP-capable assistants |
