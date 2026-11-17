# understand

Working out what each payment was for: shops, not strings.

A bank writes the same shop a dozen ways (`SWIGGY8`, `Swiggy Ltd`, `swiggy8@ybl`). Labelling the
string means asking you a dozen times. FinCo labels the **shop** instead, so one answer covers every
spelling, and it only labels on its own when it has earned the right to on your data.

## The path one transaction takes

1. **`descriptor.py`** turns a narration like `UPI/628912345678/SWIGGY8/swiggy8@ybl/HDFC` into parts:
   the rail (UPI), the shop name (swiggy), the handle, the bank.
2. **`entities.py`** finds or creates the merchant entity behind those parts.
3. **`cascade.py`** walks the stages in order and stops at the first one it believes enough:

   | Stage | What decides |
   | --- | --- |
   | S0 | your own answer for this shop (never second-guessed) |
   | S1 | rules: config rules, rules you accepted, card category codes |
   | S2 | your nearest labelled shops, by name similarity |
   | S3 | the brand dictionary |
   | S4 | the model, shown your most similar labelled shops, one batched request |
   | S5 | ask you |

4. **`calibration.py`** decides how far to believe each stage. Every stage reports a raw score;
   calibration tracks how often that stage was actually right *for you* at that score and turns the
   claim into an honest probability (isotonic, so a higher score never means lower trust).
5. **`learn.py`** handles what's left. It asks the question worth the most first (how many payments
   one answer settles, how large they are, how unsure we are). It applies your answer to the shop,
   settles every waiting payment from it, teaches calibration, and may *propose* a rule. A proposed
   rule does nothing until you accept it.

Every decision keeps its stage, scores and the candidates considered, so "why is this Food?" always
has an answer (`/api/understand/why/{id}`).

## Also here

- **`ledger.py`** runs the cascade over the whole ledger, behind a switch so the old engine
  (`legacy_pipeline.py`) can still be compared or fallen back to.
- **`advisor.py`** is the model's seat in the cascade, behind an interface so tests use a fake.
- **`gold.py`** lets the owner measure accuracy on their own real transactions without anyone
  else seeing them. The gold set stays in `data/`, which git ignores.
- **`rules.py`**, **`category_resolution.py`**, **`config.py`** hold rule matching, mapping
  template hints to your categories, and strict config loading.

## Rules

A person is never labelled automatically and never shown to a model: what a payment to a friend was
for varies too much. A category you chose yourself is never overwritten.
