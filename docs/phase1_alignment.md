# Phase 1 Alignment with Phase 0

This document maps the names and concepts used in `PLAN_PHASE1.md` to the actual reality of the Phase 0 codebase. Where a Phase 1 name differs from Phase 0, the Phase 0 name wins (or is wrapped/extended).

## Tools and Functions
| Phase 1 Plan Name | Phase 0 Actual Name | Notes |
|---|---|---|
| `execute_tool` | `execute_tool` | Exists in `copilot.tools.executor.execute_tool`. All Phase 1 tools must go through this. |
| `get_transactions` | `get_transactions` | Exists in `copilot.tools.financial.get_transactions_handler`. |
| `recategorize_transaction` | `recategorize_transaction` | Exists in `copilot.tools.financial.recategorize_transaction_handler`. Actor must be `user` or have approval. |
| `check_budgets` | `check_budgets` | Exists in `copilot.tools.financial.check_budgets_handler`. |
| `forecast_month` | `forecast_category_spend` | Phase 0 uses `forecast_category_spend`. Phase 1 will replace or wrap this to add v2 features (ranges, recurring) while likely keeping the registered name `forecast_category_spend` for backward compatibility or registering a new tool `forecast_month`. |
| `detect_anomalies` | N/A | To be built in Phase 1. |
| `detect_transfers` | N/A | To be built in Phase 1. |
| `detect_recurring` | N/A | To be built in Phase 1. |
| `BankConnector` interface | `MockBankConnector` | Phase 0 has `copilot.bank.mock_bank.MockBankConnector`. We will formalize the interface and rename/wrap to fit Account-Aggregator shape in Phase 1 (`MockAAConnector`). |
| `categorize_batch` | N/A | To be built in Phase 1. |
| `undo_categorize_batch` | N/A | To be built in Phase 1. |

## Data Models and Tables
| Phase 1 Plan Name | Phase 0 Actual Name | Notes |
|---|---|---|
| `RunState` | `RunState` | Exists in `copilot.models.run_state.RunState`. |
| `schema_migrations` | N/A | To be added in Stage 1.0. Phase 0 schema (`schema.sql`) will become migration `001_initial.sql`. |

## Config
| Phase 1 Plan Name | Phase 0 Actual Name | Notes |
|---|---|---|
| `config/settings.yaml` | `config/settings.yaml` | Exists, managed by `copilot.core.config`. Will be extended. |
| `config/policy.yaml` | `config/policy.yaml` | Exists, managed by `copilot.governance.policy`. Will be extended for actor-aware policies. |
| `config/categorization_rules.yaml` | N/A | To be added. |

All new tools in Phase 1 must enforce the `user_id` boundary, use integer paise for money, and comply with the governance defaults. No money-movement tools will be added.
