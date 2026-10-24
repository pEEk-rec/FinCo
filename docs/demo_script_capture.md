# Capture demo: tag a payment the moment it happens

About ten minutes. Part A needs no phone and no bank: the simulator sends a pretend alert through the
real parser and the real pipeline. Part B is the real thing with your phone. Part C shows the safety
behaviour when things go wrong. Everything simulated is labelled **Simulated** wherever it appears.

## Part A: the simulator path (no phone)

1. Start the app with the real clock: `cd frontend && npm run demo:imported` (the API on 8765, the app
   on 5173). Open the printed address.
2. Open **Tag payments**. Under **Try a payment**, pick Axis Bank, "Payment to someone", ₹250,
   to "XQ9 Traders Yard", press Send.
3. A card slides in at the top right of any page: the amount, the payee, three guesses, **Other…**,
   **Later**. Press `1`, `2` or `3` on the keyboard, or tap one.
4. Send the same payee again. It is tagged for you now ("A shop you have tagged before"), with a
   one-tap **Change**. Send a payment to "Ramesh K" with a UPI handle: a person is asked every time
   until three answers in a row agree, and is never remembered like a shop.
5. Send one more and press **Later**. It waits in **Waiting for you**. After the prompt's time limit
   (36 hours by default) its best guess is applied and marked as a guess.
6. Open **Today**. Every payment in and out for the day is listed once, grouped as **Needs you**,
   **Tagged for you** (with the reason) and **Tagged by you**, with totals worked out by the backend.
   Send a credit ("Money coming in" → Priya S): it is asked what it was (salary, refund, a friend
   paying you back) and a reversal alert cancels the earlier payment in both lists and the totals.
7. Open **Connect and import → Bank link**. Read the consent in plain words, press **Set up the
   link**, then **Approve**, then **Fetch now**. This is a practice link: a simulated bank that
   posts the payments the app already heard about. The count says how many were matched to payments you
   tagged. Your label is now on the ledger row, and the dashboard spend did not change, because a
   payment is never counted twice.
8. `copilot learning show` lists how the guesses are weighted. Labels you chose teach the signals
   within bounds; simulated ones do not, unless `learn_from_simulated` is switched on for a demo.
9. `copilot eval --capture` measures all of this offline and writes `docs/eval_report_capture.md`.

## Part B: with your phone (owner task)

1. In `config/sms_senders.yaml` check each sender ID against a real alert on your phone and set
   `enabled: true` for the banks you use. (They ship switched off: nothing is read until you do.)
2. `copilot capture bridge-setup` prints the exact rule to create in MacroDroid or Tasker (or
   Shortcuts on iPhone) and creates the secret in `data/capture_secret` (git-ignored).
3. Start the API with `copilot serve --real-time`. Connect the phone with USB debugging and run
   `adb reverse tcp:8765 tcp:8765` so the phone's `localhost:8765` is your laptop. (No cable: use
   `copilot serve --real-time --lan` and `bridge-setup --lan`.)
4. Install the web app: in Chrome choose **Install app** on the laptop and **Add to home screen** on the
   phone. In **Tag payments → Notifications** press **Notify me on this device** on each one.
5. Pay a friend ₹10 by UPI. Your bank sends its alert; the rule forwards it; within a couple of
   seconds a notification appears on the laptop (and the phone) with the amount, the name and the
   guesses. Tap a guess on one device: the other clears. Pay again and ignore it: open **Today** on
   either device later and it is under **Needs you**.
6. **Tag payments → Phone bridge** shows each bank, its last alert and drift. A bank whose alerts stop
   matching its template shows a warning: the wording changed, a template needs updating.

## Part C: the failure pass

| What happens | What you see |
| --- | --- |
| Backend is down when an alert arrives | The phone's forwarder shows an error; nothing is lost silently. The payment appears in the next bank fetch and is reconciled then. |
| Phone is offline | No alerts; **Phone bridge** shows "no alert lately" and coverage health warns that the bank recorded transactions with no alert. |
| The same alert is forwarded twice | One payment (same UTR or same fingerprint). |
| Reversal after you tagged it | The payment and its reversal are both struck out of the lists and the totals; your label stays in the history. |
| An unknown bank wording | Counted as unrecognised, never guessed. The drift report names the bank. |
| An OTP message | Dropped before anything is stored, even from a listed bank. |
| A message from a stranger | Dropped before it is looked at; not even logged. |
| You revoke the bank link mid-fetch | The in-flight result is discarded and the fetched copies are deleted; the next fetch is refused. |

Evidence that each of these holds is in `tests/security/test_capture_safety_rules.py` (each rule has a test
that fails when its guard is removed) and `docs/eval_report_capture.md`.
