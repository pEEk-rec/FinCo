# ADR-0001: Categorise at the moment of payment, triggered by the bank's debit alert

**Status:** Proposed (amended 2026-10-18: web-first capture, see end of document)
**Date:** 2026-10-14
**Deciders:** Owner (Prateek V Joshi)
**Related:** ADR-0002 (Account Aggregator ingestion), PLAN_PHASE1 §5.2 (categorisation pipeline), PLAN_PHASE2 §5.2 (intent), PLAN_UI §8.3 (review queue)

---

## Context

### The problem
Rules, merchant registries and an LLM can categorise *registered merchants* (Swiggy, Airtel, IRCTC). They cannot categorise the long tail, because the missing information is not in the data, it is in the user's head:
- **Person-to-person UPI** (`98xxxxxx10@ybl`, "RAMESH K"): rent, a split dinner, a loan repayment and a gift look identical.
- **Small and unregistered merchants** (`paytmqr28100505...@paytm`, a kirana store's personal VPA).
- **Cash withdrawals**, where the spending happens later.

In a real month this is easily 50 to 100+ transactions, so the Phase 1 review queue turns into a backlog that no one clears. The rest of the system (budgets, forecasts, investigations, goals, Phase 2 recommendations) is only as good as these labels.

### The idea
Ask the user **once, at the moment they pay**, when they still remember why. Offer the three most likely categories as one tap. Remember the answer where remembering is valid. Never block and never insist.

### Forces and facts that shape the design
1. **Payments happen in many apps** (Google Pay, PhonePe, Paytm, BHIM, bank apps, WhatsApp Pay, net banking, cards). Hooking each app is fragile and incomplete.
2. **The bank's debit alert is the one app-agnostic event.** Banks must ask customers to mandatorily register for SMS alerts on electronic banking transactions (RBI circular, 6 July 2017). Whatever app was used, the debit SMS comes from the bank.
3. **Android allows this, with conditions.** Google Play lists *"SMS-based money management"* ("apps that track and manage budget") as an exception for `READ_SMS` and `RECEIVE_SMS`. The exception is temporary, needs a Permissions Declaration Form, must be core functionality with no alternative, and budgeting apps "may not exfiltrate or share non-financial or personal SMS history." `SMS_RECEIVED_ACTION` is still deliverable to manifest receivers on modern Android, so the app is woken even when not running.
4. **Overlays are the wrong tool.** Since Android 10, starting activities from the background is restricted. `SYSTEM_ALERT_WINDOW` (draw over other apps) is an exemption, but it is a high-risk permission, intrusive, and needs strong policy justification. **Notifications can carry up to three action buttons** (official Android guidance). That is exactly "top three guesses as one-tap buttons", and a heads-up notification looks and feels like the Truecaller-style pop-up without the overlay permission.
5. **Gaps the bank SMS does not cover:**
   - **UPI Lite:** one SMS per day from the issuing bank, and Lite payments other than top-ups do not appear in the account passbook (BHIM/NPCI). Per-payment capture needs the payment app's own notification.
   - **Cash** spending after an ATM withdrawal.
   - Bank SMS delivered to a different phone or SIM than the one with the app.
6. **iOS gives third-party apps no access to SMS or other apps' notifications.** The only on-device route is a user-built Shortcuts *Message* automation. These can run immediately on iOS 18 and later; passing the message text into our app needs on-device verification.
7. **Sideloaded builds** (for example the demo APK) hit Android 13+ *restricted settings*, which block notification-listener (and accessibility) access for apps not installed from a store. On most devices the user can lift this from the app's info screen, but verify on the demo phone. Whether newer Android versions add similar friction for SMS permissions on sideloaded apps is not confirmed; test it.
8. **Payment apps do not solve this.** Paytm auto-tags *"every payment made through Paytm"* and lets the user edit a tag afterwards, with the edit applied to future payments to that merchant (announced September 2025). Each payment app sees only its own payments, so its view is partial for anyone who uses more than one app, a card or net banking. My reading of why no one asks at payment time: checkout friction hurts their core metric, and they cannot see the whole ledger anyway. This part is analysis, not a sourced fact.

### Non-negotiables carried from earlier phases
- The user's choice beats everything (Phase 1 precedence: user > override > rule > cache > LLM). An at-payment answer **is** a user choice.
- No money movement, no blocking, every prompt overridable.
- Privacy: raw SMS never leaves the device, is never stored, and non-bank SMS is never read beyond the sender check.

---

## Decision

Build a **capture lane** made of an Android companion with an on-device bank-SMS parser. It raises an **actionable heads-up notification** (three guess buttons; tap opens a quick sheet) only for payments the system cannot categorise confidently. Answers are stored as user labels on a **payment event**. Payment events are later **reconciled** to authoritative ledger transactions from Account Aggregator (ADR-0002) using the UPI reference number. The label then flows into the existing pipeline as `category_source = user`.

```
 Bank debit SMS ─┐                                  ┌─► auto-label (silent, "Change" link)
 UPI app notif  ─┼─► on-device parser ─► payment ───┤
 (optional,      │   (sender allowlist,   event      ├─► ASK: heads-up notification
  Lite / richer  │    templates, UTR,     + ask       │     [Guess 1] [Guess 2] [Guess 3]
  payee name)    │    amount, last4)      policy      │     tap body → quick sheet (all, split, note)
 Manual entry  ─┘                                   └─► defer: digest / inbox / weekly review
                                   │
                                   ▼  (structured fields only)
                         FinCo API: /capture/events, /capture/labels
                                   │
        AA periodic fetch ─► ledger transactions ─► reconcile (UTR → amount+time+last4)
                                   │                         │
                                   ▼                         ▼
                     categorisation pipeline       label becomes category_source=user
                     (user > override > rule > cache > LLM > review)
```

### D1. Signals and their roles
| Signal | Role | Trust |
|---|---|---|
| Bank SMS (`RECEIVE_SMS`) | Primary real-time trigger, covers all apps and banks | Unverified until reconciled (SMS can be spoofed; parse only allowlisted bank sender IDs) |
| Payment-app notification (`NotificationListenerService`, opt-in) | Secondary: UPI Lite payments, richer payee name, faster than some banks' SMS | Unverified |
| Manual quick-add | Cash spends, missed payments | User-asserted |
| AA transaction (ADR-0002) | **Authoritative ledger** | Verified |

### D2. Payment event state machine
`detected → posted → (reversed | refunded) → reconciled | orphaned`. Do not prompt on `detected` if a failure or pending message is expected; prompt on a confirmed debit. A reversal SMS cancels the prompt or turns the label into a refund link. An event that never reconciles within the AA window is shown as *unverified* and never counted twice.

### D3. When to ask (the ask policy, deterministic and configurable)
Classify the counterparty from the parsed fields (`counterparty_key` = normalised VPA, card descriptor or name; `kind` ∈ merchant / person / self / cash / unknown):
1. **Own-account transfer** → never ask; Phase 1 transfer detection excludes it from spend.
2. **Known merchant with confidence ≥ `auto_accept_min_confidence`** (override, rule, cache) → never ask; optional silent notification "Tagged Food · Change".
3. **Recurring series or UPI AutoPay mandate** → never ask; use the series category.
4. **Unknown merchant** → ask once. The answer becomes a merchant override (existing table), and the merchant is never asked again unless the user changes it.
5. **Person (P2P)** → ask, but learn a **per-person policy**: if the same category was chosen for this person *k* of the last *n* times (config, for example 3 of 3), auto-label with a visible "Change"; otherwise keep asking. The sheet offers "Always ask for this person" and "Always use <category> for this person". *Remembering a person like a merchant would be wrong*: rent and dinner go to the same friend.
6. **Cash withdrawal** → optional low-priority ask ("What will this cash be for?"), with a "Track cash spends later" choice.
7. **Below `min_ask_amount`** (config) → no prompt; best guess applied, labelled as a guess, reviewed in bulk.

### D4. The three guesses (deterministic, explainable, on-device)
Score each category with a weighted sum (weights in config):
- this counterparty's history (counts with recency decay)
- the user's own pattern by time of day and weekday (for example tea at 11:00 and dinner at 21:00)
- amount band typical of each category for this user
- day of month (rent and fees cluster near the 1st to 5th)
- merchant-name rules or registry hint, if any
- recency (the last category used, for rapid repeat payments)

Take the top three distinct categories. If fewer than three have any evidence, fill with the user's most frequent categories. No LLM on the device and no SMS text to any cloud model. For unknown *merchant-like* names, the backend may later run the existing redacted-merchant LLM path, which only improves future suggestions; it never labels silently.

### D5. Notification UX
- **Heads-up notification** in a dedicated channel ("Payment tagging", user-adjustable importance):
  title "₹250 to Ramesh K · HDFC ••1234", three action buttons (guesses), body tap → quick sheet.
- **Quick sheet:** all categories as a searchable grid (most-used first), *Split* (add a second category and amount), *Note*, *Not mine / ignore*, and per-person policy toggles. Opening from the notification is a system `PendingIntent` from a notification tap, which is allowed to start an activity.
- **Lock screen:** `VISIBILITY_PRIVATE` with a public version "1 payment to tag", so amounts and names are not shown on a locked screen.
- **Grouping:** several pending prompts collapse into one group ("3 payments to tag").
- **Never blocking:** swiping away = "later". Nothing is ever required.

### D6. Anti-fatigue rules
- Daily ask budget (`max_prompts_per_day`), quiet hours, per-merchant cooldown.
- Unanswered prompts move to an **in-app inbox**; an optional evening digest ("Tag today's 4 payments", swipe cards); after `prompt_ttl_hours` the best guess is applied as a *guess* (`category_source = cache` or `llm`, `needs_review = true`) and joins the normal review queue.
- If the user dismisses most prompts for a class (for example small P2P), lower its priority automatically, but record the change so the user can see and undo it.
- Measured, not assumed (see Metrics).

### D7. Data and privacy rules
- The parser reads only messages from an allowlist of bank sender IDs (DLT headers per bank, kept in config). All other SMS (OTP, personal) are dropped in memory without logging. The raw body is never persisted or transmitted. Only structured fields leave the parser: amount (paise), direction, account last 4, UTR or RRN, counterparty key and display name, timestamp, bank, channel.
- Prominent in-app disclosure before requesting SMS and notification access, stating exactly what is read and what is kept, matching the Play policy text.
- Labels and events sync to the FinCo backend with the existing `user_id`, audit and redaction rules. Every label is an audited `user` action and undoable.

### D8. Reconciliation (shared with ADR-0002)
Match a payment event to a ledger transaction by, in order: (1) **UTR/RRN** (12-digit UPI reference, present in most UPI debit SMS and in typical AA narrations); (2) amount + account last 4 + time window; (3) no match → keep both, never merge on ambiguity. On match, copy the label to the transaction as `category_source = user`, linked to the event for audit. The ledger is the AA transaction; the event never adds spend on its own when the account is AA-linked. For accounts without AA, events form a **provisional ledger**, clearly marked *unverified* in every view.

### D9. Coverage health
Compare reconciled events with ledger transactions per account. "We saw 12 HDFC transactions via your bank but 0 SMS: is the bank SMS going to another phone?" turns silent capture gaps into a visible, fixable state.

---

## Options considered

### Option A: Actionable notification triggered by bank SMS (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Medium: Android companion, SMS templates per bank, reconciliation |
| Cost | Low (no paid services); Play approval effort if ever published |
| Coverage | All apps, net banking, cards, AutoPay on Android; gaps: UPI Lite, cash, SMS on another phone, iOS |
| Policy risk | Medium: SMS permission is a discretionary, temporary Play exception for budgeting apps |
| UX | Low friction; three-button actions match the requirement; deferrable |

**Pros:** app-agnostic; real data; works when FinCo is closed; respects user's flow; no overlay permission.
**Cons:** Android only; Play approval not guaranteed; bank SMS formats vary and change; SMS can be delayed or spoofed, so labels need reconciliation.

### Option B: Truecaller-style overlay (`SYSTEM_ALERT_WINDOW`)
| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Policy and trust | High risk: draw-over-apps is a classic abuse vector and intrusive at checkout |
| UX | Covers part of the screen during payment confirmation, which can cause mis-taps in the payment app |

**Rejected:** notifications deliver the same interaction (three choices, one tap) with lower risk. Revisit only if users ignore notifications at scale.

### Option C: Notification listener on payment apps only
**Pros:** catches UPI Lite and richer payee names. **Cons:** misses net banking, cards and apps not listed; notification formats change with app updates; restricted settings for sideloaded builds; must not be the only source. **Decision:** optional secondary signal.

### Option D: AA only, with bulk review (status quo)
**Pros:** authoritative, consented, no SMS permission. **Cons:** AA is pull-based (periodic fetch at most hourly), so it arrives after the user has forgotten why they paid; P2P intent is lost; the review backlog returns. **Decision:** AA is the ledger, not the trigger.

### Option E: Pay through FinCo (scan QR in FinCo, hand off to the UPI app)
**Pros:** captures intent before payment, with exact payee. **Cons:** changes user habits; starts to look like payment initiation, which is outside the product's authority boundary ("never transfers, pays, trades"); only covers payments started inside FinCo. **Rejected for now;** log in `open_questions.md`.

### Option F: Email alert parsing (Gmail)
**Pros:** works on iOS. **Cons:** restricted Google scopes need an external security assessment; email alerts are optional and inconsistent; latency. **Rejected for now.**

---

## Trade-off analysis
The core trade is **real-time intent capture vs. authoritative data**. No single source gives both: SMS is immediate but unverified and Android-only; AA is verified but late. Splitting the roles (SMS triggers the question, AA confirms the transaction, UTR joins them) gets both, at the cost of a reconciliation component. That component is worth building anyway because it also catches duplicates, reversals and capture gaps.

The second trade is **label accuracy vs. interruption**. Asking every time maximises labels and destroys goodwill; never asking returns us to the backlog. The ask policy (D3) and fatigue rules (D6) put the question only where inference provably fails (unknown merchants, ambiguous people), and the metrics below tell us if the balance is wrong.

---

## Consequences
**Easier**
- Long-tail and P2P categories become user truth, not guesses; Phase 2 investigations, goals and recommendations get cleaner inputs.
- The monthly review queue should shrink to a handful of items.
- The demo uses **real transactions from the owner's own phone**, with no mock numbers.

**Harder**
- A second client (Android, Kotlin) to build and maintain; device-specific battery killers (some OEMs) can delay processing.
- Per-bank SMS templates are an ongoing maintenance cost; template drift must be detected (parse-failure rate per sender).
- Publishing on Play needs the SMS declaration and may be refused; sideloaded builds need the user to allow restricted settings for the notification listener.
- iOS users get a weaker experience (Shortcuts setup or AA plus a daily digest).

**To revisit**
- Overlay vs. notification if answer rates are low.
- Whether per-person auto-labelling thresholds are right.
- Pay-through-FinCo (Option E) if the product's authority boundary is ever reconsidered.

---

## Metrics (instrumented from day one)
| Metric | Target to start with |
|---|---|
| Prompt answer rate within 1 hour | ≥ 60% |
| Median time to answer | ≤ 30 s from notification |
| Guess hit rate (rank 1 / any of top 3) | ≥ 50% / ≥ 85% after 4 weeks |
| Prompts per day (median user) | ≤ 3 |
| Review queue at month end | ≤ 10 items |
| Event–ledger reconciliation rate | ≥ 95% for AA-linked accounts |
| SMS parse failure rate per bank sender | < 2% (alert on rise: template drift) |

Targets are starting assumptions, not facts; the evaluation reports the real values.

---

## Action items
1. [ ] Backend: tables `payment_events`, `capture_labels`, `counterparty_profiles`, `prompt_log`, `event_links`; tools `record_payment_event`, `label_payment_event` (actor user), `reconcile_events`; ask-policy and guess-ranking as pure, tested functions; API endpoints `/capture/events`, `/capture/labels`, `/capture/pending`.
2. [ ] A **payment-event simulator** in the web UI and CLI so the full flow is testable without a phone (clearly labelled as simulated).
3. [ ] SMS template corpus: collect the owner's own bank SMS, redact them (amounts and UTRs replaced), store as test fixtures only; YAML templates per bank sender with a generic fallback; parser property tests (never parses an OTP SMS; never returns a float).
4. [ ] Android companion (Kotlin): `RECEIVE_SMS` manifest receiver → expedited work → parser → local store (encrypted) → ask policy → notification with three actions → quick sheet → sync. Optional notification listener for UPI Lite. Prominent disclosure screen.
5. [ ] Reconciliation and coverage health, shared with ADR-0002.
6. [ ] Evaluate on four weeks of the owner's real usage; report the metrics table honestly.
7. [ ] Record open questions: Play publication, iOS Shortcuts path, cash tracking, Option E.

---

## Sources
- [RBI customer liability circular, 6 July 2017: mandatory SMS alert registration (summary by Nishith Desai Associates)](https://nishithdesai.com/research-and-articles/hotline/regulatory-hotline/boost-to-e-payments-customers-given-protection-for-fraudulent-transactions-5030)
- [Google Play: Use of SMS or Call Log permission groups (exceptions incl. SMS-based money management)](https://support.google.com/googleplay/android-developer/answer/10208820?hl=en)
- [Android: implicit broadcast exceptions (SMS_RECEIVED_ACTION)](https://developer.android.com/develop/background-work/background-tasks/broadcasts/broadcast-exceptions)
- [Android: create a notification (up to three action buttons)](https://developer.android.com/develop/ui/views/notifications/build-notification)
- [Android: restrictions on starting activities from the background](https://developer.android.com/guide/components/activities/background-starts)
- [Android 13 restricted settings for sideloaded apps (Chrome Unboxed)](https://chromeunboxed.com/android-13-restricted-setting-feature-blocks-sideloaded-apps-from-notifications/)
- [BHIM UPI: UPI Lite (daily SMS, not in passbook)](https://bhimupi.org.in/content/upi-lite)
- [Paytm spend tags (Digital Terminal, September 2025)](https://digitalterminal.in/amp/story/solutions/paytm-app-update-offers-customizable-spend-tags-and-smarter-financial-insights)
- [iOS Shortcuts message automations (MacMost)](https://macmost.com/how-to-set-up-your-iphone-to-automatically-respond-to-text-messages.html)

---

## Amendment, 2026-10-18: web-first capture
For the current build, FinCo does **not** ship a native Android app. The trigger is a **no-code SMS forwarder** on the user's phone (MacroDroid or Tasker on Android, a Shortcuts message automation on iPhone) that POSTs only allowlisted bank SMS to FinCo's local webhook; FinCo parses on the server and discards the text. Prompts appear as an **in-app overlay** on any open FinCo page (server-sent events) and optionally as a **PWA push notification** with the browser's limited action buttons.
- Gains: no Kotlin, no Play policy exposure, works on iPhone too, same ask policy, ranking and reconciliation.
- Costs: raw SMS travels from the phone to the user's own local backend (still never stored or logged); a third-party automation app holds the SMS permission; push needs `localhost` or HTTPS; browsers show fewer action buttons than native notifications; no true overlay over other apps.
- The native companion (Option A) remains the path for public release.
