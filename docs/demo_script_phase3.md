# Finance Copilot — Phase 3 Advanced Multi-Agent Demo Script

This script walks through the end-to-end interactive demo of **Finance Copilot (Phase 3 Multi-Agent Architecture & Governance Layer)** using the unified CLI (`copilot`). It runs completely offline against deterministic synthetic data, showcasing:
- Multi-agent orchestration with specialized sub-agents (Cashflow, Buckets, Goals, Risk)
- Dynamic commitments & calendar shortfall projection
- Virtual bucket allocations, linked goals, and governed reallocation drafts
- Investment readiness assessment & safety guardrails
- Contribution planning & Pareto-optimal trade-off analysis
- Behavioural memory formation, contextual exceptions, and selective forgetting
- Bounded feedback learning & sensitivity damping
- Background job leases & operational telemetry (`copilot ops`)
- Live MCP integration (`finco://` resources and `ask` tool)

---

## Prerequisites

Activate virtual environment:
```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## Complete Demo Walkthrough (12 Steps)

### Step 1: Initialize Database & Seed Persona
Initialize SQLite database with migrations (001 through 004) and seed the structured persona:
```bash
copilot init-db --db demo_phase3.db
copilot seed --db demo_phase3.db --months 4 --seed 42
```
Approve pending Account Aggregator consent:
```bash
copilot consent approve <consent_id> --db demo_phase3.db
```

---

### Step 2: Accept Suggested Commitments
Scan recurring outflows and accept high-confidence detected commitments:
```bash
# Suggest commitments from transaction history
copilot commitments suggest --db demo_phase3.db

# Accept or add fixed rent commitment
copilot commitments add "Apartment Rent" 25000 --cadence monthly --due "fixed_day:5" --db demo_phase3.db
copilot commitments list --db demo_phase3.db
```

---

### Step 3: Create Goal & Link to Virtual Bucket
Establish a targeted savings goal and pair it with a virtual bucket:
```bash
# Create Goal
copilot goals add "Ladakh Trip" 60000 --kind purchase --deadline 2024-09-01 --priority 1 --db demo_phase3.db

# Create virtual bucket for the trip
copilot buckets create "Ladakh Trip" --kind goal --policy accumulate --db demo_phase3.db

# Link goal to the bucket
copilot goals link-bucket g1 bk_ladakh --db demo_phase3.db
copilot buckets list --db demo_phase3.db
```

---

### Step 4: Map Categories & Allocate Monthly Surplus
Map discretionary categories and allocate funds to virtual buckets:
```bash
# Allocate initial funds into Ladakh bucket
copilot buckets allocate bk_ladakh 15000 --db demo_phase3.db
copilot buckets list --db demo_phase3.db
```

---

### Step 5: Cash Flow Calendar & Shortfall Detection
Generate a rolling 60-day calendar forecast to identify upcoming liquidity shortfalls:
```bash
copilot calendar --horizon 60 --db demo_phase3.db
```
*Expected Output:* Running daily balances, upcoming commitments, and highlighted shortfall risk before salary credit.

---

### Step 6: Multi-Agent Parallel Planning ("Can I take the trip?")
Ask a complex multi-domain question that triggers multi-agent decomposition:
```bash
copilot ask "Can I take the Ladakh trip and still keep my monthly SIP contribution?" --db demo_phase3.db
```
*What happens under the hood:*
1. **Supervisor Agent** decomposes question into sub-questions.
2. **Parallel Specialists** (CashflowSpecialist, BucketSpecialist, RiskSpecialist) execute read/compute tools concurrently.
3. **Critic/Reviewer** inspects outputs for hallucination and mathematical soundness.
4. **Synthesizer** generates answer with exact rupee figures and tradeoff options.

---

### Step 7: Investment Readiness Assessment
Assess whether the user has sufficient liquidity cushion and low debt to invest:
```bash
copilot readiness --db demo_phase3.db
```
*Expected Output:* Readiness score, status (`ready_with_conditions`), emergency cushion in months of burn, and pass/fail criteria checklist.

---

### Step 8: Contribution Planning & Trade-offs
Simulate options to fund goals and compare alternatives:
```bash
# Plan contributions across goals
copilot plan-contributions --horizon 12 --db demo_phase3.db

# Compare alternative allocation strategies
copilot trade-offs --alt '{"name":"Aggressive Trip","extra_sip":0,"trip_alloc":20000}' --db demo_phase3.db
```

---

### Step 9: Governed Reallocation Draft (Approve & Apply)
Reassign funds between virtual buckets via two-step governance:
```bash
# Create reallocation draft
copilot buckets reallocate bk_gadgets bk_ladakh 10000 --db demo_phase3.db

# Verify pending draft and decide
copilot buckets drafts --db demo_phase3.db
copilot decide approve <draft_id> --db demo_phase3.db
```

---

### Step 10: Contextual Exception & Alert Damping
Record a contextual festival exception to damp false-positive alerts:
```bash
# Record exception for festival season spending
copilot prefs set --key "contextual_exception:diwali" --value "travel" --db demo_phase3.db
copilot alerts evaluate --db demo_phase3.db
```
*Notice:* The alert reason includes `(Alert dampened by festival exception.)` without polluting permanent learning parameters.

---

### Step 11: Background Upkeep & Ops Telemetry
Execute background upkeep jobs and view system operational metrics:
```bash
# Run due background jobs under distributed lease
copilot jobs run-due --db demo_phase3.db

# Inspect operational telemetry (latency, token costs, parallel speedup)
copilot ops --db demo_phase3.db
```

---

### Step 12: Selective Forgetting & Audit Timeline
Inspect long-term memories, forget an item with verifiable deletion, and review the immutable timeline:
```bash
# List active memories
copilot memories list --db demo_phase3.db

# Forget a specific memory
copilot memories forget mem_travel_pref --db demo_phase3.db

# Verify audit trail
copilot memories audit --db demo_phase3.db
copilot timeline --db demo_phase3.db
```
