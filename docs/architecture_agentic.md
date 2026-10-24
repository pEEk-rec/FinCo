# FinCo Agentic Architecture: Concepts, Abstractions, and Implementation Map

This document provides a comprehensive technical reference for the agentic systems architecture of **FinCo (Financial Copilot)**. It details how modern agentic AI design patterns—such as the Plan-Act-Observe-Revise loop, modular skills, dual-tier memory systems, Model Context Protocol (MCP), supervisor-specialist multi-agent orchestration, Reflexion-style revision, and deterministic safety choke points—are implemented across the codebase.

---

## 1. High-Level Architectural Overview

FinCo combines autonomous LLM reasoning with deterministic financial engines and immutable safety policies. Rather than granting language models direct access to database transactions or APIs, FinCo uses a layered architecture where:
1. All domain operations pass through a single choke point (`execute_tool`).
2. Multi-domain queries are automatically routed between a single plan-act loop and a multi-agent supervisor graph.
3. Every numerical calculation (cashflow, calendar projections, waterfall contribution allocations, readiness scores) is performed strictly by deterministic Python engines using integer paise (zero floating-point math).
4. An independent critic inspects all aggregated multi-agent outputs for hallucinations, mathematical inconsistencies, and unaddressed sub-questions before final synthesis.

```
                          ┌─────────────────────────────────────┐
                          │     User Query / CLI / API / MCP    │
                          └──────────────────┬──────────────────┘
                                             │
                                             ▼
                          ┌─────────────────────────────────────┐
                          │   Routing Rule (Multi-Domain Check) │
                          └──────────┬────────────────┬─────────┘
                                     │                │
            [Single Domain Intent]   │                │   [Cross-Domain Intent]
                                     ▼                ▼
     ┌────────────────────────────────────┐      ┌────────────────────────────────────┐
     │ Phase 2 Plan-Act-Observe-Revise   │      │ Phase 3 Multi-Agent Supervisor     │
     │ Loop (Single Agent ReAct Engine)   │      │ Graph (LangGraph Parallel Subgraph)│
     └─────────────────┬──────────────────┘      └─────────────────┬──────────────────┘
                       │                                           │
                       │                                           ▼
                       │                         ┌────────────────────────────────────┐
                       │                         │   Typed SubQuestion Decomposition   │
                       │                         │   (Cashflow, Goals, Readiness, ...)│
                       │                         └─────────────────┬──────────────────┘
                       │                                           │
                       │                                           ▼
                       │                         ┌────────────────────────────────────┐
                       │                         │   Parallel Specialist Execution    │
                       │                         │   (Thread-Pool Concurrent Workers) │
                       │                         └─────────────────┬──────────────────┘
                       │                                           │
                       │                                           ▼
                       │                         ┌────────────────────────────────────┐
                       │                         │    Deterministic Merge Barrier     │
                       │                         │    (Contradiction & Gap Detection) │
                       │                         └─────────────────┬──────────────────┘
                       │                                           │
                       │                                           ▼
                       │                         ┌────────────────────────────────────┐
                       │                         │   Reflexion-Style Reviewer Node    │
                       │                         │   (Pass / Revise Iteration Loop)   │
                       │                         └─────────────────┬──────────────────┘
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             │
                                             ▼
                          ┌─────────────────────────────────────┐
                          │   Strict Tool Execution Choke Point │
                          │   `execute_tool(ctx, tool, args)`   │
                          └──────────────────┬──────────────────┘
                                             │
                                             ▼
                          ┌─────────────────────────────────────┐
                          │ Deterministic Core Engines (Paise)  │
                          │ Calendar, Goals, Buckets, Readiness │
                          └──────────────────┬──────────────────┘
                                             │
                                             ▼
                          ┌─────────────────────────────────────┐
                          │ SQLite WAL + Append-Only Audit Log  │
                          └─────────────────────────────────────┘
```

---

## 2. Agent Concept to Implementation Mapping

The table below maps foundational agentic AI concepts directly to their concrete implementations and source files in FinCo:

| Agent Concept | Architectural Role in FinCo | Primary Implementation Files |
| :--- | :--- | :--- |
| **Plan-Act-Observe-Revise** | Iterative goal execution where the agent selects tools, inspects structured observations, detects divergence, and revises its trajectory. | `src/copilot/workflow/agent_graph.py`<br>`src/copilot/workflow/nodes.py` |
| **Executable Skills** | Structured compound financial recipes with typed inputs, validation schemas, and reproducible tool sequences. | `src/copilot/skills/engine.py`<br>`config/skills/*.yaml` |
| **Short-Term Memory** | Working conversation state, ephemeral turn scratchpads, and execution graphs managed by LangGraph checkpoints. | `src/copilot/workflow/state.py`<br>`src/copilot/workflow/agent_graph.py` |
| **Long-Term Memory** | Episodic, contextual, and preference memory with Bayesian confidence tracking, exponential decay, and explicit forgetting. | `src/copilot/core/memory.py`<br>`src/copilot/context/retrieval.py`<br>`src/copilot/db/repo_phase3.py` |
| **Context Engineering** | Dynamic prompt construction, token budget allocation, hierarchical summarization, and data minimisation. | `src/copilot/context/builder.py`<br>`src/copilot/context/retrieval.py`<br>`config/context.yaml` |
| **Model Context Protocol (MCP)** | Standardised server interface exposing read-only analytical tools and live resources over stdio/in-process transports. | `src/copilot/mcp/server.py`<br>`config/mcp.yaml`<br>`src/copilot/cli/main.py` |
| **Supervisor & Specialists** | Hierarchical decomposition where a supervisor dispatches independent subquestions to specialised parallel worker agents. | `src/copilot/workflow/supervisor.py`<br>`src/copilot/workflow/specialists.py`<br>`src/copilot/workflow/decomposition.py` |
| **Deterministic Merge & Fault Tolerance** | Synchronisation barrier aggregating specialist findings, detecting domain conflicts, and reporting unhandled gaps. | `src/copilot/workflow/multi_agent.py` |
| **Reflexion-Style Revision** | Independent critic node validating merged findings against sub-questions and triggering corrective specialist replanning. | `src/copilot/workflow/reviewer.py`<br>`src/copilot/workflow/agent_graph.py` |
| **Human-in-the-Loop & Gates** | Hard isolation between analytical discovery and state mutation; draft reallocations and advice require two-phase approval. | `src/copilot/tools/governance.py`<br>`src/copilot/core/buckets.py`<br>`config/policy.yaml` |
| **Audit & Traceability** | Append-only audit logging recording actor (`agent` vs `user`), before/after JSON states, reasons, and policy evaluations. | `src/copilot/tools/executor.py`<br>`src/copilot/db/repo.py`<br>`src/copilot/db/migrations/001_initial.sql` |
| **Evaluation & Benchmarks** | Deterministic evaluation batteries on held-out seeds, golden regression scenarios, and cross-paradigm comparative harnesses. | `src/copilot/eval/harness_phase3.py`<br>`src/copilot/eval/orchestration_comparison.py`<br>`tests/golden/phase3/` |
| **Distributed Observability** | Hierarchical OpenTelemetry-style trace spans (`agent`, `specialist`, `reviewer`, `mcp`, `tool`) with PII sanitisation. | `src/copilot/tracing/spans.py`<br>`src/copilot/tools/executor.py` |
| **Continuous Learning** | Bounded Bayesian and EMA profile tuning based on user approval/rejection signals with immutable safety floors. | `src/copilot/core/learning.py`<br>`src/copilot/db/repo_phase3.py`<br>`config/learning.yaml` |

---

## 3. Deep-Dive Component Architecture

### 3.1 Plan-Act-Observe-Revise (Phase 2 Single Agent Loop)
- **Files:** `src/copilot/workflow/agent_graph.py`, `src/copilot/workflow/nodes.py`
- **Mechanism:** Implemented as a cyclic StateGraph in LangGraph. The agent node (`planner_agent`) formulates a thought and emits tool calls. The action node (`execute_tools`) invokes `execute_tool` via the choke point. The observe node evaluates outputs, and the revise edge determines whether another iteration is required or if the plan should terminate.
- **Guardrails:** Bounded strictly to `max_steps` (default 6). If the loop exceeds max steps or fails to converge, it falls back to a deterministic summary of observations rather than looping infinitely.

### 3.2 Executable Skills System
- **Files:** `src/copilot/skills/engine.py`, `config/skills/*.yaml`
- **Mechanism:** Skills are declarative multi-step procedures (e.g. `affordability_check`, `monthly_close`, `trip_planning`). Each skill defines input schemas, preconditions, deterministic step sequences (which call underlying read tools), and output formatting templates.
- **Determinism:** Skills run deterministically without generating LLM hallucination tokens during step orchestration, guaranteeing that financial audits follow repeatable playbooks.

### 3.3 Dual-Tier Memory System (Short-Term & Long-Term)
- **Files:** `src/copilot/core/memory.py`, `src/copilot/context/retrieval.py`, `src/copilot/db/repo_phase3.py`
- **Short-Term Memory:** Stored in LangGraph thread checkpointers (`MemorySaver` / SQLite). Captures intra-session conversation turns, intermediate tool outputs, and active candidate plans.
- **Long-Term Memory:** Stored in the `memory_items` and `memory_evidence` SQLite tables across 5 distinct kinds:
  1. `recurring_pattern`: Inferred or confirmed cashflow periodicity.
  2. `contextual_exception`: Festival/seasonal deviations that prevent over-alerting.
  3. `advice_feedback`: Records user rejection of specific advice categories to enforce a 30-day advice suppression cooldown.
  4. `preference`: Risk tolerance, liquidity buffer targets, or savings priorities.
  5. `merchant_habit`: Verified merchant categorization and payment methods.
- **Bayesian Confidence & Decay:** Confidence is tracked in basis points ($0 \dots 10,000$). Evidence updates confidence asymmetrically: user confirmation increases confidence by $+2,500$ bps, while contradictory evidence decreases it by $-3,000$ bps. Memories experience exponential recency decay ($e^{-\lambda \Delta t}$); items falling below 3,000 bps automatically become `stale` or `retired`.
- **Right to be Forgotten:** Dedicated tool `forget_memory(user_id, memory_id)` transitions the memory to `forgotten` status, purges active statement text, and logs a permanent governance audit event. Forgotten memories are excluded from all context retrieval.

### 3.4 Context Engineering & Token Management
- **Files:** `src/copilot/context/builder.py`, `src/copilot/context/retrieval.py`, `config/context.yaml`
- **Mechanism:** Before LLM invocation, FinCo dynamically constructs a token-budgeted prompt envelope. It prioritizes:
  1. Core system instructions & immutable safety constraints (highest priority).
  2. High-salience long-term memories relevant to the query domain (scored by exact keyword, category match, confidence, and recency).
  3. Structured state summaries (net balances, upcoming 7-day calendar cashflows, active goal progress).
  4. Short-term dialogue history (truncated to token budget).
- **Data Minimisation:** Suppresses individual transaction rows when aggregate categories suffice, protecting user privacy and preventing token bloat.

### 3.5 Model Context Protocol (MCP) Server
- **Files:** `src/copilot/mcp/server.py`, `config/mcp.yaml`
- **Mechanism:** Built using the official Anthropic Model Context Protocol Python SDK (`mcp==2.3.0`). Exposes FinCo's analytical capabilities to external AI hosts (such as Claude Desktop or IDE assistants).
- **Safety Rule 17 Enforced:** Only `read` and `compute` tools are exposed over MCP. All write tools (`create_goal`, `allocate_bucket`, `apply_reallocation`) are strictly omitted.
- **Execution Choke Point:** Every tool call received over MCP is routed through `execute_tool(ctx, tool_name, args, actor="agent")`, guaranteeing that MCP access is subject to identical audit logging, permission checks, and distributed span tracing as internal agent calls.
- **Live Resources:** Exposes read-only standard URI resources:
  - `finco://monthly_review/latest`: Latest finalized monthly financial report.
  - `finco://calendar/summary`: 30-day liquidity and cashflow forecast.
  - `finco://buckets/summary`: Virtual budget balances and over-allocation status.

### 3.6 Supervisor & Parallel Specialists
- **Files:** `src/copilot/workflow/supervisor.py`, `src/copilot/workflow/specialists.py`, `src/copilot/workflow/decomposition.py`
- **Supervisor Role:** When a query spans multiple decoupled financial domains (determined by `should_route_to_multi_agent`), the supervisor decomposes the user's intent into 2 to 4 typed `SubQuestion` specifications:
  - `cashflow_specialist`: Projects balance trajectories, commitments, and shortfalls.
  - `goal_specialist`: Assesses goal horizons, required monthly contributions, and feasibility.
  - `readiness_specialist`: Assesses emergency cushions, debt obligations, and savings ratios.
  - `policy_specialist`: Evaluates rule compliance, tax/contribution limits, and risk guardrails.
- **Parallel Dispatch:** Specialists execute concurrently across Python thread pools. Each specialist runs with an isolated context envelope restricted to tools in its domain, eliminating cross-domain context contamination.

### 3.7 Deterministic Merge Barrier & Fault Tolerance
- **Files:** `src/copilot/workflow/multi_agent.py`
- **Synchronization:** The merge node acts as a barrier waiting for all dispatched specialists to return `SpecialistReport` objects.
- **Contradiction Detection:** Checks for numerical conflicts between specialists (e.g. cashflow specialist reporting surplus while readiness specialist identifies an emergency reserve shortfall).
- **Fault Tolerance:** If one or more specialists fail, time out, or throw errors, the merge node does not crash. It aggregates successful findings, isolates the failed domain, and surfaces explicit gap notices in `SpecialistReport.gaps_json`, allowing the supervisor to provide a partial answer with transparent limitations.

### 3.8 Reflexion-Style Self-Correction (Reviewer Node)
- **Files:** `src/copilot/workflow/reviewer.py`, `src/copilot/workflow/agent_graph.py`
- **Mechanism:** Before generating the final response to the user, the merged report passes to an independent critic (`ReviewerNode`).
- **Validation Rules:**
  1. *Subquestion Coverage:* Verifies that every question decomposed by the supervisor has corresponding findings.
  2. *Arithmetic Verification:* Validates that numbers quoted match underlying database figures.
  3. *Policy & Safety Checks:* Verifies that no prohibited financial advice (such as specific mutual fund tickers or speculative stock tips) was introduced.
- **Revision Loop:** If critiques are found and the revision counter is below 1, the graph routes back to the supervisor with critique feedback (`ReviseAction`). If verification passes (or after 1 revision), the graph proceeds to final synthesis.

### 3.9 Human-in-the-Loop & Approval Gates
- **Files:** `src/copilot/tools/governance.py`, `src/copilot/core/buckets.py`, `config/policy.yaml`
- **Immutable Policy (Safety Rule 1):** Zero money movement. FinCo cannot execute UPI transfers, bank payments, or debit operations under any circumstance.
- **Two-Phase Approval:** Operations that alter virtual planning state (reallocating budget between buckets, finalizing financial advice, changing categorization rules) are generated in `draft` status. State mutation requires an explicit secondary user approval (`approve_reallocation` / `decide_advice`). Reallocations cannot be applied without explicit user sign-off.

### 3.10 Audit Logging & Choke Point Enclosure
- **Files:** `src/copilot/tools/executor.py`, `src/copilot/db/repo.py`
- **Choke Point:** All tools—whether invoked by the Phase 2 planner, a Phase 3 specialist, a skill script, the REST API, or an external MCP client—must pass through:
  ```python
  execute_tool(ctx: ToolContext, tool_name: str, arguments_dict: dict[str, Any]) -> ToolResult
  ```
- **Audit Ledger:** Every execution creates an immutable record in `audit_events` with:
  - `actor`: `"user"`, `"agent"`, or `"system"`.
  - `event_type`: The executed tool or governance decision.
  - `before_json` / `after_json`: Complete state diff for rollbacks.
  - `policy_decision`: `"allow"`, `"deny"`, or `"needs_approval"`.

### 3.11 Continuous Learning & Safety Floors
- **Files:** `src/copilot/core/learning.py`, `config/learning.yaml`
- **Mechanism:** Updates user-specific behavioural models based on user interactions:
  - Acceptance of advice increases domain receptivity.
  - Rejection or snoozing triggers advice suppression cooldowns (30 days minimum).
  - Essential spend floors and emergency reserve requirements have hardcoded lower bounds ($1.0\times$ monthly essential expenses) that cannot be altered or lowered by the learning engine, preventing the copilot from encouraging risky financial behaviour.

---

## 4. Verification and Safety Matrix

Every agentic component in FinCo is verified through automated tests, regression benchmarks, and invariant checks:

| Subsystem | Primary Verification Suite | Invariants Enforced |
| :--- | :--- | :--- |
| **Tool Execution** | `tests/tools/test_no_money_movement.py`<br>`tests/tools/test_executor.py` | 100% of tool calls pass through `execute_tool`; write tools denied to agent; zero money movement. |
| **Virtual Buckets** | `tests/core/test_buckets.py`<br>`tests/tools/test_buckets_tools.py` | Allocations cannot exceed liquid deposits; reallocations require two-phase user approval. |
| **Financial Calendar** | `tests/core/test_calendar.py`<br>`tests/tools/test_calendar_tools.py` | Integer paise cashflow arithmetic; February 28/29 leap year correctness; year boundary rolling. |
| **Multi-Agent Orchestration** | `tests/workflow/test_multi_agent.py`<br>`tests/workflow/test_reviewer.py` | Max 1 revision loop; graceful degradation on specialist failure; 0% unhandled exception rate. |
| **Model Context Protocol** | `tests/mcp/test_mcp.py` | Read-only tool exposure; Safety Rule 17 dynamic mutation rejection; data minimisation active. |
| **Behavioural Memory** | `tests/core/test_memory.py`<br>`tests/core/test_memory_decay.py` | Exponential decay over time; instant exclusion of forgotten memories; 30-day advice suppression. |
| **Evaluation Battery** | `eval/run_eval_phase3.py`<br>`tests/golden/phase3/` | 24 golden scenarios pass; deterministic math matches on held-out seeds; zero floating-point currency math. |

---

## 5. Architectural Invariants

The following invariants must be preserved across all future extensions of the codebase:
1. **Integer Currency Arithmetic:** All monetary amounts are stored and calculated in integer paise. No `float` types are permitted for currency.
2. **Choke Point Exclusivity:** Direct calls to core business logic or raw database writes bypassing `execute_tool` are strictly prohibited.
3. **Multi-Tenant Isolation:** All database tables include a `user_id` column, and every query, memory retrieval, and calendar projection filters on `user_id`.
4. **Single-Loop Routing Integrity:** Single-domain intents must never pay the latency and token overhead of multi-agent decomposition; they must route directly to the single loop.
5. **Human Primacy:** No state mutation affecting financial goals, budget allocations, or categorization rules may be applied without user consent.

## Phase 4 additions

- **New tools** (all through `execute_tool`): offers, accept/dismiss, experiment lifecycle, check-ins,
  reviews, `confirm_review_integrity`, adjustments, XP/badges, `record_contextual_exception` with
  optional day ranges. Write tools are `agent: deny, user: allow`, are not planner-selectable and
  are not exposed over MCP; only read tools are.
- **Specialist:** `CoachAgent` answers coaching and experiment questions with minimal plans of read
  tools; a failed tool degrades to a partial answer instead of an error.
- **Intent reading:** model first, rules validate and fall back (`core/intent.py`), with a redacted-
  question response cache and a glossary prompt (`config/intent_glossary.yaml`).
- **Concurrency:** one SQLite connection may be shared by threads, so `execute_tool` takes a
  per-connection lock around the savepoint, and tool registration is locked.

## Capture additions: an event-driven loop with a human in it

Everything above starts from a user's question or a schedule. Capture starts from **an event in the
world**: a bank alert. It is the same architecture with a different trigger.

```
 bank SMS -> phone rule -> POST /api/capture/sms          simulator / manual entry
                               |                                   |
                  secret, rate, size, sender allowlist, OTP drop   |
                               v                                   v
                    parse in memory (templates), text discarded -> record_payment_event
                                                                     |
        counterparty kind -> ask policy -> 3 ranked guesses ----------+
                               |
              auto-tag (known shop, regular payment)   or   ask
                               |                              |
                     "Tagged for you. Change"        overlay / notification / Today
                                                              |
                                      label_payment_event (the user's tap)
                                                              |
              +-------------------+--------------------------+
              v                   v                          v
     merchant habit -> memory   signal weights -> learner   person policy (k of n)
                                                              |
        bank link (Account Aggregator) fetch -> ledger -> reconcile_payment_events
                (consent state machine, revocable)     (UTR first, never on ambiguity)
```

- **Human in the loop at the moment of payment.** The agent proposes (ranked, explainable guesses);
  only the user's tap becomes a label with `category_source = user`, and nothing automatic may overwrite
  it. Fatigue rules (quiet hours, a daily budget, a per-payee cooldown) turn an ask into an inbox item
  rather than an interruption.
- **Every action is a tool through `execute_tool`.** Recording, labelling, simulating, reconciling,
  consent changes and fetches are governed, audited and undoable where it makes sense. The agent is
  denied every capture write; the webhook and the runtime jobs act as the system.
- **Learning from labels reuses the Phase 3 learner.** Each ranking signal (payee history, time of
  day, amount, day of month, name hint, recency) keeps a Beta posterior in `feedback_stats`; its weight is
  the configured weight times a clamped multiplier, renormalised to 10000. Bounded, resettable, visible
  in `copilot learning show`. Simulated events teach nothing unless a demo flag says so.
- **Two lanes, one ledger.** The alert lane is fast and unverified; the bank link is slow and verified.
  Reconciliation joins them, and spend views never count a payment in both.
- **Privacy is structural.** Raw message text exists only in memory between the webhook and the parser.
  Tables, logs, spans, notifications and model prompts are scanned by tests for a marker string.
