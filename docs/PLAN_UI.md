# PLAN_UI.md: Web UI for the Personal Finance & Budgeting Copilot

Project: Personal Finance & Budgeting Copilot (working product name: **FinCo**)
Scope of this file: the **web UI track** and the thin **HTTP API** it needs. It is not a numbered roadmap phase. It pulls the "Web Dashboard" part of roadmap Phase 6 forward. Conversational finance, messaging channels and proactive delivery stay in Phase 6.
Owner and only contributor: the user (repo owner).

Read this whole file first. Then read `docs/PLAN_PHASE1.md`, `docs/PLAN_PHASE2.md`, `docs/decisions.md`, `STATUS.md`, and the reference material in `D:\Academics\7thSEM\AgenticAI\FinCo\implementation\ui_SS` (the owner's saved screenshots and the two `DESIGN_*.md` style references). The backend rules (governance choke point, audit, integer paise, no money movement) still apply to everything here. The UI is a **view layer**: it never computes financial truth and never bypasses `execute_tool`.

**Precondition:** Phase 2 is complete and its cleanup sweep is done (the owner will say so). The API contract is built from the real Phase 1 and Phase 2 services; if a name in this file differs from the real code, the real code wins and the mapping goes in `docs/ui_alignment.md`.

---

## 0. Rules for the implementing agent

### 0.1 Work mode: autonomous, inside gates
Work through the stages in section 7 in order. For every stage: write the goal and the files you will touch at the top of its `STATUS.md` entry; build in small steps; a stage is done only when its **Done when** is met and the full backend suite, frontend tests and lint pass; append the explain-back entry (0.5); continue.

**Hard gates: stop and wait for the owner**
- Any git action (0.3).
- Any dependency not listed in section 3.
- Anything that costs money, signs up for a service, or deploys.
- Deleting or overwriting anything outside this repository.
- A failing test or lint error you cannot fix after an honest attempt. Never weaken, skip or delete a test.
- A change that would break a backend contract (executor choke point, audit triggers, integer paise, `user_id` on every table, no money movement).
- **The visual design gate after Stage U3** (section 7). Taste cannot be unit-tested. After the dashboard is built and screenshotted, stop and wait for the owner's visual approval before building the remaining screens. If the owner is away, continue only with Stages that do not depend on look (U4's data wiring, tests) and say so in `STATUS.md`.

**Soft gates: decide, record in `docs/open_questions.md`, continue**
- A product or design decision this plan does not cover: take the most conservative, plainest option.
- A small unrelated issue: one line in `docs/known_issues.md`, keep going.
- A font or icon is missing a glyph (see 2.3): use the fallback and record it.

### 0.2 Code rules
- TypeScript strict mode, no `any`, no `@ts-ignore` without a comment explaining why.
- Backend additions follow the same rules as before: short functions, type hints, docstrings, `Decimal` for intermediate maths, integer paise.
- **The frontend never computes a financial value.** Allowed: formatting, sorting and grouping for display, pixel scaling, animating between two values the API provided. Not allowed: summing amounts, computing percentages, deltas, forecasts, budget status, "left to spend", goal status. If a screen needs a number, the API returns it.
- **Every figure on screen comes from a typed API field.** See section 4 (data honesty).
- Every write goes through the API to `execute_tool` with `actor = "user"`. The UI cannot call any tool the planner is forbidden to select on behalf of the agent, and it cannot reach any tool that does not exist (there is no money movement anywhere).
- Windows-safe: the owner develops on Windows with Python 3.11. Use `pathlib`, cross-platform npm scripts (no `rm -rf`, no bash-only syntax), UTF-8 everywhere (the ₹ sign must round-trip).
- Never claim something works unless you ran it. Pin exact versions. Before using Tailwind, Motion, Radix or FastAPI APIs, check the current official docs for the installed version.

### 0.3 Git rules (strict, three commits for the whole UI track)
- Every git action needs the owner's explicit approval **first, every single time**: `add`, `commit`, `push`, `branch`, `tag`, `stash`, `merge`, `rebase`, remotes, config changes. Earlier approval never carries over.
- **Three commits only**, at `[GIT CHECKPOINT A]` (after U2), `[GIT CHECKPOINT B]` (after U6), `[GIT CHECKPOINT C]` (after U10). Between checkpoints run **no git commands at all**.
- At each checkpoint: make sure everything passes, then write the proposed commit message and exact file list into "Proposed commits (awaiting approval)" in `STATUS.md`. Do not commit. The owner approves, edits or declines. Push is a separate question: name the one branch and the remote.
- Commits are authored only by the owner's existing git identity. Never change `user.name` or `user.email`.
- **No AI attribution anywhere:** no `Co-Authored-By`, no "Generated with ..." lines, no session links, in commits, docs, code comments, README or the app itself.
- Messages: short, plain English, imperative, under about 70 characters. Suggested: A `Add HTTP API and design system`, B `Add dashboard, transactions, review and import flows`, C `Add monthly review, agent screens and polish`.
- Never commit `.env`, the database, `reports/`, `node_modules`, build output, screenshots under `frontend/.shots/`, or generated data.

### 0.4 STATUS.md report (newest first)
```
## Current state
Last completed stage: <N> | Blockers: <list or "none"> | Design gate: <pending / approved>

## Stage N: <name>: DONE / BLOCKED / IN PROGRESS
Goal: <2 to 3 lines>
Built: <2 to 5 bullets>
Files: <list>
Tests: backend <passed/total> | frontend <passed/total> | e2e <passed/total> | Lint: <pass/fail>
Evidence: <the real last lines of pytest, vitest, playwright and the linters, pasted>
Screenshots: <paths under frontend/.shots/ produced this stage>
Defaults chosen (open_questions.md): <list or "none">

## Proposed commits (awaiting approval)
1. <message>: <files>
```

### 0.5 Explain-back
After each stage append 4 to 8 lines to `docs/decisions.md`: what was built, why this design, what it deliberately does not do, one examiner question with its answer.

### 0.6 Honesty and quality rules
1. **Test the real path.** API tests go through the FastAPI test client into `execute_tool`, and audit assertions are made on that path.
2. **Same names everywhere.** The TypeScript API types are **generated** from the backend OpenAPI schema (a script, run in CI and before every build). Hand-written duplicates of API types are forbidden. This exists because an input-name mismatch between a UI caller and a tool is exactly the bug class that slips through.
3. **Boundary tests, both sides**, for every formatter and every threshold-driven display rule.
4. **Docs state only what tests prove.** No marketing words in docs or in the app.
5. **Reports quote real output.** Never write a number you did not read from a command.
6. **Look at what you built.** For every screen state, take real screenshots (section 6.3) and read them. "It compiles" is not a visual check.

---

## 1. Goal

> A professional, calm, fast web app over the existing agent: the user sees their real month, corrects a category and watches the numbers move, triages low-confidence items, reads a monthly review, asks the agent a question, and sees exactly why it answered as it did. It must look like a designed product, not a generated template. Every number is real.

### 1.1 Decisions already made (do not re-open)
| Decision | Choice |
|---|---|
| Theme | **Light** first. Dark theme is out of scope for now, but all colours are tokens so it can be added |
| Quality bar | "Visually appealing, professional, not AI-generated looking, nothing broken" |
| Data | No mock numbers anywhere in the UI (section 4) |
| Streamlit | The Phase 1 Streamlit view stays as a fallback; this UI replaces it for the demo |
| Backend | The Phase 1 and Phase 2 services, unchanged, behind a thin HTTP API |
| Language | English UI; all strings in one catalogue file so translation is a data task later |

### 1.2 What the UI is not
Not an investment app (no tickers, portfolios, crypto, net-worth charts, benchmarks), not a bank (no money movement), not a chat toy, not a landing-page-only site.

---

## 2. Design direction

### 2.1 What we take from the references
The owner saved screenshots of Copilot Money's web app and Origin's app, and two `DESIGN_*.md` extractions (Origin's marketing site, Dala's marketing site). Both style files describe **dark marketing sites**; we build a **light data app**. We translate principles, not pixels, and we do not copy any brand's assets, copy or layout wholesale.

| Source | Take | Leave |
|---|---|---|
| Copilot (app screenshots) | Three-pane transactions: list + persistent detail panel; date-grouped rows; category pill; budget card with an ideal-pace line and an "under/over pace" callout; "Transactions to review" card with a calm zero state; "Next two weeks" recurring list; category rows with progress bars; time-range chips | Investments, net worth, crypto, benchmarks; rainbow category colours; tiny dense type; "999%" style badges |
| Origin (app screenshots) | Warm off-white canvas with white cards and hairline borders; small uppercase mono section labels; serif headlines; "Ask anything" pinned at the bottom of the sidebar; a small spark button on a card that opens an explanation; calendar month grid with daily totals; dismissible recap cards in a side rail; "apply to all future months" style explicit toggles | Equity/brokerage/tax/estate services; promo and tax-filing cards; negative-savings empty state |
| Origin DESIGN.md | Three typographic voices (light serif for words, sans for interface, mono uppercase for labels and data tags); flat elevation by surface steps instead of shadows; one high-contrast primary action; restraint with colour | Dark canvas; full-bleed chromatic marketing tiles; 96px display type inside app screens |
| Dala DESIGN.md | Scale and tracking, not weight, make hierarchy; generous space; a single primary action per view; **the animated particle constellation as the signature motion** (reinterpreted functionally, 2.6) | Pure black void, "no cards, no borders" (a data app needs structure); weight 200 body text (illegible on light); violet as the product's main colour |

### 2.2 Principles
1. **Calm ledger.** Quiet surfaces, hairline structure, one accent per meaning, space used to separate meaning.
2. **Findings first, words second.** Screens lead with the number and its context, then the sentence. Headlines are rendered from API `headline` text built from validated findings; the frontend never composes financial sentences.
3. **Cause and effect are animated.** Motion exists to show that one thing caused another (a correction moves a budget bar; a category assignment moves a particle). Never decoration.
4. **Uncertainty is a design element.** Source badges, confidence, "not enough data yet", "inconclusive" are first-class, well-designed states, not error screens.
5. **Reversible by default.** Every change shows an Undo within reach.
6. **One accent colour has one job** (2.4).

### 2.3 Typography
Three voices, all self-hosted (privacy: no runtime calls to font CDNs). Proposed families, to be confirmed in Stage U0 by a glyph test:
| Voice | Use | Proposal | Fallbacks |
|---|---|---|---|
| Serif, light | Page headlines, review narration, large editorial statements. Weight 300 only at 24px and above; italic for one emphasised word at most | Newsreader (variable, optical size) | Source Serif 4, Georgia |
| Sans | All interface text, table cells, numbers (with `font-variant-numeric: tabular-nums`) | Geist or Inter Tight | Inter, system-ui |
| Mono, uppercase | Section labels, badges, data tags, 11 to 12px, tracking 0.06 to 0.1em | Geist Mono or JetBrains Mono | ui-monospace |

**Glyph test (Stage U0, mandatory):** render `₹ 1,23,45,678.90 ⌀ → ↗ ↘ · – −` in every chosen family, weight and tabular setting, and confirm the ₹ sign (U+20B9) and tabular figures exist. If a family lacks ₹, change the family or use a metric-matched fallback for that glyph only. Record the result in `docs/decisions.md`.

Scale (px / line-height / weight): display 56 to 72 / 1.0 / 300 serif, tracking -0.02em (landing and monthly-review title only); h1 32 / 1.15 / 300 serif; h2 20 / 1.3 / 500 sans; body 15 / 1.5 / 400; small 13 / 1.45 / 400; mono label 11 / 1.4 / 500 uppercase; hero figure 48 / 1.0 / 300 sans tabular; table cell 14 / 1.4 / 400 tabular. **Weight floor on light backgrounds: body text never below 400.**

### 2.4 Colour (all tokens in one file; no raw hex in components)
Proposed light tokens (values are starting points; Stage U0's contrast script is the authority):
| Token | Proposal | Role |
|---|---|---|
| `canvas` | #F6F5F1 | App background (warm, not white) |
| `surface` | #FFFFFF | Cards, panels |
| `surface-sunken` | #EFEDE7 | Wells, table headers, input fills |
| `hairline` / `hairline-strong` | #E4E1D8 / #CFCBC0 | Borders and dividers (structure instead of shadows) |
| `ink` | #121413 | Primary text and the **only filled primary button** |
| `ink-2` / `ink-3` | #4D514D / #6E726D | Secondary and tertiary text |
| `positive` | #0F6B53 (tint #E3F1EC) | On track, income, under pace |
| `attention` | #A16207 (tint #FBF1DC) | Approaching limit, needs review |
| `negative` | #B4382A (tint #FBE8E4) | Exceeded, failed, destructive |
| `agent` | #5B47D6 (tint #ECE8FD) | **Reserved for the agent**: AI-derived labels, Ask, investigations, the constellation. Nowhere else |

Colour semantics are strict: ink = action, green = good, amber = attention, brick = over, violet = agent. Violet is deliberately not the general brand colour (it is the default of generated fintech templates).

Categories: a defined palette of about 12 muted hues, used only for category identity (pill = tinted background + dark text of the same hue; chart series; particles). Every pair is validated for contrast and for colour-blind distinguishability; never rely on colour alone (always a text label).

Radius: 8 for buttons and inputs, 14 for cards, 999 for chips only. Elevation: flat. Menus and popovers get a hairline plus one soft shadow (`0 8px 24px rgba(18,20,19,0.08)`). Cards never carry shadows. No gradients on surfaces, buttons or text. No blur or glass effects.

### 2.5 Motion
Tokens: `fast 150ms`, `base 240ms`, `slow 600ms`, `chart 900ms`; easing `cubic-bezier(0.2, 0.7, 0.2, 1)`; list reorders use a spring with no visible overshoot. Required behaviours:
- **Number ticker:** when an API value changes after a user action, digits roll or crossfade to the new value over ~500ms; initial load does not animate.
- **Shared-element continuity:** selecting a transaction row slides the detail panel in; the selected row keeps its highlight; list reflows animate.
- **Chart draw-in** on first paint (once per session per chart), then value changes morph in place.
- **Correction cascade:** the new category pill, then the affected budget bars and the pace line, update in a short staggered sequence (the visible proof that corrections propagate), followed by a toast with Undo.
- Hover/focus: 150ms colour and opacity only. No parallax, no bounce, no autoplay carousels.
- `prefers-reduced-motion`: replace all movement with instant or crossfade changes; the constellation renders its final static layout.

### 2.6 The constellation (signature motion, functional not decorative)
Reinterpret Dala's particle field as a **live picture of the real categorisation pipeline.** Each particle is a real transaction.
- **Look:** small outlined triangles, 1 to 1.5px stroke, in the category palette. Unassigned particles are neutral grey and drift slowly.
- **Behaviour (import and categorisation screen):** as the pipeline reports progress, particles move along eased paths to their category's cluster and take its hue. Rule-matched particles settle first; AI-assigned ones settle with a faint violet ring; low-confidence ones stop at the cluster edge, hollow, and a count appears on the "Needs you" cluster. That cluster is the review queue.
- **Data truth:** the particle count equals the real fetched count up to a rendering cap; when capped, say so in plain words ("Showing 1,500 of 4,210"). Assignments come from the actual batch result events, never from a canned loop. If real data is unavailable, render a static, clearly empty state, not a fake animation.
- **Other uses (sparingly):** a small (about 120px) "agent is working" indicator beside Ask while a task runs; an ambient, number-free hero on the welcome page. **Never** on the dashboard, transactions or tables.
- **Performance rules:** Canvas 2D (WebGL only if Canvas 2D misses budget); device pixel ratio capped at 2; pause when the tab is hidden or the canvas is offscreen; target 60fps on a mid laptop; main-thread budget per frame under 6ms; reduced-motion shows the final static layout.

### 2.7 Iconography and imagery
One icon family (proposal: Phosphor, light or regular weight, 1.5px stroke), used with restraint: navigation, actions, and status. No emoji. No icons inside coloured circles on every card. No stock photography, illustrations of cartoon characters, 3D renders or device mockups. The only imagery is data and the constellation.

### 2.8 Copy
Plain, specific, sentence case, no exclamation marks, no emoji, no "Oops", no "Supercharge/Unlock/Seamless/Powerful". Say what happened and what the user can do. Examples: "No transactions yet. Connect a bank to import your statements." "Not enough history to forecast this month: needs 7 days, has 3." "Undo blocked: this transaction changed after that action." All strings live in `frontend/src/copy/en.ts`.

---

## 3. Stack

Backend (new, thin): `fastapi`, `uvicorn`, `httpx` (for the test client). Everything else already exists.
Frontend: `react`, `react-dom`, `react-router`, `typescript`, `vite`, `tailwindcss` (v4), `@radix-ui/*` headless primitives (only the ones used), `@tanstack/react-query`, `motion`, `d3-scale`, `d3-shape`, `d3-array` (charts are hand-built SVG; no chart-library defaults), `@phosphor-icons/react`, self-hosted fonts (via `@fontsource*` packages or downloaded files, SIL OFL), `openapi-typescript` (generated API types), `vitest`, `@testing-library/react`, `@playwright/test`, `@axe-core/playwright`, `eslint`, `prettier`.

The owner's handing over of this file approves this list. Anything else is a hard gate. Component primitives from Radix are **restyled completely**; default shadcn/Radix looks are forbidden (see section 5).

---

## 4. Data honesty ("no mock numbers")

1. **Zero hardcoded figures.** No currency amount, percentage, count or date literal in any component, story, route, copy file or CSS content. Test fixtures live only under `frontend/tests/` and are never imported by app code. A script `scripts/check_no_literal_figures` scans `frontend/src` (excluding `tests`) for currency symbols next to digits and for numeric literals in JSX text, and fails CI.
2. **One formatter.** `formatINR(paise: number, opts)` in `frontend/src/format/money.ts` is the only way to render money. Indian grouping (1,23,456.78 and lakh/crore words only where the copy file allows), correct negatives, zero, rounding half up to paise, no floats, thousands of unit tests including both sides of every grouping boundary. Compact forms ("₹1.2L") only on chart axes.
3. **Percent and change guards.** A percent or "change vs last month" is displayed only when the API returns it. When the baseline is missing, zero or below the API's minimum, the API returns `null` with a reason, and the UI shows a designed "no prior month" state. A value like 999% can never be produced because the UI does not compute it, and a test asserts any received percent above the API's sanity cap renders as the "not comparable" state.
4. **Insufficient data is a state.** Every chart and card has a designed insufficient-data variant that states what is missing ("needs 7 days, has 3").
5. **Empty API test.** For every screen, mount with an empty API and assert there are no digits on the page other than those inside labels, dates the user chose, or the UI chrome.
6. **Demo data is labelled.** The mock connector's data is synthetic. When the API reports `data_source = "synthetic_demo"`, a small persistent tag says "Demo data (synthetic)". The app never presents synthetic numbers as real. No fake testimonials, user counts, logos, awards or statistics anywhere, including the welcome page.
7. **Failure is visible.** A failed request shows a designed error state with a retry and the error code; it never falls back to stale or invented values.

---

## 5. "Not AI-generated" acceptance checklist

A screen is rejected if any of these is true:
- Gradient backgrounds, gradient text, glowing blobs, or a purple-to-blue gradient anywhere
- Glassmorphism or blur surfaces
- Emoji used as icons or decoration; an icon in a coloured circle on every card
- A uniform grid of identically sized, identically shadowed cards; everything centred
- Default shadcn/Radix/Tailwind look: default radii, default focus rings, default grey scale, default component spacing
- Three or more font sizes inside one small card; numbers without tabular figures; misaligned decimals in columns
- Generic hero copy ("Take control of your finances"), greetings with emoji, exclamation marks
- Placeholder text, lorem ipsum, fake numbers, "$" signs, US date formats
- Motion that does not explain cause and effect (bouncing, floating, looping decoration)
- Cartoon empty-state illustrations
- Colour used without meaning (violet outside the agent surfaces, green for decoration)

Required traits: a visible 4px baseline grid; hairline structure; consistent card padding; one primary action per view; generous negative space around the hero figure; left-aligned asymmetric layouts; specific, plain copy; every state designed (loading skeleton, empty, error, insufficient data, partial, populated).

---

## 6. Architecture

### 6.1 HTTP API (`src/copilot/api/`)
- FastAPI app started by `copilot serve` (localhost only, default port from config). Single local user per the on-device privacy principle; a per-session bearer token printed by `copilot serve` and required on every request; CORS limited to the dev origin; no request or response bodies in logs; log counts and codes only.
- Routers by domain, each handler a thin call into the existing service layer; **every write calls `execute_tool` with an `ExecutionContext(actor="user")`**; typed error mapping (`ToolFailure` and error codes to HTTP status plus a stable `code` field); OpenAPI schema exported to `docs/openapi.json` and used to generate `frontend/src/api/schema.d.ts`.
- Read models return exactly what screens need, with all derived numbers computed server side: dashboard (budget pace series, forecast band, left-to-spend, pace delta, headline text, review count, upcoming recurring, top categories, open alerts), transactions (filters, grouping keys, pagination, per-row source/confidence/needs_review), transaction detail (history, audit entries, undoability), review queue, budgets, forecast, recurring, anomalies, monthly review (versions), advice and recommendations (with explanation fields), goals, alerts, investigations, simulations, timeline, consents and ingestion batches (including progress events for the constellation: server-sent events or polling, whichever the real code supports), agent tasks (`ask` with clarification and approval interrupts).
- Endpoint names follow the real service names; record the mapping in `docs/ui_alignment.md`.
- Tests: every route with the FastAPI test client; writes asserted through to `audit_events`; user isolation; error mapping; OpenAPI snapshot test; a test that generated TS types are up to date.

### 6.2 Frontend structure
`frontend/` (Vite + React + TS strict): `src/api` (generated types, typed client, query hooks), `src/format`, `src/copy`, `src/tokens` (the single token source feeding CSS variables and Tailwind theme), `src/components` (system), `src/screens`, `src/motion`, `src/charts`, `src/constellation`, `tests`. Routing with `react-router`; server state with TanStack Query (optimistic updates only where the API result is certain; otherwise wait for the API and animate the change). No global client-side financial state.

### 6.3 Verification loop (every screen, every stage)
`npm run shots` runs Playwright against a seeded backend (the real Phase 1 seed through the real pipeline) and saves screenshots to `frontend/.shots/<screen>/<state>-<viewport>.png` for viewports 1440x900, 1024x768 and 390x844 and states: loading, empty, populated, insufficient-data, error. After building a screen the agent **opens the screenshots, checks them against section 5 and the reference images in `docs/design/refs/`, writes down concrete deviations, fixes them, and re-shoots.** At least two review iterations per screen are expected. Record the final list of checks and any accepted deviations in `STATUS.md`.

---

## 7. Stages

### Stage U0: Align and foundations
**Goal:** a verified base: real-code alignment, scaffold, tokens, formatter, honesty tooling.
**Build:** read the backend; write `docs/ui_alignment.md` (service and tool names, gaps). Scaffold `frontend/` (Vite, React, TS strict, Tailwind v4, ESLint, Prettier, Vitest, Playwright). Self-host fonts and run the **glyph test** (2.3). Implement `src/tokens` and a **contrast script** that computes WCAG ratios for every text/background token pair used and fails below AA (4.5:1 normal text, 3:1 large text and UI components); adjust token values until it passes. Implement `formatINR` with exhaustive tests. Add `scripts/check_no_literal_figures`. Build a `/design` route (kitchen sink) that renders tokens, type scale and states.
**Tests:** formatter tables (lakh/crore grouping, negative, zero, paise rounding, very large); contrast script passes; no-literal-figures script passes and also fails on a seeded violation (prove it can fail).
**Done when:** all green; `/design` route screenshots reviewed.

### Stage U1: HTTP API
**Goal:** the thin, typed, governed API (6.1).
**Build:** as 6.1, including `copilot serve`, token auth, error mapping, OpenAPI export, TS type generation script.
**Tests:** route tests through the executor; audit rows present on the real path; isolation; error codes; snapshot of the OpenAPI schema; generated types match. Extend the no-money-movement test to the API: no route can pay, transfer, trade, withdraw or deposit.
**Done when:** backend suite green; API reachable from the frontend dev server.

### Stage U2: Design system components
**Goal:** the component library and primitives, matching sections 2 and 5.
**Build:** app shell (sidebar with Ask pinned at the bottom, top bar, content frame), Button (ink primary, quiet secondary, text), Input, Select, Toggle, Chip, Badge (source: user / rule / AI with violet tint for AI; confidence), CategoryPill, Card, Stat, List row, DetailPanel, Toast with Undo, Skeleton, EmptyState, ErrorState, InsufficientDataState, Tooltip, Dialog, Menu; chart primitives (PaceChart with limit line, ideal-pace line, actual line, forecast band; BarList with progress; Sparkline; calendar month grid); motion primitives (NumberTicker, animated list, panel slide); the standalone `Constellation` component driven by a typed particle spec. Every component has all states in `/design`.
**Tests:** component tests; keyboard and focus behaviour; reduced-motion behaviour; axe checks on `/design`; Constellation performance smoke test with a particle cap; screenshots reviewed against section 5.
**Done when:** green; `/design` reviewed.
**[GIT CHECKPOINT A]** record `Add HTTP API and design system`.

### Stage U3: Dashboard (then the design gate)
**Goal:** the first real screen, the one everything else inherits from.
**Build:** see 8.1. Real data from the seeded backend.
**Tests:** empty-API, insufficient-data, error and populated states; no-literal-figures; screenshot set in all viewports.
**Design gate:** stop. Produce the full screenshot set and ask the owner for visual approval. Record approval in `STATUS.md` before continuing screens.

### Stage U4: Transactions, correction and undo
**Goal:** the core "correct it and watch it propagate" flow. See 8.2.
**Tests:** correction updates list, detail, budget bars and pace line (through the API); remember-rule; undo and the blocked-undo message; keyboard path; audit entries visible; e2e on the real backend.

### Stage U5: Review queue
**Goal:** fast triage of low-confidence items. See 8.3. **Tests:** keyboard flow, queue count updates, undo, empty state, e2e.

### Stage U6: Connect, consent and import with the constellation
**Goal:** the consent lifecycle and the live categorisation picture. See 8.4. **Tests:** consent states (pending, active, expired, revoked), failure states, progress driven by real events, reduced-motion static layout, performance budget.
**[GIT CHECKPOINT B]** record `Add dashboard, transactions, review and import flows`.

### Stage U7: Monthly review and advice approvals
**Goal:** the editorial headline screen. See 8.5. **Tests:** versions, approve/reject, explanation view, partial month, print stylesheet.

### Stage U8: Agent surface
**Goal:** Ask, investigation, what-if, goals, alerts, timeline, explanations. See 8.6. **Tests:** clarification flow, approval interrupts, inconclusive state, simulation comparison, alert preferences, timeline ordering, refusals shown plainly.

### Stage U9: Welcome page and responsive pass
**Goal:** a restrained entry page and mobile/tablet behaviour. See 8.7. **Tests:** screenshots at three viewports for every screen; no horizontal scroll at 390px for dashboard, review queue and Ask.

### Stage U10: Hardening and documentation
**Goal:** finish. **Build:** accessibility pass (axe on every screen, full keyboard navigation, visible focus, WCAG AA contrast), performance pass (bundle budget, first paint, constellation frame time), failure handling (backend down, token expired, slow API, partial data), empty-API sweep across all screens, e2e demo path, README for running API + frontend, `docs/ui_demo_script.md`, final screenshot set, update `docs/decisions.md`, `STATUS.md`, and clear `known_issues.md` of defects.
**E2E demo path (Playwright, real backend, seeded):** open app, connect consent, watch import, triage review queue, correct with remember, see budget and pace line move, undo, open monthly review, ask "why did my food spend jump?", read the investigation with evidence and confidence, run a what-if, see an alert with its explanation, approve a recommendation, open the timeline.
**Done when:** section 9 checklist all green.
**[GIT CHECKPOINT C]** record `Add monthly review, agent screens and polish`.

---

## 8. Screen specifications

All screens: desktop-first (1280 and up), fluid down to 1024, adapted for 390 where stated. Every screen has loading, empty, error, partial and insufficient-data variants.

### 8.1 Dashboard
- **Headline** in serif 300 from the API `headline` field (a validated finding sentence such as "September is running under pace"), with one italic word at most. No greeting.
- **Budget pace card (largest):** hero figure "left to spend" (sans 300, tabular, from the API), the month-to-date line, the dashed ideal-pace line, the budget limit, the **forecast band** (low to high, from forecast v2, drawn at low opacity, labelled with its confidence) and an under/over-pace callout chip. If the API says the forecast is `insufficient_data`, draw only actual and limit and state what is missing.
- **Needs your review card:** count and the top items, button to the queue; calm zero state.
- **Next two weeks:** recurring payments from `recurring_series` with amount ranges when the series varies.
- **Top categories:** rows with spend, limit and a thin progress bar (green, amber, brick by API status; never computed in the UI).
- **Alerts rail (right):** open alerts with severity and a one-line "why"; dismiss and snooze. Quiet when there are none.
- **Ask bar** persistent in the sidebar; opens the agent surface.
- Time-range chips only where the API supports ranges. Persistent "Demo data (synthetic)" tag when applicable.

### 8.2 Transactions
- Three panes: filters/accounts left (collapsible), grouped list (date headers, 48 to 52px rows), detail panel right.
- Row: merchant, account, category pill, **source badge** (user / rule / AI) and confidence for AI rows, amount (tabular, right-aligned, credits in positive ink, never red for debits).
- Detail: category (change with a searchable menu), "Remember for this merchant" toggle (creates the merchant override), recurring link, duplicate and transfer flags with explanations, notes, **history and audit entries** with before/after, and **Undo** with the plain blocked message when undo is refused.
- Correction cascade (2.5), then a toast with Undo. Filters: month, category, needs review, source. Search.

### 8.3 Review queue
- One item at a time with context (merchant normalized, amount, date, similar past items and their categories, why it is uncertain: "confidence 0.62, no rule matched").
- Keyboard-first: number keys pick a suggested category, Enter confirms, S skips, U undoes, J/K move. Mouse works equally.
- Progress and remaining count; completion state is a short calm summary, not confetti.

### 8.4 Connect, consent and import
- Consent screen: who/what is shared (accounts, date range, purpose), expiry date, revoke control; states pending, active, expired, revoked.
- Import screen: the constellation (2.6) with a plain-text status line and a count summary when finished ("Categorised by rule, by AI, needs you"); failures (timeout, partial data, malformed rows) shown as typed, readable states with retry.

### 8.5 Monthly review
- Editorial layout: serif headline, a short findings summary, category change vs previous month (API-provided deltas, `null`-safe), budget status, recurring, anomalies, forecast, data-quality notes (review queue size, duplicates found, missing days), draft advice with **Approve / Reject** and an "Explain" disclosure (evidence, calculations, assumptions, tools used, memories, simulation). Version switcher (v1, v2...). Print-friendly stylesheet. Calendar grid view of daily spend as a secondary tab.

### 8.6 Agent surface
- **Ask:** one input; answers render as a structured result, not a chat bubble stream: headline, evidence list, confidence label, then the explanation disclosure. One clarifying question at most, as a designed inline prompt. Refusals are shown plainly with what the agent can do instead.
- **Investigation view:** hypotheses tested, supported or contradicted, contribution in rupees from the API, unexplained residual, outcome and confidence. **Inconclusive is a designed, dignified state** ("Could not determine a cause. ₹X remains unexplained"), never an error.
- **What-if:** scenario builder (amount, category, one-off or recurring, months) and side-by-side comparison with the baseline; goal status changes highlighted.
- **Goals:** list with required monthly amount and status (on track, at risk, off track, unknown) from the API.
- **Alerts:** list, why-breakdown by signal, preferences (mute, minimum severity).
- **Timeline:** chronological agent activity, pending approvals pinned at the top, filter by task or run; JSON-schema-stable data from the API.
- Agent surfaces are where violet lives.

### 8.7 Welcome page and responsive
- A restrained entry page: serif display headline in the product's own words, one primary action, the ambient constellation (no numbers), a short honest explanation of what the product does and does not do (no money movement, nothing leaves the device unredacted). **No statistics, testimonials, logos or awards.**
- Responsive: dashboard, review queue and Ask must work at 390px; transactions collapses to list plus full-screen detail.

---

## 9. Exit checklist

- [ ] Backend suite, frontend tests, e2e and all linters green; Phase 0/1/2 backend tests unchanged
- [ ] API: all writes through `execute_tool` (tested); audit rows on the real path; no money-movement route (tested)
- [ ] TS API types generated from OpenAPI and up to date in CI
- [ ] `check_no_literal_figures` passes; empty-API test passes for every screen
- [ ] `formatINR` is the only money formatter; Indian grouping verified; no percent can render outside the API's guard
- [ ] Glyph test recorded; ₹ renders in every font and weight used
- [ ] Contrast script passes AA for every token pair in use; axe clean on every screen
- [ ] Every screen has loading, empty, error, partial and insufficient-data states, reviewed in screenshots at three viewports
- [ ] Section 5 checklist passed for every screen, with the owner's approval recorded at the design gate
- [ ] Correction cascade, undo and blocked-undo message demonstrated end to end on real data
- [ ] Constellation driven by real pipeline events, with a cap disclosed, reduced-motion layout, and frame budget met
- [ ] Reduced-motion and keyboard-only paths work end to end
- [ ] E2E demo path passes against the seeded backend
- [ ] No AI attribution anywhere (code, docs, app); exactly three proposed commits recorded; no git command run

---

## 10. Explicitly NOT in this track

- Dark theme (tokens allow it later), multi-user accounts, real authentication providers, deployment or hosting
- Conversational multi-turn chat, messaging channels, proactive delivery (Phase 6)
- Goals tracking dashboards beyond the minimal Phase 2 goal views, buckets/envelopes, commitments calendar (Phase 3)
- Investments, portfolios, tickers, crypto, net worth, benchmarks, tax filing
- Gamification and social features (Phases 4 and 5)
- Native mobile apps; any real bank, UPI or Account Aggregator integration

## 11. Extension points

| Built now | Used later by |
|---|---|
| Token system (single source) | Dark theme, rebranding |
| Copy catalogue | Translation, Bharat languages |
| Typed, generated API client | Phase 3 screens, Phase 6 channels |
| Timeline and explanation components | Phase 7 policy explanations |
| Constellation component with a typed particle spec | Any future "agent working" visualisation |
| Screen state matrix (loading, empty, error, insufficient) | Every future screen |
