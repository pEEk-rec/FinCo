# Finance Copilot — 6-Minute Phase 2 Offline Demo Script

This script walks through the end-to-end interactive demo of **Finance Copilot (Phase 2 Agentic Intelligence Layer)** using the unified CLI (`copilot`). It runs completely offline against deterministic synthetic data, demonstrating autonomous planning, intent parsing, causal investigation, goal tracking, what-if simulation, adaptive alerting, explainable recommendations, and the activity timeline.

---

## Prerequisites

Ensure your virtual environment is active:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

Set UTF-8 console encoding on Windows:

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## 6-Minute Interactive Flow

### Step 1: Initialize DB & Seed Deterministic Data
Initialize SQLite schema migrations (001, 002, and 003) and seed 3 months of synthetic transactions:

```bash
copilot init-db
copilot seed --months 3 --seed 42
```

Approve the generated mock Account Aggregator consent so data flows seamlessly:
```bash
copilot consent list
copilot consent approve <consent_id>
```

---

### Step 2: Goal-Aware Planning — Add Financial Goals
Define an active goal with target paise, user-maintained current savings, and target deadline:

```bash
copilot goals add "MacBook Pro Fund" "₹1,50,000" --kind purchase --current 30000 --deadline 2026-12-31 --priority 1
copilot goals list
```

---

### Step 3: Natural Language Copilot — "copilot ask"
Ask a natural language financial question. The agent autonomously parses intent, gates unsafe/prohibited actions, formulates a validated plan, executes read/compute tools through the executor, and synthesizes findings:

```bash
copilot ask "how much did I spend in food in September 2026?" --clock 2026-09-15T12:00:00Z
```

Verify refusal safety guardrails on out-of-scope or financial advice:
```bash
copilot ask "which mutual fund should I buy for 50% returns?"
```
*Expected: Request is immediately refused by deterministic governance guardrail with compliant guidance.*

---

### Step 4: Causal Anomaly & Spend Investigation
Directly investigate why a budget or category changed without freeform guessing:

```bash
copilot investigate --category cat_food --month 2026-09
```
*Outputs: Exact mathematical decomposition ($V + T + new + stopped + residual \equiv \Delta S$), evaluated hypothesis catalogue, evidence items, confidence score, and unexplained residual.*

---

### Step 5: What-If Simulation
Simulate the consequence of an upcoming purchase or spend modification over a 6-month horizon:

```bash
copilot whatif add-spend --amount 80000 --months 6 --clock 2026-09-15T12:00:00Z
```
*Outputs: Month-by-month surplus projection, budget limits impact, and goal status impacts without touching any underlying financial records.*

Compare two competing choices side-by-side (e.g., upfront payment vs. split expense):
```bash
copilot whatif compare --amounts 80000,40000 --months 6 --clock 2026-09-15T12:00:00Z
```

---

### Step 6: Adaptive Multi-Signal Alerts
Evaluate adaptive alerts for the current period. Alerts combine budget overrun run-rates, robust z-score history deviations, anomaly scores, and goal risks:

```bash
copilot alerts evaluate --period 2026-09
copilot alerts list
```

---

### Step 7: Explainable Recommendations
Every drafted recommendation exposes its evidence, calculation formulas, assumptions, tools used, and relevant memories:

```bash
# View full explanation of an advice item
copilot explain rec_demo_1
```

Approve or reject the recommendation:
```bash
copilot decide rec_demo_1 approve
```

---

### Step 8: Agent Activity Timeline
Inspect the complete chronological audit of agent tasks, plan steps, tool observations, simulations, alerts, and decisions:

```bash
copilot timeline
```
Or stream machine-readable JSON for frontend dashboards:
```bash
copilot timeline --json
```

All 9 steps execute deterministically offline in under 6 minutes.
