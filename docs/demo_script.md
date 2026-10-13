# Finance Copilot — 5-Minute Offline Demo Script

This script walks through the end-to-end interactive demo of **Finance Copilot** using the unified Typer CLI (`copilot`). It runs completely offline against deterministic synthetic bank data, exercising every stage of Phase 1: ingestion, consent governance, policy enforcement, multi-layer categorization, advice verification, user correction, undo, and versioned monthly review reporting.

---

## Prerequisites

Activate the virtual environment from the repository root:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Verify CLI installation and view all available commands:

```bash
copilot --help
```

Expected output:
```text
Usage: copilot [OPTIONS] COMMAND [ARGS]...
Personal Finance & Budgeting Copilot CLI
Commands:
  init-db       Initialize database and apply all schema migrations.
  seed          Seed demo user, accounts, categories, budgets, and synthetic bank data.
  consent       Manage bank account aggregator consents (list, create, approve, revoke).
  run           Run full agent graph: ingest -> categorize -> analyze -> advise -> review -> finalize.
  review-month  Generate and render monthly review (writes reports/<period>.md and .html).
  txns          List transactions with optional filters (--month, --needs-review, --json).
  correct       User correction: change a transaction's category (optional --remember).
  undo          Undo a specific reversible audit event.
  undo-batch    Undo an entire automated categorization batch.
  budgets       View monthly budget performance statuses.
  forecast      View month-end spend forecast.
  anomalies     View detected unusual/outlier transactions.
  recurring     View recurring subscriptions and bills.
  state         View financial state snapshot.
  audit         View audit trail with before/after state and reversibility flags.
  trace         Display node-by-node execution trace for a workflow run.
  eval          Evaluation harness runner (Stage 1.12).
```

---

## Step 1: Initialize Database & Schema

Apply all schema tables (including `consents`, `transactions`, `audit_events`, `budgets`, `monthly_reviews`, `review_reports`):

```bash
copilot init-db
```

Output:
```text
✔ Database initialized successfully at data/copilot.db
```

*(Optional machine verification: `copilot init-db --json`)*

---

## Step 2: Seed Mock Banking Environment

Generate a realistic 3-month deterministic financial history for demo user `u1`:

```bash
copilot seed --months 3 --seed 42
```

Output:
```text
✔ Seeded environment for user u1:
  • Accounts: a1 (Checking)
  • Categories & Budgets configured
  • Generated: 84 synthetic bank records
  • Consent created: consent_seed_u1_42 (Approve with 'copilot consent approve <id>')
```

---

## Step 3: Consent Governance Lifecycle

Check consent status under Account Aggregator governance:

```bash
copilot consent list
```

Observe that consent `consent_seed_u1_42` is currently in status **PENDING**.
If you attempt to run the ingestion workflow without active consent:

```bash
copilot run --auto-approve
```

Output:
```text
Error: No active consent found for user 'u1'. Approve pending consent: copilot consent approve consent_seed_u1_42
```

Now, simulate explicit user consent approval:

```bash
copilot consent approve consent_seed_u1_42
```

Output:
```text
✔ Consent consent_seed_u1_42 approved (status: ACTIVE)
```

Verify with `copilot consent list` that the consent is now **ACTIVE**.

---

## Step 4: Run the Autonomous Agent Workflow

Run the full LangGraph pipeline (`ingest` → `categorize` → `analyze` → `advise` → `review` → `finalize`):

```bash
copilot run --year 2024 --month 2 --auto-approve
```

Output:
```text
✔ Workflow execution completed (run_20261013_XXXXXX)
================================================================================
                               WORKFLOW RUN TRACE                               
================================================================================
NODE         STATUS   DURATION   TOOLS CALLED             COUNTS
--------------------------------------------------------------------------------
ingest       ok       45.2ms     ingest_statements        fetched: 84, inserted: 84, skipped_existing: 0
categorize   ok       28.1ms     categorize_batch         total: 84, categorized: 84, needs_review: 4
analyze      ok       34.6ms     detect_transfers, ...    transfers_linked: 1, recurring_detected: 3, ...
advise       ok       12.3ms     draft_advice             findings_count: 3, advice_drafted_count: 2
review       ok        1.2ms     -                        decisions_applied: 2, approved: 2
finalize     ok        4.5ms     get_financial_state      accounts_count: 1, budgets_count: 2
--------------------------------------------------------------------------------
Total duration: 125.9ms | Trace steps: 6
================================================================================
```

---

## Step 5: Inspect Transactions & Human-in-the-Loop Review Queue

View the ingested and categorized transactions in a Rich color table:

```bash
copilot txns --limit 15
```

Filter specifically for transactions routed to human review (confidence < 0.70):

```bash
copilot txns --needs-review
```

Inspect as structured JSON for pipelines or scripting:

```bash
copilot txns --limit 3 --json
```

---

## Step 6: User Correction with Merchant Memory

Pick any transaction ID from the review list (e.g., `tx_...`) and override its category with `--remember`:

```bash
copilot correct <TRANSACTION_ID> cat_dining --remember
```

Output:
```text
✔ Transaction tx_... updated to category cat_dining
  • Saved merchant override for future transactions.
```

---

## Step 7: Audit Trail & One-Click Undo

Inspect the tamper-evident audit trail showing before/after diffs and reversibility:

```bash
copilot audit --limit 10
```

Grab the Event ID of your recategorization and undo it cleanly:

```bash
copilot undo <AUDIT_EVENT_ID>
```

Output:
```text
✔ Undid event <AUDIT_EVENT_ID> successfully.
```

Verify that the transaction restored its exact original category and confidence score.

---

## Step 8: Real-Time Financial Analytics

### Check Budget Performance:
```bash
copilot budgets --month 2024-02
```

### View Month-End Spend Forecast:
```bash
copilot forecast --month 2024-02
```

### View Outlier Anomalies:
```bash
copilot anomalies --month 2024-02
```

### View Recurring Bills & Subscriptions:
```bash
copilot recurring
```

### View High-Level State Snapshot:
```bash
copilot state --month 2024-02
```

---

## Step 9: Versioned Monthly Review Generation

Generate the formal monthly financial review and render both Markdown and HTML reports:

```bash
copilot review-month 2024-02
```

Output:
```text
✔ Generated Monthly Review for 2024-02 (v1)
  • Income:     ₹50,000
  • Spend:      ₹24,350
  • Net:        +₹25,650
  • Categories: 6 tracked
  • Written:    reports/2024-02.md (1016 bytes)
  • Written:    reports/2024-02.html (5088 bytes)
```

Inspect the rendered Markdown report:
```bash
type reports\2024-02.md
```

Or open the self-contained HTML report in your browser:
```powershell
Start-Process reports\2024-02.html
```

---

## Step 10: Workflow Trace Inspection

View the full execution trace of any prior workflow run:

```bash
copilot trace <RUN_ID>
```

Displays the exact step durations, tools called, policy gates evaluated, and counts.
