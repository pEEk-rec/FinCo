# verify

How an agent checks itself before anything reaches you.

FinCo has one rule for anything a model or an agent produces: code checks it before it's used.
Every verifier answers the same way, `(holds, how)` (a yes or no, plus a short reason), so the
agent kernel and the traces can treat them alike and a dropped item always says why it was
dropped.

| Verifier | What it checks |
| --- | --- |
| `claims.py` | every number in a sentence appears in the figures that were actually computed |
| `agents/checkin.py: verify` | a check-in candidate is recomputed along a second, independent path |
| `workflow/reviewer.py` | a multi-agent answer covers every sub-question and is grounded; one revision at most |
| `planner/validator.py` | a plan only uses allowed tools with valid arguments, within its step budget |
| `understand/calibration.py` | a categorisation stage is only believed as far as its record on your answers |

The checks stay next to the code that needs them when they depend on its details. This package
holds the shared ones and the list above, so there's one place to look.
