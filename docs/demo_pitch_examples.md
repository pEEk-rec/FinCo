# The pitch, one claim at a time, with the working in our system

All outputs below were captured from the real system (demo database, demo clock 18 March 2024),
not written by hand. Amounts are integer paise (100 paise = ₹1).

> "FinCo is a personal-finance **agent**, not a chatbot. It takes a goal in plain language,
> **decides which tools to call**, runs them in a **loop**, **checks its own result**, and
> **stops to ask a human** before anything consequential. The model **never does the maths** and
> **never has the keys**. Numbers come from **deterministic code**. Every tool call passes **one
> governed gate**. Every action is **audited and reversible**."

---

## 1. "An agent, not a chatbot"

A chatbot returns a paragraph. FinCo returns a **structured run**: an intent, a plan, tool calls
with typed results, a trace, and any decision it is waiting on.

Ask: *"What if I spend ₹2,000 more on food each month for 3 months?"*

```
intent : whatif_add_spend   category=food   amount_paise=200000   horizon_months=3
plan   : 1. check_budgets   "Fetch current budgets to simulate impact of additional spend"
         2. run_whatif      "Project the monthly surplus and goal status under the scenario"
trace  : understand(11.6ms) -> plan(30.9ms) -> act(4.2ms) -> act(6.5ms) -> reflect -> synthesize
result : surplus by month = 2024-03: -269,900   2024-04: -469,900   2024-05: -469,900  (paise)
status : paused, 1 draft recommendation waiting for you
```

**Show it:** Agent > Ask > the third example button. The panel **How the agent worked** is
drawn from exactly this trace.

---

## 2. "Takes a goal in plain language"

The **understand** node turns text into a typed `Intent`. The sentence above became:

| Field | Value | How it got there |
|---|---|---|
| `type` | `whatif_add_spend` | deterministic keyword classifier over 10 intent types |
| `amount_paise` | `200000` | amount parser handles `₹2,000`, `2k`, lakh, crore |
| `category_id` | `food` | resolved against **your own category table**, never guessed |
| `horizon_months` | `3` | "for 3 months" |
| `confidence_label` / `source` | `high` / `deterministic` | no LLM needed |

If something is missing, it **asks** (one question, with real options) and resumes the same run:

```
"why did my spending change last month"
 -> status: needs_clarification
 -> "Which category would you like me to explain? Options: Dining, Education, Entertainment, Groceries."
```

---

## 3. "Decides which tools to call"

The plan is a list of **tool calls**, each with a one-line rationale. In the demo, plan
templates (`config/plan_templates.yaml`) pick the tools. With an LLM enabled, a model would
choose from a **catalogue** and the same validator would police it.

What the planner is shown (`project_tool_catalogue()`), 15 tools, for example:

```
{"tool_name": "check_budgets", "short_description": "Check budget performance status
 (ok, warning, exceeded) for a month", "tool_class": "read", "cost": "cheap",
 "intents": ["check_budget", "alerts_overview", "whatif_add_spend"]}
```

Write tools in that catalogue: **none**.

Different questions give different plans (smallest plan that answers):

| Question | Plan |
|---|---|
| How is my budget doing this month? | `check_budgets` |
| Forecast my spending this month | `forecast_month` |
| Why did my food spend change in February? | `aggregate_spend_by_category`, then `explain_change` |
| What if I spend ₹2,000 more on food...? | `check_budgets`, then `run_whatif` |

**Bad plans never run.** I handed the validator a plan an attacker or a buggy model might
produce:

```
accepted: False
  Tool 'recategorize_transaction' is not planner-selectable (write/prohibited tool)
  Tool 'transfer_money' does not exist in tool registry
  Args for tool 'check_budgets' do not conform to input schema: month <= 12
audited event: plan_rejected   (the safe deterministic plan runs instead)
```

---

## 4. "Runs them in a loop"

The loop is a **LangGraph state graph**, not a script:

```
understand -> (clarify) -> plan -> act -> act -> ... -> reflect -> synthesize -> (review) -> finalize
                                    └── repeats once per plan step ──┘
```

Each step is bounded so the loop always ends:

| Control | What it does | Where proven |
|---|---|---|
| Step budget | stops after N steps with `stop_reason = step_budget` | `test_agent_graph_step_budget_exhaustion` |
| Memoization | an identical call is served from cache, recorded `skipped_memoized` | `planner/execution.py` |
| Loop detection | the same tool beyond `max_repeat=3` ends the task `loop_detected` | `planner/execution.py` |
| Round limit | at most 2 reflection rounds | `reflect_node` |

---

## 5. "Checks its own result"

Four real self-checks. (Honest note: the `reflect` node itself is shallow, see the end.)

1. **Plan check before acting**: the validator above.
2. **Output check after each tool**: every tool result is validated against its output schema;
   a failure rolls the whole step back.
3. **Grounding check on text**: generated advice must only contain numbers that appear in a
   computed finding. In the monthly review:
   `"Food reached 102% of its budget in February 2024: ₹7,172 spent of ₹7,000."`
   Every figure there came from a finding; text containing any other number is rejected and
   replaced by a template.
4. **Abstention**: the investigation tests 8 hypotheses and, when none is supported, it says
   *"Could not determine a cause. ₹608 remains unexplained"* instead of inventing one.

---

## 6. "Stops to ask a human before anything consequential"

Four places the system **stops and waits**:

| Pause | Example | Mechanism |
|---|---|---|
| Missing information | "Which category would you like me to explain?" | graph `interrupt()` in `clarify` |
| Uncertain data | 8 imported transactions sit in the Review queue. One was matched by a rule at **0.80** confidence, below the **0.85** auto-accept line, so it waited for you | `needs_review` flag |
| Recommendations | the what-if run ended with *1 draft waiting*. Drafts never act | graph `interrupt()` in `review` |
| Decisions | approving advice, approving or revoking consent: **user-only tools**. The agent calling them: `DENIED_BY_POLICY` | per-actor policy |

---

## 7. "The model never does the maths"

Every figure is **integer arithmetic in code**. Worked examples from the system:

```
Food budget, Feb:   spent 717200, limit 700000, warn 80%
  pct_used = 717200 * 100 // 700000 = 102        -> status: exceeded   (spent > limit)

Travel budget, Feb: spent 142800, limit 150000
  pct_used = 142800 * 100 // 150000 = 95         -> status: warning

Boundary:           spent 560000, limit 700000
  pct_used = 80 (exactly the warn line)          -> status: warning     (>= is deliberate)

Dashboard, 18 Mar:  budget total 1,250,000   spent 304,600
  left to spend = 1,250,000 - 304,600           = 945,400
  ideal today   = round_half_up(1,250,000 * 18 / 31) = 725,806
  pace delta    = 725,806 - 304,600             = 421,206   -> "under pace"
```

Floats are refused at the edges: `rupees_to_paise(499.5)` raises `TypeError`; a transaction of
`1000.5` paise fails validation; a debit with a negative amount fails validation. The browser
formats integers it is given; a script (`check_no_literal_figures`) fails the build if app code
contains a hardcoded figure.

---

## 8. "Never has the keys"

Two meanings, both true:

* **No capability to move money.** There is no payment, transfer, trading or withdrawal tool.
  Ask for one and the loop never starts:

  ```
  "transfer 5000 to rahul"   -> nodes: understand, finalize   plan: 0   tools run: 0
  "my otp is 123456"         -> nodes: understand, finalize   (credentials refused at the gate)
  "should I invest in mutual funds" -> refused (investment advice)
  agent calls transfer_money -> NOT_FOUND   (the tool does not exist)
  ```

* **Least privilege.** The planner is offered 15 read-only tools; the 18 tools that change
  data are never offered. Registering a tool with an external effect is **denied in code
  even if config allows it** (`scripts/prove_governance.py` demonstrates this).
* The model also never holds API credentials for finance data; it only receives redacted text
  (UPI ids, account numbers, phone numbers, OTP/PIN patterns are masked before any prompt).

---

## 9. "One governed gate"

Every tool call, from the agent or from you in the UI, goes through `execute_tool`:

```
look up tool -> policy decision -> validate input -> run in a transaction
             -> validate output -> write audit row  (any failure rolls the step back)
```

The **same call** gets a different verdict depending on who asks:

```
recategorize_transaction
  actor=agent  approved=False -> APPROVAL_REQUIRED
  actor=user   approved=False -> OK
agent calls decide_advice     -> DENIED_BY_POLICY      (user-only)
agent calls check_budgets with month=13 -> INVALID_INPUT
agent calls transfer_money    -> NOT_FOUND
```

---

## 10. "Audited and reversible"

A user correction, end to end (a transaction a rule matched at 0.80 and flagged for review):

```
before : category groceries | source rule | confidence 0.8 | needs_review true
user   : recategorize -> travel
after  : category travel    | source user | confidence 1.0 | needs_review false

audit row  : actor=user  type=transaction_recategorized
             before={groceries, rule, 0.8, needs_review: true}
             after ={travel, user, 1.0, needs_review: false}
undo       : OK  -> restored state identical to before: True
             the undo is itself audited (actor=user, undoes event cfed8a91)
```

**Reversal is safe.** Undo an older change after a newer one:

```
STALE_DATA: Undo refused: transaction state has diverged from event after_data
```

**History cannot be edited.** `UPDATE`, `DELETE` and `INSERT OR REPLACE` on the audit table are
refused **by the database** (triggers), not by application code.

---

## Where the pitch is stronger than the system (say this first)

1. **"Checks its own result"**: the `reflect` node is shallow. It is capped at two rounds and
   its second round is a placeholder that did not trigger in the demo. The real self-checks are
   items 1 to 4 in section 5.
2. **"Stops to ask before anything consequential"**: `needs_approval` means *the caller must
   assert approval*. In my run, `actor=agent` with `approved=True` **succeeded** on
   `recategorize_transaction`. The agent graph never sets that flag, and user-only tools are now
   explicitly denied to the agent, but the gate cannot tell a human's approval from an assertion.
   The fix is to bind approval to a specific pending action; it is a known gap.
3. **"Decides which tools"**: in the demo, templates decide. The model-driven planner exists and
   is validated, but no LLM is configured here, so it was exercised with fake clients only.
4. **"Model"**: with no LLM enabled, "the model never does the maths" is true by construction.
   The same fences apply when one is enabled, but that path was not run against a live model.
