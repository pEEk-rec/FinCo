# PLAN_PHASE4.md: Phase 4, Behavioural Engagement & Gamification

Project: Personal Finance & Budgeting Copilot (FinCo, Agentic AI course project)
Scope of this file: **Phase 4 only.**
Owner and only contributor: the user (repo owner).

Roadmap definition: *"Make consistent financial behavior interactive without turning finance into an unhealthy competition."*

Read this whole file before writing code. Then read, in this order: `STATUS.md`, `docs/decisions.md`, `docs/open_questions.md`, `docs/known_issues.md`, `docs/PLAN_PHASE3.md`, `docs/phase3_alignment.md`, `docs/architecture_agentic.md` (if present), and the current code. Phase 4 builds on **whatever Phases 0 to 3 actually produced**. Stage 4.0 discovers the real system; section 0.7 says exactly what to do for each difference, so you should not need to ask the owner anything.

---

## 0. Rules for the implementing agent

### 0.1 Work mode: fully autonomous
Work through section 7 in order without waiting between stages. For every stage: write its goal and file list at the top of its `STATUS.md` entry; build in small steps; run tests and lint often; the stage is done only when its **Done when** is met and the full suite and lint pass; append the explain-back (0.5); continue.

**The owner wants no approval requests.** Product decisions are pre-made in section 1.3; differences from the plan are handled by 0.7; anything else follows 0.2.

**Hard gates (the only reasons to stop)**
1. A git command of any kind (0.3). You never run git; you only record proposals.
2. Adding a dependency. Phase 4 needs **none** (randomness from `random.Random`, statistics by hand with `Decimal`).
3. Anything that costs money, signs up for a service, deploys, or touches files outside the repository.
4. Breaking an earlier contract: `execute_tool` as the single choke point; append-only audit; integer-paise money; `user_id` on every table; no money-movement tools; user > override > rule > cache > LLM precedence; advice/narration validators; planner capability allowlist; Phase 3 learning floors; Phase 3 MCP exposure rules.
5. A failing test or lint error you cannot fix after an honest attempt. Never weaken, skip, `xfail` or delete a test. Record the blocker and continue with independent stages.

When a hard gate is hit, record it under Blockers in `STATUS.md` and continue with everything that does not depend on it.

### 0.2 Soft gates: decide, record, continue
- **Uncovered product decision:** choose the most conservative option (fewer automatic actions, gentler on the user, no pressure mechanics, more visible uncertainty); record "Decided: X. Alternative: Y. Why." in `docs/open_questions.md`; continue.
- **Name or structure differs:** the real code wins; follow 0.7; record in `docs/phase4_alignment.md`.
- **No Gemini key:** fake provider; mark live checks pending.
- **Small unrelated issue:** one line in `docs/known_issues.md`.

### 0.3 Git (two proposed commits, no git commands)
- Run **no** git command at all.
- `[GIT CHECKPOINT A]` after Stage 4.7; `[GIT CHECKPOINT B]` after Stage 4.13. At each: all tests and lint green; write the proposed message and exact file list under "Proposed commits (awaiting approval)" in `STATUS.md`; continue working.
- Messages: A = `Add experiments, challenges and progress tracking`; B = `Add experiment learning loop and coaching agent`.
- No AI attribution anywhere. Never propose committing `.env`, keys, the database, `reports/`, generated data or screenshots.

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
After each stage append 4 to 8 lines to `docs/decisions.md`: what was built, why, what it deliberately does not do, one examiner question with its answer.

### 0.6 Code, honesty and quality rules (inherited and tested)
1. Simple readable Python, type hints, docstrings on public functions.
2. **Deterministic code owns financial truth.** The LLM never computes a baseline, an outcome, XP, a badge, a probability or a target.
3. Every tool call through `execute_tool`; the architecture test covers every Phase 4 module.
4. Money in integer paise; `Decimal` for intermediate maths; probabilities, scores and rates stored as integer basis points. The only floats allowed are inside `random.Random` sampling calls, converted to basis points immediately.
5. `user_id` on every new table; every query filters by it.
6. All thresholds, catalogues, XP values and policies in YAML, validated with Pydantic.
7. No money movement. Challenges, rewards and experiments never move, lock or reserve money.
8. No investment advice, no product names, no returns.
9. IST dates; injected clock; **injected random generator** (`ExecutionContext.rng` or equivalent, seeded) so every stochastic decision is reproducible in tests.
10. Test the real path through `execute_tool`, including failure paths and audit rows.
11. Boundary tests on both sides of every threshold; mutation check on each safety rule in section 8, recorded in `decisions.md`.
12. Reports quote real output; docs state only what tests prove; no marketing language.
13. Windows-safe; UTF-8 everywhere.

### 0.7 Adaptation rules (use these instead of asking)
Stage 4.0 fills `docs/phase4_alignment.md` with one row per item: *expected*, *found*, *action taken*.

| If you find... | Do this |
|---|---|
| Phase 3 behavioural memory (`memory_items`, evidence, decay) | Add memory kind `experiment_outcome` (half-life 180 days) through its extension point; reuse lifecycle and forgetting |
| Phase 3 memory missing | Store outcomes only in Phase 4 tables; leave a hook function; record |
| Phase 3 feedback learner (`feedback_stats`, Beta state) | Reuse its storage with new `subject_kind` values (`challenge_template`); keep Phase 3 floors untouched |
| Phase 3 learner missing | Create `feedback_stats` exactly as specified in PLAN_PHASE3 §4 and use it |
| Phase 3 runtime jobs (`scheduled_jobs`, `run-due`) | Add Phase 4 job kinds there |
| Runtime missing | Compute check-ins, expiries and reviews lazily on read and via `copilot experiments tick`; record |
| Phase 3 multi-agent subgraph with specialist registry | Add `CoachAgent` as a new specialist without changing the supervisor |
| Multi-agent missing | Implement coaching as plan templates or skills in the Phase 2 planner |
| Phase 3 skills library | Implement the Phase 4 procedures as skills |
| Skills missing | Implement them as services plus plan templates |
| Phase 3 calendar, goals, buckets, essential-category config | Use them for feasibility, goal impact and the essential-category exclusion |
| Any of those missing | Use the Phase 1/2 forecast and budgets; feasibility falls back to "budget not exceeded"; record |
| API layer exists | Add endpoints, regenerate OpenAPI and TS types, add route tests |
| No API layer | Write `docs/phase4_api_contract.md` for the UI track |
| Capture-lane labels (ADR-0001) exist | Count "payments tagged at the moment" toward the data-quality XP rule |
| Phase 3 spans/`ops` | Instrument every Phase 4 tool, job and skill with spans |
| A planned table name already exists with another meaning | Prefix with `p4_`; record |

### 0.8 LLM-first, deterministic-guarded (overrides any earlier wording in this file)
FinCo must respond dynamically to any user and any phrasing. Hardcoded behaviour is a **fallback**, never the main path. Where this file says "deterministic patterns first", "templates", "closed list" or "plan templates", read it with these rules:

1. **Use the owner's existing LLM router.** Stage 4.0 records its module, providers (Gemini, Groq or others), key pool, rate limiter, retry and budget settings in the alignment doc. Every LLM call goes ContextBuilder (or the existing prompt builder) → router. Never call a provider SDK directly, never add, print, log or commit keys, never bypass the router's limiter.
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

## 1. Phase 4 goal

> The user can turn a goal or a habit they want to change into a **time-bound experiment** with a clear hypothesis and an honest measurement against their own past. FinCo offers **personalised, opt-in challenges** sized from the user's real data, **adapts** them when life changes, shows **progress against the user's own previous performance**, rewards **healthy behaviours** (never risky ones), and **learns** which kinds of experiments help this user, feeding that back into future suggestions.

### 1.1 Roadmap items and where they land
| Roadmap item | Stage |
|---|---|
| Financial Experiments (hypothesis, target behaviour, measurement, review) | 4.2, 4.3 |
| Personalised Challenges (from observed behaviour and active goals) | 4.4 |
| Adaptive Challenges (adjust difficulty when obligations or state change) | 4.5 |
| Self-Competition (against own past and personal targets) | 4.6 |
| Progress & Rewards (indicators, milestones, XP/badges, never rewarding risk) | 4.7 |
| Experiment Learning Loop (observe, feedback, evaluate, update recommendations) | 4.8, 4.9 |
| Agent integration (coach specialist, skills, runtime jobs, intents) | 4.10 |

### 1.2 How Phase 4 uses agent concepts (and why each helps a real user)
| Concept | Where | Real-user value |
|---|---|---|
| Long-horizon plan-act-observe-revise loop with durable state | An experiment *is* an agent loop over weeks: plan (hypothesis, target), act (the user's behaviour), observe (weekly measurement), revise (adaptive difficulty), review | Behaviour change takes weeks; the system keeps context across them without the user re-explaining |
| Goal decomposition | A goal ("trip in 4 months, ₹12,000 short") is decomposed into candidate weekly experiments whose expected savings close the gap | Concrete next steps instead of a vague target |
| Contextual bandit with exploration, logged propensities, off-policy evaluation | Choosing which optional challenge templates to **offer** (4.9) | Suggestions improve per user; exploration is acceptable here because offers are optional and harmless, unlike financial warnings (Phase 3 used no exploration for that reason) |
| Simulation environment and regret | `eval/sim/` user simulator to evaluate offer policies before they touch users | Policy changes are tested offline first, as in real RL practice |
| Honest measurement (counterfactual baseline, rank-based significance) | 4.2 | Users are not told they "saved" money when the change is within normal noise |
| Learning loop into memory and recommendations | 4.8 | What worked or was disliked shapes future advice, visibly and resettably |
| Specialist agent in a supervisor graph | `CoachAgent` (4.10) | Coaching questions join cross-domain answers ("can I do the trip if I run a no-delivery month?") |
| Human-in-the-loop | Every experiment, challenge and adjustment is opt-in or a proposal | The user stays in control; nothing changes behind their back |

### 1.3 Product decisions already made (do not re-open; values in config)
| Topic | Decision |
|---|---|
| Opt-in | Every challenge and experiment is opt-in; offers expire after `offers.ttl_days` (default 7); nothing starts automatically |
| Limits | At most `limits.max_active` (default 2) active experiments/challenges; at most one per category; at most `offers.max_per_week` (default 3) new offers per week |
| Duration | 7 to 56 days; default 14; windows start on the user's chosen weekday (default Monday) |
| Which spending can be targeted for reduction | **Only non-essential categories** (Phase 3 essential list inverted). Essential categories (rent, groceries, utilities, education fees, transport, health, insurance, EMIs) can never be reduction targets |
| Difficulty levels | `easy` 10%, `medium` 20%, `hard` 30% below the baseline median; targets rounded to the nearest ₹50 (5000 paise); never below `min_target_share_bp` (default 5000 = 50%) of the baseline median |
| Measurement | Baseline from the previous K comparable windows (default K = 6, minimum 3, lookback at most 26 weeks), excluding windows covered by active contextual exceptions or lacking data |
| Outcome words | "lower than all K of your previous comparable periods" style statements only; never "because of the challenge" |
| Adaptive changes | Always proposals the user accepts; the system never tightens a target on its own; it may **pause** a challenge automatically only when the user marks a contextual exception covering its window (and says so) |
| Streaks | Forgiving: one grace day per 7 days; streak "freezes" during declared exceptions; broken streaks are never shamed |
| XP | Never decreases; no monetary value; no random rewards; daily cap `xp.daily_cap` (default 100) |
| Social | None in Phase 4 (no leaderboards, no sharing); self-competition only |
| Learning | Offers chosen by Thompson sampling over challenge families (metric code × trigger class × difficulty) with a seeded generator, logged propensities, and a minimum share of "not offered" weeks when the user has dismissed several offers |
| Cooldowns | A template abandoned or rated unhelpful is not offered again for `offers.cooldown_days` (default 30) |

---

## 2. Design principles for Phase 4
1. **Healthy, not addictive.** No variable-ratio rewards, loot boxes, countdown pressure, loss framing, shame messages, artificial scarcity or confirm-shaming ("No, I don't want to save money"). Plain declines.
2. **Self-competition only.** Compare the user with their own past and their own targets.
3. **Never reward risk.** Rewards attach only to healthy behaviours on an allowlist (5.7). Cutting essentials, skipping commitments, borrowing, trading or investing more are never rewarded.
4. **Honest measurement.** Every outcome is compared with a baseline range from the user's own history, with the uncertainty stated; no causal claims.
5. **Small, specific, reversible.** Experiments are short, concrete and abandonable without penalty.
6. **Agent proposes, user decides.** Offers, adjustments and reviews are drafts or prompts; only user actions start, change or end things.
7. **Derived over stored.** Progress, personal bests and streaks are computed from transactions and ledgers; only user decisions, check-ins, offer logs and XP events are stored.
8. **Explain everything.** Each offer says why it was suggested, what it is sized from and what it could mean for a goal.

---

## 3. Stack
No new dependencies. Reuse everything from Phases 0 to 3.

---

## 4. Data model additions
Numbered migrations after the last one; idempotent; transactional; `user_id`, foreign keys, `CHECK` constraints. Extend audit event-type constraints if present.

| Table | Key columns |
|---|---|
| `experiments` | `title`, `template_code`, `hypothesis_json` (structured: intervention, metric, direction, target), `metric_def_json` (frozen at start: metric code, categories or merchants, exclusions), `params_json`, `difficulty`, `window_start`, `window_end`, `baseline_json` (frozen at start: K, window values, median, low, high, excluded windows with reasons), `target_value`, `status` (`offered`/`active`/`paused`/`completed`/`abandoned`/`expired`/`reviewed`), `origin` (`user`/`offer`/`goal_decomposition`), `offer_id`, `goal_id` (nullable), `created_at`, `started_at`, `ended_at` |
| `experiment_checkins` | `experiment_id`, `checkin_date`, `observed_value` (snapshot for history), `pace_status` (`ahead`/`on_pace`/`behind`/`insufficient`), `user_response` (`going_well`/`hard`/`want_to_pause`/`skip`/null), `created_at` |
| `experiment_reviews` | `experiment_id`, `observed_value`, `outcome` (`beyond_usual_range`/`within_usual_range`/`above_usual_range`/`no_baseline`), `rank_p_bp`, `effect_value`, `target_met` (bool), `integrity_json`, `data_quality_json`, `user_difficulty` (1 to 5, nullable), `user_helpful` (bool, nullable), `user_would_repeat` (bool, nullable), `created_at` |
| `adjustment_proposals` | `experiment_id`, `kind` (`ease_target`/`extend`/`pause`/`resume`/`raise_target_optional`/`end_early`), `reason_code`, `params_json`, `status` (`proposed`/`accepted`/`rejected`/`expired`/`auto_applied_pause`), `created_at`, `decided_at` |
| `offers` | `week_start`, `template_code`, `difficulty`, `params_json`, `rank`, `propensity_bp`, `policy_version`, `rng_seed`, `reason_json`, `status` (`shown`/`accepted`/`dismissed`/`expired`), `created_at`, `decided_at` |
| `xp_events` | append-only: `rule_code`, `points`, `ref_kind`, `ref_id`, `period_day`, `created_at`; unique (`user_id`, `rule_code`, `ref_kind`, `ref_id`) so an event is never awarded twice |
| `badge_awards` | `badge_code`, `awarded_at`, `evidence_json`; unique (`user_id`, `badge_code`) for one-time badges |
| `streak_freezes` | `streak_code`, `from_date`, `to_date`, `reason` (`grace`/`exception`) |

Derived (not stored): progress, pace, personal bests, streak lengths, levels, goal-gap decompositions.

---

## 5. Key designs

### 5.1 Metric catalogue (closed list; adding one is code plus tests)
| Code | Definition (over a window, transfers and duplicates excluded, commitment-matched transactions excluded) | Direction that counts as better |
|---|---|---|
| `category_spend` | sum of debits in the listed non-essential categories, minus refunds | lower |
| `merchant_group_spend` | sum of debits to a user-chosen merchant group (for example food delivery apps the user tags), minus refunds | lower |
| `txn_count` | number of debits in the listed categories | lower |
| `no_spend_days` | days with zero debits in the listed non-essential categories | higher |
| `bucket_adherence_days` | days a chosen spending bucket stays at or above zero (Phase 3) | higher |
| `goal_allocation` | net logical allocations to a goal bucket or manual goal contributions in the window | higher |
| `checkin_rate` | share of scheduled check-ins answered | higher |
| `tagging_completeness` | share of the window's transactions with a non-guess category (user, override, rule) | higher |

Every metric is a pure function `(user, window, params) -> int` (paise, count or days), tested on hand-built data.

### 5.2 Baseline and outcome engine (honest measurement)
**Baseline** for an experiment of length *d* days starting on date *s*:
1. Candidate windows: the previous non-overlapping windows of length *d*, aligned to the same weekday, ending before *s*, going back at most 26 weeks; take the most recent K (default 6).
2. Exclude a window if it overlaps an active contextual-exception memory for the metric's categories, overlaps another experiment on the same metric, or has missing-data days above `baseline.max_missing_days`. Record every exclusion with a reason.
3. If fewer than `baseline.min_windows` (3) remain: `no_baseline`. The experiment can still run against an absolute target the user sets, and the review says no comparison was possible.
4. `median` = median of window values (for an even count, the lower middle, so it stays an integer); `low` = min; `high` = max.

**Outcome** at review, observed value *v*, for a lower-is-better metric (mirror for higher-is-better):
- `rank_p = (1 + number of baseline windows with value ≤ v) / (K + 1)`, stored in basis points. Under "nothing changed", each window is equally likely to be the lowest, so `rank_p` behaves like an exact permutation p-value. Document this in `docs/decisions.md`.
- `beyond_usual_range` if `v < low` **and** `median − v ≥ max(min_effect_share × median, min_effect_paise)` (defaults 10% and ₹200); `above_usual_range` if `v > high`; otherwise `within_usual_range`.
- `effect_value = median − v` (signed).
- `target_met` = `v ≤ target_value` (or ≥ for higher-is-better).
- Wording comes from templates: "₹X, lower than all 6 of your previous comparable fortnights (usual range ₹A to ₹B)". Never "the challenge caused" or "you saved because". The Phase 2 causal-claim rule is extended to Phase 4 templates.

**Integrity notes** (computed at review): transactions recategorised **out of** the metric's categories during the window (count and amount); transactions added late (ingested after the window); exceptions declared inside the window. If the recategorised amount is at least `integrity.share_of_margin_bp` (default 5000 = 50%) of the margin by which the target was met, the review asks the user to confirm those corrections were genuine before `target_met` XP is awarded. This keeps self-competition honest without blocking real corrections.

**Pace (mid-experiment):** expected value to date = target × elapsed days ÷ total days for sum metrics (integer maths, round half up); `ahead`/`on_pace`/`behind` within `pace.tolerance_bp`.

### 5.3 Experiments
- **Design:** `design_experiment(template_code | custom, params)` builds a hypothesis in structured form: *"If I {intervention}, then {metric} over {d} days will be {direction} {target}, compared with my usual {median} (range {low} to {high})."* Custom experiments are allowed only with catalogue metrics and pass the same safety checks.
- **Lifecycle:** `offered → active → (paused ↔ active) → completed | abandoned | expired → reviewed`. Starting freezes the metric definition and the baseline. Abandoning is free (no penalty, no negative wording) and still offers a short review.
- **Check-ins:** weekly by default (`checkins.every_days`), created by the runtime job; each shows pace and one optional quick response; snoozable.
- **Review:** created when the window ends plus `review.delay_days` (default 2, to let late transactions arrive); deterministic numbers (5.2); user feedback (difficulty 1 to 5, helpful, would repeat) is optional.
- **Goal link:** an experiment can link to a goal; its review shows the effect in goal terms ("₹X would cover Y% of the remaining trip amount"), computed by Phase 3 goal maths, never "you will reach your goal".
- **Tools:** `design_experiment`, `start_experiment`, `pause_experiment`, `resume_experiment`, `abandon_experiment`, `answer_checkin`, `submit_review_feedback` (user actor; not planner-selectable); `get_experiment`, `list_experiments`, `experiment_progress` (read; planner-selectable); `create_checkins`, `create_due_reviews` (agent; runtime jobs).

### 5.4 Challenge templates and personalisation
**Templates** in `config/challenges/*.yaml` (closed catalogue; each with eval cases): for example `weekday_home_cooking` (category_spend on dining and delivery, weekdays only), `delivery_cap` (merchant_group_spend), `no_spend_weekend` (no_spend_days), `subscription_review` (review and decide on each subscription; metric: decisions made, no spend reduction claimed), `bucket_week` (bucket_adherence_days), `goal_boost` (goal_allocation toward a chosen goal, feasibility checked), `tag_everything_week` (tagging_completeness), `weekly_money_checkin` (checkin_rate). Each template declares: metric, eligible categories (non-essential only for reduction), allowed durations and difficulties, triggers (5.4 generator), copy template, and safety tags.

**LLM-composed challenges (primary path, 0.8):** the LLM receives the user's context (active memories and patterns, goal gaps, budgets, recent outcomes and feedback, preferences; all through the ContextBuilder, redacted) and the registries (metric codes, eligible non-essential categories from the user's own data, allowed durations and difficulties) and proposes up to `offers.llm_candidates` (default 6) challenge specs: metric code, categories or merchant group, duration, difficulty, a short title and a rationale. Every spec is validated (registry membership, categories exist and are non-essential, durations and difficulty allowed) and then sized and filtered by the deterministic steps below exactly like a template candidate; the LLM's numbers, if any, are ignored and replaced by computed targets. The configured templates are the fallback and also seed the candidate pool.

**Generator** (`suggest_challenges(week_start)`, agent allowed, writes offers only):
1. **Triggers** from existing state, deterministic: an active memory pattern (for example `weekend_heavy` dining), a non-essential budget exceeded in 2 of the last 3 months, a goal `at_risk`/`off_track`, a calendar shortfall, low tagging completeness, many open review items.
2. **Candidates:** templates whose triggers fire, with parameters fitted from data: categories, duration, difficulty levels, targets from the baseline (1.3 rules).
3. **Safety filter** (5.8): drop any candidate that targets an essential category, conflicts with an active experiment on the same category, would push a Phase 3 calendar low balance below the buffer (for allocation templates), or is in cooldown.
4. **Value estimate** per candidate: expected effect = baseline median × difficulty share (paise); goal relevance = share of a priority goal's monthly gap it could close (Phase 3 maths); success probability from the learner (5.9).
5. **Selection:** the offer policy (5.9) picks at most `max_per_week` offers; each offer stores its reason ("Your weekend dining is usually ₹A to ₹B; a medium target would be ₹T"), propensity and policy version.
- **Goal decomposition:** `decompose_goal_gap(goal_id)` lists candidate experiments whose combined expected effects cover the monthly gap, as a plan of up to 3, each still opt-in. It never promises the goal will be reached.

### 5.5 Adaptive challenges
Detectors (run daily by the runtime job, deterministic), each producing an **adjustment proposal** with a reason code:
| Detector | Proposal |
|---|---|
| A new firm commitment or a calendar shortfall inside the window | `ease_target` (one difficulty level down) or `pause` |
| User declares a contextual exception covering part of the window | automatic `pause` for the exception days (`auto_applied_pause`, shown and reversible) plus `extend` by the same days |
| Income in the window well below its usual range (Phase 3 cash-flow data) | `ease_target` |
| Pace `behind` for two consecutive check-ins | `ease_target` or `end_early` (gentle wording) |
| Pace `ahead` by a wide margin at the halfway check-in | optional `raise_target_optional`, clearly optional, never automatic |
| Check-in response `want_to_pause` | `pause` |
All other changes require `accept_adjustment` (user). Easing never affects XP for completing the experiment (5.7); `target_met` is judged against the target in force at the end.

### 5.6 Self-competition, personal bests and streaks
- **Personal bests** (derived): for each metric and comparable window length, the user's best value in history (lowest weekly dining, most no-spend days in a fortnight, highest monthly goal allocation, highest tagging completeness). A new best is recognised in the review with the previous best and its date.
- **Comparisons:** "this period vs your median of the last K comparable periods" and "vs your personal best". Never vs other people.
- **Streaks** (derived): `checkin_streak`, `tagging_streak` (days with all transactions tagged), `bucket_streak`. One grace day per 7 days; `streak_freezes` during declared exceptions. A broken streak is shown as "longest streak: N days", never as a loss.

### 5.7 Progress and rewards
- **XP rules** (`config/rewards.yaml`, allowlist only): completing a check-in; finishing an experiment (completed **or** reviewed after abandoning: learning is rewarded, not just winning); meeting a target; a new personal best; goal milestones (25/50/75/100% via Phase 3 goal progress); keeping the emergency fund at or above target for a full month; tagging completeness ≥ 95% for a week; reviewing the monthly review; answering a "Still true?" memory prompt. Each rule has points, a daily cap share, and an idempotency key (`xp_events` unique constraint).
- **Never rewarded** (enforced by a static check over the rule file and a runtime check): reductions in essential categories; skipping or delaying commitments; investment or contribution **amounts**; transaction counts or volumes; borrowing; any metric not on the allowlist. A test parses every reward rule and fails if it references a forbidden metric or category class.
- **Levels:** thresholds in config; level names neutral (no "rich", "wealthy").
- **Badges:** catalogue with deterministic predicates over XP events, reviews, bests and streaks (for example "First experiment reviewed", "Four check-ins in a row", "Tagged every payment for a week"). Awarded once, with evidence.
- **No random rewards, no loss.** XP never decreases; nothing is taken away.

### 5.8 Safety and wellbeing rules (enforced in code)
- Reduction targets only on non-essential categories; floor at 50% of the baseline median; at most one active experiment per category.
- No experiment or challenge text may encourage skipping meals, medical care, education, rent, bills or commitments; templates pass the Phase 2/3 forbidden-content validator extended with a Phase 4 list (`skip`, `starve`, `avoid paying` and similar in context).
- No pressure mechanics: no countdown timers, no "last chance", no loss framing, no shame. A copy test scans every template for a configured list of pressure phrases.
- If the user abandons or rates as unhelpful two experiments in a row, offers pause for `offers.rest_weeks` (default 2) and the next offer explains why it is back.
- Every offer is declinable with a plain "Not now" that is recorded without penalty.

### 5.9 Offer policy: Thompson sampling with logged propensities
- **Arms:** challenge families (metric code × trigger class × difficulty) that have at least one candidate passing the safety filter this week. Learning is per family, so it generalises across LLM-composed challenges that share a family; the specific candidate shown for a chosen family is the highest-value valid one.
- **State:** Beta posterior per arm per user in `feedback_stats` (`subject_kind = challenge_template`), reward = experiment **completed and reviewed** with `user_helpful` not false (abandoned → failure; dismissed offer → small failure weight `offers.dismiss_weight`, default 0.25). Priors from config.
- **Policy:** for each arm draw θ from its Beta posterior using the injected seeded `random.Random`; score = θ × value weight (expected effect and goal relevance, normalised); pick the top `max_per_week`. Floats exist only inside the draw; scores are converted to basis points before comparison and storage.
- **Propensity logging:** estimate each shown arm's selection probability with `offers.propensity_draws` (default 1000) seeded re-draws; store as basis points. This enables **off-policy evaluation** later.
- **Rest weeks:** after the rest rule (5.8) the policy shows nothing that week.
- **Transparency:** each offer says what it is sized from; `copilot learning show` lists template posteriors in plain words; reset available.
- **Why exploration is acceptable here and not in Phase 3 alerts:** offers are optional suggestions with no financial downside; warnings are not. Write this in `docs/learning_agents.md`.

### 5.10 Learning loop into memory and recommendations
After each review:
1. Update the template posterior (5.9).
2. Write an `experiment_outcome` memory (structured: template, metric, outcome, effect, helpful, difficulty) with evidence links (review id, transactions), using Phase 3 memory and decay.
3. **Recommendations:** Phase 2/3 advice drafting may cite active `experiment_outcome` memories as evidence ("When you tried weekday home cooking in August, dining was ₹X, below your usual range"), never as causation; templates rated unhelpful are suppressed in advice for the cooldown; Phase 3 contribution-plan options may include "repeat an experiment that previously landed below your usual range" as an option with its expected effect from that outcome.
4. **Failures become eval cases:** reviews with integrity questions, `no_baseline` or user difficulty 5 are exported to `eval/candidates/phase4/` for the owner (agentic SDLC flywheel; no runtime self-modification).

### 5.11 Agent integration
- **Intents:** `start_experiment` ("help me spend less on food delivery"), `experiment_status` ("how is my challenge going?"), `what_worked` ("what has worked for me before?"), `challenge_suggestions`, `progress_summary` ("show my progress"). At least 8 labelled examples each.
- **Skills** (or plan templates per 0.7): `design_experiment_from_goal`, `weekly_checkin`, `review_experiment`, `suggest_challenges`.
- **CoachAgent** specialist (per 0.7) with tools: metrics, baselines, experiments (read), offers (read), personal bests, Phase 3 goals (read). It joins multi-domain questions such as "can I afford the trip if I do a no-delivery month?" (CashflowAgent + GoalsAgent + CoachAgent).
- **Capability matrix:** read tools planner-selectable; every write tool not selectable; `suggest_challenges` and job tools agent-only.
- **Runtime jobs:** `create_checkins`, `create_due_reviews`, `expire_offers`, `run_adaptive_detectors`, `weekly_offers` (on the user's chosen weekday), `award_xp_and_badges` (idempotent).
- **Narration templates** for offers, check-ins, reviews, adjustments, progress; all pass the validators (numbers from findings, no causal claims, Phase 4 pressure-phrase check).
- **Refusals:** betting, wagers, "challenge my friend for money", lottery-style rewards → typed refusal with what FinCo offers instead.
- **Timeline** entries for offers, starts, check-ins, adjustments, reviews, XP and badges.
- **MCP** (if present): expose only the read tools (`list_experiments`, `experiment_progress`, `progress_summary`).

### 5.12 CLI (and API if present)
| Command | Does |
|---|---|
| `copilot experiments design/start/list/show/pause/resume/abandon/checkin/review/feedback/tick` | experiments end to end |
| `copilot challenges offers/accept/dismiss` | weekly offers |
| `copilot adjustments list/accept/reject` | adaptive proposals |
| `copilot progress [--json]` | XP, level, badges, personal bests, streaks |
| `copilot goals decompose <goal_id>` | candidate experiments for a goal gap |
| `copilot learning show/reset --subject challenge_template` | offer policy state |
| `copilot sim run --policy thompson|greedy|random --weeks 52 --persona ...` | offline policy simulation (evaluation only) |

---

## 6. Synthetic data v5 and the user simulator
**Transaction-level (for measurement tests):** extend the generator, keeping v1 to v4 unchanged:
- a persona who genuinely changes behaviour during an experiment window (for example delivery spend 35% lower for 2 weeks), a **null-effect** persona whose spend stays within its usual pattern, a persona with a festival exception inside the window, and one who recategorises transactions out of the target category during the window
- hidden ground truth: true effect per window, true exception days

**Decision-level simulator** (`eval/sim/`): personas with latent probabilities of accepting, completing and finding helpful each (template, difficulty), with drift (preferences change after N weeks). Used only for policy evaluation: cumulative reward, regret against the best fixed arm, offers accepted, rest-week behaviour; and to test off-policy estimates (IPS and self-normalised IPS on logged propensities) against the true value.

Dev and held-out seeds listed in config; never tune on held-out.

---

## 7. Stages

### Stage 4.0: Discover, align, adapt
**Build:** read code and docs; fill `docs/phase4_alignment.md` (0.7 table); list Phase 3 stages and status; record the baseline test run (real output); config skeletons with Pydantic validation: `experiments.yaml`, `baseline.yaml`, `challenges/`, `offers.yaml`, `rewards.yaml`, `badges.yaml`, `streaks.yaml`, `pace.yaml`, `integrity.yaml`, `phase4_safety.yaml` (pressure phrases, forbidden encouragements), defaults from 1.3.
**Tests:** config validation and boundaries (duration 7 and 56 accepted, 6 and 57 rejected; difficulty shares; K ≥ min).
**Done when:** alignment doc complete; baseline green.

### Stage 4.1: Schema and models
**Build:** migrations for section 4; models (`Experiment`, `Hypothesis`, `MetricDef`, `Baseline`, `Checkin`, `Review`, `IntegrityNote`, `AdjustmentProposal`, `Offer`, `XpEvent`, `BadgeAward`, `StreakFreeze`, `PersonalBest`, `Progress`); repo functions filtered by `user_id`.
**Tests:** constraints, uniqueness (`xp_events`, one-time badges), user isolation, JSON round trips, migration on a fresh and on a Phase 3 database with data preserved.
**Done when:** green.

### Stage 4.2: Metric catalogue and baseline engine
**Build:** 5.1 metrics and 5.2 baseline, outcome, rank-p, pace and integrity functions (pure).
**Tests:** every metric on hand-built data (refunds, transfers, duplicates, commitment-matched exclusions, weekday filters); window alignment across month and year boundaries; exclusion reasons; `no_baseline` with 2 windows and a baseline with exactly 3; even-count median rule; rank-p exact values for K = 3 and 6; outcome boundaries (v = low, low − 1 paisa; effect exactly at the minimum and one paisa below); higher-is-better mirroring; pace rounding; integrity threshold boundary; property tests (baseline invariant to ingestion order; low ≤ median ≤ high; rank-p in (0, 1]).
**Done when:** green.

### Stage 4.3: Experiments
**Build:** 5.3 (design, lifecycle, freezing, check-ins, reviews, goal link, tools, policy and capability rows).
**Tests:** lifecycle transitions allowed and forbidden; baseline and metric frozen at start (later recategorisation of history does not change the frozen baseline); review delay; abandon at any point yields a review without negative wording; goal-term statements use Phase 3 maths and never promise completion; agent cannot start, pause or abandon; through-executor tests with audit rows.
**Done when:** green.

### Stage 4.4: Challenge templates and personalisation
**Build:** 5.4 (LLM-composed challenge specs through the router with validation, templates with eval cases as seeds and fallback, triggers, parameter fitting, safety filter, value estimate, goal decomposition; offers created through the policy interface with a temporary greedy policy until 4.9).
**Tests:** scripted fake-LLM specs that name an essential category, an unknown metric, another user's category or an out-of-range duration are rejected and audited; numbers inside LLM specs are ignored and replaced by computed targets; with the LLM unavailable, templates still produce valid offers; each trigger fires on its injected pattern and stays silent otherwise; targets rounded to ₹50 and floored at 50% of median; essential categories never targeted (property test over random category sets); same-category conflict filtered; allocation templates rejected when the calendar low balance would fall below the buffer; cooldown boundary (day 29, 30, 31); goal decomposition never claims completion; offers are drafts only.
**Done when:** green.

### Stage 4.5: Adaptive challenges
**Build:** 5.5 detectors, proposals, auto-pause for exceptions with matching extension, accept/reject tools.
**Tests:** each detector at its boundary; two consecutive `behind` check-ins needed (one is not enough); `raise_target_optional` never auto-applied; auto-pause only for a declared exception and reversible; target in force at the end used for `target_met`; proposals expire.
**Done when:** green.

### Stage 4.6: Self-competition, personal bests and streaks
**Build:** 5.6 (derived bests, comparisons, streaks with grace and freezes).
**Tests:** best detection and ties (earliest wins); grace day exactly at 7-day boundaries; freeze during exceptions; broken streak wording; no comparison with any other user anywhere (scan test over outputs).
**Done when:** green.

### Stage 4.7: Progress and rewards
**Build:** 5.7 (XP allowlist, caps, idempotent awarding job, levels, badges with predicates) and 5.8 safety and copy checks.
**Tests:** static check rejects a rule referencing an essential category, a commitment skip, contribution amounts or transaction volume; awarding twice for the same event writes one row; daily cap boundary; finishing an abandoned-and-reviewed experiment earns the learning XP; integrity confirmation required before `target_met` XP when the threshold is reached; XP never decreases (property test over random event sequences); every template passes the pressure-phrase and forbidden-content scans; mutation checks for the safety rules recorded.
**Done when:** green.
**[GIT CHECKPOINT A]** record `Add experiments, challenges and progress tracking` with exact files in `STATUS.md`. Do not run git. Continue.

### Stage 4.8: Learning loop into memory and recommendations
**Build:** 5.10 (posterior updates, `experiment_outcome` memory, advice evidence and suppression, contribution-plan option, failure export).
**Tests:** posterior updates exact for completed, abandoned and dismissed; memory written with evidence and decays per Phase 3; advice cites outcomes without causal words (validator test); unhelpful templates suppressed for the cooldown; forgotten outcome memories disappear from advice; export writes candidate files.
**Done when:** green.

### Stage 4.9: Offer policy, simulator and off-policy evaluation
**Build:** 5.9 Thompson sampling with seeded draws, propensity estimation, rest weeks; `eval/sim/` personas with drift; policies `thompson`, `greedy` (posterior mean), `random` for comparison; IPS and self-normalised IPS estimators; `copilot sim run`.
**Tests:** same seed → same offers and propensities; propensities sum to at most the number of slots and each lies in (0, 1]; rest-week rule; essential-category arms never present (inherits filter); simulator reproducible; over 52 simulated weeks on dev personas Thompson's regret is below random's (report the numbers; do not assert a margin you did not measure); IPS estimate of a target policy is within the reported error of its simulated true value on held-out seeds.
**Done when:** green; simulation results written to `docs/eval_report_phase4.md` (draft section).

### Stage 4.10: Agent integration
**Build:** 5.11 (intents, skills or templates, CoachAgent, capability rows, runtime jobs, narration templates, refusals, timeline, MCP read tools).
**Tests:** intent accuracy on labelled examples; minimal tool or skill sets; LLM-off and LLM-on give the same facts; adversarial plans selecting Phase 4 write tools rejected and audited; multi-domain question uses CoachAgent alongside the others and degrades gracefully if it fails; jobs idempotent with leases; refusals for betting and lottery-style requests; MCP lists only the read tools.
**Done when:** green.

### Stage 4.11: CLI, API and demo script
**Build:** 5.12 commands; API endpoints or `docs/phase4_api_contract.md`; `docs/demo_script_phase4.md`: seed persona → weekly offers with reasons → accept "delivery cap, medium" → check-ins over simulated weeks (`tick` with an injected clock) → a declared festival exception auto-pauses and extends → review: "lower than all 6 previous comparable fortnights" with range and rank → XP, a badge and a personal best → feedback "helpful" → next week's offers reflect the learning → advice cites the outcome → `progress` → `sim run` comparing policies → timeline.
**Tests:** Typer runner tests for every command and error path; API tests if applicable; demo runs offline with the fake LLM and an injected clock.
**Done when:** green; demo runs.

### Stage 4.12: Evaluation and golden scenarios
**Build:** `copilot eval --phase 4` writing `docs/eval_report_phase4.md` on **held-out seeds** (mean and spread):
- measurement: detection rate of true effects; **false "beyond usual range" rate on null-effect windows** (compare with the theoretical 1/(K+1) before the minimum-effect rule and report how much the rule lowers it); handling of exception windows
- integrity: share of recategorisation-assisted wins flagged
- personalisation: trigger precision/recall vs ground truth; safety-filter violations (must be 0)
- policy: cumulative reward and regret for thompson vs greedy vs random; off-policy estimate error; offers per week; rest-week compliance
- agent: intent accuracy, tool minimality, trajectory accuracy for Phase 4 intents
- safety: forbidden-content, pressure-phrase and reward-allowlist scans (must be 0 violations)
Golden scenarios in `tests/golden/phase4/` (at least 18), for example: essential category never offered; target floor at 50%; null-effect window reported within usual range; genuine 35% reduction reported beyond usual range with correct rank; `no_baseline` with 2 windows; festival exception excluded from baseline and auto-pauses the active challenge; recategorisation-assisted win asks for confirmation; abandoned experiment still earns learning XP and gets a kind review; XP never awarded twice; `raise_target_optional` never auto-applied; two unhelpful ratings trigger rest weeks; Thompson offers reproducible by seed; refusal of a money bet with a friend; outcome memory cited without causal words; personal best recognised; grace day keeps a streak; no comparison with other users anywhere; MCP shows no write tool.
**Rules:** never tune on held-out seeds; report weak spots plainly.
**Done when:** report generated; golden scenarios green.

### Stage 4.13: Hardening and documentation
**Build:** failure-handling pass (experiment spanning a month and year boundary, user deletes a category used by an active experiment, goal removed mid-experiment, clock jumps over several weeks of missed jobs, all offers dismissed for months, empty history, two runners of the weekly offer job); logging review (no user notes, merchant text or memory statements in logs or spans); README Phase 4 section with diagrams (experiment loop: plan → act → observe → revise → review → learn; offer policy; reward allowlist); update `docs/architecture_agentic.md` (long-horizon loop, bandit with exploration, propensities, off-policy evaluation, simulator, human-in-the-loop opt-in) and `docs/learning_agents.md`; capability matrix regenerated; mutation checks recorded; final `decisions.md`, `STATUS.md`, `known_issues.md`.
**Done when:** section 9 all green.
**[GIT CHECKPOINT B]** record `Add experiment learning loop and coaching agent` with exact files in `STATUS.md`. Do not run git.

---

## 8. Safety rules that must each have a failing-when-removed test
1. Essential categories are never reduction targets in offers, custom experiments or goal decompositions.
2. Targets never fall below the configured floor of the baseline median.
3. No reward rule references a forbidden metric or category class; XP never decreases; no random rewards exist.
4. No template contains pressure phrases or encouragement to skip essentials or commitments.
5. Outcome wording never makes causal claims; "beyond usual range" requires both `v < low` and the minimum effect.
6. Nothing starts, tightens or ends without a user action; the only automatic change is an exception pause, which is visible and reversible.
7. Recategorisation-assisted wins above the integrity threshold require user confirmation before `target_met` XP.
8. Same seed → same offers and propensities; propensities are logged for every shown offer.
9. No comparison with other users anywhere.
10. Planner and MCP cannot reach any Phase 4 write tool.
11. Challenges, rewards and experiments never move, lock or reserve money.
12. Phase 3 learning floors on financial warnings remain untouched.

---

## 9. Phase 4 exit checklist
- [ ] Full suite and lint green; Phase 0 to 3 tests unchanged and green
- [ ] `docs/phase4_alignment.md` lists every adaptation applied
- [ ] Migrations apply on a fresh and on a Phase 3 database with data preserved
- [ ] Metrics, baselines, rank-p, outcomes, pace and integrity tested at every boundary
- [ ] Experiments: full lifecycle, frozen definitions, check-ins, reviews, goal link
- [ ] Personalised challenges with triggers, fitted targets, safety filter, goal decomposition
- [ ] Adaptive proposals; only the exception pause is automatic
- [ ] Personal bests, comparisons and forgiving streaks; no social comparison
- [ ] XP allowlist, idempotent awards, levels, badges; safety and copy scans clean
- [ ] Learning loop into posteriors, memory and recommendations; failure export
- [ ] Thompson sampling with seeded draws and logged propensities; simulator; off-policy evaluation
- [ ] Agent: intents, skills, CoachAgent, jobs, narration, refusals, timeline, MCP read tools
- [ ] CLI (and API if present); demo runs offline
- [ ] Evaluation report on held-out seeds, including the measured false-positive rate and policy regret; golden scenarios green
- [ ] Mutation checks for section 8 recorded
- [ ] Exactly two proposed commits recorded; no git command run; no AI attribution anywhere

---

## 10. Explicitly NOT in Phase 4
- Leaderboards, friends, sharing, group challenges, social comparison (Phase 5)
- Push, SMS, WhatsApp or email delivery of check-ins and offers (Phase 6); Phase 4 uses the in-app inbox and CLI only
- Cash, cashback, coupons, points with monetary value, lotteries, loot boxes, any random reward
- Challenges about investing, trading or borrowing
- Training or fine-tuning any model
- Changing users' budgets, buckets or goals automatically as a result of an experiment

## 11. Extension points Phase 4 must leave
| Built now | Used later by |
|---|---|
| Metric catalogue and baseline engine | Phase 5 group goals (each member's own baseline), Phase 7 evaluation of interventions |
| Experiments and reviews | Phase 6 conversational check-ins over messaging |
| Offer policy with propensities | Phase 7 risk-aware intervention policies, evaluated offline first |
| User simulator and off-policy estimators | Every future learning policy |
| XP/badge allowlist and safety scans | Phase 5 opt-in social goals (relative progress only) |
| CoachAgent specialist | Phase 6 conversational coach |
