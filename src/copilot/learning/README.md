# learning

Small learners that adjust FinCo's behaviour from your feedback, and never more than they should.

There's no model training here. One person's data is far too little for that, and you'd lose the
ability to see and undo what was learned. Instead each learner keeps two counts for a thing (how
often it worked, how often it didn't), starting from a modest prior so one reaction never swings
it far. Its belief is the posterior mean. **`beta.py`** holds that arithmetic, and every learner
uses it, so they all move the same way and can all be inspected and reset the same way.

| Learner | What it learns |
| --- | --- |
| `feedback.py` | how much to trust each kind of suggestion, from your accept/reject/ignore; bounded multipliers |
| `nudges.py` | which time (morning, evening, weekend) and tone (gentle, direct, numbers) you actually act on |
| `offers.py` | which challenge families are worth offering (Thompson sampling, with logged propensities) |
| `experiment_loop.py` | what finished experiments teach the memory and the recommendations |

Two more learners live next to what they tune: `capture/learning.py` (which guess signals to trust)
and `understand/calibration.py` (how far to believe each categorisation stage).

Every learner's multiplier is clamped (`config/learning.yaml`), so no signal can be switched off
or take over. `copilot learning` shows the state and can reset it.
