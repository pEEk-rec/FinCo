# Finance Copilot

An autonomous personal finance and budgeting copilot designed for students in India.

Finance Copilot ingests bank statements, classifies messy UPI transactions, discovers recurring subscriptions and transfers, monitors budgets, detects spending anomalies, and compiles versioned monthly financial reviews with mathematically verified advice. In Phase 2, FinCo introduces an **autonomous agentic intelligence layer** with dynamic planning, causal spend investigation, counterfactual what-if simulation, multi-signal adaptive alerts, and grounded explanations with a unified activity timeline.

---

## Agentic Architecture & Safety Firewalls

```
                ┌─────────────────────────────────────────────────────────┐
                │          User Interfaces (CLI / Streamlit / API)        │
                │    copilot ask / investigate / whatif / goals / alerts  │
                └────────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                ┌─────────────────────────────────────────────────────────┐
                │              Intent Understanding Gate                  │
                │   - Intent Classification (deterministic regex + LLM)   │
                │   - Entity Resolution (period, amount, category, goal)  │
                │   - Refusal Firewall (investment, money movement block) │
                └────────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                ┌─────────────────────────────────────────────────────────┐
                │             Dynamic Planner & PlanValidator             │
                │   - Step Budget Enforcement (max 5 steps per task)      │
                │   - Whitelist & Tool Signature Validation               │
                │   - Safety Invariant: Read plans reject write tools     │
                │   - Human Confirmation Gate for sensitive state writes  │
                └────────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
         ┌───────────────────────────────────────────────────────────────────────┐
         │              Governance Firewall & Execution Choke Point              │
         │                 (`execute_tool(ctx, tool_name, args)`)                │
         └───────┬───────────────────┬───────────────────┬────────────────┬──────┘
                 │                   │                   │                │
                 ▼                   ▼                   ▼                ▼
        ┌─────────────────┐ ┌─────────────────┐ ┌────────────────┐ ┌────────────┐
        │  Investigation  │ │What-If Simulation│ │Adaptive Alerts │ │ Financial  │
        │     Engine      │ │     Engine      │ │    Engine      │ │ & AA Tools │
        │ (Decomposition, │ │ (Counterfactual,│ │ (Multi-signal, │ │(Budgets,   │
        │  Hypotheses)    │ │  Conservation)  │ │  Suppression)  │ │ Category)  │
        └────────┬────────┘ └────────┬────────┘ └────────┬───────┘ └──────┬─────┘
                 │                   │                   │                │
                 └───────────────────┼───────────────────┴────────────────┘
                                     ▼
                ┌─────────────────────────────────────────────────────────┐
                │             Explanation Grounding Firewall              │
                │   - Number Extraction & Causal-Claim Verification       │
                │   - Missing Simulation Defense (consequence checks)     │
                │   - Inconclusive Hedged Sentence Fallback               │
                └────────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                ┌─────────────────────────────────────────────────────────┐
                │            SQLite Core Engine & Audit Trail             │
                │   - Strict Tables, Integer-Paise Math, User Isolation   │
                │   - Unified Activity Timeline (events, traces, actions) │
                └─────────────────────────────────────────────────────────┘
```

---

## Phase 4: Behavioural Engagement and Gamification

Phase 4 turns the copilot's advice into small, optional, measured experiments ("challenges") and
tells the user honestly whether they worked. Nothing here moves money, and nothing is automatic:
the user opts in to every challenge.

```
 weekly job -> offers (Thompson sampling, logged propensity) -> user accepts (opt-in)
      ^                                                              |
      |                                                              v
 learning loop  <- feedback <- review (rank vs own history) <- experiment (frozen baseline, pace)
 (Beta posteriors,                    ^                              |
  outcome memory)                     |            dated exception -> auto-pause / extend (user accepts)
                                      +-- integrity note if payments were recategorised
```

What it adds:

- **Honest measurement.** A result is ranked against the user's own K=6 earlier comparable periods
  ("lower than all 6 of your previous 14-day periods"). With six earlier periods a quiet window
  still looks "beyond usual range" about 1 time in 7 by chance, so the wording says what was
  compared and never claims the challenge caused the change. Small differences (under 10% and under
  ₹200) are called "within your usual range".
- **Forgiving by design.** One grace day per week on streaks, streak freezes and window pauses for
  declared exceptions (`copilot memory exception ... --from --to`), rest weeks after two abandoned
  challenges, quiet weeks after repeated "not now" answers, and no social comparison anywhere.
- **Gamification that follows real behaviour.** XP for things the user actually did, levels, badges,
  and personal bests compared only with the user's own past.
- **Learning loop.** Feedback moves a per-template Beta posterior and writes an outcome memory; the
  offer policy (Thompson sampling with a seeded generator) uses it, and an offline simulator with
  IPS/SNIPS estimates checks the policy without touching a user.
- **Model first, rules as guard.** A configured model reads each question first; the rules validate
  its answer and are the fallback (`llm_primary`, `FINCO_LLM_PRIMARY=0` to flip). Tests never use
  the network; recorded replies are in `tests/cassettes/`.

Try it (offline, about a minute): `bash scripts/demo_phase4.sh`, which follows
`docs/demo_script_phase4.md`. Evidence: `copilot eval --phase 4` writes `docs/eval_report_phase4.md`;
`python scripts/mutation_check_phase4.py` records that all 12 safety rules are guarded
(`docs/phase4_mutation_checks.md`). Weak spots are listed in `docs/known_issues.md`.

---

## Capability Matrix: Phase 1 vs. Phase 2 vs. Phase 3

| Dimension | Phase 1 (Core Automation) | Phase 2 (Agentic Intelligence) | Phase 3 (Advanced Financial Copilot) |
|---|---|---|---|
| **Query Understanding** | Structured CLI arguments only | Natural language intent routing with slot filling & refusal firewall | Automated multi-domain intent routing to multi-agent supervisor |
| **Workflow Execution** | Fixed sequential LangGraph DAG | Dynamic autonomous planner with deterministic `PlanValidator` | Supervisor + parallel specialists with Reflexion-style reviewer |
| **Cashflow & Planning** | Aggregations and category sums | Causal spend decomposition & what-if counterfactual simulations | 60-day projected calendar, virtual buckets, waterfall contributions |
| **Health & Readiness** | Basic balance checks | Static goal feasibility forecasting | Comprehensive readiness assessment, emergency reserve & debt runway |
| **Memory System** | Stateless | In-session ephemeral conversation state | Dual-tier memory with Bayesian confidence, recency decay & forgetting |
| **Protocol & Skills** | Internal CLI only | Internal tool registry | Model Context Protocol (MCP) server & executable compound skills |
| **Budget Alerts** | Hard static percentage thresholds | Multi-signal adaptive alerts with confidence damping | Festival & seasonal exceptions, 30-day advice suppression cooldown |
| **Safety & Governance** | Schema checks & integer paise | Consequence rule & causal claim firewall | Zero money movement, two-phase approval gates, audit choke point |

---

## Safety & Governance Invariants

1. **Deterministic Integer Paise:** All money amounts are stored and calculated as integer paise (`₹1.00 = 100 paise`). Floating-point money arithmetic is strictly rejected across all code paths.
2. **Unified Execution Choke Point:** No tool handler can execute directly. Every tool invocation routes through `execute_tool(ctx, tool_name, args)`, enforcing caller permissions, user data isolation (`user_id`), and writing immutable audit events.
3. **No Money Movement:** Read and analytical operations only; no money movement tools exist in the system (enforced by automated structural and dynamic tests).
4. **Autonomous Plan Safety:** Plans proposed by LLMs must pass through `PlanValidator`. Any plan exceeding 5 steps, calling non-whitelisted tools, or calling write tools for read/investigation intents is rejected 100% of the time and audited under `plan_rejected`.
5. **Causal-Claim Defense (Safety Rule 5):** Words asserting causation (`because`, `due to`, `caused by`) are strictly forbidden unless backed by an investigation with outcome `explained` and confidence >= `medium`.
6. **Consequence Rule (Safety Rule 6):** Consequential recommendations proposing spending decisions or budget adjustments must cite a completed what-if simulation ID.
7. **Conservation of Paise:** All what-if simulation projections and spend decompositions sum exactly:
   $$\Delta \text{Total} = \Delta \text{Fixed} + \Delta \text{Variable} + \text{Unexplained}$$
8. **Multi-Tier Categorization Hierarchy:** `User Override` > `Categorization Rules` > `Local Cache` > `Redacted LLM` > `Review Queue`. The agent is strictly prevented from altering user-assigned categories.

---

## Installation & Setup

Requires Python 3.11+ and SQLite 3.37+.

```bash
# 1. Clone repository
git clone https://github.com/pEEk-rec/FinCo.git
cd FinCo/implementation

# 2. Create virtual environment
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Install package with dev dependencies
pip install -e .[dev]
```

---

## Running the Application

### 1. Interactive CLI (`copilot`)

Finance Copilot provides a comprehensive terminal CLI with rich formatted tables:

```bash
# Initialize database schema
copilot init-db

# Seed synthetic student financial data (3 months, 2 accounts)
copilot seed --user-id u1

# View account balances and overall financial state
copilot state --user-id u1

# --- Phase 2 Agentic Commands ---

# Ask a natural language question (routes to autonomous planner)
copilot ask "Why did my food spend increase in September?"

# Run a dedicated causal spend investigation
copilot investigate --period 2026-09 --subject food

# Run what-if financial simulations
copilot whatif add-spend 1500000 --category shopping --note "New laptop"
copilot whatif reduce-spend 200000 --category food --months 3
copilot whatif compare sim_1 sim_2

# Manage financial goals
copilot goals list
copilot goals add "Emergency Fund" 5000000 --target-date 2026-12-31 --monthly-target 1000000

# Adaptive alerts evaluation and lifecycle
copilot alerts evaluate --period 2026-09
copilot alerts list --status open
copilot alerts ack alert_1
copilot alerts snooze alert_1 7

# Inspect the unified agent activity timeline
copilot timeline --limit 20

# Run Phase 2 evaluation benchmark harness
copilot eval --phase 2
```

### 2. Streamlit Web Blueprint

Launch the web interface:

```bash
streamlit run src/copilot/ui/app.py
```

### 3. Comprehensive Evaluation & Benchmarks

Run the deterministic golden evaluation harness across held-out seeds (`[777, 888, 999]`):

```bash
# CLI table view
copilot eval --phase 2

# Machine-readable JSON output
copilot eval --phase 2 --json

# Standalone runner script
python scripts/run_eval_phase2.py
```

Outputs a detailed benchmark report at `docs/eval_report_phase2.md`.

---

## Web UI

A calm light-theme web app over the same governed backend (React + FastAPI, localhost only).

```powershell
.\.venv\Scriptsctivate && pip install -e .[dev]
cd frontend && npm install
npm run demo            # API on :8765 and app on :5173; prints the URL to open
npm run demo:imported   # same, with statements already imported
npm run verify          # typecheck, lint, unit tests, honesty gates
npx playwright test --project=demo   # browser tests against the real API
```

Open the printed URL (`http://127.0.0.1:5173/welcome#token=demo`). Walkthrough:
`docs/ui_demo_script.md`. Status and decisions: `docs/ui_status.md`.
The API alone: `copilot serve --db data/copilot.db --demo empty --token demo`.

---

## Test Suite & Code Quality

Run tests across the entire codebase:

```bash
# Run all 564 unit, golden, and integration tests
pytest -q

# Run Phase 2 golden invariant scenarios specifically (16/16 scenarios)
pytest tests/golden/phase2/test_golden_phase2.py -v

# Run Phase 2 CLI integration tests
pytest tests/cli/test_phase2_cli.py -v

# Run Ruff linting and formatting check
ruff check src tests config scripts
```

---

## Project Structure

```
FinCo/
├── config/
│   ├── policy.yaml                # Governance permission matrix
│   ├── settings.yaml              # Application runtime settings
│   ├── categorization_rules.yaml  # Regex categorization rules
│   ├── advice_templates.yaml      # Fallback deterministic templates
│   ├── plan_templates.yaml        # Phase 2 canonical plan templates & tool signatures
│   ├── investigation_rules.yaml   # Causal investigation thresholds & hypotheses
│   ├── alerts_config.yaml         # Multi-signal alert weights and suppression tiers
│   └── explanation_templates.yaml # Hedged sentences and explanation builders
├── docs/
│   ├── PLAN_PHASE1.md             # Phase 1 specification and stage roadmap
│   ├── PLAN_PHASE2.md             # Phase 2 Agentic Intelligence layer specification
│   ├── eval_report.md             # Phase 1 benchmark report
│   ├── eval_report_phase2.md      # Phase 2 evaluation benchmark report
│   ├── decisions.md               # Architecture decision log (all stages)
│   └── demo_script_phase2.md      # 6-minute offline demo walkthrough script
├── scripts/
│   ├── run_eval.py                # Phase 1 evaluation runner
│   ├── run_eval_phase2.py         # Phase 2 evaluation runner
│   └── generate_sample_report.py  # Sample report generator
├── src/copilot/
│   ├── alerts/                    # Adaptive alert signal computation & rules
│   ├── audit/                     # Append-only audit logging & events
│   ├── bank/                      # Account Aggregator connector & synthetic generator v3
│   ├── cli/                       # Rich Typer CLI commands (ask, whatif, goals, timeline)
│   ├── core/                      # Intent router, investigation, simulation, timeline
│   ├── db/                        # SQLite connection, migrations, phase 2 schema, repo
│   ├── eval/                      # Phase 1 & Phase 2 evaluation harness
│   ├── goals/                     # Goal impact and feasibility forecasting
│   ├── governance/                # Policy enforcement & execution choke point
│   ├── llm/                       # Provider interface, PII redactor, prompt cache
│   ├── models/                    # Pydantic domain models & agentic schemas
│   ├── planner/                   # Dynamic LLM planner & deterministic PlanValidator
│   ├── review/                    # Monthly Review builder & Jinja2 renderers
│   ├── tools/                     # Tool specifications, registry, executor, alerts, whatif
│   ├── ui/                        # Minimal Streamlit UI blueprint
│   └── workflow/                  # LangGraph autonomous state graph & agentic nodes
├── tests/                         # 564 tests covering all layers
│   ├── cli/                       # CLI integration tests
│   ├── core/                      # Domain logic, money arithmetic, intent tests
│   ├── db/                        # Database schema, repo, and migration tests
│   ├── eval/                      # Evaluation harness unit tests
│   ├── golden/                    # Phase 1 & Phase 2 golden invariant tests
│   ├── planner/                   # Planner and validator tests
│   ├── tools/                     # Tool execution and governance tests
│   └── workflow/                  # LangGraph workflow tests
└── pyproject.toml                 # Package definition & dependencies
```
