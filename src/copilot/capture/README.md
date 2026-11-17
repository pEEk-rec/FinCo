# capture

Tagging a payment the moment it happens, while you still remember what it was.

Statements arrive days later, when "Rs 340 to PAYTM" means nothing to anyone. Capture listens for
the bank's alert instead (forwarded from your phone, or simulated in the demo), asks you about it
right away if it needs to, and later matches it to the statement row so nothing is counted twice.

## The path one alert takes

1. **`sms_parser.py`** reads the alert using per-bank templates (`config/sms_templates/`). It checks
   the sender against the known bank senders and drops OTPs, promotions and anything it can't read
   confidently. **The raw text is never stored, logged or sent anywhere**: only the parsed amount,
   direction, counterparty and time survive.
2. **`events.py`** records the payment event and decides what to do with it, using
   **`policy.py`**: pure logic with no database, clock or network. Is this a shop FinCo already
   knows? A person? Is it quiet hours? Has today's ask budget run out? It also ranks the three best
   guesses to offer.
3. If the decision is to ask, **`push.py`** notifies your devices (Web Push) and the prompt shows
   in the app. One tap answers it.
4. **`reconcile.py`** later matches each event to its ledger transaction (by reference, then amount
   and time). When in doubt it never merges; it leaves both and says so.
5. **`learning.py`** turns each of your answers into a small update on how much each guess signal
   should be trusted. Undo takes the lesson back too.

## Also here

- **`today.py`**: the Today screen's read model (every payment today, grouped by what still
  needs you).
- **`simulator.py`**: renders a realistic alert for a chosen bank and sends it through the *real*
  parser and capture path, so the demo exercises production code.
- **`bridge.py`**, **`secret.py`**: phone-automation setup instructions and the webhook secret.
