# Capture track: alignment with the existing codebase (Stage C0)

**Date:** 2026-10-18
**Plan:** `docs/CAPTURE/PLAN_CAPTURE.md` (web-first). **ADRs:** `docs/adr/ADR-0001-at-payment-capture.md`, `docs/adr/ADR-0002-account-aggregator.md`.
**Baseline before this stage:** 1194 backend tests pass, `ruff` clean; frontend `npm run verify` and 14 browser tests pass.

In one sentence: the capture track is mostly new code, but the repository already holds a working prototype of three of its pieces, so the first decision of this track is how to treat that prototype.

---

## 1. What already exists that the plan touches

| Plan piece | What is already here | Verdict |
|---|---|---|
| SMS parser | `src/copilot/rails/sms.py`: one tolerant regex reader for debit and credit alerts, refuses OTPs, mandates, "will be debited" and failed payments. Returns only structured fields. | **Superseded by C2.** The plan wants a per-bank template spec, a sender allowlist and a golden corpus. The prototype's good ideas (what to refuse, never parse floats) carry over as test cases. |
| Webhook | `src/copilot/live/api.py`: `POST /api/live/webhook/sms` with `X-Webhook-Secret`, constant-time compare, rate limit, size limit. | **Replaced in C5** by `POST /capture/sms`. The prototype has **no sender allowlist** (any text holding the secret is parsed) and writes directly to its own tables instead of going through `execute_tool`. |
| Payment event store | `rail_events` (own table, created at runtime by `rails/engine.py`, not by a migration): fingerprint, amount, merchant, reference, account tail, status `provisional` / verified, `parsed_json`. | **Superseded by C1** (`payment_events` with a real migration, `user_id`, states, links, labels). Raw SMS text is **not** stored by the prototype (only parsed fields), which is the right behaviour to keep. |
| Reconciliation | `rails/engine.reconcile`: matches events to statement rows. | **Reworked in C4** to the UTR-first, never-merge-on-ambiguity rules and the `event_links` audit row. |
| Receipts, splits, pacing | `rails/receipts.py`, `rail_splits`, `rails/engine.pacing`. | **Out of scope for this track.** Left untouched. |
| Connector boundary | `bank/ingest.py::BankConnector` (Protocol: `fetch_session`), `bank/mock_bank.py::MockAAConnector`. | **Extend, do not replace** (C7). |
| AA client | `src/copilot/live/aa.py`: consent, data session, fetch, `parse_fi_data`, configurable endpoints, tested against a local fake gateway; never run against a real gateway. | **Reuse in C7** as the base of `AASandboxConnector`. |
| Statement import | `src/copilot/live/statement.py` (CSV, HDFC-style). | Stays as `StatementImportConnector`, the fallback path. |
| Coverage scan | Runtime job `coverage_scan` (`config/runtime.yaml`, `runtime/runner.py`). | **Reuse** for capture coverage health (C4). |
| Merchant memory | Table `merchant_overrides`, written by `tools/financial.py`, read by `core/pipeline.py` and `core/memory.py`. | **Reuse** for "unknown merchant: ask once, the answer becomes an override" (C1). |
| Transfers and recurring | `core/patterns.detect_transfers`, `recurring_series` (`db/repo_phase3.list_recurring_series`). | **Reuse** for the ask policy ("own transfer" and "AutoPay or recurring" never ask). |
| Learner and memory | `core/learning.record_feedback`, `feedback_stats`, `memory_items`. | **Reuse in C8** for guess-rank feedback and merchant habits. |
| Tracing | `ops/tracing.span`, table `trace_spans`. | **Reuse everywhere** (spans, never with message text). |
| Category precedence | `Transaction.category_source`: `rule`, `llm`, `user`, `none`, `override`, `cache`. | Unchanged. An at-payment answer is a `user` choice. |

## 2. Layers the plan assumes, and whether they exist

| Layer | Present? | Consequence |
|---|---|---|
| HTTP API (FastAPI, bearer token, typed errors, OpenAPI snapshot) | **Yes** (`src/copilot/api/`, 1,600 lines in `app.py`) | Capture and consent endpoints go in here (C3, C5, C6, C7). Regenerate `docs/openapi.json` and `frontend/src/api/schema.d.ts` each time. FastAPI is already a dependency. |
| Frontend (Vite, React, strict TypeScript) | **Yes**, light coral theme with liquid components (Phase 4 UI work) | Inbox, simulator panel, prompt overlay, Today and consent screens follow the existing tokens, the no-hardcoded-figures gate and accessibility checks. |
| Runtime jobs | **Yes** (`runtime/runner.py`, `config/runtime.yaml`) | Reconciliation, coverage and AA fetch become jobs. |
| Spans | **Yes** | Used throughout. |
| Phase 3 memory and learner | **Yes** | Used in C8. |
| Server-sent events | **No** | Added in C6 with no new dependency (FastAPI `StreamingResponse`). |
| Web Push | **No** | `pywebpush` is pre-approved for C6b only. |
| `adb` / phone bridge | Owner's phone | Owner task, not attempted by the agent. |

## 3. Dependencies

Nothing new is needed for C0 to C5. Later: `pywebpush` (C6b, pre-approved) and `cryptography` only if the chosen AA sandbox returns ReBIT-encrypted data its gateway does not decrypt (C7; decision recorded there).

## 4. What C0 added

| Item | Where |
|---|---|
| The two ADRs, copied where the plan expects them | `docs/adr/` |
| Validated loaders and schemas for every capture config | `src/copilot/config/capture.py` |
| Ask policy, prompt budget, ranking weights, credits, webhook limits | `config/capture.yaml` |
| Bank sender allowlist (all banks **disabled** until the owner confirms the real senders) | `config/sms_senders.yaml` |
| Per-bank template files (skeletons with only the OTP guard) | `config/sms_templates/{hdfc,sbi,icici,axis,kotak}.yaml` |
| Reconciliation and coverage thresholds | `config/reconcile.yaml` |
| AA consent defaults (purpose 102, DEPOSIT, TRANSACTIONS, periodic daily, STORE) | `config/aa.yaml` |
| Tests that the shipped files load and that every bad edit fails | `tests/config/test_capture_config.py` |

Two safety properties are already enforced by config validation and tested: **no bank is read until it is enabled** (the allowed-sender map is empty today), and **a bank cannot be enabled while its templates are still a skeleton**.

## 5. Decisions recorded

- The existing `rails` prototype is treated as a prototype, not as the foundation. Its tables are left alone; new work uses migrated tables. See `docs/open_questions.md` (C-1).
- The sender IDs shipped in `sms_senders.yaml` are written from general knowledge and are **not verified**. They stay disabled until the owner copies the real sender from one alert per bank.
- Credit kinds (`salary`, `allowance`, `refund`, `split_repayment`, `gift`, `cashback`, `self_transfer_in`, `other_income`) are capture labels; mapping them to the user's own categories happens in C1.
