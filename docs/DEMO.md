# Running the demo

One story, told in order: connect the bank, watch the history arrive, then watch new payments pop
up. It takes about five minutes.

## Start it

```bash
npm run demo          # fresh database; API on :8765, web app on :5173
```

Open the address it prints. On Windows, to use it from a phone as well:

```powershell
powershell -File scripts\demo.ps1 -Reset     # wipe demo data and start both servers
powershell -File scripts\demo.ps1 -Stop      # stop them
```

The launcher prints three addresses. Do not pipe its output into another command: the servers it
starts hold the pipe open.

## The story

1. **Start empty.** The Overview says there is nothing yet.
2. **Settings, Connections.** The consent says what is read, why, for how long, and that it cannot
   move money. Press **Approve and import**.
3. **Watch the constellation.** About 180 payments fly into categories. Most are sorted by rules;
   a few go to *Needs you*.
4. **Overview.** The month is now real: spent so far, the pace curve, what is left.
5. **Live payments** (same screen). Press **Send next live payment**:
   - a new shop (Gupta Juice Centre): a card asks you,
   - Swiggy: tagged quietly, with a Change button,
   - Rahul Sharma: a person, so it always asks.
   Tick *Play one every 9 seconds* to let it run on its own.
6. **Ask.** Try "why did my food spend change this month". The steps appear live, and each figure
   was computed by a tool.
7. **Review.** Answer once for a shop and every payment from it is settled.

Everything the live feed plays is labelled *Simulated*. The history is generated from today's date
by `src/copilot/bank/demo_story.py`, so the current month is never empty.

## Real alerts from a phone

This is optional, and needs an Android phone with the free MacroDroid app.

1. **Make the app reachable over HTTPS.** Notifications and Add to Home Screen need a secure
   address. Install Tailscale on the laptop and the phone, enable HTTPS certificates, and the
   launcher publishes the app at `https://<laptop>.<tailnet>.ts.net`, reachable only from your own
   devices.
2. **Install it.** Open that address on the phone in Chrome, wait a few seconds, then Add to Home
   Screen. In Settings, Notifications, choose *Notify me on this device*.
3. **Forward bank texts.** In MacroDroid, make a macro with the trigger *SMS Received* and the
   action *HTTP Request* (POST) to `http://<laptop>:8765/api/capture/sms`, with header
   `X-Capture-Secret` set to the contents of `data/capture_secret` and body
   `{"sender":"[sms_number]","text":"[sms_message]"}`, content type `application/json`. Insert the
   two placeholders with MacroDroid's magic-text button rather than typing them.
4. **Pay.** Pay ₹1 or more by UPI. A card appears within seconds.

The webhook reads any bank-style sender (such as `VM-HDFCBK`). A phone-number sender is dropped
unread, so a test text from a friend's phone will not work unless you set the macro's sender to a
fixed name temporarily. OTPs and card mandates are never recorded, and the raw text is never
stored. To see what arrived: `Get-Content ..\.dev-cache\temp\api.err -Wait` (the launcher's log, one folder above this project).

The demo asks about every payment of ₹1 or more. The shipped default is ₹50, set in
`config/capture.yaml`; the launcher overrides it with `FINCO_MIN_ASK_PAISE=100`.

## Prove the safety claims

Import data first, then run `python scripts/prove_governance.py --db <demo database>`. It tries to
break the rules on a throwaway copy of the database and prints what happened: the planner is offered
nothing that reaches outside FinCo, no tool can move money, an audit row cannot be updated or
deleted, an agent cannot approve its own advice or revoke a consent, and money cannot be a float.

## If something goes wrong

| Symptom | Fix |
| --- | --- |
| Blank page on the phone | The servers are not running. Start the launcher again. |
| No card for a small payment | Payments under ₹50 are tagged silently by default. Use the launcher, or set `FINCO_MIN_ASK_PAISE=100`. |
| Cards work but no notification | Use the HTTPS address. Browsers allow notifications only on HTTPS. |
| "This app cannot be installed" | The tab is on the plain `http://192…` address. Open the HTTPS address, wait, reload, then install. |
| MacroDroid logs 200 but nothing appears | Check the laptop log. `Dropped (not_a_payment)` with a 13-character text means the placeholder was sent as text, not replaced. |
| MacroDroid never fires | Give it SMS permission, set battery to Unrestricted, and enable Autostart. Some phones stop background apps otherwise. |
| Start over | `powershell -File scripts\demo.ps1 -Reset` |
