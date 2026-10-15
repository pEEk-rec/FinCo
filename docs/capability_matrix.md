# Tool Capability & Governance Matrix

This matrix declares the execution class, planner selectability, operational cost, and governance classification for all tools, skills, specialists, and resources in the Personal Finance Copilot (FinCo) across Phase 1, Phase 2, and Phase 3.

---

## 1. Autonomous Analysis Tools (Planner & Specialist Selectable)

These tools are strictly deterministic `read` or `compute` operations. The autonomous planner, supervisor, parallel specialists, and MCP clients may select and invoke them without prior human approval.

| Tool Name | Class | Cost | Description | Domain / Intent |
| :--- | :--- | :--- | :--- | :--- |
| `aggregate_spend_by_category` | `read` | `cheap` | Net category spend for an IST calendar month in paise | Spending / Trends |
| `assess_goal_feasibility` | `compute` | `cheap` | Assess required monthly contributions and feasibility of goals | Goals / Planning |
| `assess_readiness` | `compute` | `cheap` | Compute liquidity, runway, debt-to-income, and savings readiness score | Readiness / Health |
| `build_calendar` | `compute` | `medium` | Generate 60-day projected daily cashflows, buffer shortfalls, and coverage | Cashflow / Calendar |
| `check_budgets` | `read` | `cheap` | Check budget performance status (ok, warning, exceeded) for a month | Budgets / Alerts |
| `compare_options` | `compute` | `medium` | Compare multiple what-if spending options side-by-side | Simulations / Tradeoffs |
| `compare_tradeoffs` | `compute` | `medium` | Compare tradeoff alternatives between competing goals and contributions | Contributions / Goals |
| `detect_anomalies` | `read` | `medium` | Detect unusual spend transactions and velocity spikes | Anomalies / Security |
| `draft_reallocation` | `compute` | `cheap` | Formulate a draft virtual budget reallocation between buckets | Buckets / Reallocation |
| `evaluate_goal_impact` | `compute` | `cheap` | Evaluate the impact of a spending decision on active goals | Goals / Impact |
| `expand_commitments` | `read` | `cheap` | Expand scheduled commitment occurrences across a time horizon | Commitments / Calendar |
| `explain_change` | `compute` | `medium` | Explain period-over-period spend changes via deterministic decomposition | Spending / Variance |
| `forecast_category_spend` | `read` | `cheap` | Run-rate forecast of month-end spend for a single category | Forecast / Budgets |
| `forecast_month` | `read` | `cheap` | Forecast month-end total spend and category breakdown | Forecast / Review |
| `get_allocation_summary` | `read` | `cheap` | Virtual buckets allocation summary, reserved balances, and over-allocation | Buckets / Allocations |
| `get_balance` | `read` | `cheap` | Current total or per-account balance in integer paise | Accounts / Balance |
| `get_financial_state` | `read` | `cheap` | Comprehensive snapshot of accounts, budgets, and spend | Overview / Dashboard |
| `get_learning_profile` | `read` | `cheap` | Retrieve user behavioural learning profile and domain receptivities | Learning / Memory |
| `get_transactions` | `read` | `cheap` | Query transactions across a UTC time window or category | Transactions / History |
| `investigate_anomaly` | `compute` | `medium` | Investigate an anomaly using the hypothesis catalogue | Anomalies / Root Cause |
| `list_alerts` | `read` | `cheap` | List active or historical adaptive alerts for the user | Alerts / Notifications |
| `list_buckets` | `read` | `cheap` | List virtual spending and savings buckets for the user | Buckets / Allocations |
| `list_commitments` | `read` | `cheap` | List recurring financial commitments, SIPs, and fixed outflows | Commitments / Recurring |
| `list_goals` | `read` | `cheap` | List the user's active or paused financial goals | Goals / Progress |
| `list_skills` | `read` | `cheap` | List available compound financial analysis skills | Skills / Workflows |
| `plan_contributions` | `compute` | `medium` | Generate waterfall monthly contribution plan across horizon | Contributions / Savings |
| `retrieve_memories` | `read` | `cheap` | Retrieve active contextual preferences and behavioural memories | Context / Memory |
| `run_skill` | `compute` | `medium` | Execute a compound financial recipe (affordability check, etc.) | Skills / Workflows |
| `run_whatif` | `compute` | `medium` | Simulate financial outcomes of spending or contribution scenarios | Scenarios / What-If |
| `suggest_commitments` | `compute` | `medium` | Suggest detected recurring transactions as candidate commitments | Commitments / Discovery |

---

## 2. Protected State Mutation & Governance Tools (Approval Required / User Only)

These tools modify financial, planning, or user behavioural state. They are **permanently barred** from autonomous execution by the planner or external MCP clients. They require explicit human approval (two-phase gates) or direct user invocation via the CLI/API.

| Tool Name | Class | Cost | Description | Reason Barred from Autonomous Execution |
| :--- | :--- | :--- | :--- | :--- |
| `add_commitment` | `write_logical` | `cheap` | Confirm and add a new recurring commitment | Financial obligation creation requires human confirmation |
| `allocate_bucket` | `write_logical` | `cheap` | Allocate money to a virtual bucket from liquid balance | Budget allocation state mutation |
| `apply_reallocation` | `write_logical` | `cheap` | Apply an approved draft budget reallocation | Two-phase approval required; cannot apply unapproved draft |
| `categorize_batch` | `write_logical` | `expensive` | Batch categorize transactions via rule engine | State mutation requires user review or fixed pipeline |
| `create_bucket` | `write_logical` | `cheap` | Create a new virtual spending/savings bucket | Virtual accounts structure creation |
| `create_goal` | `write_logical` | `cheap` | Create a new financial savings or purchase goal | Target creation requires user decision |
| `decide_advice` | `write_logical` | `cheap` | User approve or reject decision on draft advice | Advice governance approval gate |
| `decide_alert` | `write_logical` | `cheap` | User tool to acknowledge, dismiss, or snooze an alert | Human alert lifecycle decision |
| `detect_recurring` | `write_logical` | `medium` | Detect recurring subscription and bill payment series | Writes detected candidate recurring series |
| `detect_transfers` | `write_logical` | `medium` | Identify own-account transfers and exclude from spend | Alters transaction spending classification |
| `dismiss_anomaly` | `write_logical` | `cheap` | Dismiss a detected anomaly as expected | Human verification gate |
| `draft_advice` | `write_logical` | `medium` | Generate draft financial advice for user review | Advice requires human review prior to activation |
| `evaluate_alerts` | `write_logical` | `medium` | Evaluate spend and budget signals and generate alerts | Writes alert notification records |
| `forget_memory` | `write_logical` | `cheap` | Mark memory as forgotten and purge statement content | Privacy compliance and memory lifecycle |
| `ingest_statements` | `write_logical` | `expensive` | Ingest statements under valid Account Aggregator consent | Banking ingestion pipeline execution |
| `link_goal_bucket` | `write_logical` | `cheap` | Link a goal to a virtual bucket for progress tracking | Goal tracking linkage mutation |
| `recategorize_transaction` | `write_logical` | `medium` | Change a transaction's category | Financial transaction record mutation |
| `record_memory_evidence`| `write_logical` | `cheap` | Update Bayesian memory confidence with new evidence | Memory state update |
| `set_alert_preference` | `write_logical` | `cheap` | Set alert thresholds, silences, or dampening preferences | User configuration mutation |
| `undo` | `write_logical` | `medium` | Revert a single audited state mutation | Rollback execution |
| `undo_categorize_batch` | `write_logical` | `expensive` | Revert a batch categorization run | Batch rollback execution |
| `update_commitment` | `write_logical` | `cheap` | Pause, resume, or modify recurring commitment status | Financial commitment mutation |
| `update_goal` | `write_logical` | `cheap` | Update goal target amount, deadline, or status | Goal target mutation |
| `update_learning_weights`| `write_logical`| `cheap` | Update behavioural learning profile weights | Learner state mutation |

---

## 3. Parallel Multi-Agent Specialists (Phase 3 Subgraph)

Specialists are domain-bounded workers dispatched concurrently by the LangGraph Supervisor when a query spans multiple financial dimensions.

| Specialist Role | Domain | Available Tools | Primary Objective |
| :--- | :--- | :--- | :--- |
| `cashflow_specialist` | `cashflow` | `build_calendar`, `list_commitments`, `expand_commitments`, `get_balance` | Project 60-day liquid trajectory, detect shortfall periods, and evaluate commitment coverage. |
| `goal_specialist` | `goals` | `list_goals`, `assess_goal_feasibility`, `get_allocation_summary`, `list_buckets` | Assess target deadlines, calculate required monthly savings, and check bucket allocations. |
| `readiness_specialist` | `readiness` | `assess_readiness`, `plan_contributions`, `compare_tradeoffs` | Compute emergency cushion months, debt ratios, and multi-goal waterfall contribution capacity. |
| `policy_specialist` | `policy` | `check_budgets`, `retrieve_memories`, `get_learning_profile` | Verify adherence to risk preferences, tax limits, and festival/seasonal exception rules. |

---

## 4. Executable Financial Skills

Skills are declarative compound workflows defined in YAML and executed deterministically by `src/copilot/skills/engine.py`.

| Skill Identifier | Configuration Path | Steps / Invocations | Purpose |
| :--- | :--- | :--- | :--- |
| `affordability_check` | `config/skills/affordability_check.yaml` | `build_calendar` $\rightarrow$ `assess_readiness` $\rightarrow$ `run_whatif` | Evaluates whether a proposed lump-sum purchase causes liquidity shortfalls or impairs emergency reserves. |
| `contribution_review` | `config/skills/contribution_review.yaml` | `plan_contributions` $\rightarrow$ `compare_tradeoffs` $\rightarrow$ `list_goals` | Reviews monthly savings allocations across goals and suggests waterfall rebalancing options. |
| `explain_month_change`| `config/skills/explain_month_change.yaml`| `explain_change` $\rightarrow$ `aggregate_spend_by_category` $\rightarrow$ `detect_anomalies` | Decomposes period-over-period spend fluctuations into price, volume, and anomaly factors. |
| `monthly_close` | `config/skills/monthly_close.yaml` | `check_budgets` $\rightarrow$ `forecast_month` $\rightarrow$ `get_allocation_summary` | End-of-month reconciliation checking budget status and preparing virtual bucket rollovers. |
| `trip_planning` | `config/skills/trip_planning.yaml` | `assess_goal_feasibility` $\rightarrow$ `build_calendar` $\rightarrow$ `draft_reallocation` | Comprehensive vacation budget analysis balancing trip expenses against ongoing SIP contributions. |

---

## 5. Model Context Protocol (MCP) Live Resources

Live read-only context resources exposed over stdio and in-process MCP by `src/copilot/mcp/server.py`.

| URI | Content Schema | Update Frequency | Description |
| :--- | :--- | :--- | :--- |
| `finco://monthly_review/latest` | JSON | Monthly / On-Demand | Latest finalized monthly financial review, spending breakdown, and anomalies. |
| `finco://calendar/summary` | JSON | Real-Time | 30-day projected cashflows, minimum balance, and upcoming commitment list. |
| `finco://buckets/summary` | JSON | Real-Time | Active virtual buckets, allocated vs spent paise, and unallocated balance. |

---

## 6. Permanently Prohibited Tool Classes

The following operations have no tool contracts and are permanently denied by architectural policy:

1. **Money Movement:** Initiating payments, bank transfers, UPI transactions, credit card charges, or NACH mandates.
2. **Trading / Investment Execution:** Executing stock, mutual fund, crypto, or bond buy/sell orders.
3. **Credential Ingestion:** Requesting, parsing, or storing bank passwords, debit card PINs, CVVs, or OTPs.
4. **Third-Party State Alteration:** Modifying external banking records, CRA accounts, or tax portals.

---
*Generated and validated against `config/planner_capabilities.yaml`, `config/mcp.yaml`, and `src/copilot/tools/registry.py`.*
