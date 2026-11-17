# conversation

Reading what you asked, and answering from computed figures, never invented ones.

- **`intent.py`** is the front door for a question. It classifies what's being asked (spend in a
  period, a change, a what-if, a goal) and fills in the slots: the period, the category, the
  amount. It also refuses what FinCo must never do: move money, take an OTP or a PIN, give
  investment tips, predict markets. Each refusal points to what FinCo *can* do instead.
- **`hinglish.py`** runs first, so "is mahine khane pe kitna gaya?" reads like "how much on food
  this month?". It's a small, config-driven translator (`config/hinglish.yaml`), not a model.
- **`investigation.py`** answers "why did this change?" with a closed list of hypotheses and
  evidence functions. The decomposition always adds up: the change equals the fixed part, plus the
  variable part, plus what's unexplained. "Inconclusive" is an allowed answer.
- **`answers.py`** composes the reply from tool results only. A model may rephrase the reply, but
  any number in its version that a tool didn't produce is removed (`verify/claims.py`); if that
  leaves nothing usable, the rule-written answer is shown.
- **`advice.py`** is the validator for monthly-review advice, with deterministic templates when no
  model is available or the model's draft fails a check.
