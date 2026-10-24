# Account Aggregator: from this prototype to production

FinCo is a personal project. It is **not** a Financial Information User (FIU) and it does not
hold a licence. This page says what the prototype does today, and what changing that would take,
so nobody mistakes the demo link for the real thing.

## What exists today

- A consent screen (Connect and import → Bank link) that states the consent in plain words: what
  is read, why, how often, for how long, what is kept, how to stop it. The text is built by the
  API from `config/aa.yaml`; nothing is hardcoded in the web app.
- A consent state machine: `pending → active ⇄ paused`, with `revoked` and `expired` final. Every
  transition is an audit event. Only the user can change a consent; the agent is denied by policy.
- A fetch pipeline that runs only under an active, in-scope consent. The consent is checked
  before the source is called and again before anything is saved, so a revoke that lands
  mid-fetch discards the result. Revoking also deletes the fetched copies at once.
- Rows outside the consented date range are dropped. Fetched raw replies are kept only for the
  data life in the config (180 days by default), then deleted by the daily job. The ledger rows
  made from them belong to the user and stay.
- A **mock bank** that answers in the ReBIT Deposit schema (profile, summary, transactions), so
  parsing, ledger import and reconciliation with captured alerts are exercised the way they will
  be live. It "posts" payments FinCo already heard about by alert, a couple of hours later.
- A **sandbox connector** (`SandboxAASource` over `copilot.live.aa`) that is written from the
  provider's public documentation and tested against a local fake gateway. It has not been run
  against a live sandbox, because that needs the owner's credentials (`AA_BASE_URL`,
  `AA_CLIENT_ID`, `AA_CLIENT_SECRET`, `AA_PRODUCT_INSTANCE_ID` in `.env`, never committed).

## What it deliberately does not do

- It does not decrypt ReBIT-encrypted payloads. The sandbox gateways it targets return decrypted
  data to a registered FIU client. If a gateway ever returned encrypted FI data, the
  `cryptography` package would be needed, and that is a dependency decision for the owner.
- It does not move money, ever. AA is read-only by design and so is this code.
- It does not keep the aggregator's raw reply once the data life has passed.

## The regulated route, if this ever served other people

1. **Do not become an FIU.** The practical route is to partner with an RBI-regulated NBFC-AA's
   FIU-as-a-service, or a licensed FIU that offers an API, and be its customer. Direct FIU status
   needs its own regulatory standing and onboarding with the AA ecosystem (Sahamati).
2. **Certification.** The partner and the AA require conformance testing against the ReBIT
   specification, security review, and signed-request handling (JWS, key rotation) before
   production access. The sandbox is the place to rehearse this.
3. **Consent artefact fidelity.** Production consent text, purpose codes and data-life values
   must match what the AA shows the user; FinCo's screen must mirror, not replace, that artefact.
4. **DPDP Act obligations.** A notice in plain language, purpose limitation (purpose code 102 only
   for spending analysis), data minimisation (transactions only), retention limits (the data
   life above), the right to withdraw consent as easily as it was given, a grievance contact, and
   breach notification. Children's data and cross-border transfer need separate care.
5. **Operations.** Encrypted storage of fetched data, access logging, a deletion job that is
   monitored, and a runbook for a revoked consent that did not propagate.

## Owner checklist for a live sandbox check

1. Register for a sandbox and obtain credentials. Put them in `.env`; set `connector: sandbox`
   in `config/aa.yaml`.
2. Create the link in the web app, approve it in the aggregator's page, then press Approve in
   FinCo (it checks the aggregator reports the consent as active first).
3. Fetch now. Expect the transactions in the ledger and any matching alerts reconciled.
4. If a path or header name differs, change it in `AAConfig` (`copilot.live.aa`); it is
   configuration, not logic.
