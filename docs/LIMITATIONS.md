# Limitations

What FinCo does not do yet, and where its evidence is thin. Nothing here is hidden elsewhere; the
evaluation page ([EVALUATION.md](EVALUATION.md)) has the matching numbers.

## What was and was not tested against the real world

- **The bank in the demo is synthetic.** The history is generated from today's date so the current
  month is never empty. The Account Aggregator link has been run against a local fake, not a live
  gateway, and a real sandbox needs your own credentials.
- **Bank SMS wording comes from published alert styles.** The golden corpus is hand-written (five
  banks, 32 alerts). The webhook reads any bank-style sender, so an unfamiliar wording is dropped
  with a reason in the log rather than guessed.
- **The evaluations use simulated people and a simulated model.** The structure and the targets carry
  over to real use; the exact percentages will not.
- **The weekly check-in has run on synthetic data and the demo**, not on weeks of real use. Its
  thresholds are starting values in `config/checkin.yaml`.

## Capture

- **UPI Lite** payments appear only as a daily summary, so they cannot be captured one by one.
- **Push notifications need HTTPS**, and on iPhone the app must be added to the Home Screen first.
  Delivery depends on the platform. The in-app card works without them.
- **A phone macro is the capture path on Android.** It needs SMS permission and unrestricted
  battery use, and some phones stop background apps. iPhone has no equivalent.
- **Automatic tags are not perfect.** About 86% were right in simulation, lowest for a person paid
  for several reasons.

## Categorising and understanding

- **A new shop is always asked once.** A model alone never labels it. That is the price of never
  mislabelling silently.
- **The brand dictionary is a few dozen well-known brands**, written by hand.
- **Without a model, Review's one-tap guesses are the most-used categories**, not guesses about the
  shop. Every category is one tap away under "Choose any category"; a configured model gives better
  first guesses.
- **Hinglish covers common phrasing, not every word order.** Held-out accuracy is 77.8%.
- **Reading a question by rules is 75% accurate on held-out phrasing.** A model improves on
  paraphrases, but that path was checked on only 25 recorded questions.
- **The profile interview is a fixed list**, not a conversation, so every stored value is one you
  typed or confirmed.

## Product gaps

- No web screen yet for shared expenses, rule proposals or the per-transaction "Why?". They work
  through the API and `copilot me ...` / `copilot understand why`.
- A subscription's price changes and renewals are detected, but only you can say whether you still
  use it.
- "Beyond your usual range" is noisy with little history: with six earlier months a quiet month is
  flagged about one time in seven by chance.

## Engineering

- **One user, one machine.** The API is token-protected and listens on localhost unless started with
  `--lan`. It is not built for many users, and SQLite takes a brief write lock for every governed
  call, so heavy parallel load would queue.
- **The agent graph keeps its checkpoints in memory.** A production deployment would use a
  persistent store.
- **The session token travels in the URL fragment** on first open. It never reaches a server log, but
  it is a development convenience, not real sign-in.
- **API keys.** The model keys live in a local `.env`, which is git-ignored. Rotate any key that has
  been shared before publishing.
