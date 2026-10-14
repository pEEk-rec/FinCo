# Live mode: your real data in the same app

Live mode runs the **same frontend and the same API** on your own data. It is a separate set of
processes with a separate database, so the mocked demo (`npm run demo`) is untouched and can run
at the same time.

| | Demo | Live |
|---|---|---|
| Start | `npm run demo` | `npm run live` |
| API / web ports | 8765 / 5173 | 8200 / 5273 |
| Database | `frontend/.demo/demo.db` (synthetic) | `frontend/.demo/live.db` (yours, git-ignored) |
| Clock | fixed demo date | real time |
| Language model | on if keys exist | **off** unless you pass `--llm` |
| Extra screen | none | **Live data** |

Budgets for live mode come from `config/live.yaml`. Edit them, then restart.

## What works with real data today

1. **Statement import (CSV).** Download your statement from net banking, open **Live data**,
   choose the file. Reads HDFC-style (separate debit and credit columns), single amount with Dr/Cr,
   account details above the header, and common date formats. Rows are categorised by the existing
   rules; unknown merchants go to **Review**. Importing an overlapping statement adds nothing.
   Rows that cannot be read are listed with their line number, never guessed.
2. **Phone alerts (SMS webhook).** Install an Android SMS-forwarder app and point it at
   `POST http://<your computer>:8200/api/live/webhook/sms` with the header
   `X-Webhook-Secret: <secret shown on the Live data screen>` and JSON `{"text": "<sms>"}`
   (a `message`/`body` field, form data or plain text also work). Start with
   `npm run live -- --lan` so the phone on your Wi-Fi can reach it. Each alert becomes a pending
   payment and the budgets react; when a statement arrives, matching alerts become verified and are
   never counted twice. OTPs, mandates and failed payments are ignored.
3. **Receipts.** Paste receipt text on the Live data screen; a category split is drafted and waits
   for your approval.
4. **Everything else in the app** (dashboard, transactions, review, monthly review, Ask agent,
   what-if, anomalies) works on the imported rows because they use the same tables.

## Account Aggregator (consent flow)

The consent, data-session and data-fetch flow for an AA gateway is implemented
(`src/copilot/live/aa.py`) and tested against a local fake gateway. To enable it, set:

```
AA_BASE_URL=...           AA_CLIENT_ID=...
AA_CLIENT_SECRET=...      AA_PRODUCT_INSTANCE_ID=...
```

**Honest status.** It has not been run against a real gateway: that needs credentials from an AA
provider (for example Setu's sandbox, see https://docs.setu.co/data/account-aggregator). A sandbox
returns test data, not your bank's. Pulling your own bank's data through AA in production needs an
RBI-registered FIU or a licensed provider. Endpoint paths and header names are configurable in
`AAConfig`, so a difference from the provider's current API is a small change.

## Privacy and safety

- Everything stays in `live.db` on your computer. It is git-ignored; do not copy it elsewhere.
- Raw statement narrations are kept locally; audit events record counts only.
- The model is off in live mode. With `--llm`, prompts are redacted and the answer step only
  receives computed figures, not statement lines.
- All routes need the session token printed by `npm run live`. The SMS webhook has its own secret.
- Nothing here moves money. It is read-only analysis and drafts.
- Use `--lan` only on a network you trust; the webhook is then reachable from it.

## Not built

- PDF statements (CSV only).
- A real e-mail connection (receipts are pasted).
- Auto-forwarding on iOS (it does not allow reading SMS).
