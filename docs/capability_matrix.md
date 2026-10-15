# Tool Capability & Governance Matrix

> **DRAFT: awaiting user review**

This matrix declares the execution class, planner selectability, operational cost,
and governance classification for all tools in the Personal Finance Copilot.

## 1. Autonomous Analysis Tools (Planner Selectable)

These tools are strictly deterministic `read` or `compute` operations.
The autonomous planner may select and invoke them without prior human approval.

| Tool Name | Class | Cost | Description | Relevant Intents |
|---|---|---|---|---|
| `affordability_check` | `compute` | `medium` | Run affordability check skill: calendar projection, what-if spend, commitments, and goals | affordability |
| `aggregate_spend_by_category` | `read` | `cheap` | Get aggregated net category spend for an IST calendar month in paise | summarize_period, explain_change, check_budget, alerts_overview |
| `assess_investment_readiness` | `compute` | `medium` | Assess savings capacity and financial cushion against readiness criteria | readiness_check, affordability |
| `check_budgets` | `read` | `cheap` | Check budget performance status (ok, warning, exceeded) for a month | check_budget, alerts_overview, whatif_add_spend |
| `check_commitment_coverage` | `read` | `cheap` | Check commitment coverage against buffer in calendar projection | commitment_check, affordability |
| `compare_options` | `compute` | `medium` | Compare multiple what-if spending options side-by-side | whatif_add_spend, whatif_reduce_spend |
| `compare_tradeoffs` | `compute` | `medium` | Compare scenario alternatives assessing cash flow and constraints | tradeoff_analysis, affordability |
| `contribution_review` | `compute` | `medium` | Run contribution review skill: investment readiness, contribution plan, and goal status | contribution_check |
| `design_experiment_from_goal` | `compute` | `medium` | Run goal-to-experiment decomposition skill | start_experiment, goal_check |
| `detect_anomalies` | `read` | `medium` | Detect unusual spend transactions and velocity spikes | investigate_anomaly, alerts_overview |
| `evaluate_goal_impact` | `compute` | `cheap` | Evaluate the impact of a spending decision on active goals | goal_check, whatif_add_spend |
| `experiment_progress` | `read` | `cheap` | Get progress, current observed spend/metric, and pace for an experiment | experiment_status |
| `explain_change` | `compute` | `medium` | Explain period-over-period spend changes via deterministic decomposition | explain_change, summarize_period |
| `explain_memory` | `read` | `cheap` | Explain evidence and confidence calculations for a memory item | memory_query |
| `explain_month_change` | `compute` | `medium` | Run explain month change skill: causal investigation into spend changes and memory context | explain_change |
| `forecast_category_spend` | `read` | `cheap` | Compute run-rate forecast of month-end spend for a single category | forecast, check_budget, whatif_add_spend |
| `forecast_month` | `read` | `cheap` | Forecast month-end total spend and category breakdown | forecast, alerts_overview |
| `get_allocation_summary` | `read` | `cheap` | Summarize reserved bucket totals and available unallocated funds | bucket_check, summarize_period |
| `get_balance` | `read` | `cheap` | Get current total or per-account balance in integer paise | summarize_period, goal_check |
| `get_bucket_status` | `read` | `cheap` | Evaluate derived balance, spend, and status for a virtual bucket | bucket_check |
| `get_calendar` | `compute` | `medium` | Project daily cash flow, running balances, and commitment coverage | cashflow_projection, affordability |
| `get_commitment_status` | `read` | `cheap` | Get status, due dates, and match history for a commitment | commitment_check |
| `get_experiment` | `read` | `cheap` | Get financial experiment details by id | experiment_status |
| `get_financial_state` | `read` | `cheap` | Get a comprehensive snapshot of accounts, budgets, and spend | summarize_period, goal_check, alerts_overview |
| `get_goal_progress` | `read` | `cheap` | Evaluate current balance, pace, and projected completion for a goal | goal_check, goal_progress, summarize_period |
| `get_offer_details` | `read` | `cheap` | Get full details of a specific challenge offer | challenge_suggestions, start_experiment |
| `get_personal_bests` | `read` | `cheap` | Get user personal best records across metrics | progress_summary, what_worked |
| `get_readiness_assessment` | `compute` | `medium` | Assess savings capacity and financial cushion against readiness criteria | readiness_check, affordability |
| `get_transactions` | `read` | `cheap` | List transactions for a user across a UTC time window or category | summarize_period, explain_change, investigate_anomaly |
| `get_user_progress` | `read` | `cheap` | Get user gamification progress snapshot (XP, level, streak, badges) | progress_summary |
| `investigate_anomaly` | `compute` | `medium` | Investigate a detected financial anomaly using the hypothesis catalogue | investigate_anomaly, alerts_overview |
| `investigate_month_change` | `compute` | `medium` | Investigate period-over-period spend changes via deterministic decomposition | explain_change |
| `list_adjustments` | `read` | `cheap` | List adaptive adjustment proposals for active or past experiments | experiment_status |
| `list_alerts` | `read` | `cheap` | List active or historical adaptive alerts for the user | alerts_overview, summarize_period |
| `list_buckets` | `read` | `cheap` | List virtual spending, goal, and flexible buckets | bucket_check, summarize_period |
| `list_commitments` | `read` | `cheap` | List commitments and recurrence schedules for a user | commitment_check, summarize_period |
| `list_experiments` | `read` | `cheap` | List financial experiments for user with optional status filter | experiment_status, what_worked, start_experiment |
| `list_goals` | `read` | `cheap` | List the user's active or paused financial goals | goal_check, summarize_period |
| `list_memories` | `read` | `cheap` | List observed and confirmed behavioural memories and patterns | memory_query |
| `list_offers` | `read` | `cheap` | List personalized challenge offers for user | challenge_suggestions, start_experiment |
| `monthly_close` | `compute` | `medium` | Run monthly close skill: rollover buckets, refresh memory confidence, scan alerts, and draft review | monthly_close |
| `plan_contributions` | `compute` | `medium` | Compute monthly waterfall contribution plan and generate options | contribution_plan, affordability |
| `refresh_memories` | `compute` | `medium` | Run observers to refresh behavioural memory candidates and confidence | monthly_close, memory_query |
| `review_experiment` | `compute` | `medium` | Run completed experiment review skill: outcome and baseline comparison | experiment_status, what_worked |
| `rollover_buckets` | `compute` | `medium` | Rollover unspent balances for reset_monthly buckets to unallocated | monthly_close |
| `run_skill` | `compute` | `medium` | Execute a certified skill procedure by name | affordability, trip_planning, contribution_check |
| `run_whatif` | `compute` | `medium` | Simulate financial outcomes of spending or contribution scenarios | whatif_add_spend, whatif_reduce_spend, goal_check |
| `trip_planning` | `compute` | `medium` | Run trip planning skill: goal progress, bucket allocation, calendar buffer, and trade-offs | trip_planning |
| `weekly_checkin` | `compute` | `medium` | Run weekly experiment checkin skill: progress and pace | experiment_status |

## 2. Protected State Mutation & Governance Tools (Approval Required / User Only)

These tools write to financial/user state, or require explicit human decisions.
They are **permanently barred** from autonomous selection by the planner.

| Tool Name | Class | Cost | Description | Reason Barred from Planner |
|---|---|---|---|---|
| `abandon_experiment` | `write_logical` | `cheap` | Abandon an experiment at any time without penalty | State mutation requires user authorization or fixed pipeline node |
| `accept_adjustment` | `write_logical` | `cheap` | User accepts an adaptive adjustment proposal | State mutation requires user authorization or fixed pipeline node |
| `accept_commitment` | `write_logical` | `cheap` | Accept a suggested draft commitment | State mutation requires user authorization or fixed pipeline node |
| `accept_offer` | `write_logical` | `cheap` | Accept a challenge offer to start an experiment | State mutation requires user authorization or fixed pipeline node |
| `allocate_to_bucket` | `write_logical` | `cheap` | Allocate funds to a virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `answer_checkin` | `write_logical` | `cheap` | Answer a scheduled weekly check-in | State mutation requires user authorization or fixed pipeline node |
| `apply_reallocation` | `write_logical` | `cheap` | Apply an approved reallocation draft | State mutation requires user authorization or fixed pipeline node |
| `apply_reallocation_draft` | `write_logical` | `cheap` | Apply an approved reallocation draft | State mutation requires user authorization or fixed pipeline node |
| `approve_consent` | `write_logical` | `cheap` | Record the user's consent | State mutation requires user authorization or fixed pipeline node |
| `archive_bucket` | `write_logical` | `cheap` | Archive a virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `award_xp_and_badges` | `write_logical` | `medium` | Runtime maintenance job: evaluate and award pending XP and badges | State mutation requires user authorization or fixed pipeline node |
| `build_monthly_review` | `write_logical` | `cheap` | Build the monthly review | State mutation requires user authorization or fixed pipeline node |
| `categorize_batch` | `write_logical` | `expensive` | Batch update of transactions by automated rule pipeline | State mutation requires user authorization or fixed pipeline node |
| `confirm_memory` | `write_logical` | `cheap` | User tool to confirm a memory candidate into active status | State mutation requires user authorization or fixed pipeline node |
| `confirm_review_integrity` | `write_logical` | `cheap` | User confirms that recategorised payments in an experiment window were genuine | State mutation requires user authorization or fixed pipeline node |
| `create_bucket` | `write_logical` | `cheap` | Create a new virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `create_checkins` | `write_logical` | `medium` | Runtime maintenance job: generate due weekly check-ins | State mutation requires user authorization or fixed pipeline node |
| `create_commitment` | `write_logical` | `cheap` | Create a new financial commitment | State mutation requires user authorization or fixed pipeline node |
| `create_due_reviews` | `write_logical` | `medium` | Runtime maintenance job: generate due reviews | State mutation requires user authorization or fixed pipeline node |
| `create_goal` | `write_logical` | `cheap` | Create a new financial savings or purchase goal | State mutation requires user authorization or fixed pipeline node |
| `create_reallocation_draft` | `write_logical` | `cheap` | Create a reallocation draft between buckets | State mutation requires user authorization or fixed pipeline node |
| `decide_advice` | `write_logical` | `cheap` | User approve or reject decision on draft advice | State mutation requires user authorization or fixed pipeline node |
| `decide_alert` | `write_logical` | `cheap` | User tool to acknowledge, dismiss, or snooze an alert | State mutation requires user authorization or fixed pipeline node |
| `decide_reallocation` | `write_logical` | `cheap` | Decide on a reallocation draft | State mutation requires user authorization or fixed pipeline node |
| `decide_reallocation_draft` | `write_logical` | `cheap` | Decide on a reallocation draft | State mutation requires user authorization or fixed pipeline node |
| `design_experiment` | `write_logical` | `medium` | Design a new financial experiment with baseline sizing | State mutation requires user authorization or fixed pipeline node |
| `detect_recurring` | `write_logical` | `medium` | Detect recurring subscription and bill payment series | State mutation requires user authorization or fixed pipeline node |
| `detect_transfers` | `write_logical` | `medium` | Identify own-account transfers and exclude them from spend | State mutation requires user authorization or fixed pipeline node |
| `dismiss_anomaly` | `write_logical` | `cheap` | User tool to dismiss a detected anomaly as expected | State mutation requires user authorization or fixed pipeline node |
| `dismiss_offer` | `write_logical` | `cheap` | Dismiss a challenge offer | State mutation requires user authorization or fixed pipeline node |
| `draft_advice` | `write_logical` | `medium` | Generate draft financial advice for user review | State mutation requires user authorization or fixed pipeline node |
| `draft_reallocation` | `write_logical` | `cheap` | Draft a reallocation between buckets | State mutation requires user authorization or fixed pipeline node |
| `edit_memory_statement` | `write_logical` | `cheap` | User tool to edit bounded fields of a memory statement | State mutation requires user authorization or fixed pipeline node |
| `end_commitment` | `write_logical` | `cheap` | End an active commitment | State mutation requires user authorization or fixed pipeline node |
| `evaluate_alerts` | `write_logical` | `medium` | Evaluate spend and budget signals and generate adaptive alerts | State mutation requires user authorization or fixed pipeline node |
| `expire_offers` | `write_logical` | `cheap` | Runtime maintenance job: expire stale shown offers | State mutation requires user authorization or fixed pipeline node |
| `expire_stale_proposals` | `write_logical` | `cheap` | Runtime maintenance job: expire stale adjustment proposals | State mutation requires user authorization or fixed pipeline node |
| `forget_memory` | `write_logical` | `cheap` | User tool to clear content and forget a memory item | State mutation requires user authorization or fixed pipeline node |
| `ingest_statements` | `write_logical` | `expensive` | Fetch and ingest statements under valid AA consent | State mutation requires user authorization or fixed pipeline node |
| `map_category_to_bucket` | `write_logical` | `cheap` | Map a category to a virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `pause_commitment` | `write_logical` | `cheap` | Pause an active commitment | State mutation requires user authorization or fixed pipeline node |
| `pause_experiment` | `write_logical` | `cheap` | Pause an active financial experiment | State mutation requires user authorization or fixed pipeline node |
| `reassign_between_buckets` | `write_logical` | `cheap` | Reassign funds between two virtual buckets | State mutation requires user authorization or fixed pipeline node |
| `recategorize_transaction` | `write_logical` | `medium` | User or approved agent change of a transaction's category | State mutation requires user authorization or fixed pipeline node |
| `record_contextual_exception` | `write_logical` | `cheap` | Record a contextual exception for a category and period | State mutation requires user authorization or fixed pipeline node |
| `record_goal_contribution` | `write_logical` | `cheap` | Record a manual contribution or withdrawal against a savings goal | State mutation requires user authorization or fixed pipeline node |
| `reject_adjustment` | `write_logical` | `cheap` | User rejects an adaptive adjustment proposal | State mutation requires user authorization or fixed pipeline node |
| `reject_commitment` | `write_logical` | `cheap` | Reject a suggested commitment | State mutation requires user authorization or fixed pipeline node |
| `reject_memory` | `write_logical` | `cheap` | User tool to reject a memory candidate or item | State mutation requires user authorization or fixed pipeline node |
| `release_from_bucket` | `write_logical` | `cheap` | Release funds from a virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `resume_experiment` | `write_logical` | `cheap` | Resume a paused financial experiment | State mutation requires user authorization or fixed pipeline node |
| `revoke_consent` | `write_logical` | `cheap` | Withdraw the user's consent | State mutation requires user authorization or fixed pipeline node |
| `run_adaptive_detectors` | `write_logical` | `medium` | Runtime maintenance job: run adaptive challenge detectors over active experiments | State mutation requires user authorization or fixed pipeline node |
| `set_alert_preference` | `write_logical` | `cheap` | User tool to set alert preferences, silences, or limits | State mutation requires user authorization or fixed pipeline node |
| `start_experiment` | `write_logical` | `cheap` | Start an offered financial experiment | State mutation requires user authorization or fixed pipeline node |
| `submit_review_feedback` | `write_logical` | `cheap` | Submit user feedback for an experiment review | State mutation requires user authorization or fixed pipeline node |
| `suggest_challenges` | `read` | `medium` | Generate candidate challenge offers without saving | State mutation requires user authorization or fixed pipeline node |
| `suggest_commitments` | `write_logical` | `medium` | Suggest draft commitments from recurring payment series | State mutation requires user authorization or fixed pipeline node |
| `undo` | `write_logical` | `medium` | Revert a single audited state mutation | State mutation requires user authorization or fixed pipeline node |
| `undo_categorize_batch` | `write_logical` | `expensive` | Revert a batch categorization run | State mutation requires user authorization or fixed pipeline node |
| `update_bucket` | `write_logical` | `cheap` | Update properties of an existing virtual bucket | State mutation requires user authorization or fixed pipeline node |
| `update_commitment` | `write_logical` | `cheap` | Update a financial commitment | State mutation requires user authorization or fixed pipeline node |
| `update_goal` | `write_logical` | `cheap` | Update an existing financial goal's target, progress, or deadline | State mutation requires user authorization or fixed pipeline node |
| `weekly_offers` | `write_logical` | `medium` | Runtime maintenance job: generate weekly challenge offers | State mutation requires user authorization or fixed pipeline node |

## 3. Permanently Prohibited Tool Classes

The following operations have no tool contracts and are permanently denied by policy:

- **Money Movement:** Initiating payments, bank transfers, UPI transactions, charges.
- **Trading / Execution:** Executing stock, mutual fund, crypto, or commodity orders.
- **Credential Ingestion:** Requesting or caching OTPs, PINs, passwords, or card numbers.
- **External Mutations:** Modifying third-party bank records or external APIs.

---
*Generated from `config/planner_capabilities.yaml`.*
