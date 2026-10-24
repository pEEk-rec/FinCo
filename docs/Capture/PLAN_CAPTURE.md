# PLAN_CAPTURE.md: Capture & Ledger track (at-payment categorisation + Account Aggregator), web-first

Project: FinCo (Personal Finance & Budgeting Copilot)
Implements: `docs/adr/ADR-0001-at-payment-capture.md` and `docs/adr/ADR-0002-account-aggregator.md`. Read both ADRs first; this file turns them into stages.
Owner and only contributor: the user (repo owner). Implementer: Claude Code.

**Web-first decision (amends ADR-0001, 2026-10-18):** no native Android app. A web page cannot read SMS or draw over other apps, so the trigger comes from a **no-code SMS forwarder** the owner configures on the phone (MacroDroid or Tasker on Android, a Shortcuts message automation on iPhone), which POSTs only bank SMS to FinCo's local webhook. FinCo parses it on the server, decides whether to ask, and prompts in the **web app**: an in-app overlay on any open FinCo page (real time) and, optionally, a **PWA push notification** with action buttons on the phone. A native companion stays a later option (ADR-0001 Option A).

Read, in order: this file, both ADRs, `STATUS.md`, `docs/decisions.md`, `docs/open_questions.md`, `docs/known_issues.md`, the latest phase alignment doc, `docs/architecture_agentic.md` (if present) and the current code. Build on what exists.

---

## 0. Rules

### 0.1 Work mode
Autonomous, stage by stage (section 4). Each stage: goal and files at the top of its `STATUS.md` entry; small steps; full suite and lint green before moving on; explain-back in `docs/decisions.md`.

**Hard gates (stop only for these):**
1. Any git command (record proposals only, 0.3).
2. A dependency not pre-approved in section 2.
3. Money, sign-ups, deployment, files outside the repo. **Sandbox sign-ups and Android device setup are owner tasks (section 1)**; never attempt them.
4. Breaking an earlier contract (executor choke point, append-only audit, integer paise, `user_id` everywhere, no money movement, user > override > rule > cache > LLM precedence, validators, capability allowlist, LLM router rules from PLAN_PHASE3/4 §0.8).
5. A failing test you cannot fix honestly. Never weaken or skip tests.

**Soft gates:** conservative default, record in `docs/open_questions.md`, continue. Missing owner prerequisite (no sandbox access yet, no phone connected): build and test everything against mocks and the simulator, mark the live check pending, continue.

### 0.2 Code and honesty rules
All rules from PLAN_PHASE3/4 §0.6 and §0.8 apply (LLM-first through the existing router for understanding and wording; deterministic code for numbers, matching, policy and validation; fake provider in tests; live calls capped; record and replay). Additionally:
- **Raw SMS text goes only from the owner's phone to the owner's own local FinCo webhook**, is parsed in memory, then discarded: never stored, never logged, never in spans, never sent to any LLM. Only parsed structured fields are kept.
- **Only allowlisted bank sender IDs are parsed.** Every other SMS is dropped in memory; OTP-looking messages are dropped even from bank senders.
- **Test fixtures use redacted SMS only** (amounts, UTRs, account digits, names replaced). No real personal data in the repo.
- Frontend code follows PLAN_UI rules (tokens, no hardcoded figures, accessibility, reduced motion).

### 0.3 Git
No git commands. Two proposed commits in `STATUS.md`: A after Stage C4 `Add payment capture backend and reconciliation`; B after Stage C9 `Add web payment prompts and AA sandbox connector`. No AI attribution anywhere.

### 0.4 Adaptation rules
| If you find... | Do this |
|---|---|
| HTTP API layer (PLAN_UI) | Add capture and consent endpoints there; regenerate OpenAPI and TS types |
| No API layer | Add a minimal FastAPI router only for capture endpoints if FastAPI is already a dependency; otherwise record the gap and build CLI + services |
| Frontend exists (Phase 4 / UI track) | Add the web capture inbox, simulator panel and consent screen to it, following PLAN_UI design rules |
| Phase 3 memory, learner, runtime, spans | Reuse: merchant habits → memory; guess-ranking feedback → learner; reconciliation and coverage scans → runtime jobs; spans everywhere |
| `merchant_overrides`, `recurring_series`, transfer detection | Reuse for the ask policy (do not duplicate) |
| `BankConnector` + `MockAAConnector` | Extend; do not replace |

---

## 1. Owner prerequisites (manual; the agent never does these)
Do these in parallel while the agent builds C0 to C4. Record outcomes in `docs/open_questions.md` as you go.
1. **Phone bridge (no coding):** on the phone that receives your bank SMS, install an automation app (MacroDroid or Tasker on Android; Shortcuts on iPhone). Create one rule: *trigger* = SMS received from your bank sender IDs only; *action* = HTTP POST to the FinCo webhook URL with the message text, sender and time, and the secret header Claude Code gives you in Stage C5. Never forward from all senders.
   - Connection for the demo: USB cable plus `adb reverse tcp:<port> tcp:<port>` (Android platform-tools only, not Android Studio), so the phone reaches `http://localhost:<port>` and the backend stays private. Alternative: same Wi-Fi with the LAN flag from C5 (token required).
2. **SMS corpus:** export 30 to 60 of your own bank messages (debits, credits, UPI, card, ATM, reversals, AutoPay, UPI Lite daily summary if you use it) from each bank you use. Run the agent's local redaction script (Stage C2) on them **before** they enter the repo. Never paste raw SMS into any chat or LLM.
3. **AA sandbox access**, try in this order and note which works:
   - Sahamati developer simulators (developer.sahamati.org.in): AA simulator and FIP simulator.
   - Finvu or OneMoney sandboxes (sign-up pages linked from Sahamati's hackathon FAQ).
   - Setu Bridge sandbox (asks for company PAN and GSTIN; likely not available to you).
   Put credentials only in `.env` (never committed). If none works, the track still completes with the upgraded mock (C7).

---

## 2. Stack and pre-approved dependencies
- **Backend:** no new Python dependency, except `cryptography` **only if** the chosen AA sandbox returns ReBIT-encrypted data (ECDH key exchange + symmetric decryption) that its gateway does not decrypt for you. Check the sandbox docs first; record the decision.
- **No native app.** Real-time in-app prompts use server-sent events (no new dependency).
- **Notifications on laptop and phone** (Stage C6b, required): `pywebpush` on the backend (pre-approved) and the browser's built-in Push API in a service worker. Push needs a secure context: `http://localhost` qualifies, so the phone's Chrome must reach the app via `adb reverse` (or an HTTPS origin, which would be deployment and is out of scope). Push action buttons are limited by the browser (check `Notification.maxActions`; Chrome on Android typically shows 2), so the third choice and "Other" live on the tap-through quick sheet.
- **Connectivity for the demo:** `adb reverse` over USB keeps everything on localhost. A `--lan` flag may bind the webhook to the LAN for the Wi-Fi option, only with the secret token, and prints a warning.

---

## 3. Architecture (web-first)
```
Phone                                         Laptop (FinCo backend + web app)
 bank SMS ─► MacroDroid/Tasker/Shortcuts ── POST /capture/sms (secret header) ──► sender allowlist → parser (in memory, text discarded)
            (bank senders only)                                                   │
                                                                                  ▼
                                                                payment_events → ask policy + top-3 guesses
                                                                                  │ (ask only if ambiguous)
                       ┌──────────────── SSE ─────────────────────────────────────┤
                       ▼                                                          ▼ (optional C6b)
  any open FinCo page: overlay card "₹250 to Ramesh K: what was this?"     Web Push → phone notification
  [Guess 1] [Guess 2] [Guess 3] [Other…]  Undo                              [Guess 1] [Guess 2], tap → quick sheet
                       └──────────── POST /capture/labels ───────────────────────┘
 AA sandbox / mock ── consent → periodic fetch ──► transactions ── reconcile (UTR → amount+last4+time) → label = category_source user
```
If nothing is open and push is off, prompts wait in the **capture inbox**, with the same TTL-to-guess fallback as ADR-0001 D6.

---

## 4. Stages

### Stage C0: Align
**Build:** copy both ADRs into `docs/adr/`; `docs/capture_alignment.md` (0.4 table, current phase status, API/frontend presence); config skeletons with validation: `capture.yaml` (ask policy thresholds, prompt budget, quiet hours, TTL, min ask amount, P2P k-of-n), `sms_senders.yaml` (bank sender allowlist), `sms_templates/` (per bank), `reconcile.yaml`, `aa.yaml` (purpose 102, fiTypes, fetch type and frequency, data life, consent duration).
**Done when:** baseline green; alignment doc complete.

### Stage C1: Capture domain (backend)
**Build:** migrations and models for `payment_events` (source sms/notification/manual/simulator; amount paise; direction; account last 4; UTR/RRN; counterparty key, kind merchant/person/self/cash/unknown, display name; bank; channel; occurred_at; state detected/posted/reversed/reconciled/orphaned), `capture_labels`, `counterparty_profiles`, `prompt_log`, `event_links`. Tools: `record_payment_event` (agent/device actor, idempotent on UTR or a fingerprint), `label_payment_event` (user actor, audited, undoable), `pending_prompts`, `set_counterparty_policy` (user).
**Ask policy** (pure, ADR-0001 D3): own transfer, known merchant above threshold, recurring/AutoPay → no ask; unknown merchant → ask once, answer becomes a merchant override; person → per-person k-of-n rule with "always ask" and "always <category>" options; cash → optional; below min amount → guess only. Prompt budget, quiet hours, TTL to inbox, then best guess as a guess with `needs_review`.
**Incoming money is covered too.** Credits go through the same pipeline with credit categories (for example salary or allowance, refund, split repayment from a friend, gift, cashback, self transfer in, other income): refunds matched to an earlier debit and own-account transfers are auto-labelled; salary/allowance from a known recurring inflow is auto-labelled; a credit from a person or an unknown source is asked (a friend repaying a split can also be linked to the original debit from the quick sheet, so net spend is correct).
**Guess ranking** (pure, ADR-0001 D4): counterparty history with recency decay, time-of-day/weekday pattern, amount band, day of month, merchant hints, last used. For unknown *merchant-like* names only, an LLM suggestion through the router (normalised name only, never SMS text, never for persons) may enter the candidate set; ranking stays deterministic.
**Tests:** every policy branch at its boundary; P2P never remembered like a merchant; budget and quiet hours; TTL fallback; ranking determinism and tie-breaks; LLM never called for persons (fake provider call log); labels become `category_source = user` on reconciliation (tested in C4); through-executor tests with audit.

### Stage C2: SMS parsing (shared spec, two implementations)
**Build:**
- A local **redaction script** (`scripts/redact_sms.py`) the owner runs on their exported SMS: replaces amounts, UTRs, account digits and names with typed placeholders while keeping structure; outputs JSON fixtures plus expected parse results to fill in.
- **Template spec** in `sms_templates/<bank>.yaml`: sender IDs, regex patterns with named groups (amount, direction, account last 4, UTR/RRN, counterparty VPA or name, balance, channel), message kinds (debit, credit, reversal, autopay, upi_lite_summary, otp → drop).
- **Python parser** (server side), driven by the template files. A **golden corpus** (`tests/sms_corpus/*.json`: redacted input → expected structured output) runs in CI.
- **Template drift detector:** parse-failure rate per sender over a rolling window, exposed in `ops`.
**Tests:** every fixture parses to its expected output; OTP and non-bank messages always dropped; unknown format → `unparsed` (counted, never guessed); amounts never parsed as floats; property test: parser never returns data for a sender outside the allowlist.

### Stage C3: Simulator and web capture inbox
**Build:** `copilot capture simulate --bank X --kind debit --amount 250 --to "ramesh@ybl"` and a simulator panel in the web UI (clearly labelled "Simulated payment") that render a realistic SMS from the templates, run it through the Python parser and post the event; a **web capture inbox** with the same three-guess interaction, the quick sheet (all categories, split, note, per-person policy) and Undo.
**Tests:** simulated event → ask decision → label → audit; inbox keyboard flow; nothing in the UI shows simulated events as real (label always present).

### Stage C4: Reconciliation and coverage health
**Build:** matcher (UTR/RRN first; then amount + account last 4 + time window; never merge on ambiguity); label carries to the transaction as `category_source = user` with an `event_links` row; reversal handling; provisional ledger for accounts without AA (marked unverified everywhere, never double counted); coverage health per account (events vs ledger, "bank SMS may be going to another phone"); runtime job for periodic reconciliation.
**Tests:** exact UTR match; ambiguous duplicates left unmerged; reversal cancels or refunds; no double counting in any spend view (property test); label precedence (agent cannot overwrite); coverage message thresholds.
**[GIT CHECKPOINT A]** record `Add payment capture backend and reconciliation`. Do not run git.

### Stage C5: SMS webhook and phone bridge
**Build:** `POST /capture/sms` (secret token in a header, constant-time comparison, rate limit, body size limit, sender allowlist check before parsing, OTP drop, idempotency on UTR or fingerprint so a re-forwarded SMS creates no duplicate); request bodies never logged; the parsed event goes into C1's pipeline. `copilot capture bridge-setup` prints, for each bank sender in config, the exact rule to create in MacroDroid, Tasker or iPhone Shortcuts (trigger, sender filter, URL, header, body fields) and the `adb reverse` command; `--lan` option with a warning. A **bridge health** indicator in the web app (last SMS received per bank, parse failures).
**Tests:** auth failures rejected and audited without body content; non-allowlisted sender rejected before parsing; OTP dropped; duplicate forward ignored; body never appears in logs or spans (scan test); end-to-end with the test client from webhook to pending prompt.
**Live check (owner):** configure the rule, pay ₹1, see the event arrive within seconds. Record the latency.

### Stage C6: Web prompts (in-app overlay)
**Build:** an SSE stream `/capture/stream` (token-authenticated) that emits a prompt only when the ask policy says ask; a **prompt overlay** component mounted at the app shell, so it appears on any open FinCo page: amount, counterparty, bank and time, three guess buttons, "Other…" opening the quick sheet (all categories with search, split, note, "always ask / always <category> for this person", "not mine"), keyboard shortcuts 1, 2, 3, Esc for later; stacked prompts collapse into "3 payments to tag"; after a choice, the correction cascade and an Undo toast (PLAN_UI motion rules); silent "Tagged Food · Change" chips for auto-labelled payments if the user enables them; the capture inbox page for everything not answered.
Design follows PLAN_UI (tokens, copy rules, no pressure language, reduced motion, accessibility). Prompts never block navigation and never reappear after "later" until the inbox.
**Tests:** component tests for every state; SSE reconnect; only ambiguous payments produce prompts (seeded mix: known merchant, AutoPay, own transfer → no overlay; unknown merchant and person → overlay); keyboard flow; axe check; e2e with the simulator.

### Stage C6b: Notifications on laptop and phone (required for the demo)
**Build:** web app manifest and service worker so the same frontend installs as an app on the phone's home screen and on the laptop; opt-in "Notify me on this device" per device; VAPID keys generated locally into `.env`; push subscriptions stored per device; when a prompt is created, send a Web Push to every subscribed device (laptop Chrome shows a system notification at the screen corner; phone Chrome shows a heads-up notification) with up to `Notification.maxActions` guess actions; an action posts the label from the service worker and the other devices' notifications for that payment are closed; body tap opens the app straight into that payment's quick sheet; lock-screen safe text ("1 payment to tag") where the platform allows. If a FinCo page is focused, show the in-app overlay instead of a system notification on that device.
**Tests:** subscription lifecycle per device; payload limited to amount, direction, short counterparty name and guesses; action posts the right label once even if two devices act; dedupe across devices; graceful no-op where push is unsupported.
**Live check (owner):** laptop and phone both subscribed (phone via `adb reverse`), pay ₹10, notification appears on both, tap a category on one, the other clears.

### Stage C6c: "Today" review (mobile and desktop, same frontend)
**Build:** a **Today** screen (also reachable for any past day) listing every incoming and outgoing transaction for the day in time order, grouped as **Needs you** (asked and not answered), **Auto-tagged** (with the reason chip: known merchant, AutoPay, own transfer, refund link, recurring inflow; each one tap to change) and **Tagged by you**; day totals in and out computed by the backend; one-tap guesses inline; swipe or keyboard to tag; a "Review today" entry point on the dashboard and as the notification-tap fallback when several payments are pending; the evening digest (optional runtime job) links here. Mobile-first layout at 390 px and the full desktop layout from PLAN_UI, one codebase; PWA install on the phone so "open the app later" is a home-screen tap.
**Tests:** credits and debits both listed with correct signs and grouping; ignored notification leads to the item under **Needs you**; tagging from Today updates the dashboard and closes any outstanding notification; empty day state; screenshots at 390 px and 1440 px reviewed per PLAN_UI.

### Stage C7: AA connector (sandbox or upgraded mock)
**Build:** upgrade `MockAAConnector` to ReBIT Deposit-schema-shaped output; `AASandboxConnector` for whichever sandbox the owner obtained (consent create with purpose 102, `DEPOSIT`, `TRANSACTIONS`, `PERIODIC` daily, `STORE`, data life from config; status by webhook or polling; data session; fetch; decrypt only if required, per section 2); consent screen in the web UI mirroring the artefact in plain language (what, why, how often, how long, revoke); revoke stops fetches immediately; data-life expiry deletes fetched raw data; periodic fetch as a runtime job; `docs/production_path_aa.md` (regulated FIU partner route, certification, DPDP obligations).
**Tests:** consent state machine (pending, active, paused, revoked, expired) at every transition; fetch blocked outside scope or after revoke; schema parsing on sandbox samples or ReBIT examples; reconciliation of AA transactions with captured events end to end; data-life deletion.
**Live check (owner):** one consent and fetch against the sandbox, if access exists; else mark pending.

### Stage C8: Learning from labels
**Build:** feed labels into the Phase 3 learner and memory: guess-rank feedback (which rank was picked) adjusts ranking weights within bounds; merchant habits become memory evidence; P2P per-person policies update; `copilot learning show` includes capture.
**Tests:** bounded updates; reset; per-person policy changes only through the k-of-n rule or explicit user choice; no learning from simulated events unless flagged for demo.

### Stage C9: Evaluation, demo, hardening
**Build:** `copilot eval --capture` reporting on the redacted corpus and simulator: parse accuracy per bank, unparsed rate, reconciliation rate, double-count violations (must be 0), ask rate per 100 payments, guess hit rate (rank 1 and top 3) on held-out simulated histories; if the owner provides four weeks of real usage, the ADR-0001 metrics table with real values (answer rate, time to answer, prompts per day, month-end review queue size). `docs/demo_script_capture.md`: phone bridge forwarding via `adb reverse` → real ₹10 payment to a friend → system notification on the laptop (and the phone) with guesses → tap one; second payment ignored → later open the app on the phone (or laptop) → **Today** shows it under Needs you alongside an incoming payment → tag both → AA sandbox or mock fetch → reconciliation → dashboard updates with the user label → coverage health → simulator fallback path for when no phone is present. Failure pass (backend down, phone offline, duplicate SMS, reversal after label, unknown bank format, revoked consent mid-fetch). README section (bridge setup with screenshots of the rule), and `docs/architecture_agentic.md` update (capture as an event-driven agent loop; human-in-the-loop at the moment of payment; learning from labels).
**[GIT CHECKPOINT B]** record `Add web payment prompts and AA sandbox connector`. Do not run git.

---

## 5. Safety rules with failing-when-removed tests
1. Non-allowlisted senders and OTP messages are never parsed, stored or sent.
2. No raw SMS text in the database, logs, spans, push payloads or LLM prompts; the webhook body is discarded after parsing.
3. No LLM call for person-to-person counterparties; only normalised merchant names ever reach the router.
4. Labels from the user are never overwritten by the agent; reconciliation never merges ambiguous matches.
5. Captured events never double count spend when a ledger transaction exists.
6. AA fetches never happen outside an active, in-scope consent; revoke takes effect immediately.
7. Simulated events are always labelled as simulated in every view.

## 6. Not in this track
A native Android companion and Google Play publication (later option, ADR-0001), screen overlays over other apps (impossible from the web), email parsing, pay-through-FinCo, becoming an FIU, any money movement.
