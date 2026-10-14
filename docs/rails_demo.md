# FinCo Rails: live alerts and receipts (separate demo)

A second, self-contained demo API. It does **not** touch the main demo: its own port, its own
database file, its own routes. The main app and its tests are unchanged.

## Run it

```
.venv\Scripts\python -m copilot.rails            # http://127.0.0.1:8100
```

It prints a URL with a session token. Open that URL. Options: `--port`, `--db`, `--token`
(or `RAILS_PORT`, `RAILS_DB`, `RAILS_TOKEN`). API docs are at `/docs`.
The main demo (`npm run demo`) keeps running on its own ports.

## What it adds on top of the Account Aggregator statement

| Rail | What it does | Where |
|---|---|---|
| Bank alerts (SMS) | Reads Indian bank alert texts (SBI, HDFC, ICICI, Axis, card) into a payment the moment it arrives. Refuses OTPs, mandates and failures. | `rails/sms.py` |
| Receipts (email) | Reads an order receipt and drafts a category split of one payment (for example Rs 850 into Education 600 and Dining 250). Fees and discounts are spread in whole paise that add up exactly. | `rails/receipts.py` |
| Bill-pay billers, merchant codes | Known billers and everyday merchants map to a category without guessing. | `config/rails.yaml` |
| Reconcile | When the statement contains the same payment, the alert becomes verified and is never counted twice. | `rails/engine.py` |
| Pacing | Month-to-date spend per budget from the statement plus unconfirmed alerts, with a straight-line projection. | `rails/engine.py` |

The statement stays the source of truth. Alerts are provisional until it confirms them.

## Demo script (about 3 minutes)

1. Open the page. Budgets show the statement only (latest statement row is 17 March).
2. **Send all alerts.** Dining and Shopping turn "projected over" within a second, before any
   statement exists. The person-to-person UPI payment is left for you to categorise, not guessed.
   The OTP and autopay buttons show that non-payments are ignored.
3. **Read receipt.** The Amazon payment is matched and a split is drafted. Nothing changes yet.
   Approve it: Shopping drops by 850 and Education and Dining take their parts.
4. **Run the nightly sync.** The statement posts, five alerts become verified, one stays waiting.
   Totals do not change (no double counting). Run it again: zero rows added.
5. Show the **audit trail** at the bottom: every step is logged, the approval as the user.

## Governance (same rules as the main app)

- Nothing moves money. Everything here is read-only analysis or a draft.
- Splits are drafts until the user approves; a decision is final.
- Every state change writes an audit event (`rail_*`).
- Alerts store the parsed fields only (amount, merchant, last four digits of the account), never the raw text.
- Duplicate alerts and repeated syncs are idempotent (fingerprints).

## Honest limits

- The statement sync is a demo stand-in for a real Account Aggregator pull; the SMS and email
  inputs are pasted text, not a phone listener or a mailbox connection.
- Receipts are parsed from plain text lines; real HTML emails would need a reader in front.
- Projection is straight-line and ignores recurring bills due later in the month.
