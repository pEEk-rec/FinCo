# Tool Capability & Governance Matrix

> **DRAFT: awaiting user review**

This matrix declares the execution class, planner selectability, operational cost,
and governance classification for all tools in the Personal Finance Copilot.

## 1. Autonomous Analysis Tools (Planner Selectable)

These tools are strictly deterministic `read` or `compute` operations.
The autonomous planner may select and invoke them without prior human approval.

| Tool Name | Class | Cost | Description | Relevant Intents |
|---|---|---|---|---|
| `aggregate_spend_by_category` | `read` | `cheap` | Get aggregated net category spend for an IST calendar month in paise | summarize_period, explain_change, check_budget, alerts_overview |
| `check_budgets` | `read` | `cheap` | Check budget performance status (ok, warning, exceeded) for a month | check_budget, alerts_overview, whatif_add_spend |
| `compare_options` | `compute` | `medium` | Compare multiple what-if spending options side-by-side | whatif_add_spend, whatif_reduce_spend |
| `detect_anomalies` | `read` | `medium` | Detect unusual spend transactions and velocity spikes | investigate_anomaly, alerts_overview |
| `evaluate_goal_impact` | `compute` | `cheap` | Evaluate the impact of a spending decision on active goals | goal_check, whatif_add_spend |
| `explain_change` | `compute` | `medium` | Explain period-over-period spend changes via deterministic decomposition | explain_change, summarize_period |
| `forecast_category_spend` | `read` | `cheap` | Compute run-rate forecast of month-end spend for a single category | forecast, check_budget, whatif_add_spend |
| `forecast_month` | `read` | `cheap` | Forecast month-end total spend and category breakdown | forecast, alerts_overview |
| `get_balance` | `read` | `cheap` | Get current total or per-account balance in integer paise | summarize_period, goal_check |
| `get_financial_state` | `read` | `cheap` | Get a comprehensive snapshot of accounts, budgets, and spend | summarize_period, goal_check, alerts_overview |
| `get_transactions` | `read` | `cheap` | List transactions for a user across a UTC time window or category | summarize_period, explain_change, investigate_anomaly |
| `investigate_anomaly` | `compute` | `medium` | Investigate a detected financial anomaly using the hypothesis catalogue | investigate_anomaly, alerts_overview |
| `list_alerts` | `read` | `cheap` | List active or historical adaptive alerts for the user | alerts_overview, summarize_period |
| `list_goals` | `read` | `cheap` | List the user's active or paused financial goals | goal_check, summarize_period |
| `run_whatif` | `compute` | `medium` | Simulate financial outcomes of spending or contribution scenarios | whatif_add_spend, whatif_reduce_spend, goal_check |

## 2. Protected State Mutation & Governance Tools (Approval Required / User Only)

These tools write to financial/user state, or require explicit human decisions.
They are **permanently barred** from autonomous selection by the planner.

| Tool Name | Class | Cost | Description | Reason Barred from Planner |
|---|---|---|---|---|
| `categorize_batch` | `write_logical` | `expensive` | Batch update of transactions by automated rule pipeline | State mutation requires user authorization or fixed pipeline node |
| `create_goal` | `write_logical` | `cheap` | Create a new financial savings or purchase goal | State mutation requires user authorization or fixed pipeline node |
| `decide_advice` | `write_logical` | `cheap` | User approve or reject decision on draft advice | State mutation requires user authorization or fixed pipeline node |
| `decide_alert` | `write_logical` | `cheap` | User tool to acknowledge, dismiss, or snooze an alert | State mutation requires user authorization or fixed pipeline node |
| `detect_recurring` | `write_logical` | `medium` | Detect recurring subscription and bill payment series | State mutation requires user authorization or fixed pipeline node |
| `detect_transfers` | `write_logical` | `medium` | Identify own-account transfers and exclude them from spend | State mutation requires user authorization or fixed pipeline node |
| `dismiss_anomaly` | `write_logical` | `cheap` | User tool to dismiss a detected anomaly as expected | State mutation requires user authorization or fixed pipeline node |
| `draft_advice` | `write_logical` | `medium` | Generate draft financial advice for user review | State mutation requires user authorization or fixed pipeline node |
| `evaluate_alerts` | `write_logical` | `medium` | Evaluate spend and budget signals and generate adaptive alerts | State mutation requires user authorization or fixed pipeline node |
| `ingest_statements` | `write_logical` | `expensive` | Fetch and ingest statements under valid AA consent | State mutation requires user authorization or fixed pipeline node |
| `recategorize_transaction` | `write_logical` | `medium` | User or approved agent change of a transaction's category | State mutation requires user authorization or fixed pipeline node |
| `set_alert_preference` | `write_logical` | `cheap` | User tool to set alert preferences, silences, or limits | State mutation requires user authorization or fixed pipeline node |
| `undo` | `write_logical` | `medium` | Revert a single audited state mutation | State mutation requires user authorization or fixed pipeline node |
| `undo_categorize_batch` | `write_logical` | `expensive` | Revert a batch categorization run | State mutation requires user authorization or fixed pipeline node |
| `update_goal` | `write_logical` | `cheap` | Update an existing financial goal's target, progress, or deadline | State mutation requires user authorization or fixed pipeline node |

## 3. Permanently Prohibited Tool Classes

The following operations have no tool contracts and are permanently denied by policy:

- **Money Movement:** Initiating payments, bank transfers, UPI transactions, charges.
- **Trading / Execution:** Executing stock, mutual fund, crypto, or commodity orders.
- **Credential Ingestion:** Requesting or caching OTPs, PINs, passwords, or card numbers.
- **External Mutations:** Modifying third-party bank records or external APIs.

---
*Generated from `config/planner_capabilities.yaml`.*
