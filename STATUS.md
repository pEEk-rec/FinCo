## Current state
Last completed stage: 3.18 (Phase 3 100% COMPLETE) | Blockers: none

## [GIT CHECKPOINT B]
Status: PENDING USER INSTRUCTION (zero git commands executed per constraints)
Commit Message: `Advanced Financial Copilot complete: multi-agent, memory, MCP, calendar, buckets`
Exact File List:
- config/buckets.yaml
- config/calendar.yaml
- config/commitments.yaml
- config/context.yaml
- config/contributions.yaml
- config/decomposition.yaml
- config/goals.yaml
- config/learning.yaml
- config/mcp.yaml
- config/memory.yaml
- config/ops.yaml
- config/planner_capabilities.yaml
- config/policy.yaml
- config/readiness.yaml
- config/runtime.yaml
- config/skills/affordability_check.yaml
- config/skills/contribution_review.yaml
- config/skills/explain_month_change.yaml
- config/skills/monthly_close.yaml
- config/skills/trip_planning.yaml
- docs/architecture_agentic.md
- docs/capability_matrix.md
- docs/decisions.md
- docs/demo_script_phase3.md
- docs/eval_report_phase3.md
- docs/known_issues.md
- docs/orchestration_paradigms.md
- docs/phase3_alignment.md
- docs/phase3_api_contract.md
- eval/run_eval_phase3.py
- README.md
- src/copilot/api/app.py
- src/copilot/cli/main.py
- src/copilot/config/phase2.py
- src/copilot/config/phase3.py
- src/copilot/context/builder.py
- src/copilot/context/retrieval.py
- src/copilot/core/alerts.py
- src/copilot/core/buckets.py
- src/copilot/core/calendar.py
- src/copilot/core/commitments.py
- src/copilot/core/contributions.py
- src/copilot/core/goals.py
- src/copilot/core/investigation.py
- src/copilot/core/learning.py
- src/copilot/core/memory.py
- src/copilot/core/readiness.py
- src/copilot/core/recommendations.py
- src/copilot/db/migrations/004_phase3_schema.sql
- src/copilot/db/repo.py
- src/copilot/db/repo_phase3.py
- src/copilot/eval/harness_phase3.py
- src/copilot/eval/orchestration_comparison.py
- src/copilot/mcp/__init__.py
- src/copilot/mcp/server.py
- src/copilot/models/agentic.py
- src/copilot/models/phase3.py
- src/copilot/runtime/runner.py
- src/copilot/skills/engine.py
- src/copilot/tools/alerts.py
- src/copilot/tools/buckets.py
- src/copilot/tools/calendar.py
- src/copilot/tools/commitments.py
- src/copilot/tools/contributions.py
- src/copilot/tools/goals.py
- src/copilot/tools/governance.py
- src/copilot/tools/investigation.py
- src/copilot/tools/learning.py
- src/copilot/tools/memory.py
- src/copilot/tools/readiness.py
- src/copilot/tools/registry.py
- src/copilot/tools/skills.py
- src/copilot/workflow/agent_graph.py
- src/copilot/workflow/decomposition.py
- src/copilot/workflow/multi_agent.py
- src/copilot/workflow/nodes.py
- src/copilot/workflow/reviewer.py
- src/copilot/workflow/specialists.py
- src/copilot/workflow/supervisor.py
- STATUS.md
- tests/api/test_phase3_api.py
- tests/config/test_phase3_config.py
- tests/core/test_buckets.py
- tests/core/test_calendar.py
- tests/core/test_commitments.py
- tests/core/test_contributions.py
- tests/core/test_goals.py
- tests/core/test_memory.py
- tests/core/test_memory_decay.py
- tests/core/test_readiness.py
- tests/db/test_phase3_schema.py
- tests/golden/phase3/test_golden_phase3.py
- tests/mcp/test_mcp.py
- tests/skills/test_skills_golden.py
- tests/skills/test_skills_manifest.py
- tests/skills/test_skills_runner.py
- tests/tools/test_buckets_tools.py
- tests/tools/test_calendar_tools.py
- tests/tools/test_commitments_tools.py
- tests/tools/test_contributions_tools.py
- tests/tools/test_goals_tools.py
- tests/tools/test_memory_tools.py
- tests/tools/test_no_money_movement.py
- tests/tools/test_readiness_tools.py
- tests/workflow/test_decomposition.py
- tests/workflow/test_multi_agent.py
- tests/workflow/test_orchestration_comparison.py
- tests/workflow/test_phase3_hardening.py
- tests/workflow/test_reviewer.py
- tests/workflow/test_specialists.py
- tests/workflow/test_supervisor.py

## Stage 3.18: Hardening, Documentation, and Checkpoint B: DONE
Goal: Run failure-handling passes, PII/log sanitization reviews, author `docs/architecture_agentic.md`, update capability matrix & README, verify 100% test pass rate, and record Checkpoint B.
Built:
- `tests/workflow/test_phase3_hardening.py`: 8 comprehensive hardening and failure-handling tests (blank database, deleted category foreign-key cascade, calendar year boundary, leap-year month ends, conflicting memory ranking, all specialists failing gracefully, simulated job crash and lease recovery, and log sanitization).
- `docs/architecture_agentic.md`: In-depth agentic systems architecture document mapping every agentic concept to its concrete source implementation.
- `docs/capability_matrix.md`: Fully updated capability matrix documenting 30 read/compute tools, 24 protected state mutation tools, 4 specialists, 5 skills, and 3 MCP resources.
- `README.md` & `docs/known_issues.md`: Updated capability matrix and future integration items.
- Regression verification: 942 passed out of 942 tests (100% green).
Files:
- `tests/workflow/test_phase3_hardening.py`
- `docs/architecture_agentic.md`
- `docs/capability_matrix.md`
- `docs/known_issues.md`
- `README.md`
- `docs/decisions.md`
- `STATUS.md`

Exact File List:
- config/buckets.yaml
- config/calendar.yaml
- config/commitments.yaml
- config/context.yaml
- config/contributions.yaml
- config/decomposition.yaml
- config/goals.yaml
- config/learning.yaml
- config/mcp.yaml
- config/memory.yaml
- config/ops.yaml
- config/planner_capabilities.yaml
- config/policy.yaml
- config/readiness.yaml
- config/runtime.yaml
- config/skills/affordability_check.yaml
- config/skills/contribution_review.yaml
- config/skills/explain_month_change.yaml
- config/skills/monthly_close.yaml
- config/skills/trip_planning.yaml
- docs/decisions.md
- docs/phase3_alignment.md
- src/copilot/config/phase2.py
- src/copilot/config/phase3.py
- src/copilot/core/alerts.py
- src/copilot/core/buckets.py
- src/copilot/core/calendar.py
- src/copilot/core/commitments.py
- src/copilot/core/contributions.py
- src/copilot/core/goals.py
- src/copilot/core/investigation.py
- src/copilot/core/memory.py
- src/copilot/core/readiness.py
- src/copilot/core/recommendations.py
- src/copilot/db/migrations/004_phase3_schema.sql
- src/copilot/db/repo.py
- src/copilot/db/repo_phase3.py
- src/copilot/models/agentic.py
- src/copilot/models/phase3.py
- src/copilot/tools/alerts.py
- src/copilot/tools/buckets.py
- src/copilot/tools/calendar.py
- src/copilot/tools/commitments.py
- src/copilot/tools/contributions.py
- src/copilot/tools/goals.py
- src/copilot/tools/investigation.py
- src/copilot/tools/memory.py
- src/copilot/tools/readiness.py
- src/copilot/workflow/nodes.py
- STATUS.md
- tests/config/test_phase3_config.py
- tests/core/test_buckets.py
- tests/core/test_calendar.py
- tests/core/test_commitments.py
- tests/core/test_contributions.py
- tests/core/test_goals.py
- tests/core/test_memory.py
- tests/core/test_memory_decay.py
- tests/core/test_readiness.py
- tests/db/test_phase3_schema.py
- tests/tools/test_buckets_tools.py
- tests/tools/test_calendar_tools.py
- tests/tools/test_commitments_tools.py
- tests/tools/test_contributions_tools.py
- tests/tools/test_goals_tools.py
- tests/tools/test_memory_tools.py
- tests/tools/test_no_money_movement.py
- tests/tools/test_readiness_tools.py

## Stage 3.17: CLI, API, Demo Script, and Evaluation: DONE
Goal: Implement Section 5.11 CLI commands, RESTful API endpoints and contract (`docs/phase3_api_contract.md`), comprehensive offline demo script (`docs/demo_script_phase3.md`), evaluation harness (`src/copilot/eval/harness_phase3.py` & `docs/eval_report_phase3.md`), and 24 Phase 3 golden scenarios (`tests/golden/phase3/test_golden_phase3.py`).
Built:
- `src/copilot/cli/main.py`: Integrated commitments, goals status/link-bucket, buckets, calendar, readiness, memories, skills, plan-contributions, trade-offs, and `--phase 3` evaluation flag.
- `src/copilot/api/app.py`: Implemented Phase 3 REST endpoints under `/api/` for commitments, calendar, buckets, readiness, memories, learning, and runtime ops, tested in `tests/api/test_phase3_api.py`.
- `docs/phase3_api_contract.md`: Comprehensive API contract documenting endpoints, request/response models, error codes, and auth headers.
- `docs/demo_script_phase3.md`: Offline walkthrough executing the end-to-end user journey across all Phase 3 capabilities.
- `src/copilot/eval/harness_phase3.py` & `eval/run_eval_phase3.py`: Evaluation runner executing 8 test batteries on held-out seeds, producing `docs/eval_report_phase3.md`.
- `tests/golden/phase3/test_golden_phase3.py`: 24 golden scenario integration tests covering all critical invariants and edge cases from Section 7.
Files:
- `src/copilot/cli/main.py`
- `src/copilot/api/app.py`
- `docs/phase3_api_contract.md`
- `docs/demo_script_phase3.md`
- `src/copilot/eval/harness_phase3.py`
- `eval/run_eval_phase3.py`
- `docs/eval_report_phase3.md`
- `tests/golden/phase3/test_golden_phase3.py`
- `tests/api/test_phase3_api.py`
- `docs/decisions.md`
- `STATUS.md`

## Stage 3.16: Orchestration comparison: DONE
Goal: Implement Section 5.13 & Section 7 Orchestration comparison across paradigms (Phase 1 fixed graph, Phase 2 single planner loop with LLM off and on, Phase 3 supervisor with parallel specialists with LLM off and on, and AutoGen-style conversational multi-agent described), measuring accuracy, sub-question coverage, mean/p95 latency, LLM calls, failure rate, and partial-answer rate on a standardized 10-question evaluation battery, and authoring `docs/orchestration_paradigms.md`.
Built:
- `src/copilot/eval/orchestration_comparison.py`: Benchmark harness running identical evaluation questions across 5 built paradigm variations, recording real empirical metrics, and generating `docs/orchestration_paradigms.md`.
- `src/copilot/workflow/agent_graph.py`: Added `force_single_loop` flag support to allow rigorous A/B comparison of the Phase 2 single planner loop against the Phase 3 multi-agent subgraph on identical multi-domain intents.
- `src/copilot/workflow/decomposition.py`: Fixed `DecompositionValidator.config` attribute access and registered question kind catalogue introspection.
- `docs/orchestration_paradigms.md`: In-depth deliverable detailing empirical benchmark table, qualitative analysis of all four paradigms, trade-off matrix, failure modes, token scaling, and the strategic rationale for the automated routing rule.
- `tests/workflow/test_orchestration_comparison.py`: Regression test suite asserting benchmark execution, architectural invariants (Phase 3 coverage > Phase 2 > Phase 1, Phase 1 lowest latency, 0 LLM calls when LLM off, 0% failure rate across built paradigms), and document generation.
Files:
- `src/copilot/eval/orchestration_comparison.py`
- `src/copilot/workflow/agent_graph.py`
- `src/copilot/workflow/decomposition.py`
- `docs/orchestration_paradigms.md`
- `tests/workflow/test_orchestration_comparison.py`
- `docs/decisions.md`
- `STATUS.md`

## Stage 3.15: MCP server: DONE
Goal: Implement Section 5.17 Model Context Protocol (MCP) server exposing planner-selectable tools over stdio and in-process MCP (FastMCP / MCPServer), with Safety Rule 17 (only planner-selectable read/compute tools and skills; write tools strictly prohibited), execution choke point routing with actor="agent", distributed tracing and audit with kind="mcp", data minimisation flag (mcp.allow_transaction_detail: false default suppressing transaction row details), autonomous ask tool running the agent graph with actor="agent", live resources (finco://monthly_review/latest, finco://calendar/summary, finco://buckets/summary), CLI mcp-serve command, and comprehensive test suite.
Built:
- `src/copilot/mcp/server.py`: Complete MCP server using official SDK (`mcp==2.3.0`), registering 36 selectable read tools with typed Pydantic parameter schemas, `ask` agent query tool running the agent graph, resources for latest monthly reviews, 30-day projected calendar, and virtual buckets allocations, strict choke point dispatch through `execute_tool(ctx, ...)` with `actor="agent"`, distributed span tracing with `kind="mcp"`, data minimisation interceptor for transactions, and stdio server runner `run_mcp_stdio_server`.
- `config/mcp.yaml`: Configuration specifying `server_name: "finco-mcp"`, `protocol_version: "2024-11-05"`, `transport: "stdio"`, `allow_transaction_detail: false`, and `exposed_tools` listing selectable read tools.
- `src/copilot/config/phase3.py`: Added `MCPConfig` with `allow_transaction_detail` and `exposed_tools`, plus `load_mcp_config`.
- `src/copilot/cli/main.py`: Added CLI command `copilot mcp-serve` and subcommand `copilot mcp serve` with `--user-id` and `--db`.
- `tests/mcp/test_mcp.py`: 11 comprehensive tests covering selectable tool listing, write tool absence, Safety Rule 17 dynamic registration rejection, non-exposed tool error handling, data minimisation toggle, audit/tracing with `kind="mcp"`, `ask` tool agent graph invocation, resource listing and reading, injection corpus penetration test, and multi-tenant isolation.
Files:
- `config/mcp.yaml`
- `src/copilot/config/phase3.py`
- `src/copilot/mcp/__init__.py`
- `src/copilot/mcp/server.py`
- `src/copilot/cli/main.py`
- `tests/mcp/test_mcp.py`
- `docs/decisions.md`
- `STATUS.md`

## Stage 3.14: Bounded feedback learning: DONE
Goal: Implement Section 5.16 Bounded feedback learning (explainable learner over explicit tenant feedback signals, integer milli-count Beta posterior, sensitivity multiplier $m = \text{clamp}(1 + \eta(2p-1), m_{\min}, m_{\max})$, hard floor protection per Safety Rule 16 for exceeded budgets, not_covered commitments, and off_track goals, ordering of advice by utility $p$, why-text transparency note only on severity change, learning reset per subject/all, and comprehensive docs/learning_agents.md).
Built:
- `src/copilot/core/learning.py`: Implemented Beta posterior mean computation from integer milli-counts ($\alpha_{\text{milli}}, \beta_{\text{milli}}$), clamped multiplier formula, multi-tenant feedback recording (`record_feedback`), hard floor evaluation (`is_hard_floor_alert`), sensitivity adjustment with floor protection (`apply_learning_to_alert`), advice utility ordering (`order_advice_by_utility`), learning reset (`reset_learning`), and tenant stats inspection (`list_tenant_learning_stats`).
- `src/copilot/db/repo_phase3.py`: Added `get_feedback_stat`, `upsert_feedback_stat`, `list_feedback_stats`, and `delete_feedback_stat`.
- `src/copilot/config/phase3.py`: Updated `load_learning_config` defaulting to `config/learning.yaml`.
- Integration into alert evaluation & actions (`src/copilot/tools/alerts.py`):
  - In `evaluate_alerts_handler`: computes $m$, enforces hard floor, adjusts score and severity, adds explainable why-text note only when severity tier actually changed.
  - In `decide_alert_handler`: `acknowledge` records useful feedback (+1000 $\alpha$); dismissal with contextual reason (`festival`, `travel`, ...) records `contextual_exception` in memory and skips negative feedback; generic dismissal records not-useful feedback (+1000 $\beta$).
  - In `set_alert_preference_handler`: muting category records not-useful feedback (+1000 $\beta$).
- Integration into buckets (`src/copilot/tools/buckets.py`):
  - In `apply_reallocation_handler`: applying approved reallocation records useful feedback (+1000 $\alpha$) for target bucket.
- Integration into advice (`src/copilot/tools/advice.py`):
  - In `draft_advice_handler`: orders advice items by utility $p$ descending via `order_advice_by_utility`.
  - In `decide_advice_handler`: `approved` records useful feedback (+1000 $\alpha$), `rejected` records not-useful feedback (+1000 $\beta$).
- CLI commands (`src/copilot/cli/main.py`):
  - Added `copilot learning show` (table + `--json`) and `copilot learning reset` (`--subject` / `--all`).
- Documentation (`docs/learning_agents.md`):
  - Comprehensive documentation explaining the bandit framing, why zero random exploration / no Thompson sampling in finance, why RLHF/RLAIF/DPO are out of scope, hard floors, and contextual exceptions vs. negative feedback.
- Tests (`tests/learning/test_learning.py`):
  - 13 comprehensive tests covering exact posterior updates, bounds clamping, hard floor protection, contextual dismissals routing to memory, generic dismissals, acknowledgments, muted categories, reallocations, advice approval/rejection and utility ordering, why-text attribution, reset, CLI, and deterministic reproducibility.
Files:
- `src/copilot/core/learning.py`
- `src/copilot/config/phase3.py`
- `src/copilot/db/repo_phase3.py`
- `src/copilot/tools/alerts.py`
- `src/copilot/tools/buckets.py`
- `src/copilot/tools/advice.py`
- `src/copilot/cli/main.py`
- `docs/learning_agents.md`
- `docs/decisions.md`
- `STATUS.md`
- `tests/learning/test_learning.py`
Tests: 890 passed / 890 total | Lint: pass
Evidence:
890 passed (100% green across entire test suite)
All checks passed!
Defaults chosen: none
Live checks pending: none

## Stage 3.13: Agent runtime and observability: DONE
Goal: Implement Section 5.15 Agent runtime and observability (scheduled_jobs with 7 background upkeep jobs, lease-based locking, period-based idempotency, exponential backoff retries and dead_letter transition, actor='agent' Safety Rule 18 execution strictly via execute_tool, distributed tracing with span API and span tree builder, JSONL export, Safety Rule 19 raw-text sanitization, operational telemetry dashboard copilot ops, and foreground daemon copilot agentd).
Built:
- `src/copilot/db/repo_phase3.py`: Added span functions (`insert_span`, `list_spans`, `get_span`) and scheduled job/run functions (`get_scheduled_job`, `get_scheduled_job_by_id`, `list_due_jobs`, `acquire_job_lease`, `release_job_lease`, `list_job_runs`, `get_latest_job_run`, `update_job_run`, `insert_job_run`, `update_scheduled_job`).
- `src/copilot/ops/tracing.py`: Context-propagated tracing module with `span` context manager supporting kinds `('node', 'tool', 'llm', 'job', 'skill', 'specialist', 'mcp')`, Safety Rule 19 runtime validator rejecting raw user text/merchant names, `export_trace_spans_jsonl`, and `build_span_tree`.
- Span hooks in choke points: `execute_tool`, `ContextBuilder.complete`/`structured_call`, `run_skill`, `run_specialist`, and `run_specialists_fanout`.
- `src/copilot/runtime/scheduler.py`: Schedule parser (`compute_next_run_at`) supporting `daily@HH:MM`, `every_N_minutes`, and `monthly@1st_HH:MM`, and tenant job seeder `init_scheduled_jobs`.
- `src/copilot/runtime/runner.py`: Complete job runner with atomic lease acquisition (`acquire_job_lease`), period idempotency (`compute_period_key`), 7 handlers (`rollover_buckets`, `refresh_memories`, `evaluate_alerts`, `coverage_scan`, `suggest_commitments`, `expire_drafts`, `monthly_close`), exponential backoff retry scheduling, dead-letter transition, and `run_due_jobs` / `retry_dead_letter_job`.
- `src/copilot/runtime/daemon.py`: Foreground daemon `run_agentd` with cycle limits, stop event handling, and interval sleeping.
- `src/copilot/ops/telemetry.py`: Telemetry reporter `compute_ops_telemetry` calculating p50/p95 latency per node and skill, LLM calls and tokens per task (with cost estimation), failures by error code, budget stops, validator fallback rate, critic catch rate, revision success rate, job status counts, and parallel speed-up.
- `src/copilot/cli/main.py`: Added `copilot jobs run-due`, `copilot jobs list`, `copilot jobs retry`, `copilot agentd`, and `copilot ops`.
- `tests/runtime/test_runtime.py` and `tests/ops/test_ops.py`: 11 tests verifying due-job selection, lease locking against race conditions, period idempotency, exponential backoff, dead letter, retry, Safety Rule 18 user-write restriction, daemon loop, span tree construction, Safety Rule 19 no-user-text scan, JSONL export, and hand-counted telemetry calculations.
Files:
- `src/copilot/cli/main.py`
- `src/copilot/db/repo_phase3.py`
- `src/copilot/ops/telemetry.py`
- `src/copilot/ops/tracing.py`
- `src/copilot/runtime/daemon.py`
- `src/copilot/runtime/runner.py`
- `src/copilot/runtime/scheduler.py`
- `tests/ops/test_ops.py`
- `tests/runtime/test_runtime.py`
Tests: 877 passed / 877 total | Lint: pass
Evidence:
877 passed in 40.81s
All checks passed!
Defaults chosen: none
Live checks pending: none

## Stage 3.12: Context Engineering and Injection Hardening: DONE
Goal: Implement Section 5.14 Context Engineering & Injection Hardening (ContextBuilder single choke point, token budgeting per section, dynamic memory retrieval ranking with recency decay and tenant isolation, PII/secret redactor with counts, injection pattern detection and XML boundary isolation, ContextManifest auditing without raw text per Safety Rule 19, adversarial corpus penetration suite).
Built:
- `src/copilot/context/hardening.py`: Implemented data-field delimiting (`delimit_data_field`) with security boundary notices, PII and secret redaction (`redact_and_count`) returning per-type counts (PAN, Aadhaar, 16-digit credit cards with Luhn check, bank accounts, secrets), and adversarial prompt injection signature detector (`detect_injection_attempt`).
- `src/copilot/context/retrieval.py`: Implemented dynamic memory retrieval ranking (`retrieve_relevant_memories`) with tenant isolation (`user_id = ?`), dynamic active/validity filtering, subject match weighting (exact: 3.0, parent: 2.0, global: 1.0), exponential recency decay, and deterministic ID tie-breaking.
- `src/copilot/context/builder.py`: Implemented `ContextBuilder` as the single choke point for budgeted prompts across all LLM purposes (`intent_extraction`, `planning`, `narration`, `critique`, `decomposition`). Logs `ContextManifest` into `context_manifests` table without raw prompt/user text (Safety Rule 19). Provides `complete()` and `structured_call()` wrappers.
- `src/copilot/db/repo_phase3.py`: Added `get_context_manifest` and `list_context_manifests`.
- Integrated `ContextBuilder` across `LLMPlanner.propose`, `decomposition.py:decompose_intent`, `reviewer.py:llm_critic_review`, and `intent.py:llm_classify_intent`.
- `tests/context/test_context_engineering.py`: 8 comprehensive tests for token budgeting, section exclusions, deterministic ordering, Safety Rule 19 manifest raw-text safety, memory retrieval scoring, tenant isolation, dynamic active status, PII redaction, and architectural AST enforcement.
- `tests/security/injection/test_adversarial_corpus.py`: 6 adversarial penetration tests covering direct instruction overrides, role elevation, enum breakout attempts, write tool rejection via PlanValidator, specialist tool containment, and manifest leakage protection.
- Evidence: 866/866 tests passing (100% green), `ruff check` passes with 0 errors.

## Stage 3.11: Multi-Agent Planning: DONE
Goal: Implement Section 5.13 Multi-Agent Planning (supervisor/decompose with LLM proposal and YAML fallback, 4 specialist subgraphs with restricted tool subsets and tool call rejection auditing, parallel fan-out with timeout and failure containment, deterministic merge with contradiction detection, deterministic + closed-set LLM reviewer, bounded Reflexion-style revision up to max_revision_rounds, reflection logging, candidate failure export to eval/candidates/).
Built:
- `config/decomposition.yaml`: Added registered question kinds for 4 specialist domains (cashflow, goals, readiness, behaviour).
- `src/copilot/config/phase3.py`: Added `registered_question_kinds` to `DecompositionConfig`.
- `src/copilot/workflow/decomposition.py`: Built decomposition engine with strict validation (`DecompositionValidator`), tenant isolation check (`other_user_ids` / `valid_user_ids`), deterministic template fallback, and routing rule (`should_route_to_multi_agent`).
- `src/copilot/workflow/specialists.py`: Implemented 4 specialist roles (`CashflowAgent`, `GoalsAgent`, `ReadinessAgent`, `BehaviourAgent`) with restricted tool subsets, auditing of out-of-subset attempts (`specialist_tool_rejected`), transient error retry, and `_to_dict` serialization for findings.
- `src/copilot/workflow/multi_agent.py`: Built parallel fan-out (`ThreadPoolExecutor`) with timeout/failure containment, and deterministic merge with contradiction detection (audited `merge_conflict` and metric exclusion from narration).
- `src/copilot/workflow/reviewer.py`: Built deterministic review checks, closed-set LLM critic with Safety Rule 14 enforcement (rejection of any critic output containing numbers), and bounded revision (up to `max_revision_rounds`, default 1).
- `src/copilot/workflow/multi_agent_graph.py`: Built LangGraph compiled subgraph and runner `run_multi_agent_workflow`.
- `src/copilot/ops/failures.py`: Built failure candidate exporter (`export_failures`) exporting to `eval/candidates/` as draft golden cases.
- `src/copilot/workflow/agent_graph.py` & `src/copilot/workflow/agentic_nodes.py`: Integrated `multi_agent` routing and node into the main planner agent graph.
- `tests/workflow/test_multi_agent.py`: 15 comprehensive unit & integration tests covering all requirements.
Files:
- `config/decomposition.yaml`
- `src/copilot/config/phase3.py`
- `src/copilot/db/repo_phase3.py`
- `src/copilot/ops/failures.py`
- `src/copilot/workflow/agent_graph.py`
- `src/copilot/workflow/agentic_nodes.py`
- `src/copilot/workflow/decomposition.py`
- `src/copilot/workflow/multi_agent.py`
- `src/copilot/workflow/multi_agent_graph.py`
- `src/copilot/workflow/reviewer.py`
- `src/copilot/workflow/specialists.py`
- `tests/workflow/test_multi_agent.py`
Adaptations applied (0.7):
- Reused `get_connection(":memory:", check_same_thread=False)` for SQLite thread-safety in worker threads.
- Serialized Pydantic ToolOutput instances using `_to_dict` before writing to `specialist_reports.findings_json`.
Tests: 852 passed / 852 total | Lint: pass
Evidence:
852 passed in 30.26s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 3.10: Skills Library and Agent Integration: DONE
Goal: Implement Section 5.12 Skills Library (YAML manifests in config/skills/, validator rejecting unknown and write tools, runner with preconditions/conditionals calling through execute_tool), tool wrappers, 10 Phase 3 intents in planner and classifier, and activity timeline Phase 3 extensions (PLAN_PHASE3 Stage 3.10, Section 5.10, Section 5.12).
Built:
- `src/copilot/models/phase3.py`: Added `SkillManifest` model.
- `src/copilot/db/repo_phase3.py`: Added `insert_skill_run`, `update_skill_run`, `get_skill_run`, `list_skill_runs`.
- `src/copilot/skills/manifest.py`: Implemented `load_skill_manifest`, `validate_skill_manifest` (rejects non-existent tools, write tools, and undeclared placeholders), and `load_all_skills`.
- `src/copilot/skills/runner.py`: Implemented `run_skill` calling all steps strictly through `execute_tool`, checking deterministic preconditions (`has_transactions`), evaluating conditionals (`if_status`), and tracking runs in `skill_runs`.
- `src/copilot/skills/tools.py`: Registered skill tool wrappers (`affordability_check`, `monthly_close`, `trip_planning`, `contribution_review`, `explain_month_change`, and generic `run_skill`).
- `config/skills/`: Certified manifests for 5 standard skills with 15 golden evaluation cases in `tests/skills/`.
- `src/copilot/models/agentic.py`: Added 10 Phase 3 intents to `IntentType` enum (`goal_progress`, `commitment_check`, `calendar_lookahead`, `bucket_status`, `investment_readiness`, `contribution_check`, `tradeoff_compare`, `affordability`, `trip_planning`, `memory_query`) and timeline kinds.
- `src/copilot/core/intent.py`: Extended `classify_intent` with robust regex and entity extraction for all 10 Phase 3 intents while preserving backward compatibility on Phase 2 labelled benchmark queries.
- `src/copilot/core/timeline.py`: Extended `build_timeline` with commitments, reallocation drafts, readiness, contribution plans, tradeoffs, and memory items (verifying privacy on forgotten memories).
- Config updates: `config/plan_templates.yaml`, `config/intent_patterns.yaml`, `config/policy.yaml`, `config/planner_capabilities.yaml`.
Files:
- `config/intent_patterns.yaml`
- `config/plan_templates.yaml`
- `config/planner_capabilities.yaml`
- `config/policy.yaml`
- `config/skills/affordability_check.yaml`
- `config/skills/contribution_review.yaml`
- `config/skills/explain_month_change.yaml`
- `config/skills/monthly_close.yaml`
- `config/skills/trip_planning.yaml`
- `docs/decisions.md`
- `src/copilot/config/phase2.py`
- `src/copilot/core/intent.py`
- `src/copilot/core/timeline.py`
- `src/copilot/db/repo_phase3.py`
- `src/copilot/models/agentic.py`
- `src/copilot/models/phase3.py`
- `src/copilot/skills/__init__.py`
- `src/copilot/skills/manifest.py`
- `src/copilot/skills/runner.py`
- `src/copilot/skills/tools.py`
- `src/copilot/tools/buckets.py`
- `src/copilot/tools/calendar.py`
- `src/copilot/tools/contributions.py`
- `src/copilot/tools/goals.py`
- `src/copilot/tools/investigation.py`
- `src/copilot/tools/whatif.py`
- `src/copilot/workflow/nodes.py`
- `STATUS.md`
- `tests/core/test_intent_phase3.py`
- `tests/core/test_timeline_phase3.py`
- `tests/skills/affordability_check/case_01.json`
- `tests/skills/affordability_check/case_02.json`
- `tests/skills/affordability_check/case_03.json`
- `tests/skills/contribution_review/case_01.json`
- `tests/skills/contribution_review/case_02.json`
- `tests/skills/contribution_review/case_03.json`
- `tests/skills/explain_month_change/case_01.json`
- `tests/skills/explain_month_change/case_02.json`
- `tests/skills/explain_month_change/case_03.json`
- `tests/skills/monthly_close/case_01.json`
- `tests/skills/monthly_close/case_02.json`
- `tests/skills/monthly_close/case_03.json`
- `tests/skills/test_skills_golden.py`
- `tests/skills/test_skills_manifest.py`
- `tests/skills/test_skills_runner.py`
- `tests/skills/trip_planning/case_01.json`
- `tests/skills/trip_planning/case_02.json`
- `tests/skills/trip_planning/case_03.json`
Adaptations applied (0.7):
- Reused Phase 2 `execute_tool` choke point as single execution runner for all skill steps.
- Registered skills as `compute` tools in capability matrix for single-step selection by deterministic planner.
Tests: 837 / 837 passed | Lint: pass
Evidence:
```
tests/skills/test_skills_golden.py::test_skill_eval_cases[...] PASSED
tests/skills/test_skills_manifest.py::test_load_all_standard_skills PASSED
tests/skills/test_skills_manifest.py::test_reject_unknown_tool PASSED
tests/skills/test_skills_manifest.py::test_reject_write_tool PASSED
tests/skills/test_skills_manifest.py::test_reject_user_allocate_write_tool PASSED
tests/skills/test_skills_manifest.py::test_reject_bad_argument_placeholder PASSED
tests/skills/test_skills_runner.py::test_precondition_failure_cannot_run PASSED
tests/skills/test_skills_runner.py::test_precondition_success_runs_ok PASSED
tests/skills/test_skills_runner.py::test_missing_required_input_cannot_run PASSED
tests/skills/test_skills_runner.py::test_registered_skill_tool_execution PASSED
tests/skills/test_skills_runner.py::test_generic_run_skill_tool PASSED
tests/core/test_intent_phase3.py::test_refusal_suite PASSED
tests/core/test_intent_phase3.py::test_intent_accuracy_on_labelled_examples PASSED
tests/core/test_intent_phase3.py::test_tool_minimality_per_phase3_intent PASSED
tests/core/test_intent_phase3.py::test_adversarial_plans_with_write_tools_rejected_and_audited PASSED
tests/core/test_timeline_phase3.py::test_timeline_phase3_entries_and_forgotten_memory_privacy PASSED
==================== 837 passed in 28.88s ====================
All checks passed!
```
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 3.9: Confidence, Decay and Memory Use: DONE
Goal: Implement Section 5.9 confidence formulas and lifecycle transitions, anchor calculation, active memory integration into alerts (score damping & why_text explanation), investigations (catalogue hypothesis known_exception), advice drafting (suppression during 30d cooldown, no reinforcement loops), memories_json population, and property tests (PLAN_PHASE3 Stage 3.9, Section 5.9).
Built:
- `src/copilot/core/memory.py`:
  - Updated `compute_memory_confidence` anchor timestamp to use $\max(last\_evidence\_at, last\_confirmed\_at)$, ensuring confirmations refresh decay age.
  - Added `get_active_contextual_exception` helper picking the highest confidence active exception for a (category, period) tuple.
  - Added `check_advice_suppression` enforcing 30-day cooldown suppression for rejected advice and preventing approved advice boosting.
- `src/copilot/config/phase3.py` & `config/memory.yaml`: Added `exception_damping_bp: 5000` (50% damping).
- `src/copilot/core/alerts.py` & `src/copilot/tools/alerts.py`:
  - Damps alert score when an active contextual exception covers category and period.
  - Appends `Damped by active {reason} exception.` to alert `why_text`.
  - Populates `components["memories"]` with the active exception item.
- `src/copilot/core/investigation.py` & `src/copilot/tools/investigation.py`:
  - Added 9th catalogue hypothesis `known_exception` supported with high confidence (9000 bp) when an active exception covers the category and period.
- `src/copilot/core/recommendations.py`:
  - Connected `find_relevant_memories` to query `memory_items` for active behavioral memories, populating `memories_json` on recommendations.
- `tests/core/test_memory_decay.py`: 11 comprehensive unit and property tests verifying:
  - Exact decay values at 0, 1, and 2 half-lives (8000 -> 4000 -> 2000 bp).
  - Preference memories never decay regardless of elapsed time.
  - Boundary threshold transitions (6000 -> active, 5999 -> candidate, 2000 -> stale, 1999 -> retired).
  - User-confirmed contradicted memory becomes `stale` with `still_true_check=True`.
  - Drift scenario: old habit ceasing evidence decays to stale, new habit with 3 evidence items becomes active.
  - Alerts damped only by an active exception for matching category and period.
  - `known_exception` hypothesis supported strictly when active exception covers subject.
  - Suppression cooldown boundary: day 29 suppressed, day 30 and 31 elapsed (back).
  - `memories_json` populated on recommendations and alerts.
  - Monotonicity property: confidence never increases with age alone across 400 days.
  - Boundedness property: confidence is always in [0, 10000].
Files: src/copilot/core/memory.py, src/copilot/config/phase3.py, config/memory.yaml, src/copilot/core/alerts.py, src/copilot/tools/alerts.py, src/copilot/core/investigation.py, src/copilot/tools/investigation.py, src/copilot/core/recommendations.py, tests/core/test_memory_decay.py, docs/decisions.md, STATUS.md
Tests: 807 passed / 807 total | Lint: pass (0 ruff errors)
Evidence:
807 passed in 28.72s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 3.8: Behavioural Memory Store and Observers: DONE
Goal: Implement memory items and evidence models, five deterministic observers, pure confidence calculation and lifecycle status engine with Decimal half-life decay, bounded statement editing, forgetting invariant, 8 governance tools, capability matrix metadata, policy rules, and tests (PLAN_PHASE3 Stage 3.8, Section 5.8).
Built:
- `src/copilot/core/memory.py`:
  - 5 deterministic observers (`observe_recurring_patterns`, `observe_contextual_exceptions`, `observe_advice_feedback`, `observe_preferences`, `observe_merchant_habits`).
  - Allowed contextual exception reasons bounded: `festival`, `travel`, `one_off_purchase`, `medical`, `family_event`, `other`.
  - Pure lifecycle & confidence engine (`compute_memory_confidence`, `determine_memory_status`): prior_bp (5000), support/contradict weighting (`k_s=1.0`, `k_c=1.5`, capped at 10000 bp), half-life decay using Decimal arithmetic (`preference` decay=1), candidate/active/stale/retired/rejected/forgotten transitions.
  - Idempotent `refresh_memories` running observers and preventing duplicate evidence.
  - Bounded statement editing (`edit_memory_statement_bounded`).
  - Forgetting invariant (`forget_memory`): clears statement_json to `{}`, deletes all evidence rows, sets status to `forgotten`, and records a content-free audit event (`memory_forgotten`).
  - Strict invariant: zero LLM provider calls across all memory functions.
- `src/copilot/tools/memory.py`:
  - Implemented 8 tools: `list_memories` (read), `explain_memory` (read), `confirm_memory` (user-only), `reject_memory` (user-only), `edit_memory_statement` (user-only), `forget_memory` (user-only), `refresh_memories` (agent/user), `record_contextual_exception` (write).
- `src/copilot/db/repo_phase3.py`: Added `update_memory_statement` and `get_memory_by_subject`.
- `src/copilot/config/phase3.py`: Added `observers: dict[str, Any]` to `MemoryConfig`.
- `config/memory.yaml`: Added observer parameters (`min_weeks: 2`, `weekend_ratio_threshold_bp: 15000`, etc.).
- `config/policy.yaml` & `config/planner_capabilities.yaml`: Registered all 8 memory tools with strict policy rules and capability matrix metadata.
- `src/copilot/workflow/nodes.py`: Added `register_memory_tools()` to `ensure_tools_registered()`.
- `tests/core/test_memory.py`: 14 comprehensive unit tests passing.
- `tests/tools/test_memory_tools.py`: 8 through-executor integration tests passing.
- `tests/tools/test_no_money_movement.py`: Registered memory tools and verified 0 banned words.
Files: src/copilot/core/memory.py, src/copilot/tools/memory.py, src/copilot/db/repo_phase3.py, src/copilot/config/phase3.py, config/memory.yaml, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_memory.py, tests/tools/test_memory_tools.py, tests/tools/test_no_money_movement.py, docs/decisions.md, STATUS.md
Tests: 796 passed / 796 total | Lint: pass (0 ruff errors)
Evidence:
796 passed in 25.47s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Stage 3.7: Contribution Planning & Trade-offs: DONE
Goal: Implement pure waterfall allocation engine, dynamic option generator with linked simulations, multi-alternative trade-off analysis engine with constraint evaluation, snapshot persistence, read/compute tools, governance, and tests (PLAN_PHASE3 Stage 3.7, Section 5.7).
Built:
- `src/copilot/core/contributions.py`: Pure waterfall allocation engine and trade-off analyzer:
  - Waterfall allocation (`plan_contributions`):
    - Aggregates monthly inflows (median income from complete months).
    - Evaluates allocation steps in prioritized waterfall order:
      1. Firm commitments (mandatory contractual obligations).
      2. Essential spend (median historical non-commitment essential spending).
      3. Emergency fund top-up (gradual replenishment towards 3-month target).
      4. Goals by user-configured priority and deadline.
      5. Planned investments (user-specified SIPs/allocations).
      6. Discretionary spending (residual available cash).
    - Guarantees exact math: for every step `funded + shortfall == need` and `total_funded <= inflow`.
    - Synthesizes verdicts: `fits` (total need <= inflow), `fits_expected_only` (fits expected but fails conservative buffer), or `does_not_fit` (inflow < total need).
    - Deterministic option generation: when contributions do not fit, generates up to 3 non-increasing outflow options (reduce planned contributions, pause contributions to build emergency fund, shift lower-priority goal deadline), each linking an actual simulation run via `insert_simulation`.
  - Trade-off analysis engine (`compare_tradeoffs`):
    - Compares baseline against up to 3 alternatives on goal completions, emergency reserve coverage, unfulfilled commitments count, lowest projected liquid balance, shortfall days, and total planned contributions.
    - Strictly uses plain sum of contributions (zero assumed market returns/growth rates).
    - Evaluates hard constraints: zero firm commitments `not_covered`, and emergency cushion minimum preserved.
    - Sets `best_alternative_name` strictly when exactly one alternative satisfies all hard constraints.
  - Snapshot persistence: records plans in `contribution_plans` and trade-offs in `tradeoff_analyses` tables.
- `src/copilot/tools/contributions.py`: Tools:
  - `plan_contributions`: pure read/compute tool evaluating monthly cash waterfall and options.
  - `compare_tradeoffs`: pure read/compute tool evaluating scenario trade-offs against baseline.
- `src/copilot/db/repo_phase3.py`: Added repository methods `insert_contribution_plan`, `get_latest_contribution_plan`, `list_contribution_plans`, `insert_tradeoff_analysis`, `get_latest_tradeoff_analysis`, `list_tradeoff_analyses` with tenant isolation.
- `config/policy.yaml` & `config/planner_capabilities.yaml`: Registered `plan_contributions` and `compare_tradeoffs` for all actors, planner-selectable.
- `src/copilot/workflow/nodes.py`: Registered contribution tools in `ensure_tools_registered`.
- `tests/core/test_contributions.py`: 9 unit tests verifying waterfall exact sums, user custom ordering, verdict transitions, option outflow limits, simulation linkage, hand-calculated trade-off metrics, single-best constraint satisfaction, plain sums/zero growth, zero forbidden content scanner, and tenant isolation.
- `tests/tools/test_contributions_tools.py`: 3 through-executor tests covering policy governance, persistence, and tenant isolation.
- `tests/planner/test_capabilities.py`: 5 tests passing capability matrix verification.
Files: src/copilot/core/contributions.py, src/copilot/tools/contributions.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_contributions.py, tests/tools/test_contributions_tools.py, docs/decisions.md, STATUS.md
Tests: 774 passed / 774 total | Lint: pass (0 ruff errors)
Evidence:
774 passed in 25.66s
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add contribution planning and trade-off analysis engine, tools, snapshot persistence, and tests: src/copilot/core/contributions.py, src/copilot/tools/contributions.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_contributions.py, tests/tools/test_contributions_tools.py, docs/decisions.md, STATUS.md

## Stage 3.5: Financial Calendar: DONE
Goal: Implement financial calendar projection engine, liquid balance baseline, active commitment occurrence expansion, variable spend run-rate from forecast v2, daily running balances (`low <= expected <= high`), commitment coverage evaluation (`covered`, `at_risk`, `not_covered`, `unknown`), shortfall ranges, scenario simulation extension point, read tools, governance, and tests (PLAN_PHASE3 Stage 3.5, Section 5.4).
Built:
- `src/copilot/core/calendar.py`: Pure calendar projection engine:
  - Starting liquid balance baseline from all active liquid accounts with reconciliation invariant `balance_today == opening + sum(credits) - sum(debits)`.
  - Occurrence expansion across the horizon (`horizon_days`, default 60, clamped to 180) for all active commitments.
  - Daily variable spend run-rate derived from forecast v2, strictly excluding commitment categories to prevent double counting.
  - Computes running balances preserving ordering `running_balance_low <= running_balance_expected <= running_balance_high` across all days.
  - Commitment coverage evaluation (`calculate_commitment_coverage`): evaluates each commitment occurrence as `covered` (low >= 0), `at_risk` (expected >= 0 and low < 0), `not_covered` (expected < 0), or `unknown` (missing forecast/baseline), with exact integer shortfall ranges.
  - Scenario simulation extension point (`CalendarScenario`) allowing what-if injection of income/outflow adjustments.
- `src/copilot/tools/calendar.py`: Read tools:
  - `get_calendar`: returns full calendar projection with daily cash flow breakdowns, running balances, and aggregated shortfalls.
  - `check_commitment_coverage`: evaluates coverage status and shortfall for a specific commitment across horizon.
- `config/policy.yaml` & `config/planner_capabilities.yaml`: Registered calendar tools (allowed for all actors, planner-selectable).
- `src/copilot/workflow/nodes.py`: Registered calendar tools in `ensure_tools_registered`.
- `tests/core/test_calendar.py`: 11 unit tests covering reconciliation invariant, 60-day horizon defaults and bounds clamping, occurrence expansion, commitment category exclusion from variable spend, coverage classifications, shortfall ranges, scenario simulation, and multi-tenant isolation.
- `tests/tools/test_calendar_tools.py`: 3 through-executor tests covering `get_calendar` and `check_commitment_coverage` execution, policy governance, and tenant isolation.
- `tests/tools/test_no_money_movement.py`: Verified registry checks for calendar tools.
Files: src/copilot/core/calendar.py, src/copilot/tools/calendar.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_calendar.py, tests/tools/test_calendar_tools.py, tests/tools/test_no_money_movement.py, docs/decisions.md, STATUS.md
Tests: 745 passed / 745 total | Lint: pass (0 ruff errors on phase 3 files)
Evidence:
============================= 745 passed in 27.03s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add financial calendar projection engine, commitment coverage analysis, tools, and tests: src/copilot/core/calendar.py, src/copilot/tools/calendar.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_calendar.py, tests/tools/test_calendar_tools.py, tests/tools/test_no_money_movement.py, docs/decisions.md, STATUS.md

## Stage 3.4: Virtual Buckets: DONE
Goal: Implement derived balances, reserved vs available funds, idempotent month rollover, overspend detection, category mapping, reallocation drafts lifecycle (separate decide and apply), and comprehensive governance tools (PLAN_PHASE3 Stage 3.4, Section 5.3).
Built:
- `src/copilot/core/buckets.py`: Pure engine and calculation module:
  - `bucket_allocated_paise`: Derived allocations per period with support for `reset_monthly` (period-specific) and `accumulate` (cumulative).
  - `bucket_spent_paise`: Net spend derived directly from transactions mapped by category or matched to commitments, excluding duplicates and excluded spend, netting refunds, floored at 0.
  - `bucket_balance`: Derived balance (`allocated - spent`) and status (`ok`, `low` when below `low_threshold_bp`, `depleted` when negative).
  - `get_allocation_summary`: Computes `reserved_total` (`sum(max(0, balance))`), `liquid_balance`, `available_unallocated` (`liquid - reserved`), and `over_allocated_by`, guaranteeing the invariant `available_unallocated + reserved_total == liquid_balance`.
  - `would_exceed`: Pure check testing whether spending `amount_paise` pushes bucket balance below 0.
  - `rollover_buckets`: Idempotent month rollover for `reset_monthly` buckets, releasing unspent funds in closing period (`source = system_rollover`), preserving depleted buckets, ignoring `accumulate` buckets, and writing nothing on repeated calls.
- `src/copilot/tools/buckets.py`: Tool specifications and handlers:
  - `create_bucket`, `update_bucket`, `archive_bucket`: Bucket metadata management (write_logical, user allowed, agent needs approval).
  - `map_category_to_bucket`: 1-to-1 category mapping uniqueness via `ON CONFLICT DO UPDATE`.
  - `allocate_to_bucket`, `release_from_bucket`: Ledger allocation and release operations.
  - `reassign_between_buckets`: Matched pairs (`reassign_out` / `reassign_in`) sharing a `pair_id` and summing to exactly 0.
  - `draft_reallocation` / `create_reallocation_draft`: Autonomous agent allowed (writes drafts only!).
  - `decide_reallocation` / `decide_reallocation_draft`: User actor only (approval alone writes zero allocation rows).
  - `apply_reallocation` / `apply_reallocation_draft`: User actor only (applies approved draft, writes paired rows, validates TTL).
  - `list_buckets`, `get_bucket_status`, `get_allocation_summary`: Read tools (allowed for all actors, planner-selectable).
- `src/copilot/db/repo_phase3.py`: Added `update_bucket` repository function with tenant filtering.
- `config/policy.yaml`: Added actor rules for all 16 bucket tools.
- `config/planner_capabilities.yaml`: Added capability matrix definitions with read tools planner-selectable and write tools not planner-selectable.
- `src/copilot/workflow/nodes.py`: Registered bucket tools in `ensure_tools_registered`.
- `tests/core/test_buckets.py`: 10 comprehensive unit tests covering the four invariants, rollover idempotency, depleted rollover preservation, threshold boundaries, refund netting, `would_exceed`, and multi-tenant isolation.
- `tests/tools/test_buckets_tools.py`: 5 through-executor tests verifying policy governance, category uniqueness, separate decide/apply lifecycle, TTL expiry rejection, and tenant isolation.
Files: src/copilot/core/buckets.py, src/copilot/tools/buckets.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_buckets.py, tests/tools/test_buckets_tools.py, tests/tools/test_no_money_movement.py, docs/decisions.md, STATUS.md
Tests: 731 passed / 731 total | Lint: pass (0 ruff errors on phase 3 files)
Evidence:
============================= 731 passed in 26.39s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add virtual buckets engine, governance tools, rollover, and tests: src/copilot/core/buckets.py, src/copilot/tools/buckets.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_buckets.py, tests/tools/test_buckets_tools.py, tests/tools/test_no_money_movement.py, docs/decisions.md, STATUS.md



## Stage 3.3: Goals Full (Progress Sources, History, Projections, and Feasibility): DONE
Goal: Implement multi-source progress tracking (`manual`, `bucket`, `account`), contribution history, deterministic pace and completion projections, full goal progress evaluation, Phase 3 goal fields persistence, and governance tools (PLAN_PHASE3 Stage 3.3, Section 5.2).
Built:
- `src/copilot/core/goals.py`: Pure deterministic engine functions:
  - `goal_current_paise`: Derived balance from `manual` (base + sum of goal_contributions), `bucket` (linked bucket allocations minus spend), and `account` (account opening balance minus transaction debits).
  - `monthly_contribution_history`: Monthly net contribution history across previous complete calendar months in integer paise.
  - `projected_completion`: Low, median, and high pace completion dates (or `never_at_current_pace`) using ceil division `((remaining + p - 1) // p)`.
  - `goal_progress`: Typed `GoalProgress` evaluation with integer percent bounded `[0, 100]`, pace status, remaining paise, and required monthly savings.
- `src/copilot/tools/goals.py`:
  - Extended `create_goal` and `update_goal` with Phase 3 fields (`progress_source`, `linked_account_id`, `start_date`, `essential`, `notes`).
  - Added `record_goal_contribution` tool (write_logical, user allowed, agent needs approval) with input validation (manual goals only, nonzero amount, ISO date, user isolation, audit event).
  - Added `get_goal_progress` tool (read, allowed for all actors, planner-selectable) returning complete progress evaluations.
- `src/copilot/db/repo.py`: Extended `insert_goal`, `update_goal`, `get_goal`, `list_goals` to store and retrieve Phase 3 goal fields with multi-tenant filtering.
- `config/policy.yaml`: Added actor rules for `record_goal_contribution` and `get_goal_progress`.
- `config/planner_capabilities.yaml`: Added capability matrix definitions with `get_goal_progress` planner-selectable and `record_goal_contribution` not planner-selectable.
- `tests/core/test_goals.py`: Added 4 tests verifying progress sources (manual, bucket, account), boundary edge cases (0%, 100%, negative, 0 target), projection ranges with ceil rounding, and feasibility regression.
- `tests/tools/test_goals_tools.py`: Added 3 tests verifying Phase 3 fields persistence on create/update, governance and validation on contributions, and `get_goal_progress` tool output.
Files: src/copilot/core/goals.py, src/copilot/tools/goals.py, src/copilot/db/repo.py, config/policy.yaml, config/planner_capabilities.yaml, tests/core/test_goals.py, tests/tools/test_goals_tools.py, docs/decisions.md, STATUS.md
Tests: 716 passed / 716 total | Lint: pass (0 ruff errors on phase 3 files)
Evidence:
============================= 716 passed in 25.31s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add full Phase 3 goals progress sources, projections, tools, and tests: src/copilot/core/goals.py, src/copilot/tools/goals.py, src/copilot/db/repo.py, config/policy.yaml, config/planner_capabilities.yaml, tests/core/test_goals.py, tests/tools/test_goals_tools.py, docs/decisions.md, STATUS.md



## Stage 3.2: Commitments and Occurrence Engine: DONE
Goal: Implement the pure deterministic occurrence expansion and transaction matching engine, commitment lifecycle management, draft suggestions from recurring payment series, 9 tool contracts and handlers, actor governance policies, capability matrix rows, and thorough test suite (PLAN_PHASE3 Stage 3.2, Section 5.1).
Built:
- `src/copilot/core/commitments.py`: Pure deterministic engine for occurrence expansion (`monthly` day 29-31 clamping, `yearly` Feb 29 leap/non-leap adjustment, `every_n_days` anchor stepping, `weekly`, `once`) and matching against transactions with 1-to-1 transaction match guarantee, amount and date tolerances, category matching preference, and status transitions (`paid`, `partially_paid`, `overdue`, `upcoming`).
- `src/copilot/tools/commitments.py`: 9 tool specs and handlers: `create_commitment`, `update_commitment`, `pause_commitment`, `end_commitment`, `accept_commitment`, `reject_commitment` (write_logical, user allowed, agent needs approval), `list_commitments`, `get_commitment_status` (read, allowed, planner-selectable), `suggest_commitments` (write_logical, drafts only, agent/user allowed).
- `src/copilot/db/repo_phase3.py`: Added `update_commitment` and `list_recurring_series` repo functions with strict `user_id` filtering.
- `config/policy.yaml`: Added actor rules for all 9 commitment tools.
- `config/planner_capabilities.yaml`: Added capability matrix definitions with read tools planner-selectable and write tools not planner-selectable.
- `src/copilot/workflow/nodes.py`: Registered commitment tools in `ensure_tools_registered`.
- `tests/core/test_commitments.py`: 8 unit tests covering leap year Feb 29, monthly 31st clamping, `every_n_days` across boundaries, bounds enforcement, paused/ended exclusions, half-up rounding, 1-to-1 matching invariant, and tolerance windows.
- `tests/tools/test_commitments_tools.py`: 5 through-executor governance tests verifying policy enforcement, draft suggestions, draft activation/rejection, user isolation, and status matching.
Files: src/copilot/core/commitments.py, src/copilot/tools/commitments.py, src/copilot/models/phase3.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_commitments.py, tests/tools/test_commitments_tools.py, docs/decisions.md, STATUS.md
Tests: 709 passed / 709 total | Lint: pass (0 ruff errors on phase 3 files)
Evidence:
============================= 709 passed in 25.02s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add financial commitments engine, tools, policy governance, and tests: src/copilot/core/commitments.py, src/copilot/tools/commitments.py, src/copilot/models/phase3.py, src/copilot/db/repo_phase3.py, config/policy.yaml, config/planner_capabilities.yaml, src/copilot/workflow/nodes.py, tests/core/test_commitments.py, tests/tools/test_commitments_tools.py, docs/decisions.md, STATUS.md


## Stage 3.1: Schema and Models: DONE
Goal: Implement migration 004, extend goals, upgrade buckets from stub, add 21 Phase 3 tables, build 30 typed Pydantic models, and implement multi-tenant repo functions (PLAN_PHASE3 Stage 3.1, Section 4).
Built:
- `src/copilot/db/migrations/004_phase3_schema.sql`: 21 new tables and goals extensions (`progress_source`, `linked_account_id`, `start_date`, `essential`, `notes`) with foreign keys, checks, and indexes. Upgraded `buckets` table via safe copy-table pattern.
- `src/copilot/models/phase3.py`: 30 typed Pydantic models (`Commitment`, `Occurrence`, `CommitmentMatch`, `GoalProgress`, `Bucket`, `BucketAllocation`, `BucketBalance`, `AllocationSummary`, `ReallocationDraft`, `Calendar`, `CalendarDay`, `Coverage`, `Readiness`, `ReadinessCriterion`, `ContributionPlan`, `TradeoffResult`, `MemoryItem`, `MemoryEvidence`, `UserPreference`, `SkillRun`, `SubQuestion`, `SpecialistReport`, `Reflection`, `ContextManifest`, `Span`, `ScheduledJob`, `JobRun`, `FeedbackStat`).
- `src/copilot/models/agentic.py`: Updated `Goal` model with Phase 3 fields for forward/backward compatibility.
- `src/copilot/db/repo_phase3.py`: 30+ parameterised repository functions enforcing mandatory `user_id` filtering.
- `tests/db/test_phase3_schema.py`: 7 comprehensive tests verifying fresh migration, Phase 2 data preservation, user isolation, 1-to-1 category-bucket mapping, reallocation drafts, memory forgetting, and scheduled jobs.
Files: src/copilot/db/migrations/004_phase3_schema.sql, src/copilot/models/phase3.py, src/copilot/models/agentic.py, src/copilot/db/repo_phase3.py, tests/db/test_phase3_schema.py, docs/decisions.md, STATUS.md
Tests: 696 passed / 696 total | Lint: pass (0 ruff errors)
Evidence:
============================= 696 passed in 24.46s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add Phase 3 database migration, domain models and repository functions: src/copilot/db/migrations/004_phase3_schema.sql, src/copilot/models/phase3.py, src/copilot/models/agentic.py, src/copilot/db/repo_phase3.py, tests/db/test_phase3_schema.py, docs/decisions.md, STATUS.md


## Stage 3.0: Discover, Align, Adapt & Phase 3 Config Foundation: DONE
Goal: Establish exact codebase alignment, fill 0.7 adaptation table, verify LangGraph 1.2.15 capabilities, add and validate 14 Phase 3 config YAMLs, and record 100% green test baseline (PLAN_PHASE3 Stage 3.0, Section 0.7).
Built:
- `docs/phase3_alignment.md`: Complete Section 0.7 adaptation table (all 16 items), Phase 2 stage verification table, LangGraph parallel fan-out/fan-in and subgraph capabilities analysis, and test baseline.
- `config/commitments.yaml`: Tolerance bp, date tolerance days, allowed certainties, directions, kinds, and schedules.
- `config/goals.yaml`: Merged Phase 2 keys with Phase 3 projection months, progress sources, and default progress source.
- `config/buckets.yaml`: Low threshold bp, draft TTL days, allowed kinds, period policies, and default policies.
- `config/calendar.yaml`: Default horizon 60d, max horizon 180d, min buffer ₹1,000 (100,000 paise).
- `config/readiness.yaml`: Emergency months target 3 (range 1-12), emergency min months 1, CV bp 5000, essential categories.
- `config/contributions.yaml`: Waterfall order, horizon bounds (6 to 24 months), max alternatives 3.
- `config/memory.yaml`: Advice cooldown 30d, thresholds bp (use: 6000, stale: 4000, retire: 2000), half lives, decay weights, exception reasons.
- `config/skills/`: Manifests for `affordability_check.yaml`, `monthly_close.yaml`, `trip_planning.yaml`, `contribution_review.yaml`, `explain_month_change.yaml`.
- `config/decomposition.yaml`: Max subquestions per task 4, domain decomposition templates.
- `config/context.yaml`: Token budgets per purpose, top-k memories 5, token estimation ratio.
- `config/runtime.yaml`: Loop interval 60s, lease duration 300s, max retries 3, standard job definitions.
- `config/learning.yaml`: Beta prior α=2, β=2, η=0.5, multiplier bounds [0.5, 1.5], hard floor severities.
- `config/ops.yaml`: Pricing, retention, latency percentiles.
- `config/mcp.yaml`: Server name, protocol version, transport (stdio), exposed tool list.
- `src/copilot/config/phase3.py`: Strict Pydantic schemas and loaders with boundary checks and extra='forbid'.
- `src/copilot/config/phase2.py`: Updated `GoalsConfig` with Phase 3 merged fields for forward/backward compatibility.
- `tests/config/test_phase3_config.py`: 7 boundary and validation tests passing.
Files: docs/phase3_alignment.md, config/commitments.yaml, config/goals.yaml, config/buckets.yaml, config/calendar.yaml, config/readiness.yaml, config/contributions.yaml, config/memory.yaml, config/skills/affordability_check.yaml, config/skills/monthly_close.yaml, config/skills/trip_planning.yaml, config/skills/contribution_review.yaml, config/skills/explain_month_change.yaml, config/decomposition.yaml, config/context.yaml, config/runtime.yaml, config/learning.yaml, config/ops.yaml, config/mcp.yaml, src/copilot/config/phase3.py, src/copilot/config/phase2.py, tests/config/test_phase3_config.py, tests/api/test_api.py, docs/decisions.md, STATUS.md
Tests: 689 passed / 689 total | Lint: pass (0 ruff errors on phase 3 files)
Evidence:
============================= 689 passed in 23.71s =============================
All checks passed!
Defaults chosen (open_questions.md): none
Live checks pending: none

## Proposed commits (awaiting approval)
1. Add Phase 3 alignment report, configuration schemas and validated defaults: docs/phase3_alignment.md, config/commitments.yaml, config/goals.yaml, config/buckets.yaml, config/calendar.yaml, config/readiness.yaml, config/contributions.yaml, config/memory.yaml, config/skills/*.yaml, config/decomposition.yaml, config/context.yaml, config/runtime.yaml, config/learning.yaml, config/ops.yaml, config/mcp.yaml, src/copilot/config/phase3.py, src/copilot/config/phase2.py, tests/config/test_phase3_config.py, tests/api/test_api.py, docs/decisions.md, STATUS.md


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
