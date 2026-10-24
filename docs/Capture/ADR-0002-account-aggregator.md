# ADR-0002: Account Aggregator as the authoritative ledger, behind the existing connector interface

**Status:** Proposed
**Date:** 2026-10-14
**Deciders:** Owner (Prateek V Joshi)
**Related:** ADR-0001 (at-payment capture), PLAN_PHASE1 §5.1 (`BankConnector`, `MockAAConnector`)

---

## Context

### The problem
FinCo currently ingests synthetic data through a mock connector shaped like the Account Aggregator (AA) flow. Real users will not download and upload CSV or PDF statements every week. The production-grade way to get Indian bank data with consent is the RBI Account Aggregator framework.

### How AA works (only what matters for this decision)
- Three roles: **FIP** (holds data, for example a bank), **AA** (consent manager and data pipe, cannot read the data), **FIU** (the app that receives the data).
- The FIU raises a **consent request**; the user approves it in their AA's interface; the FIU then requests a data session and receives the financial information.
- Consent parameters (Setu's documented consent object, which follows the ReBIT specification):
  - `fiTypes` (for example `DEPOSIT` for bank accounts) and `consentTypes` (`PROFILE`, `SUMMARY`, `TRANSACTIONS`)
  - `purpose`: code **102 = "Customer spending patterns, budget or other reportings"**, which is FinCo's purpose exactly
  - `fetchType`: `ONETIME` or `PERIODIC`, with `frequency` (Setu caps it at one request per hour)
  - `dataRange`, `consentDuration`, `dataLife` (how long the FIU may keep the data), `consentMode` (`VIEW`, `STORE`, `QUERY`, `STREAM`)
- The user can revoke consent at any time; pipelines must handle consent becoming invalid between scheduled fetches.

### The hard constraint: who may be an FIU
- An FIU must be **regulated by RBI, SEBI, IRDAI or PFRDA** (Sahamati FIU page: "Get registered and regulated by at least one of the Financial Service Regulators"; RBI's direction also requires being an FIP first where applicable).
- An unregulated company **cannot directly become an FIU**. The practical routes are: obtain a licence, or partner with a regulated entity that acts as the FIU while the fintech builds the product layer. Technology Service Providers build FIU modules *for* regulated entities but cannot themselves be the licensed participant.
- Going live also needs: ReBIT-compliant FIU module, testing against AA sandboxes, UAT Central Registry enrolment, certification by a Sahamati-empanelled auditor, and listing in the Central Registry.
- RBI recognised Sahamati as the self-regulatory organisation for the AA ecosystem on 5 June 2026; this does not change the ReBIT API contract.
- One published first-year integration estimate is ₹5 to 25 lakh over 5 to 10 months; it comes from a vendor with a competing product, so treat it as an order of magnitude only.

**Conclusion:** FinCo, as a student project, cannot be a production FIU. It can build a production-shaped integration against real AA sandboxes and simulators, and its documented production path is to sit behind a regulated FIU partner.

### What AA does not do
- **It is not real-time.** It is a consented pull at most hourly, so it cannot trigger the at-payment question (that is ADR-0001's job).
- **UPI Lite spending** (other than top-ups) is not in the account passbook, so it is invisible to a deposit-account fetch.
- **Cash** is invisible to everything except the user.
- Coverage varies by FIP and FI type; check what each bank serves.

### Developer access (what exists, as found on 14 Oct 2026)
- **Setu AA gateway sandbox:** sign-up on Setu's Bridge asks for a company PAN and GSTIN; provides mock data for all 23 FI types and webhooks for consent and data-ready events. A student without a GSTIN may not get access; check.
- **AA sandboxes listed by Sahamati** for an earlier hackathon (Finvu, NADL, OneMoney, Perfios, Yodlee Finsoft); availability and sign-up terms may have changed.
- **Sahamati developer simulators** (AA simulator and FIP simulator) documented on developer.sahamati.org.in.

---

## Decision

1. **Keep the `BankConnector` interface as the boundary.** Everything above it (ingestion, categorisation, Phase 2) stays unchanged.
2. **Three connector implementations, chosen by config:**
   - `MockAAConnector`: synthetic, for tests and evaluation; upgraded to emit **ReBIT Deposit-schema-shaped** data (narration, mode, reference, value date, balances) so switching sources does not change parsing.
   - `AASandboxConnector`: a real ReBIT-shaped client against one AA sandbox or the Sahamati simulators. Implements consent create (purpose 102, `DEPOSIT`, `TRANSACTIONS`, `PERIODIC` daily, `consentMode = STORE`, `dataLife` matching the user's retention choice), consent-status webhook or polling, data session, fetch, and decryption or gateway-decrypted payloads, whichever the sandbox uses.
   - `StatementImportConnector`: fallback for users who decline AA or whose bank is not covered (CSV, and e-statement PDF later). Not the main path.
3. **AA is the authoritative ledger.** For an AA-linked account, only AA transactions count as spend. Capture events from ADR-0001 attach labels to them through reconciliation (UTR first, then amount + last 4 + time window, never merging on ambiguity).
4. **Consent is a first-class object in the product.** FinCo's consent screen mirrors the AA artefact in plain language: what is shared (accounts, types), the purpose (code 102 in words), the date range, how often data is fetched, how long it is kept, when consent expires, and a revoke control. Revocation stops fetches immediately and is audited; `dataLife` expiry triggers deletion of fetched raw data per the stated retention.
5. **Fetch schedule:** daily periodic fetch by default (cheaper and enough for a ledger), plus an on-demand fetch when the user opens the monthly review. Hourly is allowed by the spec but not needed, because real-time comes from ADR-0001.
6. **Production path (documented, not built):** partner with a regulated FIU (bank, NBFC or another licensed entity) or an AA gateway operated for one; FinCo remains the product layer. Before any real user data: DPDP Rules, 2025 compliance (notified November 2025, phased over 18 months), privacy notice, retention policy, data-processing agreement with the FIU partner.

---

## Options considered

### Option A: Connector abstraction with AA sandbox + mock + statement fallback (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Medium: ReBIT schemas, consent lifecycle, webhooks, encryption or gateway |
| Cost | Sandbox: free or low to access, subject to sign-up terms |
| Production realism | High: same consent artefact and data shapes as production |
| Regulatory fit | Correct: does not pretend to be an FIU |

**Pros:** honest, production-shaped, swappable, testable offline. **Cons:** sandbox data is not the owner's real data; sandbox sign-up may need company identifiers.

### Option B: Become an FIU
**Rejected:** requires being a regulated financial entity. Not possible for this project.

### Option C: Statement upload only (CSV/PDF)
**Pros:** works for anyone today. **Cons:** manual and periodic; users stop doing it; PDF formats vary by bank; password-protected e-statements. **Kept as fallback only.**

### Option D: Screen-scraping net banking with user credentials
**Rejected outright:** collecting bank credentials is unsafe, against bank terms, and violates FinCo's own rule of never handling passwords.

### Option E: Commercial aggregator API (non-AA)
**Rejected:** the AA framework is the consented, regulated route for Indian bank data; anything else adds legal and trust risk.

---

## Trade-off analysis
The real trade is **production realism vs. what a student can legally access**. Option A gets the same consent artefact, purpose code, fetch semantics and data schema as production, while being honest that production access needs a regulated partner. Combined with ADR-0001, the owner can still demo **real** transactions: the capture lane parses the owner's own bank SMS on their own phone, and the AA sandbox demonstrates the consented ledger path. Neither requires mock numbers to be presented as real.

---

## Consequences
**Easier**
- Switching from sandbox to a partner FIU later is configuration plus credentials, not a rewrite.
- Reconciliation gives a verified ledger and catches duplicate, reversed and missing transactions.
- The consent screen becomes a strong, regulator-aligned trust feature in the UI.

**Harder**
- ReBIT schema handling, webhook security, consent state machine (pending, active, paused, revoked, expired), and partial-FIP failures all need tests.
- Sandbox access may require identifiers the owner does not have; the Sahamati simulators are the fallback.
- Two sources of truth during the gap between capture and fetch must be shown clearly (provisional vs. verified).

**To revisit**
- Purpose code and `dataLife` once a real FIU partner exists.
- Adding FI types beyond `DEPOSIT` (term and recurring deposits) when Phase 3 goals need them.
- DPDP consent-manager developments (registration and penalties phase in from November 2026).

---

## Action items
1. [ ] Try sandbox sign-ups in this order: Sahamati simulators (no commercial identifiers expected), Finvu / OneMoney sandboxes, Setu (needs PAN + GSTIN). Record which one works in `docs/open_questions.md`.
2. [ ] Upgrade `MockAAConnector` to ReBIT Deposit-schema output; keep hidden ground truth for evaluation.
3. [ ] Implement `AASandboxConnector`: consent create, status, data session, fetch, decrypt or gateway payload, revoke; typed errors for every failure; audit events for consent changes and fetches.
4. [ ] Consent UI per decision 4 (feeds PLAN_UI §8.4).
5. [ ] Reconciliation and coverage health shared with ADR-0001.
6. [ ] Retention: honour `dataLife`; deletion job; tests that expired data is gone.
7. [ ] `docs/production_path_aa.md`: regulated-partner model, certification steps, DPDP obligations.

---

## Sources
- [Sahamati: Financial Information User onboarding (regulator requirement, steps)](https://sahamati.org.in/financial-information-user-fiu)
- [Account Aggregator integration in 2026: consent architecture, DPDP overlap and SRO changes (eCorpIT, 17 July 2026)](https://ecorpit.com/account-aggregator-integration-fintech-builders-2026/)
- [Setu: AA consent object (fetchType, frequency, dataLife, purpose codes)](https://docs.setu.co/data/account-aggregator/consent-object)
- [Setu: AA quickstart (sandbox, mock data, webhooks)](https://docs.setu.co/data/account-aggregator/quickstart)
- [Setu support: generating sandbox credentials (PAN, GSTIN)](https://support.setu.co/support/solutions/articles/81000412878-how-does-one-generate-sandbox-credentials-)
- [Sahamati: AA hackathon tech FAQ (list of AA sandboxes)](https://sahamati.org.in/account-aggregator-hackathon-tech-faq/)
- [Sahamati developer docs: integration with simulators](https://developer.sahamati.org.in/sahamatinet-mvp/integration-with-simulators)
- [BHIM UPI: UPI Lite (not in passbook)](https://bhimupi.org.in/content/upi-lite)
