# Evaluation

Every evaluation suite is offline and deterministic. It declares its targets before it measures, and
a missed target stays in the report instead of being tuned away. List and run them with:

```bash
copilot eval --list
copilot eval --suite categorise
```

The full generated reports are alongside this file (`eval_report_*.md`). This page is the summary.

## Software tests

| Layer | What it covers |
| --- | --- |
| Backend (`pytest`) | Unit tests, a golden corpus of bank SMS, API contract tests, security tests, and a one-user journey over the HTTP API. About 1,740 tests. |
| Frontend unit | Components, formatting, the live Ask stream parser. |
| Frontend checks | Type check, lint, contrast on every colour pair used, a rule that no literal figure appears in a screen, and a check for missing glyphs. |
| End to end | Playwright drives a real browser through connect, import, live payments, review, Ask, goals and challenges, with an accessibility scan (axe) on each screen. |

## Categorisation: does it label payments correctly?

Simulated people and a simulated model, so read the structure and the targets, not the exact
percentages.

| Check | Result | Target |
| --- | --- | --- |
| Accuracy on labels it applied | 97.0% (old pipeline 82.2%) | at least 95% |
| Coverage of shop payments after two weeks of learning | 85.3% (old 68.1%) | at least 85% |
| Calibration error | 1.4 points | at most 5 |
| Entity resolution, precision and recall | 1.000 and 1.000 | at least 0.99 and 0.9 |
| People labelled automatically | 0 of 112 (old pipeline 29, of which 16 wrong) | 0 |
| Accuracy with an always-wrong model | 97.0% | at least 95% |

The last row is the safety result: because a model only suggests, a bad model costs extra
questions (the one-tap guess is right 65% of the time with a strong model, 0% with a wrong one) and
never a wrong silent label.

## Capture: reading bank alerts

| Check | Result |
| --- | --- |
| Parse accuracy on the golden SMS corpus (five banks, 32 alerts) | 100%, with 0 unparsed |
| OTPs and unknown senders dropped | 11 of 11 |
| Reconciliation with the statement | 100%, with 0 double counts |
| Questions per active day (median) | 1.0 (target at most 3) |
| Correct guess ranked first, held out | 65% (target 50%); in the top three, 93% |
| Automatic tags that were right | 86% of 803. People paid for different reasons are the hard case |

The corpus is hand-written from published alert styles, not from real accounts. The webhook also
reads any bank-style sender; that path is covered by unit tests rather than the corpus.

## Agent behaviour

| Area | Result |
| --- | --- |
| Refusals (money movement, investing, credentials) | 100% precision and recall |
| Planner picks exactly the needed tools, no extras | 100% exact set, 0 extra tools |
| Rejects adversarial and disallowed plans | 100% |
| False explanation on months with no real cause | 0% |
| Alerts: quiet in an ordinary month | 100%, and 66.7% fewer alerts than a raw threshold |
| Calendar and budget invariants (paise conserved, shortfalls found) | 100% |
| Hinglish intent reading, held out | 14 of 18 (77.8%) against a 70% target |

## Checks that do not pass

- **Intent reading on held-out phrasing is 75% against an 80% target** with the rule-based reader.
  A configured model helps on paraphrases, but that path was checked on only 25 recorded questions.
- **Spotting a real cut in spending is noisy with little history.** With six earlier months a quiet
  month is called "beyond your usual range" about one time in seven by chance. The wording never says
  "significant".
- **Anomaly detection has low F1 (0.05) against a 0.70 target** on the Phase 1 synthetic benchmark,
  because the detector needs at least three earlier data points per category.
  `eval_report.md` now shows this as FAIL rather than hiding it.
- **Finding the planted cause of a spending change succeeds 66.7% of the time** against targets of
  85% (standard) and 75% (hard). When it cannot find a cause it says so, and the false-explanation
  rate on months with no cause is 0%.
- **Entity extraction from questions is 63.6%** against an 85% target. A missing period or
  category triggers a clarifying question rather than a guess.

Earlier versions of two generated reports (`eval_report.md`, `eval_report_phase2.md`) printed PASS in
the status column regardless of the number. They now compare the measured value to the target, so
the misses above show as FAIL.
