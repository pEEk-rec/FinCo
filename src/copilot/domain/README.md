# domain

The money logic. Pure, deterministic functions in integer paise, with no model calls, no hidden
clock and no network. If a number appears on screen, it was computed here (or in `personal/`).

| Module | What it works out |
| --- | --- |
| `forecast.py` | where this month's spend is heading |
| `anomalies.py` | payments that stand out from your own history |
| `patterns.py` | transfers between your own accounts, and recurring payments |
| `alerts.py` | which budget alerts are worth raising, scored on several signals and damped when unsure |
| `goals.py` | whether a goal is on track, and what it needs per month |
| `whatif.py` | "what if I spent Rs 2,000 more on food for three months?", without changing anything |
| `commitments.py` | rent, EMIs, subscriptions and SIPs: due dates and which transaction paid which occurrence |
| `calendar.py` | a day-by-day projection of your balance over the coming weeks |
| `buckets.py` | virtual buckets that set money aside without moving it |
| `contributions.py` | splitting spare money across goals in the order you chose, and the trade-offs |
| `readiness.py` | whether your reserves and cash flow make investing sensible yet (not *what* to invest in) |
| `essentials.py` | which categories count as essential, so FinCo never suggests cutting them |

The invariants are tested directly. Decompositions and simulations always add up to the paisa. A
what-if never writes to the database. The same inputs always give the same output.
