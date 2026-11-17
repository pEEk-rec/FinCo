# engagement

Experiments, challenges and progress: small tries at a better habit, measured honestly.

The idea is to compare you only with yourself. A challenge ("eat out twice a week instead of
four times") runs as an **experiment**: a baseline is frozen from your own history when it starts,
progress is measured against it with a fixed metric, and the review at the end says what happened
without claiming a cause it can't show.

- **`experiments.py`**: design and lifecycle (offered, active, paused, completed, abandoned).
- **`metrics.py`**: the metric catalogue. Each metric is a pure function of your data over a window,
  and not every metric is money (some count payments or days; `labels.py` names the units).
- **`baseline.py`**: baselines, outcomes, pace and integrity checks, in integer paise and basis
  points.
- **`challenges.py`**, **`adaptive.py`**: challenge templates fitted to your categories, and the
  daily detectors that notice when a challenge needs adjusting.
- **`self_competition.py`**, **`rewards.py`**: personal bests, forgiving streaks, XP and badges.
  Rewards only attach to allowlisted actions and never to spending more.
- **`recommendations.py`**, **`review_wording.py`**: explainable recommendations (evidence,
  confidence, and what would change the advice) and plain wording for experiment reviews.

Which challenge to offer next is learned by `learning/offers.py`.
