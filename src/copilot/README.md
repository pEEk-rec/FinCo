# How FinCo is put together

This is the map of the backend. If you read one file before touching the code, read this one.

FinCo looks after one person's day-to-day money: it reads their bank statements and payment
alerts, works out what each payment was for, answers questions about where the money went, helps
them plan a budget around what they care about, and now and then tells them the one thing worth
knowing. It never moves money. Everything it does is something you could check by hand.

The code is organised by **what a piece of it is for**, not by when it was built. Earlier the
project grew in phases and the folders said so (`core/`, `repo_phase3.py`, `harness_phase4.py`);
those names still resolve so nothing breaks, but new code should use the homes below.

---

## The three ideas everything hangs on

**1. Tools are the only way to touch data.** There are 155 tools, each a small typed function with
an input model, an output model and a declared side effect (`read` or `write_logical`; nothing is
`external`). Every call, from the API, the CLI, a planner or an agent, goes through one function:
`tools.executor.execute_tool`. That is where policy is checked (`config/policy.yaml`), where the
user's id is enforced, and where the audit row is written. If something isn't a tool, an agent
cannot do it.

**2. Code does the arithmetic; a model only ever helps with words.** Totals, forecasts, budgets,
what-ifs and investigations are deterministic functions in integer paise. A language model may
read a question, suggest a plan, or phrase an answer. Whatever it produces is checked by code
before anyone sees it: plans by the validator, sentences by the claim checker, categories by
calibration. When no model is available, everything still works with rules and templates.

**3. Agents check themselves and say why.** Every agent records what it looked at, what it
dropped and why, and what it did. You can ask "why was this tagged Food?" or "why did you say
that?" and get a real answer from stored data, not a guess.

---

## How things move through the system

### A question ("why did food go up in February?")

```
api/routes/ask.py ─► conversation/intent      read the question; refuse money movement, OTPs, tips
                  ─► planner/                 pick the smallest set of tools that answers it
                     planner/validator        reject any plan with a tool it may not use
                  ─► workflow/agent_graph     LangGraph: understand → plan → act → observe → finalize
                     tools/executor           every step is a governed tool call
                  ─► conversation/answers     compose the answer from tool results only
                     verify/claims            any number not computed by a tool is removed
```

Questions that span several areas (budget *and* goals *and* subscriptions) go to
`workflow/multi_agent_graph`: a supervisor splits the question, specialists answer their part with
only their own tools, a deterministic merge combines them, and a reviewer checks the result and may
ask for one revision.

### A payment ("Rs 250 debited, UPI to SWIGGY")

```
api/routes/capture.py ─► capture/sms_parser   bank alert → amount, direction, counterparty (no raw text kept)
                      ─► capture/events       record it; decide whether to ask you now
                         capture/policy       known shop? a person? quiet hours? daily ask budget?
                      ─► push / in-app prompt three best guesses, one tap to answer
                      ─► capture/reconcile    when the statement arrives, match it to the ledger row
                      ─► capture/learning     each answer adjusts how much each guess signal is trusted
```

### Making sense of a statement

```
understand/descriptor   "UPI/6289.../SWIGGY8/swiggy8@ybl/HDFC" → rail, shop name, handle
understand/entities     all the ways a bank spells one shop → one entity
understand/cascade      S0 your answer → S1 rules → S2 your similar shops → S3 brand dictionary
                        → S4 the model (shown your own examples) → S5 ask you
understand/calibration  each stage is believed only as far as its track record on *your* answers
understand/learn        ask the question that settles the most payments first; learn from the answer
```

### The weekly check-in (an agent acting on its own)

```
agents/kernel   precheck → perceive → rank → verify → propose → commit
agents/checkin  quiet hours and a twice-a-week budget → signals from your money → your priorities
                → recompute each one a second way → word it (every number checked) → save it
learning/nudges which time and tone you actually respond to, learned per person
```

---

## Where things live

| Package | What it is for |
| --- | --- |
| `agents/` | Agents that act on their own initiative: the shared loop (`kernel`), the check-in agent, and `registry`, the list of every agent in FinCo. `copilot agents` prints it. |
| `tools/` | The 155 tools, the registry, the executor, and `catalog`, the single list of tool families. |
| `governance/` | The policy matrix and `decide()`: what may run, for whom, with or without approval. |
| `verify/` | How agents check themselves: claim checking, and pointers to the other verifiers. |
| `understand/` | Categorising transactions: descriptor parsing, merchant entities, the cascade, calibration, asking well. |
| `capture/` | Tagging a payment the moment it happens: SMS parsing, the ask policy, push, reconciliation. |
| `banklink/` | The Account Aggregator link: consent, fetching, the mock source. |
| `conversation/` | Reading a question (including Hinglish), refusing what FinCo must not do, composing grounded answers. |
| `planner/` | Turning a question into a validated plan of tool calls: deterministic templates first, the model second. |
| `workflow/` | The LangGraph graphs: the ask agent, the monthly run, and the multi-agent supervisor with its reviewer. |
| `domain/` | The money logic: budgets, goals, forecasts, commitments, buckets, calendar, readiness, what-if. Pure functions. |
| `personal/` | The personal model: your values profile, the budget co-pilot, subscriptions, shared expenses. |
| `memory/` | What FinCo remembers about you, with evidence, confidence that fades, and a way to forget. |
| `learning/` | The bounded learners (all share one Beta-posterior arithmetic in `beta.py`). |
| `engagement/` | Experiments, challenges, rewards and progress: comparing you only with yourself. |
| `context/` | Building model prompts: token budgets, memory retrieval, and fencing off untrusted text. |
| `llm/` | The one place a model is called: client, Gemini provider, router, redaction, prompts. |
| `runtime/` | Scheduled jobs with leases, retries and a dead letter; the background daemon. |
| `skills/`, `mcp/` | Compound skills built from tools; FinCo's tools exposed over the Model Context Protocol. |
| `review/` | The monthly review and its renderers. |
| `audit/`, `ops/` | The append-only audit log; tracing, telemetry and the activity timeline. |
| `api/` | The HTTP API: `app.py` builds it, `routes/` has one module per area. |
| `cli/` | The `copilot` command: one module per area. |
| `eval/` | Offline evaluation suites, listed in `eval/registry.py`. |
| `common/`, `models/`, `db/`, `config/` | Foundations: money and time, typed models, SQLite access, validated config loaders. |
| `bank/`, `live/`, `rails/` | Synthetic data and the mock bank; live mode on real statements; the separate multi-rail demo. |
| `core/` | **Old paths only.** Each file points to its new home so older imports keep working. Don't add code here. |

---

## Rules that hold everywhere

These are checked by tests, not just written down.

- **Money is integer paise.** No floats anywhere near money.
- **Every query carries the user's id.** Data never crosses users.
- **Every change goes through `execute_tool`** and leaves an audit row naming the actor (`user`,
  `agent` or `system`). The audit table rejects updates and deletes at the database level.
- **Nothing reaches outside FinCo.** No tool has an `external` side effect, and the policy denies
  that class outright, so there is no path that can pay, transfer, trade, withdraw or deposit.
- **Nothing the user decided is overwritten.** A category you chose is never second-guessed by a
  rule, a model or an agent.
- **Agents propose; you decide.** Rule suggestions, budget plans, profile guesses and advice wait
  for your approval before they change anything.
- **Raw SMS text is never stored, logged or sent anywhere.** Only the parsed fields are kept.
- **The API only has GET and POST routes**, every route but `/api/health` needs the session
  token, and logs record method, route, status and timing only.

---

## How this maps onto agentic AI ideas

FinCo was built alongside a course on agentic AI, so here is where each idea actually lives. None of
it is there for show: each piece earns its place by making the product safer or more useful.

**Foundations: what makes something an agent.** Something here counts as an agent when it chooses
its own next step toward a goal, using tools, and checks itself. `agents/registry.py` lists each one
with its trigger (a question, a schedule, an event), goal, tools, self-check and output. Two loop
styles exist on purpose. Open-ended work (a question that might need any tool) runs as a LangGraph
graph with a planner in the middle. Narrow, repeated work (the check-in) runs on the fixed
`agents/kernel` loop. Categorisation and capture are deliberately pipelines, not free agents: they
decide one payment at a time by calibrated confidence and ask you when unsure.

**Frameworks, tools, memory, protocols, runtime.** LangGraph drives the graphs (`workflow/`). Tools
are typed, registered from one catalogue (`tools/catalog.py`) and governed at one choke point. The
planner sees only a curated subset (`config/planner_capabilities.yaml`). Memory has two tiers: the
run's own state, and a long-term store of behaviours with evidence, decaying confidence and
explicit forgetting (`memory/`). Retrieval and prompt building have a token budget and fence off
untrusted text (`context/`). Skills combine tools into procedures (`skills/`). The same tools are
offered to other agents over MCP (`mcp/`). Scheduled work runs on leases with retries
(`runtime/`).

**Multi-agent orchestration.** The supervisor splits a multi-area question, specialists work in
parallel with isolated tool sets, a deterministic merge combines them, and a Reflexion-style
reviewer checks the result with at most one revision (`workflow/multi_agent_graph.py`,
`workflow/specialists.py`, `workflow/reviewer.py`). One agent hands a draft to a human: advice,
reallocations and budget plans wait for your decision.

**Learning, safety and governance.** The learners are small and bounded on purpose. Beta posteriors
learn which nudges you act on, which capture signals to trust and which offers help. Calibration
learns how far each categorisation stage can be believed. Thompson sampling runs over offers with
logged propensities. All of them share `learning/beta.py`, can be inspected, and can be reset.
Safety comes from structure rather than hope: a policy matrix, a plan validator, claim checking,
an append-only audit log, human approval for consequential writes, and offline evaluation suites
with targets set before measuring (`eval/registry.py`).

**What is deliberately not here.** No fine-tuning or RLHF: one person's data is far too small, and
the bounded learners above do the useful part. No second agent framework alongside LangGraph. No
extra model calls where a rule or a lookup does the job better. These were weighed and left out on purpose.

---

## Finding your way around

- `copilot agents` lists every agent; `copilot agents checkin` shows one in full.
- `copilot eval --list` lists the evaluation suites; `copilot eval --suite categorise` runs one.
- `tests/journey/test_one_user_journey.py` walks one person through a first session over the HTTP
  API. It is the quickest way to see the pieces working together.
- Each package has its own short README with the details.
