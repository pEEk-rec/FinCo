# Architecture

FinCo is a local-first web app: a Python API with a SQLite database, and a React app that talks to
it. This page explains the shape of it and the reasons behind the shape. For a package-by-package
map of the backend, read [src/copilot/README.md](../src/copilot/README.md).

## The pieces

| Piece | Technology | Job |
| --- | --- | --- |
| Web app | React, TypeScript, Tailwind, Vite. Installable as a PWA | Shows figures the API computed. It never calculates money itself, and a build check fails if a literal figure appears in a screen. |
| API | FastAPI | GET and POST only. Every route except `/api/health` needs the session token. |
| Agents and graphs | LangGraph | The Ask agent, the monthly run, and a multi-agent supervisor with a reviewer. |
| Tools | Typed Python functions (155) | The only way to read or change data. |
| Store | SQLite, integer paise | Transactions, budgets, goals, memory, and an append-only audit log. |
| Model (optional) | Gemini through a router | Reads paraphrased questions, suggests plans, words answers, suggests categories. |

## One gate for everything

Whoever asks (the API, the CLI, a planner, a scheduled agent), the call goes through
`tools.executor.execute_tool`:

1. check the policy (`config/policy.yaml`) for this actor and this tool,
2. enforce the user's id so data never crosses users,
3. validate the input and the output against their types,
4. run the tool inside a savepoint,
5. write an audit row naming the actor (`user`, `agent` or `system`).

The audit table rejects updates and deletes at the database level. Tools are declared `read` or
`write_logical`; none is `external`, and the policy denies that class, so no code path can pay,
transfer, trade, withdraw or deposit. The planner is offered 49 of the tools: 47 read-only, plus two
that only do FinCo's own bookkeeping (refreshing memory candidates and rolling unspent bucket
balances over). `scripts/prove_governance.py` checks all of this live.

## Answering a question

```mermaid
flowchart LR
  Q["Question"] --> G["Input gate: refuse money movement,<br/>OTPs, tips"]
  G --> U["Understand: intent, period, category"]
  U --> P["Plan: templates first,<br/>model second"]
  P --> V["Plan validator: allowed tools only"]
  V --> A["Act: governed tool calls"]
  A --> R["Reflect: enough evidence?"]
  R -->|"need more"| A
  R --> S["Synthesize from tool results"]
  S --> C["Claim check: drop any number<br/>no tool computed"]
  C --> Out["Answer + steps shown live"]
```

The steps stream to the screen as they happen (`POST /api/ask/stream`), so you see the plan, each
tool, and the figure check rather than a spinner. A question that spans several areas goes to the
supervisor graph: specialists answer their part with only their own tools, a deterministic merge
combines them, and a reviewer may ask for one revision.

## Tagging a payment

```mermaid
flowchart LR
  A["Bank alert"] --> W["POST /api/capture/sms<br/>(secret header)"]
  W --> P["Parse: amount, direction, payee.<br/>OTPs and mandates dropped.<br/>Raw text never stored"]
  P --> D{"Ask policy"}
  D -->|"known shop"| Q["Tag quietly, offer Change"]
  D -->|"new shop or a person"| K["Card with 3 guesses"]
  K --> L["Your answer teaches the guess ranking"]
  Q --> R["Statement arrives later:<br/>reconcile with the ledger row"]
  L --> R
```

A phone macro posts the alert text to the API. Any bank-style sender is read; a phone-number sender
is dropped unread. The card reaches the open app over a server-sent-events stream and, when the
app is installed on a phone, as a push notification (which needs HTTPS).

## Categorising

Each payment goes down a cascade and stops at the first stage that is confident enough:

1. your own earlier answer,
2. rules (`config/categorization_rules.yaml`),
3. shops you have already tagged that look like this one,
4. a hand-written brand dictionary,
5. a model, shown your own examples,
6. a question to you.

Every stage's confidence is calibrated against how often it has been right on *your* answers, so a
stage with a poor record is trusted less. A model only suggests: swapping in an always-wrong model
costs extra questions, not wrong labels. People are never labelled automatically.

## Why it is built this way

- **Safe by structure.** Safety does not depend on a prompt. It depends on there being no tool that
  can do harm and one gate that every call must pass.
- **Numbers you can trust.** Money is integer paise, and a claim checker removes any figure in an
  answer that a tool did not compute. A model can fail and the figures stay right.
- **Works with no model.** Every model-assisted step has a rule-based fallback, so the product
  degrades to plainer wording rather than to an error.
- **Asks when unsure.** The cost of a wrong silent label is higher than the cost of one question,
  so the system is built to ask, and to ask the question that settles the most payments first.

Decision records for the two big external choices are in [adr/](adr/): capturing at the moment of
payment, and using an Account Aggregator.
