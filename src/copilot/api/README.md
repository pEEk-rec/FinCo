# api

The HTTP API the web app talks to: thin, typed, and governed. It runs on localhost only, for one
user, with a per-session bearer token.

## How it's laid out

- **`app.py`** builds the app: CORS, request logging (method, route, status, timing; never bodies),
  and the error shape. That's all it does.
- **`routes/`** has one module per area of the product. Each has a `register(app, state)`, and
  `routes/__init__.py` lists them in the order they're added.

  | Module | Routes for |
  | --- | --- |
  | `session` | health and the session check |
  | `ledger` | dashboard, categories, transactions, review queue, consents, imports |
  | `review` | the monthly review and its advice |
  | `ask` | the agent, timeline, investigations, anomalies, alerts, goals, what-ifs |
  | `planning` | commitments, the cash calendar, buckets, readiness |
  | `memory`, `ops` | memories and learning; scheduled jobs |
  | `engagement` | experiments, challenges, offers, adjustments, progress |
  | `capture` | the SMS bridge, push, payments tagged as they happen |
  | `banklink` | the Account Aggregator link |
  | `personal` | understanding, profile, budget, subscriptions, splits, check-ins |

- **`contracts.py`** holds every request and response model, so input is validated before route code
  runs and the OpenAPI document (`docs/openapi.json`, from which the frontend's types are generated)
  stays exact.
- **`deps.py`** provides the token check and the database connection, both read from the app's state.
- **`helpers.py`** has `call_tool` (run one tool as the user and commit) and a few small shared
  helpers.
- **`read_models.py`**, **`coach_view.py`**, **`capture_stream.py`**: read models for the screens
  and the live capture stream.
- **`services.py`**, **`state.py`**, **`server.py`**: demo setup, the per-app state, and
  `copilot serve`.

## Rules (tested)

- Only GET and POST. Every route but `/api/health` needs the token.
- Every write goes through `execute_tool` as the user, so it's policy-checked and audited.
- Errors carry a stable `code` (`errors.py`).
- No route can pay, transfer, trade, withdraw or deposit.
- A fixed path never sits behind an earlier `{param}` path (`tests/api/test_route_layout.py`).
  This is easy to get wrong when adding routes.
