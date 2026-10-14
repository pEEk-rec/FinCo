# Phase 2 Alignment with Phase 1

This document maps the concepts, models, tools, and configurations specified in `PLAN_PHASE2.md` to the active Phase 1 codebase. Where a name or signature exists from Phase 0 or Phase 1, the existing code contract wins.

## 1. Baseline State (Stage 2.0 Entry)

- **Test Suite Baseline Output:**
  ```
  403 passed in 11.10s
  ```
- **Linter Baseline Output:**
  ```
  All checks passed!
  ```

## 2. Infrastructure Gaps Identified and Fixed in Stage 2.0

### A. Failure-Path Audit Survival
- **Gap:** In Phase 1, when a tool handler raised `ToolFailure`, the handler's savepoint rolled back all internal mutations—including any custom failure audit rows (e.g. `undo_refused`) recorded by the handler. The executor then wrote a generic `event_type="tool_call"` event.
- **Resolution:** Enhanced `ToolFailure` (`src/copilot/core/errors.py`) with optional `audit_event_type: str | None` and `audit_metadata: dict | None`. In `src/copilot/tools/executor.py`, `_fail` executes in its own clean savepoint and records the custom `event_type` (e.g. `undo_refused`, `plan_rejected`, `input_refused`) and merged metadata.
- **Verification:** Unit tests in `tests/tools/test_executor.py` (`test_failure_path_custom_audit_event_and_metadata`) and `tests/tools/test_undo.py` (`test_undo_execute_tool_diverged`) verify that refusal audit events survive on the real `execute_tool` path.

### B. UI Tool Caller Parameter Alignment
- **Gap:** In `src/copilot/ui/app.py`, the Undo button called `execute_tool(ctx, "undo", {"event_id": eid})`, whereas `UndoInput` in `src/copilot/tools/undo.py` strictly declares `audit_event_id: str`.
- **Resolution:** Fixed `src/copilot/ui/app.py` to pass `{"audit_event_id": eid}`. Added `test_undo_called_as_in_ui` in `tests/tools/test_undo.py` asserting that the UI invocation succeeds cleanly through `execute_tool`.

## 3. Name and Contract Mapping

| Plan Name | Actual Code / Target Module | Status / Notes |
|---|---|---|
| `execute_tool` | `copilot.tools.executor.execute_tool` | Unchanged choke point. All Phase 2 tools must invoke handlers solely via `execute_tool`. |
| `ToolFailure` | `copilot.core.errors.ToolFailure` | Extended in Stage 2.0 with `audit_event_type` and `audit_metadata`. |
| `list_specs` | `copilot.tools.registry.list_specs` | Canonical registry query function (not `list_tools`). |
| `undo` tool | `copilot.tools.undo.undo_handler` | Input: `UndoInput(audit_event_id=...)`. |
| `goals` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `agent_tasks` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `plan_steps` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `investigations` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `hypotheses` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `evidence_items` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `simulations` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `alerts` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `alert_preferences` table | `db/migrations/003_phase2_schema.sql` | To be created in Stage 2.1. |
| `advice_items` (extended) | `db/migrations/003_phase2_schema.sql` | To be extended in Stage 2.1 with explanation fields. |
| Capability Matrix | `config/planner_capabilities.yaml` | Created in Stage 2.0 with Pydantic validation. |
| Capability Doc | `docs/capability_matrix.md` | Generated in Stage 2.0 via `scripts/generate_capability_matrix.py`. |
| Intent Patterns | `config/intent_patterns.yaml` | Created in Stage 2.0. |
| Plan Templates | `config/plan_templates.yaml` | Created in Stage 2.0. |
| Investigation Config | `config/investigation.yaml` | Created in Stage 2.0. |
| Goals Config | `config/goals.yaml` | Created in Stage 2.0. |
| What-If Config | `config/whatif.yaml` | Created in Stage 2.0. |
| Alerts Config | `config/alerts.yaml` | Created in Stage 2.0. |
| Explanation Templates | `config/explanation_templates.yaml` | Created in Stage 2.0. |

## 4. Phase 2 Invariants Confirmed

1. **Integer Paise Money:** All amounts in `goals`, `simulations`, `investigations`, and `alerts` use integer paise with `Decimal` intermediate rounding.
2. **User Isolation:** All new tables have `user_id` foreign keys and index queries by `user_id`.
3. **No Money Movement:** No tools exist or will be added that transfer, pay, trade, or withdraw funds.
4. **Planner Boundaries:** Write tools are permanently barred from `planner_selectable: true`.
