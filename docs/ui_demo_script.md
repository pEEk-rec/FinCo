# Web UI demo script (about 7 minutes)

Everything on screen comes from the real backend. The data is synthetic and the app says so
("Demo data (synthetic)" in the sidebar). Nothing in this demo can move money: no such tool or
route exists.

## Start it

From `implementation/` (Windows PowerShell, once):

```powershell
.\.venv\Scripts\activate
pip install -e .[dev]                 # adds fastapi and uvicorn
cd frontend
npm install
npx playwright install chromium       # only needed for the browser tests
```

Every time:

```powershell
cd frontend
npm run demo                          # starts empty, so you import live
```

Open the URL it prints: `http://127.0.0.1:5173/welcome#token=demo`.
`npm run demo:imported` starts with the statements already imported (skip step 2).
`npm run demo -- --keep` keeps the previous demo database instead of resetting it.

## Walkthrough

1. **Welcome page.** One sentence on what it does and one on what it cannot do (move money).
   Click *Open the dashboard*.
2. **Empty dashboard, then import.** The empty state says what to do and shows no numbers.
   Click *Connect a bank*. Read the consent card: accounts, date range, purpose, expiry. Click
   *Approve and import*. The constellation appears: every triangle is one real transaction, and
   each settles into its category. The orange cluster is *Needs you* (the review queue). The
   summary line states the counts. "By AI: 0" is true: no language model is configured, so
   anything the rules do not recognise goes to a human.
3. **Dashboard.** "March is running *under* pace." Left to spend, the month-to-date line, the
   dashed ideal-pace line, the budget line and the forecast range. Every number is computed by
   the server.
4. **Review queue** (sidebar, *Review*). One item at a time with the reason it is uncertain.
   Press `1` to pick the first suggestion, `Enter` to confirm. The toast offers *Undo*. Press
   `S` to skip, `U` to undo the last one. "Remember for this merchant" teaches a rule.
5. **Transactions.** Open *Transactions*, click any row. The side panel shows its audited
   history. Change its category with the searchable menu. Watch the history gain an entry, then
   click *Undo* in the toast. Try *Undo* on an older change after a newer one: it is refused
   with a plain message, because the transaction changed since.
6. **Monthly review.** Pick *February 2024* and click *Generate review*. Findings, category
   changes against the previous month ("No prior month to compare" instead of an invented
   percentage), budgets, forecast, and suggestions. Open *Explain* on a suggestion to see the
   evidence and assumptions. Click *Approve*. Every number in the suggestion text was checked
   against the findings before it was shown.
7. **Agent** (sidebar). *Ask* tab: click "Send money to a friend". The agent refuses plainly.
   Click "How is my budget doing this month?" and read what it looked at.
   *Investigate* tab: click *Investigate* on a payment. Hypotheses are listed as supported or
   not, with rupee contributions and cited evidence. When nothing explains a change the screen
   says so and states how much remains unexplained.
   *What if* tab: "Spend more, Food, 2000 a month, 6 months", then *Compare with now*. The
   table shows each month's surplus with and without the change, and the goal status.
   *Goals and alerts* and *Activity*: the goal, and the audit-backed timeline of what the agent
   did.
8. **Prove it is governed (optional, 30 seconds).** `copilot audit` in another terminal lists
   every action above with actor, before and after. Editing history is refused by the database.

## If something looks wrong

* *"The FinCo service is not running"*: the API terminal exited. Run `npm run demo` again.
* *"Session token missing or expired"*: open the URL with `#token=demo` again.
* Port 8765 or 5173 busy: stop the other process; the ports are fixed on purpose.
