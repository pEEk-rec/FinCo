# FinCo: end-to-end demo, with the Agentic AI concepts explained

Audience: you, presenting. About 15 minutes (a 6-minute cut is marked **[short]**).
Every claim below was checked against the code. Where something is **not built**, it says so;
say so too, it is stronger than being caught.

---

## 0. The one-minute pitch

> FinCo is a personal-finance **agent**, not a chatbot. It takes a goal in plain language,
> **decides which tools to call**, runs them in a **loop**, checks its own result, and
> **stops to ask a human** before anything consequential. The twist: **the model never does
> the maths and never has the keys**. Numbers come from deterministic code. Every tool call
> passes one governed gate. Every action is audited and reversible.

```
 you ──► INPUT GATE ──► UNDERSTAND ──► (CLARIFY?) ──► PLAN ──► VALIDATOR
         (refuse)       intent+entities  1 question    steps     reject unsafe plans
                                                                       │
        ┌──────────────────────────────────────────────────────────────┘
        ▼
       ACT  ──► EXECUTOR (the choke point) ──► TOOLS (33)  ──► SQLite + audit log
        │        policy · schema · audit · rollback          (integer paise, no floats)
        ▼
     REFLECT ──► SYNTHESIZE ──► REVIEW (human approves) ──► FINALIZE
     (bounded)    (grounded)     (graph pauses)
```

**Say it like this:** "Autonomy with guardrails. The agent proposes; deterministic code
computes; a gate decides; a human approves."

---

## 1. Concept map (keep this open while presenting)

| Agentic AI concept | What it means | In FinCo | You see it in the UI |
|---|---|---|---|
| **Agent loop** | observe, plan, act, reflect, repeat until done or budget is hit | LangGraph state graph: `understand → clarify → plan → act (loop) → reflect → synthesize → review → finalize` (`workflow/agent_graph.py`) | Agent > Ask: **How the agent worked** |
| **Tool calling** | the model/planner selects typed functions instead of inventing answers | `ToolSpec` (name, description, input schema, output schema, side effect, handler); 33 tools in one registry | Plan steps and "Ran N tools" |
| **Structured output** | model output must validate against a schema or is retried and then rejected | `structured_call()` with Pydantic models, bounded retries | (LLM is off in the demo; the path is tested) |
| **Planner / executor split** | one component proposes a plan, another enforces it | `DeterministicPlanner` and `LLMPlanner`, then `PlanValidator`, then `execute_tool` | Plan, then Act |
| **Guardrails (input)** | refuse before reasoning | input gate: investment advice, money movement, market prediction, credentials, out-of-scope | Ask "Should I invest...?" |
| **Guardrails (plan)** | never trust a model's plan | validator: tool exists and is selectable, args fit schema, ids belong to the user, step limit, no duplicates | "Checked by the plan validator" |
| **Least privilege** | the agent only gets what it needs | planner sees 15 read-only tools; 18 write tools are never offered | Terminal proof (step 11) |
| **Human in the loop** | pause for approval on consequential steps | graph `interrupt()` for clarification and review; review queue; advice approval; consent | Review, Approve, "waits for you" |
| **Grounding** | every number in generated text traces to a computed fact | findings, then draft, then number validator, else template fallback | Monthly review > Explain |
| **Determinism boundary** | LLM for language, code for money | integer paise everywhere; floats rejected at three layers | Terminal proof |
| **Reflection** | check the result, optionally try again | `reflect` node, hard limit of two rounds | "Reflect: rounds used 1 of two" |
| **Cost and loop control** | bounded autonomy | step budget, LLM budget, memoization, loop detection | `stop_reason`, "memoized" |
| **Memory** | remember user corrections | merchant overrides ("Remember for this merchant"), categorisation cache | Review: remember toggle |
| **Observability** | see what the agent did and why | per-node trace, append-only audit log, timeline | Activity tab, `copilot audit` |
| **Reversibility** | undo agent and user actions safely | `undo` tool with stale-state refusal | Transactions > Undo |
| **Evaluation** | prove behaviour, not vibes | 594 backend tests, golden scenarios, eval harness (`copilot eval`), mutation checks | `pytest` |
| **MCP** | a standard protocol for exposing tools to AI clients | **not built** (see section 4) | n/a |
| **Skills** | packaged instructions loaded on demand | **not built**; our playbooks-as-config is the analogue (section 5) | n/a |

---

## 2. Setup (do this before you present)

```powershell
cd implementation
.\.venv\Scripts\activate
pip install -e .[dev]
cd frontend
npm install
npm run demo                  # fresh, empty database: you import live
```

Open **http://127.0.0.1:5173/welcome#token=demo**.

* Already imported (skip step 3): `npm run demo:imported`.
* Reset between takes: Ctrl+C, then `npm run demo` again (it wipes the demo database).
* Second terminal for the proof step, in `implementation\`:
  `python scripts/prove_governance.py --db frontend/.demo/demo.db`
* Data is synthetic and labelled "Demo data (synthetic)". "Today" in the demo is **18 March 2024**.
* **No language model is configured.** Everything below is the deterministic path. That is
  deliberate: it is reproducible, and it shows the safety design works without trusting a model.

---

## 3. The walkthrough

Format: **Do** (click), **Say** (talk track), **Concept** (the idea to name).

### Step 1. Welcome  (30 s)
**Do:** open the URL. **Say:** "It reads statements, sorts them, forecasts, explains. It cannot
move money, and that is by design: no payment tool exists to select." **Concept:** capability
boundary defined before any model is involved.

### Step 2. Empty dashboard  (20 s)
**Do:** click *Open the dashboard*. **Say:** "No data, so no numbers. The UI never invents a
figure; every number on every screen is a typed field from the API." **Concept:** honesty about
uncertainty; the frontend is a view, not a calculator.

### Step 3. Connect and import  (2 min)  **[short]**
**Do:** *Connect a bank*, read the consent card, click *Approve and import*.
**Say:**
* "Consent is explicit: accounts, date range, purpose, expiry, revocable. Approving it is a
  **user-only tool**; the agent is denied it by policy."
* "Import runs a small **pipeline of agent tool calls**: `ingest_statements`, then
  `categorize_batch`, then `detect_transfers`, `detect_recurring`, `detect_anomalies`,
  `evaluate_alerts`. Each is audited."
* Point at the constellation: "Each triangle is one real transaction. It settles into its
  category. The orange cluster, **Needs you**, is the review queue."
* "107 of 115 were handled by **rules**. Precedence is fixed: **your override, then rules,
  then cache, then the LLM, then a human**. The LLM can only ever fill gaps, its confidence is
  capped at 0.85, and PII is redacted before any prompt. Here the LLM is off, so the 8 unknown
  local shops go to a human instead of being guessed."

**Concepts:** tool calling in a fixed pipeline; **deterministic first, LLM as fallback**;
confidence thresholds as a routing signal (below 0.85 goes to a human); consent as authorisation;
idempotent ingestion (click *Import again*: "Nothing new to import").

### Step 4. Dashboard  (1 min)  **[short]**
**Do:** *Dashboard*. **Say:** "'March is running *under* pace.' Left to spend, actual line,
dashed ideal pace, the budget line, and a forecast range. All computed server-side in integer
paise." Point at **Alerts**: "This was raised by the **adaptive alerts engine**: five signals
(threshold, forecast, history deviation, anomaly, goal impact) weighted and damped by
confidence, with a cooldown and a **quiet mode**. Its score (about 28 out of 100) only reached the 'info' tier, so
it raised a quiet note, not an alarm. Restraint over noise." **Concepts:** tool-computed facts, explainable
scoring, calibrated escalation.

### Step 5. Review queue: human in the loop  (1.5 min)  **[short]**
**Do:** *Review*. Press `1`, then `Enter`. Toast appears; press `U`. **Say:**
* "The agent was unsure, so **it stops and asks**. It shows *why* ('No rule matched') and gives
  suggestions from past choices."
* "'Remember for this merchant' writes a **merchant override**. That is the agent's **memory of
  your preferences**, and it outranks every rule and the LLM. The agent is *forbidden* to
  overwrite a category you set (policy: `DENIED_BY_POLICY`)."
* "Correct, then **Undo**: the action is reversible, and undo is **refused if the transaction
  changed since**, so it can never clobber newer state."

**Concepts:** HITL, learning from feedback, reversibility with stale-state protection.

### Step 6. Transactions and the audit trail  (1 min)
**Do:** *Transactions*, click a row, change its category, open the history. **Say:** "Every
change records actor (you or agent), before, after, and reason in an **append-only audit log**.
The database itself refuses edits to it. I will prove that in a minute." **Concept:**
accountability and provenance; the 'source' badge (rule, you, AI) is shown on every row.

### Step 7. Monthly review and grounded advice  (2 min)
**Do:** *Monthly review*, *February 2024*, *Generate review*, open **Explain** on one
suggestion, click **Approve**. **Say:**
* "Generating the review ran `check_budgets`, `forecast_month`, `detect_anomalies`, then turned
  results into typed **Findings**, then `draft_advice`."
* "Advice is **grounded**: a validator extracts every number from the text and rejects it unless
  it appears in a finding. If it fails, a **deterministic template** is used. So the system can
  *never display a number the tools did not compute.*"
* "In this build the LLM drafting step is wired but not enabled, so you are seeing the validated
  template path, which is the fallback working exactly as designed."
* "Approve is a **user-only tool**: the agent drafts, the human decides, and the decision is
  audited."

**Concepts:** grounding and hallucination control, generate-then-verify, structured findings,
human approval.

### Step 8. The agent loop: Agent > Ask  (4 min)  **the centrepiece**  **[short]**

Open **Agent**. Click the example buttons; each run shows **How the agent worked** from the
real execution trace. Narrate the stages:

| Stage | What happens | Concept to name |
|---|---|---|
| **Understand** | Deterministic classifier assigns one of 10 intents, parses amount, period, category. Entities are resolved **against your own records**, never guessed. An LLM can assist extraction, but its output is re-validated against the database. | Input gate, entity grounding, prompt-injection resistance |
| **Clarify** | If something is missing, ask **one** concrete question with real options, then resume the same run. | Ask rather than guess; graph `interrupt()` |
| **Plan** | Steps come from a planner: deterministic templates now, an LLM planner when enabled. | Planner |
| **Validate** | The validator checks every step before anything runs; on failure it audits `plan_rejected` and **falls back to the safe plan**. | Never trust model output |
| **Act** | Each step is a **tool call through the executor**: policy, schema validation, handler in a transaction, output validation, audit. Results are memoized; repeats are loop-detected. | **Tool calling**, idempotence, loop guard |
| **Reflect** | Looks at the result; bounded to two rounds. | Reflection (bounded) |
| **Synthesize / Review** | Drafts a recommendation. It **pauses for you**; drafts never act. | HITL |

**Run these four, in this order:**

1. **"Should I invest in mutual funds?"** Red refusal. Point: *"The loop never started. No plan,
   no tool, no model. Refusal classes: investment advice, money movement, market prediction,
   credentials (try 'my otp is 123456'), out of scope."* Concept: **input guardrail**.
2. **"How is my budget doing this month?"** One-step plan: `check_budgets`. Point: "The agent
   chose the smallest plan that answers the question." Concept: **minimal tool use**.
3. **"Why did my food spend change in February?"** **Two-step plan**:
   `aggregate_spend_by_category`, then `explain_change`. Point at the investigation card:
   "It tested **eight explanations**, in a catalogue (one-off large, more frequent, higher
   ticket, new merchant, recurring change, miscategorisation, duplicate or refund, seasonal).
   Nothing had enough evidence, so it says **'Could not determine a cause'** and states how
   much is unexplained. *An agent that says 'I don't know' is the feature.*" Concept:
   **hypothesis-driven reasoning, calibrated confidence, abstention**.
4. **"What if I spend ₹2,000 more on food each month for 3 months?"** Shows natural language to
   structured intent (amount, category, horizon extracted), then plan `check_budgets`,
   `run_whatif`, a month-by-month surplus, and **"Drafted a recommendation and waits for
   you."** Concept: **NL to tool arguments**, simulation as a tool, HITL.

**Bonus (30 s):** type "why did my spending change last month" with no category. It asks
"Which category?" with real options. Answer "Dining" to resume the same run.

### Step 9. Investigate and What-if tabs  (1 min)
**Do:** *Investigate*, click *Investigate* on the possible duplicate. **Say:** "Same engine,
direct. Here a hypothesis is **supported** (duplicate charge) with the rupee amount attributed and
the evidence cited. Confidence is a label (high, medium, low) set by how much of the change the
supported hypotheses explain." Then *What if*: spend more on Dining, *Compare with now*. "Counterfactual
simulation is a **tool**, so the agent can use it and so can you. Horizon is capped, and
assumptions are listed." Concept: **simulation / counterfactual reasoning as a tool**.

### Step 10. Activity: observability  (30 s)
**Do:** *Activity*. **Say:** "'Waiting for your approval' lists every draft the agent made.
Below is the chronological record of what it did." Concept: **traceability**.

### Step 11. Prove the safety claims live  (1.5 min)  **[short]**
**Do:** in the second terminal:
```powershell
python scripts/prove_governance.py --db frontend/.demo/demo.db
```
**Say:** it works on a throwaway copy and tries to break the rules:
* 33 tools: **15 read-only offered to the planner, 18 write tools never offered**.
* `UPDATE`, `DELETE` and `INSERT OR REPLACE` on the audit log are **refused by the database**.
* The agent asks for `transfer_money`: `NOT_FOUND`. For `recategorize` without approval:
  `APPROVAL_REQUIRED`. For `decide_advice` or `revoke_consent`: `DENIED_BY_POLICY`. For an
  external tool even with config allowing it: **denied in code**.
* A float amount, or a debit with a negative amount: rejected.

Optional: `copilot audit --db frontend/.demo/demo.db --limit 15`.

---

## 4. MCP (Model Context Protocol): honest answer

**What it is:** an open protocol where a *server* exposes **tools, resources and prompts** with
JSON-Schema definitions, and any compliant AI *client* can discover them (`tools/list`) and call
them (`tools/call`). It standardises the plumbing between a model app and its capabilities.

**In FinCo: not implemented.** There is no MCP server or client in the repo. Say so.

**Why the design is MCP-shaped, and how it would plug in:**

| MCP idea | FinCo equivalent today |
|---|---|
| Tool definition (name, description, input schema) | `ToolSpec` plus Pydantic `model_json_schema()`, already used by `project_tool_catalogue()` to build the planner's tool list |
| `tools/list` | `list_specs()` filtered by planner capability |
| `tools/call` | `execute_tool(ctx, name, args)` |
| Server-side authorisation | the executor's policy check (default deny, per actor) |

A thin adapter would map those two functions to MCP. **The important design point:** MCP does
not make tools safe. A finance MCP server should expose **only the read/compute tools by
default**, and keep the executor as the single enforcement point. FinCo already separates those
two sets (15 and 18), which is the hard part.

*Examiner question: "Does it use MCP?"* **"No. The tool layer is built so it could be exposed as
an MCP server: same schemas, one choke point. I deliberately kept it in-process so I could
enforce policy and audit every call."**

## 5. Skills: honest answer

**What they are:** packaged folders of instructions (and scripts) an agent loads **on demand**,
so the model sees a short description first and the full playbook only when relevant
(*progressive disclosure*).

**In FinCo: not implemented in the Skills format.** The same ideas appear as our own mechanism:

* **Playbooks as data:** `config/plan_templates.yaml` (per-intent tool plan),
  `investigation.yaml` (hypothesis catalogue), `advice_templates.yaml`,
  `explanation_templates.yaml`, `alerts.yaml`. Behaviour changes by editing config, not code.
* **Progressive disclosure:** the planner is shown a **compact catalogue** (tool name, one-line
  description, cost, relevant intents), not every schema and implementation detail.
* **Capability matrix** (`docs/capability_matrix.md`, `config/planner_capabilities.yaml`):
  declares which tools are read, compute or write, their cost, and whether the planner may
  select them.

*Examiner question: "Where are Skills?"* **"Not used. Playbooks are config-driven and the
planner gets progressive disclosure through a tool catalogue; that is the same principle, but
it is my own mechanism, not the Skills format."**

---

## 6. Other concepts to mention if asked

* **Plan-and-execute with bounded reflection**, not free-running ReAct: safer and cheaper for
  money; the cost is flexibility. The step budget, LLM budget, memoization and loop detection
  make runs finite.
* **Autonomy levels:** reads and computations are autonomous; writes need approval or are
  user-only. This is a dial, set per tool in `config/policy.yaml`, per actor (agent or user).
* **Prompt-injection posture:** model output is never executed directly. Plans are validated,
  tool args are schema-checked, entity ids are re-verified against the user's rows, PII is
  redacted before prompts, and credential-like input is refused at the gate.
* **Multi-model routing:** `SmartLLMRouter` assigns API keys per purpose (planning, intent,
  investigation) with rate limiting. Off in the demo.
* **Evaluation:** deterministic golden scenarios, held-out seeds in `copilot eval`, and
  mutation checks (break a rule on purpose and confirm a test fails).

---

## 7. Likely questions

| Question | Answer |
|---|---|
| Is it really *agentic*? | It has the loop (understand, plan, act, reflect), selects tools, asks clarifying questions, pauses for humans, and stops on budgets. Autonomy is deliberately bounded because the domain is money. |
| Where is the LLM? | Optional and fenced: categorisation fallback, entity extraction, planning, advice wording. Each is schema-validated and falls back to deterministic code. In this demo it is off. |
| How do you stop hallucinated numbers? | The LLM never computes. Text with numbers is generated from findings and verified against them; failures fall back to templates. |
| What if the planner proposes something bad? | The validator rejects it, audits `plan_rejected`, and the deterministic plan runs. |
| What stops it moving money? | No such tool exists; unknown tools return `NOT_FOUND`; external-effect tools are denied in code. |
| What happens when it does not know? | It says so: "Could not determine a cause, ₹X unexplained", or it asks one question. |
| How is it tested? | 594 backend tests, 82 frontend unit tests, 11 browser tests against the real API, golden scenarios and mutation checks. |

---

## 8. Honest limits (state these before you are asked)

1. **No LLM in the demo**, so "By AI: 0" is true. The LLM paths are implemented and tested with
   fake clients, not run against a live model here.
2. **Plans are minimal.** The deterministic planner builds one or two steps; richer composition
   is the LLM planner's job.
3. **Reflection is shallow.** `reflect` is bounded to two rounds, and its second round is
   currently a placeholder data-gathering step; it did not trigger in the demo.
4. **Advice wording is template-based** in this build (the LLM drafting call is wired to a fake
   client). It is validated either way.
5. **Ask's generated summary text is not shown**; it was not reliable enough. You see the plan,
   the tool results, and the investigation instead.
6. **Alerts are deliberately quiet:** one info-level alert in the demo data.
7. **MCP and Skills are not implemented** (sections 4 and 5).
8. **Do not pick 12 months in the What-if tab.** The engine caps horizon at 6; use 3 or 6.
9. Memory beyond merchant overrides (retrieval, decay) is schema only.

---

## 9. If something goes wrong

| Symptom | Fix |
|---|---|
| "The FinCo service is not running" | the API terminal exited; run `npm run demo` again |
| "Session token missing or expired" | reopen the URL with `#token=demo` |
| Port busy | stop whatever holds 8765 or 5173 (a previous demo) |
| Constellation empty after import | you clicked *Import again*; reset with `npm run demo` |
| Blank agent answer | check the API terminal for the error code; ask one of the example buttons |
