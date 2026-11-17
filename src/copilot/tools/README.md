# tools

Everything FinCo can do to your data, as small typed functions behind one door.

## The idea

A tool is a `ToolSpec`: a name, a description, an input model, an output model, a declared side
effect (`read` or `write_logical`), and a handler. Nobody calls a handler directly. The API, the
CLI, the planner, the specialists, the agents and the scheduled jobs all go through
`executor.execute_tool(ctx, name, args)`, which:

1. looks the tool up and validates the arguments against its input model;
2. asks `governance/policy.py` whether this actor (`user`, `agent`, `system`) may run it, and
   whether it needs approval;
3. runs it with the caller's `user_id`, so it only ever sees that user's data;
4. writes an audit row saying who ran what, with which decision, and what changed.

That single path is why the safety rules can be tested instead of trusted. If a capability isn't a
tool, an agent simply cannot reach it.

## What's here

- **`catalog.py`**: the list of tool families (ledger, goals, what-if, investigations, alerts,
  commitments, buckets, calendar, readiness, contributions, memory, skills, experiments, capture,
  personal model, understanding, bank link, adjustments, challenges, rewards, consents).
  `register_all()` loads them all once. Add a new family here and nowhere else.
- **`registry.py`**, **`executor.py`**, **`contracts.py`**: the registry, the choke point and the
  shared shapes.
- One module per family (`goals.py`, `capture.py`, `personal.py`, ...). Each is thin: it validates,
  calls the real logic in `domain/`, `capture/`, `understand/` or `personal/`, and returns a typed
  result.

## Rules

- 155 tools today: 59 `read`, 96 `write_logical`, none `external`. The policy denies `external`
  outright, so there's no tool that could move money.
- Every tool needs a rule in `config/policy.yaml` and an entry in `config/planner_capabilities.yaml`
  (which also says whether the planner may pick it). `tests/tools/test_catalog.py` checks both.
- Writes that matter (approving advice, applying a reallocation, confirming a memory) are
  `user: allow, agent: deny`: an agent can draft them but only you can apply them.
