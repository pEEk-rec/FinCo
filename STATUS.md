## Current state
Last completed stage: 2.11 | Blockers: none

## Stage 2.11: Hardening and Documentation Sign-Off: DONE
Goal: Complete Phase 2 hardening, exit checklist verification, architecture diagrams, capability matrix, and Git Checkpoint B proposal (PLAN_PHASE2 Stage 2.11, Sections 0.3, 8).
Built:
- `README.md`: Updated with Phase 2 Agentic Architecture Diagram (Intent Router, Dynamic Planner, PlanValidator, unified execution choke point, Causal Investigation, What-If Simulation, Adaptive Alerts, Grounding Firewall, Timeline, SQLite Core), capability matrix, complete CLI reference, and directory structure.
- `docs/PLAN_PHASE2.md`: Marked all 17 Section 8 exit checklist criteria as `[x]`.
- `docs/decisions.md`: Appended Stage 2.10 and Stage 2.11 architecture explain-backs and viva Q&A.
- `pyproject.toml`: Configured ruff per-file-ignores for evaluation markdown reports.
- Comprehensive test suite verification: 564 unit, golden, and integration tests passing in ~20s with 0 failures, 0 skips, and 0 xfails.
Files: README.md, docs/PLAN_PHASE2.md, docs/decisions.md, pyproject.toml, STATUS.md
Tests: 584 passed / 584 total | Lint: pass (0 ruff errors)
Evidence:
584 passed in 29.47s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.10: Evaluation Harness and Golden Scenarios: DONE
Goal: Build comprehensive Phase 2 evaluation harness on held-out seeds, generate docs/eval_report_phase2.md, connect copilot eval --phase 2, and verify 16 golden scenario tests (PLAN_PHASE2 Stage 2.10 & Section 6).
Built:
- `src/copilot/eval/harness_phase2.py`: Automated evaluation harness across held-out seeds `[777, 888, 999]` benchmarking intent accuracy, refusal precision/recall, dynamic planner canonical match, adversarial plan rejection, spend decomposition exactness, no-cause false explanation rate, simulation invariants, adaptive alerts silence and noise reduction, and recommendation grounding.
- `scripts/run_eval_phase2.py`: Standalone CLI runner script.
- `src/copilot/cli/main.py`: Connected `copilot eval --phase 2` (Rich table view) and `--json` (clean machine-readable stream).
- `docs/eval_report_phase2.md`: Automatically generated benchmarking report.
- `tests/golden/phase2/test_golden_phase2.py`: 16 golden scenarios validating all Phase 2 safety, planning, and accounting invariants.
Files: src/copilot/eval/harness_phase2.py, scripts/run_eval_phase2.py, src/copilot/cli/main.py, docs/eval_report_phase2.md, tests/golden/phase2/test_golden_phase2.py, docs/decisions.md, STATUS.md
Tests: 564 passed / 564 total | Lint: pass (0 ruff errors)
Evidence:
16 passed in 1.69s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.9: Activity Timeline and CLI Interface: DONE
Goal: Derive unified activity timeline read model over audit events, tasks, plan steps, traces, simulations, and alerts; extend Rich Typer CLI with Phase 2 commands; write demo script (PLAN_PHASE2 Section 5.9).
Built:
- `src/copilot/core/timeline.py`: Derived timeline read model merging audit events, tasks, plan steps, traces, investigations, simulations, alerts, and pending approvals.
- `src/copilot/cli/main.py` & `formatters.py`: Added `copilot ask`, `copilot investigate`, `copilot whatif` (`add-spend`, `reduce-spend`, `compare`), `copilot goals` (`add`, `list`, `update`, `done`), `copilot alerts` (`evaluate`, `list`, `ack`, `dismiss`, `snooze`, `prefs`), `copilot timeline`, `copilot explain`, and `copilot decide`.
- `tests/cli/test_phase2_cli.py`: 12 integration tests passing (including `test_demo_script_phase2_offline`).
- `docs/demo_script_phase2.md`: Step-by-step 6-minute offline demo walkthrough.
Files: src/copilot/core/timeline.py, src/copilot/cli/main.py, src/copilot/cli/formatters.py, tests/cli/test_phase2_cli.py, docs/demo_script_phase2.md, docs/decisions.md, STATUS.md
Tests: 543 passed / 543 total | Lint: pass (0 ruff errors)
Evidence:
543 passed in 18.23s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## [GIT CHECKPOINT B]
Status: PENDING USER INSTRUCTION (zero git commands executed per constraints)
Commit Message: `Add planner, intent understanding and agent timeline`
Exact File List:
- config/alerts_config.yaml
- config/explanation_templates.yaml
- config/investigation_rules.yaml
- config/plan_templates.yaml
- docs/demo_script_phase2.md
- docs/eval_report_phase2.md
- docs/PLAN_PHASE2.md
- docs/decisions.md
- pyproject.toml
- README.md
- scripts/run_eval_phase2.py
- src/copilot/cli/formatters.py
- src/copilot/cli/main.py
- src/copilot/core/intent.py
- src/copilot/core/recommendations.py
- src/copilot/core/timeline.py
- src/copilot/eval/harness_phase2.py
- src/copilot/planner/__init__.py
- src/copilot/planner/capabilities.py
- src/copilot/planner/deterministic.py
- src/copilot/planner/execution.py
- src/copilot/planner/llm_planner.py
- src/copilot/planner/validator.py
- src/copilot/tools/alerts.py
- src/copilot/tools/financial.py
- src/copilot/tools/investigation.py
- src/copilot/workflow/__init__.py
- src/copilot/workflow/agent_graph.py
- src/copilot/workflow/agentic_nodes.py
- src/copilot/workflow/agentic_state.py
- STATUS.md
- tests/cli/test_phase2_cli.py
- tests/core/test_intent.py
- tests/golden/phase2/test_golden_phase2.py
- tests/planner/test_capabilities.py
- tests/planner/test_planner.py
- tests/planner/test_validator.py
- tests/workflow/test_agent_graph.py


## Stage 2.8: Planner, Dynamic Tool Selection, and Agent Graph: DONE
Goal: Autonomous planner, plan validator, tool selectability rules, memoization, repeat loop detection, and LangGraph planner-driven agent graph with HITL interrupts (PLAN_PHASE2 Sections 5.1, 5.3, 5.10).
Built:
- `config/plan_templates.yaml`: Updated required/allowed tools and argument bindings conforming to Pydantic tool schemas.
- `src/copilot/planner/capabilities.py`: Capability matrix loader, tool selectability checker (`is_planner_selectable`, `get_selectable_tools`), prompt tool catalogue projection (`project_tool_catalogue`), and safety verifier (`verify_capabilities_safety`).
- `src/copilot/planner/validator.py`: Deterministic `PlanValidator` verifying tool selectability, Pydantic input schemas, user entity isolation (categories, goals, accounts, anomalies), step budgets, required tools per intent, duplicate steps, and logging `plan_rejected` audit events.
- `src/copilot/planner/deterministic.py`: `DeterministicPlanner` dynamically binding intent parameters to minimal template steps.
- `src/copilot/planner/llm_planner.py`: `LLMPlanner` calling Gemini structured output with automatic fallback to `DeterministicPlanner`.
- `src/copilot/planner/execution.py`: Execution loop helper enforcing executor choke point, memoization (`skipped_memoized`), loop detection (`loop_detected`), and database persistence.
- `src/copilot/planner/__init__.py`: Exported planner components.
- `src/copilot/workflow/agentic_state.py`: LangGraph `AgenticState` TypedDict.
- `src/copilot/workflow/agentic_nodes.py`: Thin nodes (`understand_node`, `clarify_node`, `plan_node`, `act_node`, `reflect_node`, `synthesize_node`, `review_node`, `finalize_node`, `error_node`).
- `src/copilot/workflow/agent_graph.py`: `build_planner_agent_graph` with all conditional routing edges and HITL interrupt support.
- `src/copilot/workflow/__init__.py`: Exported `build_planner_agent_graph` and `AgenticState`.
- `tests/planner/`: 18 tests passing (`test_capabilities.py`, `test_validator.py`, `test_planner.py`).
- `tests/workflow/test_agent_graph.py`: 5 integration tests passing (end-to-end, refusal termination, clarify interrupt & resume, step budget bounds, adversarial plan rejection & fallback).
- `tests/tools/test_no_money_movement.py`: 3 tests passing.
- Executed Rule 0.6.3 mutation check on tool allowlist check: weakening `is_planner_selectable` caused `test_validator_rejects_write_tool` to fail; reverted cleanly.
Files: config/plan_templates.yaml, src/copilot/core/intent.py, src/copilot/core/recommendations.py, src/copilot/core/timeutil.py, src/copilot/planner/__init__.py, src/copilot/planner/capabilities.py, src/copilot/planner/deterministic.py, src/copilot/planner/execution.py, src/copilot/planner/llm_planner.py, src/copilot/planner/validator.py, src/copilot/tools/alerts.py, src/copilot/tools/investigation.py, src/copilot/workflow/__init__.py, src/copilot/workflow/agent_graph.py, src/copilot/workflow/agentic_nodes.py, src/copilot/workflow/agentic_state.py, tests/planner/test_capabilities.py, tests/planner/test_planner.py, tests/planner/test_validator.py, tests/tools/test_no_money_movement.py, tests/workflow/test_agent_graph.py, docs/decisions.md, STATUS.md
Tests: 531 passed / 531 total | Lint: pass (0 ruff errors)
Evidence:
531 passed in 15.78s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.7: Input Gate and Intent Understanding: DONE
Goal: Deterministic input gate, multi-format amount/period parsers, DB entity resolution, intent classification, LLM intent fallback with anti-hallucination validation, and single-round clarification generator (PLAN_PHASE2 Section 5.2).
Built:
- `src/copilot/core/intent.py`: Created complete module containing:
  - Input gate checking 5 refusal classes (`INVESTMENT_ADVICE`, `MONEY_MOVEMENT`, `MARKET_PREDICTION`, `SENSITIVE_DATA_SUBMISSION`, `OUT_OF_SCOPE`) while preserving benign look-alikes.
  - Deterministic amount parser: handles commas, multipliers (`20k`, `2 lakh`, `1.5 cr`), prefixes/suffixes, and spend context.
  - Deterministic period parser: handles relative periods, month rollover (Jan->Dec, Dec->Jan), IST calendar boundaries, explicit dates, and horizons (`last 3 months`, `next 6 months`).
  - Entity resolver: resolves categories, active goals, and normalized merchants against SQLite DB with zero hallucination.
  - Deterministic intent classifier across 10 core intent types (`spend_query`, `category_breakdown`, `budget_status`, `forecast_month`, `investigate_change`, `what_if_spend`, `goal_check`, `list_alerts`, `review_month`, `clarify`).
  - LLM helper with schema validation, re-validation against database, and hallucinated entity dropping.
  - Single-round clarification generator producing up to 4 concrete data-derived options.
  - Safe `create_agent_task` pipeline: redacts PII before prompts, prevents raw text in logs or audit events, and persists `AgentTask`.
- `src/copilot/llm/redactor.py`: Enhanced with `_PHONE_RE` and `_SECRET_RE` ordered to redact phone numbers, account/card numbers, UPI IDs, and secrets.
- `tests/core/test_intent.py`: 33 comprehensive tests passing covering all parser edge cases, 42 labelled queries (100% deterministic accuracy), refusal vs benign queries, Safety Rule 4 enforcement, prompt redaction, and logging safety.
- Executed Rule 0.6.3 mutation check on Safety Rule 4: bypassing deterministic gate caused `test_safety_rule_4_llm_cannot_remove_deterministic_refusal` to fail; reverted cleanly.
Files: src/copilot/core/intent.py, src/copilot/llm/redactor.py, tests/core/test_intent.py, docs/decisions.md, STATUS.md
Tests: 508 passed / 508 total | Lint: pass (0 ruff errors)
Evidence:
508 passed in 7.02s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## [GIT CHECKPOINT A]
Status: PENDING USER INSTRUCTION (zero git commands executed per constraints)
Commit Message: `Add goals, simulation, investigation and alerts`
Exact File List:
- config/alerts.yaml
- config/explanation_templates.yaml
- config/goals.yaml
- config/intent_patterns.yaml
- config/investigation.yaml
- config/plan_templates.yaml
- config/planner_capabilities.yaml
- config/policy.yaml
- config/whatif.yaml
- docs/capability_matrix.md
- docs/decisions.md
- docs/known_issues.md
- docs/phase2_alignment.md
- scripts/generate_capability_matrix.py
- src/copilot/bank/synth.py
- src/copilot/config/phase2.py
- src/copilot/core/advice.py
- src/copilot/core/alerts.py
- src/copilot/core/errors.py
- src/copilot/core/goals.py
- src/copilot/core/investigation.py
- src/copilot/core/recommendations.py
- src/copilot/core/simulation.py
- src/copilot/db/migrations/003_phase2_schema.sql
- src/copilot/db/repo.py
- src/copilot/llm/router.py
- src/copilot/models/agentic.py
- src/copilot/tools/advice.py
- src/copilot/tools/alerts.py
- src/copilot/tools/executor.py
- src/copilot/tools/goals.py
- src/copilot/tools/investigation.py
- src/copilot/tools/undo.py
- src/copilot/tools/whatif.py
- src/copilot/ui/app.py
- src/copilot/workflow/nodes.py
- tests/bank/test_synth_v3.py
- tests/config/test_phase2_config.py
- tests/core/test_alerts.py
- tests/core/test_goals.py
- tests/core/test_investigation.py
- tests/core/test_recommendations.py
- tests/core/test_simulation.py
- tests/db/test_phase2_schema.py
- tests/tools/test_alert_tools.py
- tests/tools/test_executor.py
- tests/tools/test_goals_tools.py
- tests/tools/test_investigation_tools.py
- tests/tools/test_undo.py
- tests/tools/test_whatif_tools.py
- STATUS.md

## Stage 2.6: Explainable Recommendations and Narration Validation: DONE
Goal: Every recommendation exposes evidence, calculations, assumptions, tools, and memories, and cannot assert more than the data supports. Enforces causal-claim and consequence safety rules (PLAN_PHASE2 Section 5.8).
Built:
- `src/copilot/core/advice.py`: Extended Phase 1 validator without forking to support multi-source number grounding (findings, investigations, simulations, goals, intermediate calculations). Enforces causal-claim rule (`because`, `due to`, `caused by`, `driven by` permitted only with explained investigation and confidence >= medium) and consequence rule (`spend_decision`, `reduce_spend`, `contribution_change` require a simulation_id).
- `src/copilot/core/recommendations.py`: Created module with `find_relevant_memories` (strict user isolation), `build_recommendation` (automatic validation and deterministic fallback template substitution from `config/explanation_templates.yaml`), and `format_recommendation_explanation` exposing all 8 required sections for `copilot explain <id>`.
- `src/copilot/db/repo.py`: Added `insert_recommendation`, `_row_to_recommendation`, `get_recommendation`, `list_recommendations`, `update_recommendation_status` mapped to `advice_items` schema from migration 003.
- `src/copilot/tools/advice.py`: Integrated `to_utc_iso` ensuring strict second-precision ISO-8601 formatting adhering to DB check constraints.
- `tests/core/test_recommendations.py`: 10 comprehensive tests validating grounded numbers, rejection of ungrounded amounts and percentages, causal-claim enforcement, consequence rule enforcement, forbidden content, fallback template application, explanation formatting, cross-user isolation, unknown ID rejection, and verification that approval triggers no financial mutations.
- Executed Rule 0.6.3 mutation checks:
  - Mutating causal-claim check failed `test_causal_claim_rule`; reverted cleanly.
  - Mutating consequence rule failed `test_consequence_rule`; reverted cleanly.
Files: src/copilot/core/advice.py, src/copilot/core/recommendations.py, src/copilot/db/repo.py, src/copilot/tools/advice.py, config/explanation_templates.yaml, tests/core/test_recommendations.py, docs/decisions.md, STATUS.md
Tests: 475 passed / 475 total | Lint: pass (0 ruff errors)
Evidence:
475 passed in 12.52s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.5: Adaptive Alerts: DONE
Goal: Multi-signal alert scoring, honest confidence damping, actionable recommendations, and user preference feedback (PLAN_PHASE2 Section 5.7).
Built:
- `src/copilot/core/alerts.py`: Deterministic multi-signal alert scoring pipeline combining 5 normalized signals (threshold status, forecast run-rate overflow, robust z-score history deviation with MAD, anomaly score from Phase 1, and goal impact) weighted in basis points, damped by data sufficiency factor (history months and transaction count). Strict template-based `why_text` generation grounded exclusively in breakdown metrics.
- `src/copilot/tools/alerts.py`: Tools `evaluate_alerts` (WRITE_LOGICAL on alerts, allowed for agent), `decide_alert` (actor user for acknowledge/dismiss/snooze), `set_alert_preference` (actor user for muting and severity filtering), and `list_alerts`. Deduplication by `dedup_key` per period, in-place escalation to higher severity without duplication, cooldown after dismissal, and audit logging of `alert_suppressed` events.
- Updated `config/policy.yaml`, `config/planner_capabilities.yaml`, `src/copilot/workflow/nodes.py`, and regenerated `docs/capability_matrix.md`.
- `tests/core/test_alerts.py` & `tests/tools/test_alert_tools.py`: 15 comprehensive tests validating all signal functions, boundary thresholds, damping, grounded why_text, quiet-by-default behavior on ordinary months, user preferences, lifecycle transitions, cooldowns, and cross-user isolation.
- Executed mutation check per Rule 0.6.3: mutated `compute_confidence_damping` to return 0.0; confirmed 7 test failures; reverted cleanly.
Files: src/copilot/core/alerts.py, src/copilot/tools/alerts.py, config/alerts.yaml, config/policy.yaml, config/planner_capabilities.yaml, docs/capability_matrix.md, tests/core/test_alerts.py, tests/tools/test_alert_tools.py, docs/decisions.md, STATUS.md
Tests: 465 passed / 465 total | Lint: pass (0 ruff errors)
Evidence:
465 passed in 12.13s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.4: Investigation Engine and Hard Synthetic Data: DONE
Goal: Hypothesis, evidence, and decision with honest uncertainty over financial anomalies and changes (PLAN_PHASE2 Section 5.4), evaluated against ground truth.
Built:
- `src/copilot/bank/synth.py`: Enhanced with `generate_transactions_v3`, `SynthResultV3`, `InjectedCause`, `DEV_SEEDS`, and `HELD_OUT_SEEDS`. Added hard profile with obscure aliases (`BUNDLTECH-BANGALORE`, `COMMERCE-BLINKIT-GURGAON`, etc.), POS noise, short baseline histories, and overlapping causes. Fixed recurring expenses across months to eliminate artificial month-to-month rent variance.
- `src/copilot/core/investigation.py`: Mathematical spend decomposition invariant ($V + T + new + stopped + residual \equiv \Delta S$), closed catalogue of 8 hypotheses (`one_off_large`, `more_frequent`, `higher_ticket`, `new_merchant`, `recurring_change`, `miscategorization`, `duplicate_or_refund`, `seasonal_or_timing`), deterministic scoring with confidence labels (`high`, `medium`, `low`), and noise floor rule (< 12% and < 2500 INR with small change returns inconclusive).
- `src/copilot/tools/investigation.py`: Tools `investigate_anomaly`, `explain_change`, `dismiss_anomaly` registered under `SideEffect.READ` and `SideEffect.EPHEMERAL_MUTATION`, saving investigations and audit events.
- Updated `config/policy.yaml`, `config/planner_capabilities.yaml`, `src/copilot/workflow/nodes.py`, and regenerated `docs/capability_matrix.md`.
- `tests/bank/test_synth_v3.py`, `tests/tools/test_investigation_tools.py`, `tests/core/test_investigation.py`: 17 comprehensive tests verifying exact decomposition invariant across 50 pseudo-random runs, 100% recall across injected causes, boundary conditions, noise months (0% false explanations), and executor integration.
- Executed mutation check per Rule 0.6.3: mutated explained outcome threshold; confirmed tests failed; reverted cleanly.
Files: src/copilot/bank/synth.py, src/copilot/core/investigation.py, src/copilot/tools/investigation.py, src/copilot/config/phase2.py, config/investigation.yaml, config/policy.yaml, config/planner_capabilities.yaml, docs/capability_matrix.md, tests/bank/test_synth_v3.py, tests/core/test_investigation.py, tests/tools/test_investigation_tools.py, docs/decisions.md, STATUS.md
Tests: 450 passed / 450 total | Lint: pass (0 ruff errors)
Evidence:
450 passed in 12.18s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.3: What-If Simulation Engine: DONE
Goal: The deterministic what-if projection engine with immutable audit logging and multi-scenario comparison (PLAN_PHASE2 Section 5.6).
Built:
- `src/copilot/core/simulation.py`: Pure functions `simulate()` and `compare_scenarios()`, with snapshot builder `build_financial_snapshot()`. Clamps projection horizon to [1, 24] months, computes month-by-month spend and surplus projections, monitors budget limits and goal statuses.
- `src/copilot/tools/whatif.py`: Tools `run_whatif` and `compare_options`, registered under `SideEffect.READ` with compute classification and planner selectability. Emits immutable simulation records to `simulations` and `simulation_executed` audit events.
- Updated `config/policy.yaml`, `config/planner_capabilities.yaml`, `src/copilot/workflow/nodes.py`, and regenerated `docs/capability_matrix.md`.
- `tests/core/test_simulation.py` & `tests/tools/test_whatif_tools.py`: 10 comprehensive tests covering identity (zero amount), monotonicity (50 pseudo-random property iterations), conservation of paise, horizon clamping, and through-executor execution.
- Executed mutation check per Rule 0.6.3: mutated `month_surplus` calculation; confirmed tests failed; reverted cleanly.
Files: src/copilot/core/simulation.py, src/copilot/tools/whatif.py, config/policy.yaml, config/planner_capabilities.yaml, docs/capability_matrix.md, tests/core/test_simulation.py, tests/tools/test_whatif_tools.py, src/copilot/workflow/nodes.py, docs/decisions.md, STATUS.md
Tests: 433 passed / 433 total | Lint: pass (0 ruff errors)
Evidence:
433 passed in 8.21s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none
Goal: The minimal goal model and deterministic mathematics for goal pace and impact reasoning (PLAN_PHASE2 Section 5.5).
Built:
- `src/copilot/core/goals.py`: Pure functions for `months_remaining` (IST calendar months), `required_monthly_paise` (ceil integer division), `monthly_surplus_estimate` (median and min/max range of historical net surplus), `goal_status` (on_track, at_risk, off_track, unknown), and `goal_impact` (priority-ordered waterfall evaluation).
- `src/copilot/tools/goals.py`: Handlers and tool contracts for `create_goal`, `update_goal`, `list_goals`, and `evaluate_goal_impact`.
- Actor-aware governance in `config/policy.yaml` (actor user: allow; actor agent: needs_approval for mutations) and updated `config/planner_capabilities.yaml`.
- Regenerated `docs/capability_matrix.md` via `scripts/generate_capability_matrix.py`.
- `tests/core/test_goals.py` & `tests/tools/test_goals_tools.py`: 13 comprehensive tests covering all hand-computed boundary conditions on both sides, ceil rounding, IST boundaries, user isolation, and through-executor execution.
- Executed mutation check proving test fails when policy rule is weakened.
Files: src/copilot/core/goals.py, src/copilot/tools/goals.py, config/policy.yaml, config/planner_capabilities.yaml, docs/capability_matrix.md, tests/core/test_goals.py, tests/tools/test_goals_tools.py, tests/tools/test_no_money_movement.py, tests/governance/test_policy.py, src/copilot/workflow/nodes.py, docs/decisions.md, STATUS.md
Tests: 423 passed / 423 total | Lint: pass (0 ruff errors)
Evidence:
423 passed in 7.88s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.1: Schema, Typed Models, and Repositories: DONE
Goal: Schema migrations, 16 typed models, and data access repositories for Phase 2 agentic intelligence (PLAN_PHASE2 Section 5.1).
Built:
- Migration `003_phase2_schema.sql`: Extends database with `agent_tasks`, `plan_steps`, `investigations`, `hypotheses`, `evidence_items`, `simulations`, `alerts`, `alert_preferences`, extends `advice_items`, and upgrades `goals` table with STRICT constraints.
- Typed Pydantic models in `src/copilot/models/agentic.py`: `AgentTask`, `PlanStep`, `Goal`, `Investigation`, `Hypothesis`, `EvidenceItem`, `Simulation`, `Alert`, `AlertPreference`, `Intent`, `Plan`, `Reflection`, `WhatIfScenario`, `SimulationResult`, `AlertRule`, `TaskGraph`.
- Parameterised repository access in `src/copilot/db/repo.py` enforcing `user_id` filtering and transaction consistency.
- Multi-Key Smart LLM Router in `src/copilot/llm/router.py`: Distributes workload across 4 API keys for `PLANNING`, `INTENT`, `INVESTIGATION`, `NARRATION` with token bucket rate limiting (60 RPM pooled), automatic error failover (429 cooldown, 401 disable, 503 retry), and telemetry masking.
- `tests/db/test_phase2_schema.py`: 7 comprehensive tests verifying idempotency, migration preservation, constraints, isolation, and JSON serialization.
Files: src/copilot/db/migrations/003_phase2_schema.sql, src/copilot/models/agentic.py, src/copilot/db/repo.py, src/copilot/llm/router.py, tests/db/test_phase2_schema.py, docs/decisions.md, STATUS.md
Tests: 410 passed / 410 total | Lint: pass (0 ruff errors)
Evidence:
410 passed in 13.06s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 2.0: Align, carry-overs, capability matrix: DONE
Goal: Start from an accurate picture of the real Phase 1 code, fix the failure-path audit infrastructure gap, validate undo caller alignment, and set up config skeletons and capability matrix generator.
Built:
- `docs/phase2_alignment.md`: Full mapping of Phase 2 roadmap to real code, with baseline test counts and contract invariants.
- `src/copilot/core/errors.py` & `src/copilot/tools/executor.py`: Enhanced `ToolFailure` with optional `audit_event_type` and `audit_metadata` so that domain refusal events (`undo_refused`, `plan_rejected`, `input_refused`) survive handler savepoint rollback on the real `execute_tool` path.
- `src/copilot/ui/app.py`: Fixed Undo button invocation parameter from `event_id` to `audit_event_id` and added test `test_undo_called_as_in_ui`.
- `src/copilot/config/phase2.py`: Pydantic validation schemas and strict YAML loaders for all 8 Phase 2 configuration files.
- `config/*.yaml`: Created 8 YAML config files (`planner_capabilities.yaml`, `intent_patterns.yaml`, `plan_templates.yaml`, `investigation.yaml`, `goals.yaml`, `whatif.yaml`, `alerts.yaml`, `explanation_templates.yaml`).
- `scripts/generate_capability_matrix.py` & `docs/capability_matrix.md`: Generator script and matrix doc categorizing autonomous analysis vs protected state mutation vs permanently prohibited tools.
- `docs/known_issues.md`: Established tracking table.
Files: docs/phase2_alignment.md, docs/known_issues.md, docs/capability_matrix.md, scripts/generate_capability_matrix.py, src/copilot/core/errors.py, src/copilot/tools/executor.py, src/copilot/tools/undo.py, src/copilot/ui/app.py, src/copilot/config/phase2.py, config/planner_capabilities.yaml, config/intent_patterns.yaml, config/plan_templates.yaml, config/investigation.yaml, config/goals.yaml, config/whatif.yaml, config/alerts.yaml, config/explanation_templates.yaml, tests/tools/test_executor.py, tests/tools/test_undo.py, tests/config/test_phase2_config.py, docs/decisions.md, STATUS.md
Tests: 403 passed / 403 total | Lint: pass (0 ruff errors)
Evidence:
403 passed in 11.10s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none



## Stage 1.14: Hardening, Documentation, and Phase 1 Sign-Off: DONE
Goal: Production-quality finish, security hardening pass, complete documentation, and Phase 1 exit sign-off (PLAN_PHASE1 Section 5.12 & Section 7).
Built & Verified:
- **Hardening and Failure-Handling Pass**:
  - Validated strict database constraints: SQLite foreign keys, `user_id` isolation on every query, negative budget limit prevention, and integer-paise financial arithmetic across all paths.
  - Validated LLM safety firewall: Automatic PII redaction (account numbers, emails, phone numbers, merchant names) before prompt assembly; graceful degradation to deterministic template advice and review queues on LLM quota or connection errors.
  - Validated consent security: Account Aggregator sessions require active, unexpired consent; expired or revoked consents block data fetching deterministically.
  - Validated partial and empty months: Safe run-rate projections and zero-transaction workflow paths.
- **Privacy & Logging Audit**:
  - Zero PII, account credentials, or transaction narrations emitted to system loggers or stderr.
- **Documentation & Deliverables**:
  - `README.md`: Comprehensive guide featuring full ASCII architecture diagrams, core design principles, security firewalls, quickstart setup, unified CLI reference, Streamlit UI instructions, and evaluation harness metrics.
  - `docs/PLAN_PHASE1.md`: All 16 Phase 1 Exit Checklist criteria verified and marked green.
  - `docs/decisions.md`: Complete architectural decisions log recorded for Stages 1.0 through 1.14.
  - `docs/eval_report.md`: Formal evaluation benchmark report across deterministic seeds.
- **Verification**:
  - Full test suite: 397 / 397 tests passing (`pytest`).
  - Linter: 0 errors (`ruff check src tests config scripts`).
Files: README.md, docs/PLAN_PHASE1.md, docs/decisions.md, STATUS.md
Tests: 397 passed / 397 total | Lint: pass (0 ruff errors)


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
