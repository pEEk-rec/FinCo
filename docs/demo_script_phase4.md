# Finance Copilot — Phase 4 Behavioral Engagement & Gamification Demo Script

This script walks through the end-to-end interactive demo of **Finance Copilot (Phase 4 Behavioral Engagement & Gamification Layer)** using the unified CLI (`copilot`). It runs completely offline against deterministic synthetic data with an injected clock, showcasing:
- Objective, non-coercive opt-in challenge suggestions with explicit reasons
- Opt-in acceptance turning offers into active experiments
- Mid-experiment weekly check-ins with observational pace calculation
- A dated exception (a trip) that pauses the challenge on its own and offers to extend it
- Review generation using honest empirical quantile ranking against the user's own earlier comparable periods (K=6)
- Habit-building rewards: deterministic XP, level progression, badges, and personal bests
- Honest post-experiment feedback loop updating Beta conjugate priors
- Advice drafting citing past successful experiment outcomes without causal claims
- Simulator benchmark comparing Thompson sampling with a random policy
- Complete tamper-evident audit trail via `copilot timeline`

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

## Run it in one go

`scripts/demo_phase4.sh` runs every step below on a fresh database, offline, with `FINCO_LLM=off`
(so nothing leaves the machine and the output is repeatable):

```bash
bash scripts/demo_phase4.sh /tmp/demo_phase4.db
```

The steps are the same commands, shown one at a time. The persona's history ends on 2024-04-30, so
the demo uses `--clock` to say "it is now 1 May 2024". Without `--clock` the real date is used.

## Walkthrough (12 steps)

Set `DB=demo_phase4.db` and `EXP`, `OFFER`, `ADJ` to the ids printed by the earlier steps
(`scripts/demo_phase4.sh` reads them from the database for you).

### Step 1: Create the database, seed four months, approve consent, categorise
```bash
copilot init-db --db $DB
copilot seed --db $DB --months 4 --seed 42
copilot consent approve consent_seed_u1_42 --db $DB
copilot run --db $DB --year 2024 --month 2        # ingest and categorise (about 170 transactions)
```
The seeded persona stays inside its budgets, so no challenge has a reason to be offered yet. To give
one, set a food budget the persona went over in two of the last three months (this is the demo's
only direct database edit; the app itself never lowers a budget for you):
```bash
sqlite3 $DB "update budgets set limit_paise=300000 where category_id='food'"
```

### Step 2: See this week's offers
```bash
copilot challenges offers --clock 2024-05-01T10:00:00+05:30 --db $DB
```
Real output: one offer, `Delivery App Spend Cap`, difficulty `medium`, target `₹350`, with the reason
"Your typical merchant_group_spend is ₹447; ...". The target comes from the user's own history (the
median of six earlier comparable weeks), never from the model.

### Step 3: Accept it (opt-in)
```bash
copilot challenges accept $OFFER --clock 2024-05-01T10:00:00+05:30 --db $DB
copilot experiments list --db $DB
```
An active 7-day experiment, window 2024-05-01 to 2024-05-07, with its baseline frozen at that moment.

### Step 4: Mid-week check-in and pace
```bash
copilot experiments show $EXP --clock 2024-05-04T10:00:00+05:30 --db $DB
copilot experiments checkin $EXP going_well --clock 2024-05-04T10:00:00+05:30 --db $DB
```
Pace is `AHEAD`, `ON_PACE` or `BEHIND`, worked out from the numbers. Baseline shown: ₹161 to ₹910,
median ₹447, K=6.

### Step 5: Declare a trip (dated exception), auto-pause, accept the extension
```bash
copilot memory exception --category food --reason travel --from 2024-05-03 --to 2024-05-05 --db $DB
copilot experiments tick --clock 2024-05-04T12:00:00+05:30 --db $DB
copilot adjustments list --db $DB
copilot adjustments accept $ADJ --clock 2024-05-04T13:00:00+05:30 --db $DB     # the `extend` one
```
`adjustments list` shows `pause / exception_overlap_auto_pause / auto_applied_pause` (pausing is
harmless, so it needs no approval), `extend / exception_overlap_extend / proposed` and
`raise_target_optional / ahead_at_midpoint_wide_margin / proposed`. Only the user can accept the
other two; the paused days do not count against the window.

### Step 6: The review
```bash
copilot experiments tick --clock 2024-05-12T12:00:00+05:30 --db $DB
copilot experiments review $EXP --db $DB
```
Real output: "₹0, lower than all 6 of your previous comparable 10-day periods (usual range ₹161 to
₹910) ... says nothing about the reason for the difference. Your target was ₹350: reached."
Outcome `BEYOND_USUAL_RANGE`, rank p-value 14.28% (that is 1 in 7, the smallest possible with six
earlier periods, so the app calls it "beyond your usual range" and never "significant"). If a
payment was recategorised during the window the review says so and asks you to confirm with
`copilot experiments confirm $EXP`.

### Step 7: Progress, XP and personal bests
```bash
copilot progress --db $DB
```
Level 2 "Explorer", XP, unlocked badges, forgiving streaks and the personal best
(`merchant_group_spend`, 10 days, ₹0). Streak lengths are measured to today's date, so on this
2024 data they look huge; with live data they are real.

### Step 8: Feedback
```bash
copilot experiments feedback $EXP --difficulty 2 --helpful --repeat --clock 2024-05-12T13:00:00+05:30 --db $DB
```
The first feedback teaches the learning loop once; sending it again changes nothing.

### Step 9: What was learned
```bash
copilot learning show --db $DB
```
`challenge_template / delivery_cap`: alpha 3.0, beta 2.0, posterior 0.6000, multiplier 1.1000.
That raises the chance this template is offered again; it never forces it.

### Step 10: Ask what worked
```bash
copilot ask "what worked for me so far" --db $DB --clock 2024-05-13T10:00:00+05:30
```
The question is read as `what_worked`, and the plan runs exactly two read tools. The saved outcome
memory is available to advice drafting (worded like the review, never "caused"), but the terminal
answer is terse today ("Analyzed what_worked ..."); see `docs/known_issues.md`.

### Step 11: Offline policy comparison
```bash
copilot sim run --policy thompson --persona ThriftyCook --weeks 26 --seed 42
copilot sim run --policy random   --persona ThriftyCook --weeks 26 --seed 42
```
Real output (seed 42): Thompson total reward 40.00, regret 0.21, 47 completed; random 29.00, regret
11.21, 36 completed. One seed, one persona: an illustration, not a proof. The evaluation report
(`copilot eval --phase 4`, `docs/eval_report_phase4.md`) repeats this over many seeds.

### Step 12: Audit timeline
```bash
copilot timeline --db $DB
```
Every offer, acceptance, check-in, adjustment, review, XP award and badge, newest first, each with
the reason it happened.
