# Finance Copilot

An autonomous personal finance and budgeting copilot designed for students in India.

Finance Copilot ingests bank statements, classifies messy UPI transactions, discovers recurring subscriptions and transfers, monitors budgets, detects spending anomalies, and compiles versioned monthly financial reviews with mathematically verified advice.

---

## Architecture & Safety Firewalls

```
                ┌──────────────────────────────────────┐
                │   User Interfaces (CLI / Streamlit)  │
                └──────────────────┬───────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │    LangGraph Autonomous Workflow     │
                └──────────────────┬───────────────────┘
                                   │
                                   ▼
        ┌────────────────────────────────────────────────────────┐
        │       Governance Firewall & Execution Choke Point       │
        │           (`execute_tool(ctx, tool_name, ...)`)        │
        └───────┬──────────────────┬──────────────────┬──────────┘
                │                  │                  │
                ▼                  ▼                  ▼
       ┌────────────────┐  ┌───────────────┐  ┌───────────────┐
       │ Financial Tools│  │ Bank Ingestion│  │ Advice Engine │
       │ (Budgets, Calc)│  │ (AA Consents) │  │ (& Validator) │
       └────────┬───────┘  └───────┬───────┘  └───────┬───────┘
                │                  │                  │
                └──────────────────┼──────────────────┘
                                   ▼
        ┌────────────────────────────────────────────────────────┐
        │            SQLite Core Engine & Audit Trail            │
        │        (Strict Tables, Append-Only Triggers, Undo)      │
        └────────────────────────────────────────────────────────┘
```

### Safety & Accounting Invariants
1. **Deterministic Integer Paise:** All money amounts are stored and calculated as integer paise (`₹1.00 = 100 paise`). Floats are strictly rejected to eliminate precision drift.
2. **Execution Choke Point:** No tool handler can be called directly. Every action routes through `execute_tool(ctx, ...)` where policy is enforced and every action is audited.
3. **No Money Movement:** Read and logical write operations only; no money movement tools exist in the system (enforced by automated structural tests).
4. **Multi-Tier Categorization Hierarchy:** Follows strict precedence: `User Override` > `Categorization Rules` > `Local Cache` > `Redacted LLM` > `Review Queue`. The agent is strictly prevented from overwriting user category choices.
5. **PII Redaction & LLM Quarantine:** Transaction narrations, account IDs, and user details are redacted prior to LLM calls. LLM failures degrade safely to the review queue and never crash the workflow.
6. **Advice Grounding Firewall:** Generated advice must cite deterministic `Finding` objects. The advice validator extracts all numbers, currency figures, and percentages; any ungrounded figure is rejected and triggers deterministic template fallback.
7. **Idempotent Ingestion:** Re-syncing bank records with identical Account Aggregator sessions inserts 0 duplicate records.

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

Finance Copilot provides a rich terminal CLI with formatted tables:

```bash
# Initialize database schema
copilot init-db

# Seed synthetic student financial data (3 months, 2 accounts)
copilot seed --user-id u1

# View account balances and overall financial state
copilot state --user-id u1

# List transactions with review status
copilot txns --month 2024-02

# Run full autonomous LangGraph workflow with interactive human review
copilot run --interactive

# Generate versioned Monthly Review report (Markdown + HTML)
copilot review-month 2024-02

# Query immutable audit log with before/after state diffs
copilot audit
```

### 2. Streamlit Web Blueprint

Launch the minimal web interface:

```bash
streamlit run src/copilot/ui/app.py
```

The Streamlit UI provides 5 core tabs:
- **📊 Financial Overview:** Live account balances, budget burn progress bars, and recent spend.
- **📋 Review Queue (HITL):** Uncategorized / low-confidence transactions with one-click category assignment.
- **💡 Advice Approvals:** Pending advice recommendations with Approve and Reject actions.
- **📑 Monthly Review Viewer:** Interactive viewer for versioned monthly financial reviews.
- **📜 Audit Trail & Undo:** Reversible system actions with one-click undo buttons.

### 3. Evaluation & Benchmarks

Run the deterministic golden evaluation harness across multiple held-out seeds:

```bash
# Run evaluation via CLI
copilot eval

# Or execute standalone script
python scripts/run_eval.py
```
Outputs a detailed benchmark report at `docs/eval_report.md`.

---

## Test Suite & Code Quality

Run tests across the entire codebase:

```bash
# Run all 397 unit, golden, and integration tests
pytest -v

# Run golden invariant scenarios specifically
pytest tests/golden/test_golden_scenarios.py -v

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
│   └── advice_templates.yaml      # Fallback deterministic templates
├── docs/
│   ├── PLAN_PHASE1.md             # Complete specification and stage roadmap
│   ├── eval_report.md             # Benchmarking and accuracy report
│   ├── decisions.md               # Architecture decision log
│   └── demo_script.md             # Offline demo walkthrough script
├── scripts/
│   ├── run_eval.py                # Standalone evaluation runner
│   └── generate_sample_report.py  # Sample report generator
├── src/copilot/
│   ├── audit/                     # Append-only audit logging & events
│   ├── bank/                      # Account Aggregator mock connector & ingestion
│   ├── cli/                       # Rich Typer CLI commands & tables
│   ├── core/                      # Money, timeutil, errors, and domain math
│   ├── db/                        # Migrations, connection pooling, repository
│   ├── eval/                      # Multi-seed evaluation harness
│   ├── governance/                # Policy enforcement & check engine
│   ├── llm/                       # Provider interface, PII redactor, prompt cache
│   ├── models/                    # Pydantic domain models & schemas
│   ├── review/                    # Monthly Review builder & Jinja2 renderers
│   ├── tools/                     # Tool specifications, registry, and executor
│   ├── ui/                        # Minimal Streamlit UI blueprint
│   └── workflow/                  # LangGraph state machine & node graph
├── tests/                         # 397 tests covering all layers
└── pyproject.toml                 # Package definition & dependencies
```
