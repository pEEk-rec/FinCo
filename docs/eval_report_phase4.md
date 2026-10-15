# Finance Copilot: Phase 4 Evaluation Report

Generated 2026-10-15 21:18 IST in 41.6s by `copilot eval --phase 4`.
Held-out seeds: `[999, 12345, 88888]`. Dev seeds: `[42, 101, 2024]`. Trials per seed: 40. Nothing was tuned on the held-out seeds.

**Result: some checks FAIL (see weak spots)**

## 1. Verification matrix

| Check | Measured | Target | Result |
|---|---|---|:---:|
| A real ~35% cut is told apart from noise | detected 51.7%, false alarms 18.3% (x2.8) | detection >= 2.5x the false-alarm rate | PASS |
| False 'beyond usual range' on null windows | 18.3% (rank-only: 19.2%) | <= 14.3% + 6.4 points (2 standard errors) | PASS |
| Minimum-effect rule lowers false alarms | 19.2% -> 18.3% | not higher than without the rule | PASS |
| Declared historic exception set aside | 100.0% | 100% | PASS |
| Exception pauses and extends by the exact days | 100.0% | 100% | PASS |
| Recategorisation-assisted wins flagged | 96.2% of 53 | >= 90% | PASS |
| Genuine wins not falsely flagged | 0.0% of 36 | 0% | PASS |
| Trigger weekend_heavy | precision 100.0% / recall 100.0% | >= 95% / >= 95% | PASS |
| Trigger budget_exceeded | precision 100.0% / recall 100.0% | >= 95% / >= 95% | PASS |
| Trigger goal_at_risk | precision 100.0% / recall 100.0% | >= 95% / >= 95% | PASS |
| Trigger low_tagging_completeness | precision 100.0% / recall 100.0% | >= 95% / >= 95% | PASS |
| Trigger many_open_reviews | precision 100.0% / recall 100.0% | >= 95% / >= 95% | PASS |
| Safety-filter violations | 0 | 0 | PASS |
| Thompson regret below random (held-out) | 13.39 vs 27.27 | thompson < random | PASS |
| Rest-week violations (two abandoned in a row) | 0 | 0 | PASS |
| Quiet-week violations (offers keep being dismissed) | 0 | 0 | PASS |
| Off-policy estimate within its bound (held-out) | 9/9 | >= 80% | PASS |
| Intent accuracy on held-out phrasing | 75.0% | >= 80% | FAIL |
| Confidently wrong intent (not just 'unknown') | 5.0% | <= 5% | PASS |
| Other intents not misread as Phase 4 | 100.0% | 100% | PASS |
| Model-path replay reproduces the recordings | 100.0% | 100% | PASS |
| Tool minimality | 100.0% | 100% | PASS |
| Trajectory accuracy | 100.0% | 100% | PASS |
| Safety scan violations | 0 | 0 | PASS |

## 2. Measurement: does it find real changes and ignore noise?

Persona `reducer` spends about 35% less in the window; persona `null` does not change. Baseline K = 6, 120 and 120 trials. Minimum-effect rule: 10% of median and at least 200 rupees.

| Measure | Value |
|---|---|
| True effect reported as beyond the usual range | 51.7% (without the minimum-effect rule: 52.5%) |
| Null window reported as beyond the usual range | 18.3% |
| ...same, rank rule alone (no minimum effect) | 19.2% |
| Theoretical false rate for rank alone, 1/(K+1) | 14.3% |
| Null window that still met a 20% cut target by chance | 18.3% |
| Mean measured effect on the reducer | 30.0% (true: about 35%) |
| Mean rank p-value on null windows | 56.9% (about 50% if calibrated) |
| Trials with no baseline | 0 |

Sensitivity to how much history is compared (held-out seeds, not used for any decision):

| Windows compared (K) | True effect reported | Null window reported | Theoretical false rate |
|--:|--:|--:|--:|
| 6 (the default) | 51.7% | 18.3% | 14.3% |
| 12 | 45.0% | 5.0% | 7.7% |

Comparing against 12 windows instead of 6 moves the false-alarm rate from 18.3% to 5.0% and detection from 51.7% to 45.0%, at the cost of needing more weeks of history first. The default of six windows is a product decision; this table is the evidence for revisiting it.

The wording only ever says a value was lower than the user's previous comparable periods; it never says the challenge caused it.

## 3. Exceptions

| Measure | Value |
|---|---|
| Declared festival window in the history set aside | 100.0% |
| Same baseline inflated when the exception is NOT declared | 100.0% |
| Active experiment paused and extended by exactly the covered days | 100.0% |

## 4. Integrity (uses the real recategorise tool)

| Measure | Value |
|---|---|
| Target met only by moving payments to another category | 53 trials |
| ...of those, flagged for the user to confirm | 96.2% |
| Genuine wins (no recategorising) | 36 trials |
| ...of those, wrongly flagged | 0.0% |

## 5. Personalisation

Each trigger against patterns injected into synthetic users (about half the users have each pattern):

| Trigger | Precision | Recall | TP | FP | FN |
|---|--:|--:|--:|--:|--:|
| weekend_heavy | 100.0% | 100.0% | 49 | 0 | 0 |
| budget_exceeded | 100.0% | 100.0% | 58 | 0 | 0 |
| goal_at_risk | 100.0% | 100.0% | 61 | 0 | 0 |
| low_tagging_completeness | 100.0% | 100.0% | 55 | 0 | 0 |
| many_open_reviews | 100.0% | 100.0% | 52 | 0 | 0 |

Safety filter: 45 random category sets (including rent, utilities, EMI and custom names), with a model that proposes essential categories on purpose. 133 offers inspected; **0 targeted an essential category**. 648 proposed specs were rejected and audited.

## 6. Offer policy

52-week simulation, three personas with preference drift. Regret is measured against the best fixed offer in hindsight (lower is better).

| Policy | Dev seeds (overall) | Held-out seeds (overall) | Offers per week |
|---|--:|--:|--:|
| thompson | 13.94 | 13.39 | 3.0 |
| greedy | 13.28 | 12.61 | 3.0 |
| random | 23.83 | 27.27 | 2.9 |

Per persona, held-out seeds:

| Persona | thompson | greedy | random |
|---|--:|--:|--:|
| ThriftyCook | 13.85 | 9.85 | 30.51 |
| BusyCommuter | 5.39 | 11.39 | 31.39 |
| FickleDrifter | 20.92 | 16.59 | 19.92 |

Off-policy evaluation on held-out seeds (logs from the random policy, self-normalised estimator): mean absolute error 0.099, true value inside the estimator's own error bound in 9/9 cases (100.0%).

Rest weeks: a persona that accepts every offer and abandons each was offered something in 18 of 52 weeks; violations of the rest rule (nothing for two weeks after two abandoned in a row): 0.

Quiet weeks: a persona that dismisses every offer was offered something in 27 of 52 weeks; violations of the quiet-week rule (nothing the week after six dismissed in a row): 0.

## 7. Agent

Held-out phrasing, written separately from the patterns (40 configured examples were used to build them and are not counted here).

| Intent | Correct | Total | Accuracy |
|---|--:|--:|--:|
| start_experiment | 7 | 12 | 58.3% |
| experiment_status | 11 | 12 | 91.7% |
| what_worked | 7 | 12 | 58.3% |
| challenge_suggestions | 10 | 12 | 83.3% |
| progress_summary | 10 | 12 | 83.3% |

Held-out accuracy 75.0% (the dev set the patterns were tuned on: 100.0%; the gap is the cost of tuning). Confidently wrong rather than unsure: 5.0%. Other intents not misread as Phase 4: 100.0%. Tool minimality 100.0%, trajectory accuracy 100.0%.

The figures above are the rule-based fallback classifier. With a model configured, the model reads the question first and the rules are the fallback:

| Recording | Questions | Model right | Rules right (same questions) |
|---|--:|--:|--:|
| names only, set A (first recording) | 25 | 84.0% | 88.0% |
| with glossary, set A (not independent: written after set A's misses) | 25 | 100.0% | 88.0% |
| with glossary, set B (untouched, independent) | 25 | 96.0% | 72.0% |

Each recording is a fixed set of questions asked once of the live providers and saved; this report replays them without any call. Replay reproduces every recording exactly. The first recording showed the model confusing starting a challenge with being offered one, and answering rewards questions as goal questions, because it was given intent names without meanings. A short glossary of what each intent means (`config/intent_glossary.yaml`) fixed that on set A, but set A is not evidence for the fix. Set B was recorded after the glossary was written and never used to change it.

- names only, set A (first recording): miss: start_experiment: 'can you set me up with a challenge to eat out less' -> challenge_suggestions
- names only, set A (first recording): miss: start_experiment: 'put me on a challenge to lower my food spending' -> challenge_suggestions
- names only, set A (first recording): miss: progress_summary: 'how many badges have I collected' -> memory_query
- names only, set A (first recording): miss: progress_summary: 'what level am I at' -> goal_progress
- with glossary, set B (untouched, independent): miss: start_experiment: 'I want to take on a savings challenge this fortnight' -> challenge_suggestions

## 8. Safety scans

48 strings scanned (challenge titles and rationales, narration templates, badges, reward rules) for pressure phrases, encouragement to skip essentials, social comparison and causal claims. Violations: **0**. Reward allowlist valid: True.

## 9. Weak spots

- Intent accuracy on held-out phrasing: measured 75.0%, target >= 80%
- intent miss: start_experiment: 'can you set me up with a challenge to eat out less' -> unknown
- intent miss: start_experiment: 'put me on a challenge to lower my food spending' -> unknown
- intent miss: start_experiment: 'start something that helps me spend less on subscriptions' -> list_recurring
- intent miss: start_experiment: 'build me an experiment around cutting down my cab rides' -> unknown
- intent miss: start_experiment: 'let's try cutting my dining out budget for a few weeks' -> check_budget
- intent miss: experiment_status: 'how many days remain in my experiment' -> unknown
- intent miss: what_worked: 'what has helped me spend less in the past' -> unknown
- intent miss: what_worked: 'what did I do before that cut my spending' -> unknown
- intent miss: what_worked: 'remind me which experiments were helpful' -> unknown
- intent miss: what_worked: 'list the things that worked for my savings' -> unknown

## 10. Not run

- LLM-path quality on a recorded cassette set: not run in this session (needs `--live`).
- Live provider calls: none made; every LLM interaction above used the scripted fake client.
