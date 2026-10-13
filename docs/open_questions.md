# Open Decisions & Architecture Questions

## 1. Distinct `undo_refused` Event Type Under Executor Choke Point
- **Context:** When `undo` is called directly, the handler writes `event_type="undo_refused"` before raising `ToolFailure(ErrorCode.STALE_DATA)`. When routed through `execute_tool` (the production path for agents and CLI), the executor's `with savepoint(conn):` rolls back all changes from the failed handler, and `execute_tool._fail` records a failure audit row with `event_type="tool_call"`, `metadata.error_code="STALE_DATA"`, and `reason="Undo refused: ..."`.
- **Question:** Should `undo_refused` exist as a distinct `event_type` in `audit_events` on the `execute_tool` path?
- **Options:**
  1. *Keep current behavior (Default):* Accept executor's standard `tool_call` failure audit row with `STALE_DATA`. This adheres strictly to the Phase 0 contract that failed tool handlers roll back all internal mutations and let the executor record the single failure event.
  2. *Write outside savepoint:* Pass a dedicated unmanaged connection or write after rollback. This breaks the single-savepoint unit-of-work principle.
  3. *Enhance executor auditing:* Allow `ToolFailure` to optionally carry an `event_type` override for `_fail`. This modifies the Phase 0 `executor.py` contract.
- **Decision:** Option 1 chosen for Phase 1. The refusal is guaranteed to be audited with `error_code="STALE_DATA"`. Any change to `execute_tool` failure event naming is deferred.
