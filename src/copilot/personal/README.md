# personal

The personal model: what matters to you, and the plans built on it.

- **`profile.py`**: a small, typed values profile. It holds your income pattern, what you're saving
  for, how you like to be nudged, and what you'd rather not cut. Every value is labelled as
  **stated** (you said it) or **inferred** (FinCo suggested it from your data). An inferred value is
  only a suggestion until you confirm it. Some fields simply don't exist (religion, health, anything
  sensitive) and are refused. Every field can be forgotten.
- **`budget.py`**: the budget co-pilot. It splits a month's income in a fixed order: commitments
  first, then goals and savings, then essentials from your own history, then what's left for the
  rest. It doesn't plan until it knows your income. When the month goes off course, `replan` shows
  what to move and what that costs. A model never does the arithmetic here.
- **`subscriptions.py`**: what renews, when, for how much, and what changed (a price rise, a plan
  you stopped using), built on the recurring payments FinCo already detects.
- **`splits.py`**: shared expenses with roommates or on a trip: who paid, who owes whom, and the
  fewest settle-ups. It only records and shows. Settling up means two people agreeing, and no money
  moves here.
