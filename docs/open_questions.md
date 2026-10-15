# Open Decisions & Architecture Questions

## 1. Distinct `undo_refused` Event Type Under Executor Choke Point
- **Context:** When `undo` is called directly, the handler writes `event_type="undo_refused"` before raising `ToolFailure(ErrorCode.STALE_DATA)`. When routed through `execute_tool` (the production path for agents and CLI), the executor's `with savepoint(conn):` rolls back all changes from the failed handler, and `execute_tool._fail` records a failure audit row with `event_type="tool_call"`, `metadata.error_code="STALE_DATA"`, and `reason="Undo refused: ..."`.
- **Question:** Should `undo_refused` exist as a distinct `event_type` in `audit_events` on the `execute_tool` path?
- **Options:**
  1. *Keep current behavior (Default):* Accept executor's standard `tool_call` failure audit row with `STALE_DATA`. This adheres strictly to the Phase 0 contract that failed tool handlers roll back all internal mutations and let the executor record the single failure event.
  2. *Write outside savepoint:* Pass a dedicated unmanaged connection or write after rollback. This breaks the single-savepoint unit-of-work principle.
  3. *Enhance executor auditing:* Allow `ToolFailure` to optionally carry an `event_type` override for `_fail`. This modifies the Phase 0 `executor.py` contract.
- **Decision:** Option 1 chosen for Phase 1. The refusal is guaranteed to be audited with `error_code="STALE_DATA"`. Any change to `execute_tool` failure event naming is deferred.

## 2. Property Testing Framework
- **Context:** `PLAN_PHASE2.md` mentions property tests `(Hypothesis)` in Stage 2.3. However, `hypothesis` is not in `pyproject.toml` and Rule 0.1 establishes a hard gate: zero new dependencies allowed in Phase 2.
- **Decision:** Built deterministic property-based test suites using Python's standard library `random` across pseudo-random iterations with fixed seeds. This rigorously validates all simulation invariants (pure functions, zero-delta identity, monotonicity, conservation of paise) without violating the zero-new-dependency rule.


# Phase 4 decisions that were not in the plan

## P4-1. Is travel an essential category?
- **Decided:** Yes, travel and commute is protected (no challenge targets it). **Alternative:** treat only fuel and public transport as essential. **Why:** the persona's cab rides are mixed with commuting and the safe error is to leave them alone; a user can still design their own experiment on it.

## P4-2. Quiet weeks after dismissals
- **Decided:** After three dismissals in a row (`offers.yaml: dismissed_in_a_row: 3`) no offers for two weeks (`quiet_weeks: 2`). **Alternative:** keep offering with a lower propensity. **Why:** three "not now" answers are an answer; silence respects it and costs nothing.

## P4-3. Number of earlier periods (K)
- **Decided:** K=6 with a minimum of 3, lookback 26 weeks. **Alternative:** K=12. **Why:** six comparable periods is what four to six months of history gives; K=12 is reported as a sensitivity check and lowers the chance rate (1/13 against 1/7) but needs about a year of data.

## P4-4. Model reads first
- **Decided:** `llm_primary: true`: the configured model reads each question first and the rules validate and fall back (set `FINCO_LLM_PRIMARY=0` to flip). **Alternative:** rules first. **Why:** PLAN_PHASE4 section 0.8; paraphrases are where the rules fail. The same redacted question reuses a cached answer for an hour.

## P4-5. Offer arms are template codes
- **Decided:** The offer policy learns per template code. **Alternative:** per template and difficulty. **Why:** too few observations per user to learn finer arms in six months.

## P4-6. Some XP rules are defined but not yet awarded
- **Decided:** Rules for things the product has no event for yet stay in config and are not awarded. **Alternative:** invent events. **Why:** XP must follow something real the user did.

## P4-7. Dated exceptions
- **Decided:** A user declares a trip with a first and last day, per category. **Alternative:** month-level only. **Why:** a month-level exception would discount weeks the user was at home and hide real results.
