# Web UI track: status

Last verified with real commands (outputs quoted in the final report, not repeated here):
backend `pytest`, frontend `tsc`, `eslint`, `prettier`, `vitest`, the three honesty gates,
`vite build`, and Playwright against the real API (10 end-to-end tests, 3 screenshot passes).

## What exists

| Area | Where |
|---|---|
| HTTP API (30 routes, bearer token, typed errors) | `src/copilot/api/` |
| New governed tools: approve and revoke consent, build monthly review | `src/copilot/tools/consents.py`, `config/policy.yaml` |
| Frontend (Vite, React, strict TypeScript, Tailwind 4) | `frontend/` |
| Generated API types | `docs/openapi.json` to `frontend/src/api/schema.d.ts` (`npm run gen:api`) |
| Tokens, contrast gate, glyph gate, no-literal-figures gate | `frontend/src/tokens`, `frontend/scripts/` |
| Screens | Welcome, Dashboard, Transactions, Review, Connect and import, Monthly review, Agent (Ask, Investigate, What if, Goals and alerts, Activity), Design |
| Tests | `tests/api/` (20), `frontend/tests/unit` (82), `frontend/tests/e2e` (10) |

## Rules kept

* Reads are read models; every write calls `execute_tool` with actor `user` (tested, with audit rows).
* No route can move money (tested). Only GET and POST exist.
* The frontend never computes a financial value; it formats integers the API returns.
* `formatINR` is the only money formatter (Indian grouping, BigInt maths, boundary-tested).
* Percent display refuses values outside a sanity range and shows "No prior month to compare".
* No literal figures in app code (a script scans `frontend/src`; a seeded violation proves it can fail).
* Contrast: 55 of 55 token pairs pass WCAG AA. Axe reports no serious issues on the tested screens.

## Bugs the browser tests found in the existing backend (fixed)

1. A correction in the review queue left the item in the queue (`needs_review` was not cleared). Fixed, undo restores it, regression-tested.
2. Any uncategorised spend crashed monthly review generation (sorting `None` with strings).
3. Approving an already-decided suggestion raised an internal error (a nonexistent error code); it now returns a typed 422.
4. Advice templates existed only for category spend; the other kinds rendered "You had a ... finding". Templates added, numbers still validated against findings.
5. Request connections were opened and closed on different worker threads.

## Deviations from PLAN_UI.md (decided, not hidden)

* **Design gate:** the plan asks for owner approval of the dashboard before continuing. The owner asked for the whole demo in one pass with no approvals, so the screens were built together; the screenshots are in `frontend/.shots/` for review.
* **No git actions** were run, including the three planned checkpoint commits.
* **Dark theme, calendar tab, per-signal alert breakdown, print stylesheet polish** are not built. The Monthly review has a basic print button.
* **Ask** shows the tools the agent ran and their real results, not its generated prose: the Phase 2 synthesis text was still being finished and gave wrong sentences ("current spend of ₹0"), so it is not displayed. Investigations and what-ifs call the real tools directly.
* **TypeScript 5.9.3, not 7:** `typescript-eslint` and `openapi-typescript` do not support 7 yet.
* **Pace chart** sums budgeted categories only; the forecast band is the Phase 1 run-rate with a fixed plus or minus 20 percent on variable spend, labelled as such.

## Known limits

* The demo clock is fixed at 18 March 2024 so the synthetic data lines up. `ApiState.clock = None` uses the real clock.
* No language model is configured: uncategorisable merchants go to the review queue and "By AI" reads 0.
* The constellation draws up to 1500 particles and says so when it caps.
* Alerts are empty in the demo data because nothing crosses an alert threshold.
