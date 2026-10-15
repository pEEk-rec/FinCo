# Phase 3 Alignment & Adaptation Report (Stage 3.0)

**Date:** 2026-10-14  
**Workspace:** `d:/Academics/7thSEM/AgenticAI/FinCo/implementation`  
**Phase:** 3 (Advanced Financial Copilot)  
**Baseline Test Suite:** 682 passed in 22.23s, 0 failures, 0 skips, 0 xfails  
**Lint Status:** Ruff 0.8.2 clean (0 errors)  

---

## 1. Adaptation Table (PLAN_PHASE3 Section 0.7)

| If you find... | Found in Codebase | Action Taken |
|---|---|---|
| **Phase 2 `goals` table exists** | Yes: `goals` table defined in `003_phase2_schema.sql` with columns `(id, user_id, name, kind, target_paise, current_paise, deadline, priority, created_at, updated_at)`. | In Stage 3.1, apply migration `004_phase3_schema.sql` adding `progress_source`, `linked_account_id`, `start_date`, `essential`, and `notes`. Never recreate table; existing rows remain valid. Column `deadline` is retained as the target date column. |
| **No `goals` table (Phase 2 deviated)** | N/A (table exists). | N/A. |
| **Phase 2 goal maths (`required_monthly_paise`, `monthly_surplus_estimate`, `goal_status`) exist** | Yes: implemented in `src/copilot/core/goals.py` with integer paise and ceil rounding. | Reused directly. Extended with multi-month contribution history, projected completion range (`low`/`expected`/`high`), and feasibility without duplicating or altering existing functions or tests. |
| **Phase 2 simulation engine with a scenario model** | Yes: implemented in `src/copilot/core/whatif.py` (`Scenario`, `SimulationResult`, scenario types `add_spend`, `reduce_spend`, `income_shock`). | Add new Phase 3 scenario kinds (`change_contribution`, `add_commitment`, `remove_commitment`, `shift_goal_date`, `allocate_to_bucket`) via the simulation dispatch table / extension point in Stage 3.5. Existing scenarios behave identically. |
| **Simulation engine missing or not extensible** | N/A (extensible via scenario kind dispatch). | Unified projection engine in `src/copilot/core/calendar.py` serves as the forward-looking daily engine. |
| **Phase 0 memory models** | Yes: `src/copilot/models/memory.py` contains `MemoryEntry` model. | Extended and reused in `src/copilot/models/memory.py` and `src/copilot/core/memory.py`. No parallel memory system. |
| **Phase 1 `recurring_series`** | Yes: `recurring_series` table exists in Phase 1 schema with cadence, amount, and confidence. | Used directly by `suggest_commitments()` to suggest draft commitments. |
| **Phase 1 views `v_balance`, `v_category_totals_month`, budget status** | Yes: defined in `001_phase1_schema.sql` and used across services. | Used directly as the source of truth for liquid balances and monthly category spend. Balances are never recomputed separately. |
| **Phase 2 planner, capability matrix, intents, plan templates, narration validator** | Yes: fully implemented in `src/copilot/agent/`, `src/copilot/core/intent.py`, and `src/copilot/validation/`. | Extended with new Phase 3 intents, plan templates, capability matrix rows, and narration templates. Never forked. |
| **Phase 2 is incomplete** | N/A (Phase 2 is 100% complete and hardened). | All Phase 2 stages (2.0 to 2.11) are complete. |
| **An HTTP API layer exists (`src/copilot/api/`)** | Yes: FastAPI app exists with OpenAPI schema, TS generator, and test client (`tests/api/test_api.py`). | Add Phase 3 read and write endpoints to `src/copilot/api/`, regenerate OpenAPI snapshot and TS types, add route tests. |
| **No API layer** | N/A (API layer exists). | N/A. |
| **Capture-lane tables (ADR-0001: `payment_events`, `capture_labels`)** | Not yet created in SQLite schema. | Added hook function `record_capture_label_evidence()` in `src/copilot/core/memory.py` to ingest user labels into behavioural memory when capture lane arrives. |
| **A Phase 3 table name already exists with a different meaning** | Checked all schema tables: no naming collisions. | Standard table names used directly. |
| **A config file named in this plan exists** | `config/goals.yaml` exists with Phase 2 keys (`max_horizon_months`, `surplus_lookback_months`, `min_history_months_for_surplus`, `allowed_priorities`). | Merged new Phase 3 keys (`projection_months: 3`, `allowed_progress_sources`, `default_progress_source`) preserving all existing keys. |

---

## 2. Phase 2 Stages and Verification Status

| Stage | Name | Status | Evidence |
|---|---|---|---|
| Stage 2.0 | Discover, Align, Adapt & Pydantic Configs | DONE | `test_phase2_config.py` passed |
| Stage 2.1 | Schema Migrations & Pydantic Models | DONE | `003_phase2_schema.sql` applied |
| Stage 2.2 | Tool Infrastructure & Capability Matrix | DONE | 17 tools governed by `execute_tool` |
| Stage 2.3 | Intent Understanding & Refusal Firewalls | DONE | 100% intent classification and refusal |
| Stage 2.4 | Dynamic Planner & Step-Level Validation | DONE | Deterministic templates + validator |
| Stage 2.5 | Goal-Aware Reasoning Engine | DONE | Integer paise, status logic |
| Stage 2.6 | Causal Investigation Engine | DONE | 8 hypotheses, counterfactual evidence |
| Stage 2.7 | What-If Simulation Engine | DONE | 3 scenario types, comparison engine |
| Stage 2.8 | Grounded Narration & Adaptive Alerts | DONE | Damped alerts, grounded explanations |
| Stage 2.9 | Activity Timeline & Rich CLI Interface | DONE | Unified timeline read model |
| Stage 2.10| Evaluation Harness & Golden Scenarios | DONE | 16 golden scenarios passed |
| Stage 2.11| Hardening & Documentation Sign-Off | DONE | Exit checklist verified |

---

## 3. LangGraph Version & Capability Analysis

- **Installed Version:** `langgraph 1.2.15` (with `langgraph-checkpoint 2.1.3`, `langsmith 0.14.8`).
- **Parallel Branches (Fan-Out / Fan-In):**
  - **Static Fan-Out:** `builder.add_edge("decompose", "cashflow_specialist")`, `builder.add_edge("decompose", "goals_specialist")`, `builder.add_edge("decompose", "readiness_specialist")`, `builder.add_edge("decompose", "behaviour_specialist")`. LangGraph automatically runs independent branch nodes concurrently.
  - **Dynamic Fan-Out (Map-Reduce):** Supports `langgraph.types.Send(node_name, sub_question_state)` from conditional edges to dynamically fan-out across generated sub-questions.
  - **Fan-In / Merge:** Branch outputs converge at a single downstream node (e.g. `merge_node`) via standard incoming edges (`builder.add_edge("cashflow_specialist", "merge")`, etc.).
- **Compiled Subgraphs as Nodes:**
  - `builder.add_node("specialist_role", compiled_subgraph)` is natively supported in LangGraph 1.2.x. Each specialist agent can be a compiled `StateGraph` encapsulated with its own state slice, tools, and error boundary.

---

## 4. Baseline Test Suite Execution

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Academics\7thSEM\AgenticAI\FinCo\implementation
configfile: pyproject.toml
plugins: anyio-4.15.1, langsmith-0.14.8
collected 682 items

........................................................................ [ 10%]
........................................................................ [ 21%]
........................................................................ [ 31%]
........................................................................ [ 42%]
........................................................................ [ 52%]
........................................................................ [ 63%]
........................................................................ [ 73%]
........................................................................ [ 84%]
........................................................................ [ 95%]
..................................                                       [100%]
682 passed in 22.23s
============================= 682 passed in 22.23s =============================
```

---

## 5. Phase 3 Configuration Skeletons Added

The following 14 YAML configuration files are created and validated with Pydantic in `src/copilot/config/phase3.py`:
1. `config/commitments.yaml` - tolerance, matching rules, allowed kinds and schedule cadences.
2. `config/goals.yaml` - merged with Phase 2 keys, adds projection lookback and progress sources.
3. `config/buckets.yaml` - low balance threshold bp, draft TTL, allowed bucket kinds, period policies.
4. `config/calendar.yaml` - default horizon (60 days), max horizon (180 days), min buffer (₹1,000 / 100,000 paise).
5. `config/readiness.yaml` - criteria thresholds, emergency months target (3), emergency min months (1), essential categories.
6. `config/contributions.yaml` - waterfall order, default horizon (6 mo), max horizon (24 mo), max alternatives (3).
7. `config/memory.yaml` - thresholds bp (use: 6000, stale: 4000, retire: 2000), half lives, decay weights, exception reasons.
8. `config/skills/` - directory containing manifests for `affordability_check`, `monthly_close`, `trip_planning`, `contribution_review`, and `explain_month_change`.
9. `config/decomposition.yaml` - max subquestions per task (4), domain decomposition templates.
10. `config/context.yaml` - token budgets per purpose, top-k memories (5), token estimation ratio.
11. `config/runtime.yaml` - loop interval (60s), lease duration (300s), max retries (3), standard job definitions.
12. `config/learning.yaml` - Beta prior (α=2, β=2), learning rate η=0.5, multiplier bounds [0.5, 1.5], hard floor severities.
13. `config/ops.yaml` - observability pricing, retention, reporting settings.
14. `config/mcp.yaml` - server name, protocol version, transport (stdio), exposed tool list.
